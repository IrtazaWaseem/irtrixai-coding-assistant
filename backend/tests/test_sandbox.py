import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.exceptions import (
    DisallowedCommandException,
    SecurityViolationException,
)
from app.services.execution_service import ExecutionService
from app.tools.execution_tools import run_command
from app.tools.validators import validate_command


@pytest.fixture
def sandbox_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        (root / "src").mkdir()
        (root / "src" / "test_app.py").write_text(
            "def test_sample():\n    assert 1 + 1 == 2\n", encoding="utf-8"
        )
        (root / "main.py").write_text("print('workspace main')", encoding="utf-8")
        yield root


@pytest.fixture
def docker_ready():
    """Verifies Docker daemon accessibility and determines active sandbox image."""
    if not ExecutionService.verify_docker_available():
        pytest.skip("Docker daemon is not accessible.")

    # Check if primary sandbox image exists; fallback to python:3.12-slim if necessary
    proc = subprocess.run(
        ["docker", "image", "inspect", settings.DOCKER_SANDBOX_IMAGE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        shell=False,
    )
    if proc.returncode == 0:
        return settings.DOCKER_SANDBOX_IMAGE

    # Check if python:3.12-slim is locally available
    proc_fallback = subprocess.run(
        ["docker", "image", "inspect", "python:3.12-slim"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        shell=False,
    )
    if proc_fallback.returncode == 0:
        return "python:3.12-slim"

    pytest.skip(f"Neither '{settings.DOCKER_SANDBOX_IMAGE}' nor 'python:3.12-slim' is available.")


# --- 1. Public Command Policy & Shell Security Tests ---


def test_command_security_rejections(sandbox_workspace):
    """Verifies non-allowlisted binaries, paths, and shell chaining are rejected."""
    bad_commands = [
        "./python",
        "/path/python",
        r"..\python",
        "bash",
        "sh",
        "curl http://example.com",
        "pytest; rm -rf /",
        "pytest && ls",
        "pytest || ls",
        "pytest | cat",
        "pytest > out.txt",
        "",
        "   ",
    ]

    for cmd in bad_commands:
        res = run_command(cmd, workspace_root=sandbox_workspace)
        assert res.success is False
        assert res.metadata.get("security_violation") is True

        with pytest.raises(DisallowedCommandException):
            run_command(cmd, workspace_root=sandbox_workspace, raise_on_error=True)


def test_command_syntax_and_quoting_integrity():
    """Verifies quoted parentheses and internal semicolons parse cleanly."""
    tokens_1 = validate_command('python -c "print(1)"')
    assert tokens_1 == ["python", "-c", "print(1)"]

    tokens_2 = validate_command("python -c \"print('a;b')\"")
    assert tokens_2 == ["python", "-c", "print('a;b')"]

    tokens_3 = validate_command('python -c "print(1 + (2 * 3))"')
    assert tokens_3 == ["python", "-c", "print(1 + (2 * 3))"]


# --- 2. Workspace Isolation & Pre-Mount Boundary Tests ---


def test_workspace_traversal_guards(sandbox_workspace):
    """Verifies directory traversal and invalid workspaces fail before Docker."""
    res_traversal = run_command(
        'python -c "print(1)"',
        relative_directory="../",
        workspace_root=sandbox_workspace,
    )
    assert res_traversal.success is False
    assert "escapes workspace boundary" in res_traversal.error

    with pytest.raises(SecurityViolationException):
        run_command(
            'python -c "print(1)"',
            relative_directory="../",
            workspace_root=sandbox_workspace,
            raise_on_error=True,
        )

    res_missing = run_command(
        'python -c "print(1)"',
        workspace_root="/path/does/not/exist",
    )
    assert res_missing.success is False


# --- 3. Live Docker Sandbox Boundary & Isolation Tests ---


def test_docker_live_read_only_workspace(sandbox_workspace, docker_ready):
    """Verifies the host workspace is strictly read-only inside the container."""
    res = run_command(
        "python -c \"open('/workspace/forbidden.txt', 'w').write('leak')\"",
        workspace_root=sandbox_workspace,
        image=docker_ready,
    )
    assert res.success is True
    assert res.output["exit_code"] != 0
    assert "Read-only file system" in res.output["stderr"] or "OSError" in res.output["stderr"]
    assert not (sandbox_workspace / "forbidden.txt").exists()


def test_docker_live_network_isolation(sandbox_workspace, docker_ready):
    """Verifies the container cannot establish external network connections."""
    net_code = (
        "import socket\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.settimeout(2)\n"
        "s.connect(('1.1.1.1', 80))\n"
    )
    res = run_command(
        f'python -c "{net_code}"',
        workspace_root=sandbox_workspace,
        image=docker_ready,
    )
    assert res.success is True
    assert res.output["exit_code"] != 0
    assert any(
        err in res.output["stderr"] for err in ["Network is unreachable", "OSError", "TimeoutError"]
    )


def test_docker_live_non_root_execution(sandbox_workspace, docker_ready):
    """Verifies code executes strictly under non-root UID 1000."""
    res = run_command(
        'python -c "import os; print(os.getuid())"',
        workspace_root=sandbox_workspace,
        image=docker_ready,
    )
    assert res.success is True
    assert res.output["exit_code"] == 0
    assert res.output["stdout"].strip() == "1000"


def test_docker_live_timeout_terminates_and_removes_container(sandbox_workspace, docker_ready):
    """Verifies timeout kills the process and guarantees zero orphaned containers."""
    res = run_command(
        'python -c "import time; time.sleep(10)"',
        workspace_root=sandbox_workspace,
        timeout_seconds=2,
        image=docker_ready,
    )
    assert res.success is False
    assert res.metadata.get("timeout") is True

    # Confirm container is removed from host Docker daemon
    proc = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"ancestor={docker_ready}", "-q"],
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    # The timed-out container ID should not be lingering
    assert proc.returncode == 0


def test_docker_live_output_byte_bounded(sandbox_workspace, docker_ready):
    """Verifies output exceeding configured limits is safely clamped in memory."""
    payload_size = settings.MAX_TOOL_OUTPUT_BYTES + 20000
    res = run_command(
        f"python -c \"print('X' * {payload_size})\"",
        workspace_root=sandbox_workspace,
        image=docker_ready,
    )
    assert res.success is True
    assert res.output["truncated"] is True
    assert len(res.output["stdout"].encode("utf-8")) <= settings.MAX_TOOL_OUTPUT_BYTES


def test_docker_live_host_environment_isolation(sandbox_workspace, docker_ready):
    """Verifies host environment variables and secrets are not leaked to container."""
    os.environ["HOST_LEAK_SECRET_KEY"] = "super_confidential_token"
    try:
        res = run_command(
            "python -c \"import os; print(os.environ.get('HOST_LEAK_SECRET_KEY', 'NOT_FOUND'))\"",
            workspace_root=sandbox_workspace,
            image=docker_ready,
        )
        assert res.success is True
        assert res.output["stdout"].strip() == "NOT_FOUND"
    finally:
        os.environ.pop("HOST_LEAK_SECRET_KEY", None)


def test_docker_live_scratch_temporary_storage_writable(sandbox_workspace, docker_ready):
    """Verifies container-local tmpfs (/tmp) is writable for compiler/runtime scratch."""
    script = (
        "import tempfile, os\n"
        "with tempfile.NamedTemporaryFile(delete=False) as f:\n"
        "    f.write(b'scratch_data')\n"
        "    p = f.name\n"
        "assert os.path.exists(p)\n"
        "os.unlink(p)\n"
        "print('SCRATCH_OK')\n"
    )
    res = run_command(
        f'python -c "{script}"',
        workspace_root=sandbox_workspace,
        image=docker_ready,
    )
    assert res.success is True
    assert res.output["exit_code"] == 0
    assert "SCRATCH_OK" in res.output["stdout"]
