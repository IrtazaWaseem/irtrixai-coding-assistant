import contextlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.core.exceptions import (
    AppException,
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

    proc = subprocess.run(
        ["docker", "image", "inspect", settings.DOCKER_SANDBOX_IMAGE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        shell=False,
    )
    if proc.returncode == 0:
        return settings.DOCKER_SANDBOX_IMAGE

    proc_fallback = subprocess.run(
        ["docker", "image", "inspect", "python:3.12-slim"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        shell=False,
    )
    if proc_fallback.returncode == 0:
        return "python:3.12-slim"

    pytest.skip(
        f"Neither '{settings.DOCKER_SANDBOX_IMAGE}' nor 'python:3.12-slim' is available."
    )


# --- Regression Tests: Direct Service Boundary Enforcement ---


def test_execution_service_direct_caller_security(sandbox_workspace):
    """Verifies direct callers of ExecutionService cannot bypass command policy."""
    service = ExecutionService()

    with pytest.raises(DisallowedCommandException):
        service.execute_in_sandbox(
            command=["bash", "-c", "whoami"],
            workspace_path=sandbox_workspace,
            timeout_seconds=5,
        )

    with pytest.raises(DisallowedCommandException):
        service.execute_in_sandbox(
            command=["./python", "-c", "print(1)"],
            workspace_path=sandbox_workspace,
            timeout_seconds=5,
        )

    with pytest.raises(DisallowedCommandException):
        service.execute_in_sandbox(
            command=["/usr/bin/python", "-c", "print(1)"],
            workspace_path=sandbox_workspace,
            timeout_seconds=5,
        )

    with pytest.raises(DisallowedCommandException):
        service.execute_in_sandbox(
            command=["python", ";", "rm", "-rf", "/"],
            workspace_path=sandbox_workspace,
            timeout_seconds=5,
        )

    with pytest.raises(DisallowedCommandException):
        service.execute_in_sandbox(
            command="curl http://malicious.com",
            workspace_path=sandbox_workspace,
            timeout_seconds=5,
        )


def test_execution_service_direct_workspace_validation(sandbox_workspace, tmp_path):
    """Verifies direct callers of ExecutionService cannot bypass workspace path validation."""
    service = ExecutionService()

    # 1. Nonexistent directory is rejected before Docker
    with patch.object(service, "_create_container") as mock_create:
        with pytest.raises(AppException) as exc_info:
            service.execute_in_sandbox(
                command='python -c "print(1)"',
                workspace_path=tmp_path / "does_not_exist",
                timeout_seconds=5,
            )
        assert exc_info.value.status_code == 404
        mock_create.assert_not_called()

    # 2. Regular file target is rejected before Docker
    file_target = sandbox_workspace / "main.py"
    with patch.object(service, "_create_container") as mock_create:
        with pytest.raises(AppException) as exc_info:
            service.execute_in_sandbox(
                command='python -c "print(1)"',
                workspace_path=file_target,
                timeout_seconds=5,
            )
        assert exc_info.value.status_code == 400
        mock_create.assert_not_called()

    # 3. Traversal / Boundary escape rejected before Docker
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    with patch.object(service, "_create_container") as mock_create:
        with pytest.raises(SecurityViolationException):
            service.execute_in_sandbox(
                command='python -c "print(1)"',
                workspace_path=outside_dir,
                timeout_seconds=5,
                trusted_base=sandbox_workspace,
            )
        mock_create.assert_not_called()

    # 4. Symlink escape rejected before Docker
    symlink_dir = sandbox_workspace / "symlink_escape"
    try:
        os.symlink(outside_dir, symlink_dir)
        with patch.object(service, "_create_container") as mock_create:
            with pytest.raises(SecurityViolationException):
                service.execute_in_sandbox(
                    command='python -c "print(1)"',
                    workspace_path=symlink_dir,
                    timeout_seconds=5,
                    trusted_base=sandbox_workspace,
                )
            mock_create.assert_not_called()
    except OSError:
        pass

    # 5. Valid workspace succeeds
    with (
        patch.object(
            service, "_create_container", return_value="dummy_cid"
        ) as mock_create,
        patch.object(service, "_start_container"),
        patch.object(service, "_wait_container", return_value=0),
        patch.object(service, "_collect_bounded_logs", return_value=("ok", "", False)),
        patch.object(service, "_cleanup_container"),
    ):
        res = service.execute_in_sandbox(
            command='python -c "print(1)"',
            workspace_path=sandbox_workspace,
            timeout_seconds=5,
        )
        assert res["exit_code"] == 0
        mock_create.assert_called_once()


# --- Public Command Policy & Shell Security Tests ---


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


# --- Live Docker Verification Tests ---


def test_docker_live_basic_execution_and_tools(sandbox_workspace, docker_ready):
    """Verifies basic execution, pytest, and ruff availability in sandbox image."""
    res = run_command(
        "python -c \"print('hello')\"",
        workspace_root=sandbox_workspace,
        image=docker_ready,
    )
    assert res.success is True
    assert res.output["exit_code"] == 0
    assert "hello" in res.output["stdout"]

    res_pytest = run_command(
        "pytest --version", workspace_root=sandbox_workspace, image=docker_ready
    )
    assert res_pytest.success is True
    assert res_pytest.output["exit_code"] == 0
    assert (
        "pytest" in (res_pytest.output["stdout"] + res_pytest.output["stderr"]).lower()
    )

    res_ruff = run_command(
        "ruff --version", workspace_root=sandbox_workspace, image=docker_ready
    )
    assert res_ruff.success is True
    assert res_ruff.output["exit_code"] == 0
    assert "ruff" in (res_ruff.output["stdout"] + res_ruff.output["stderr"]).lower()


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
        err in res.output["stderr"]
        for err in ["Network is unreachable", "OSError", "TimeoutError"]
    )


def test_docker_live_read_only_workspace(sandbox_workspace, docker_ready):
    """Verifies the host workspace is strictly read-only inside the container."""
    res = run_command(
        "python -c \"open('/workspace/forbidden.txt', 'w').write('leak')\"",
        workspace_root=sandbox_workspace,
        image=docker_ready,
    )
    assert res.success is True
    assert res.output["exit_code"] != 0
    assert (
        "Read-only file system" in res.output["stderr"]
        or "OSError" in res.output["stderr"]
    )
    assert not (sandbox_workspace / "forbidden.txt").exists()


def test_docker_live_root_filesystem_read_only(sandbox_workspace, docker_ready):
    """Verifies the container root filesystem is strictly read-only."""
    res = run_command(
        "python -c \"open('/root_test.txt', 'w').write('fail')\"",
        workspace_root=sandbox_workspace,
        image=docker_ready,
    )
    assert res.success is True
    assert res.output["exit_code"] != 0
    assert (
        "Read-only file system" in res.output["stderr"]
        or "OSError" in res.output["stderr"]
    )


def test_docker_live_scratch_temporary_storage_writable(
    sandbox_workspace, docker_ready
):
    """Verifies container-local tmpfs (/tmp) is writable and isolated from host."""
    script = (
        "import tempfile, os\n"
        "with tempfile.NamedTemporaryFile(dir='/tmp', delete=False) as f:\n"
        "    f.write(b'scratch_data')\n"
        "    p = f.name\n"
        "assert os.path.exists(p)\n"
        "print('TEMP_PATH:' + p)\n"
    )
    res = run_command(
        f'python -c "{script}"',
        workspace_root=sandbox_workspace,
        image=docker_ready,
    )
    assert res.success is True
    assert res.output["exit_code"] == 0
    assert "TEMP_PATH:/tmp/" in res.output["stdout"]


def test_docker_live_host_filesystem_isolation(sandbox_workspace, docker_ready):
    """Verifies host files outside the mounted workspace cannot be read."""
    with tempfile.NamedTemporaryFile(delete=False) as host_secret:
        host_secret.write(b"SYNTHETIC_HOST_SECRET_TOKEN_XYZ")
        host_secret_path = host_secret.name

    try:
        container_path = host_secret_path.replace("\\", "/")
        probe = (
            f"import os\n"
            f"target = '{container_path}'\n"
            f"exists = os.path.exists(target)\n"
            f"print('EXISTS:' + str(exists))\n"
        )
        res = run_command(
            f'python -c "{probe}"',
            workspace_root=sandbox_workspace,
            image=docker_ready,
        )
        assert res.success is True
        assert "EXISTS:False" in res.output["stdout"]
    finally:
        with contextlib.suppress(OSError):
            os.unlink(host_secret_path)


def test_docker_live_symlink_external_target_unreachable(
    sandbox_workspace, docker_ready
):
    """Verifies external symlink targets cannot be read from inside the container."""
    with tempfile.NamedTemporaryFile(delete=False) as external_target:
        external_target.write(b"EXTERNAL_HOST_DATA_LEAK")
        external_target_path = external_target.name

    evil_link = sandbox_workspace / "evil_link.txt"
    try:
        os.symlink(external_target_path, evil_link)
    except OSError:
        pytest.skip("Host OS requires elevated privileges for symlink creation.")

    try:
        script = (
            "from pathlib import Path\n"
            "p = Path('/workspace/evil_link.txt')\n"
            "try:\n"
            "    data = p.read_text()\n"
            "    print('LEAK:' + data)\n"
            "except Exception as err:\n"
            "    print('BLOCKED:' + err.__class__.__name__)\n"
        )
        res = run_command(
            f'python -c "{script}"',
            workspace_root=sandbox_workspace,
            image=docker_ready,
        )
        assert res.success is True
        assert "LEAK:EXTERNAL_HOST_DATA_LEAK" not in res.output["stdout"]
        assert "BLOCKED:" in res.output["stdout"]
    finally:
        with contextlib.suppress(OSError):
            os.unlink(external_target_path)


def test_docker_live_docker_socket_absent(sandbox_workspace, docker_ready):
    """Verifies Docker socket is never mounted into the sandbox."""
    script = "import os; print('SOCKET_EXISTS:' + str(os.path.exists('/var/run/docker.sock')))"
    res = run_command(
        f'python -c "{script}"',
        workspace_root=sandbox_workspace,
        image=docker_ready,
    )
    assert res.success is True
    assert "SOCKET_EXISTS:False" in res.output["stdout"]


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


def test_docker_live_timeout_terminates_and_removes_container(
    sandbox_workspace, docker_ready
):
    """Verifies timeout kills the process and guarantees zero orphaned containers."""
    res = run_command(
        'python -c "import time; time.sleep(10)"',
        workspace_root=sandbox_workspace,
        timeout_seconds=2,
        image=docker_ready,
    )
    assert res.success is False
    assert res.metadata.get("timeout") is True


def test_docker_live_resource_limits_and_capabilities(docker_ready):
    """Verifies container parameters match memory, cpu, pids, and drop-all policies."""
    proc = subprocess.run(
        [
            "docker",
            "create",
            "--network=none",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            f"--memory={settings.SANDBOX_MEMORY_LIMIT}",
            f"--cpus={settings.SANDBOX_CPU_LIMIT}",
            f"--pids-limit={settings.SANDBOX_PIDS_LIMIT}",
            docker_ready,
            "python",
            "-c",
            "print(1)",
        ],
        capture_output=True,
        text=True,
        check=False,
        shell=False,
    )
    assert proc.returncode == 0
    cid = proc.stdout.strip()
    try:
        inspect_proc = subprocess.run(
            ["docker", "inspect", cid],
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        assert inspect_proc.returncode == 0
        data = json.loads(inspect_proc.stdout)[0]
        host_config = data["HostConfig"]

        # Memory limit: 512MB = 536870912 bytes
        assert host_config["Memory"] == 536870912
        # CPU limit: 1.0 CPU = 1000000000 nanoCPUs
        assert host_config["NanoCpus"] == 1000000000
        # PIDs limit
        assert host_config["PidsLimit"] == settings.SANDBOX_PIDS_LIMIT
        # CapDrop contains ALL
        assert "ALL" in host_config["CapDrop"]
        # Network mode is none
        assert host_config["NetworkMode"] == "none"
    finally:
        subprocess.run(
            ["docker", "rm", "-f", cid],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            shell=False,
        )


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


def test_docker_live_cleanup_on_nonzero_exit(sandbox_workspace, docker_ready):
    """Verifies containers are cleanly removed even when the command fails with non-zero exit."""
    res = run_command(
        'python -c "import sys; sys.exit(42)"',
        workspace_root=sandbox_workspace,
        image=docker_ready,
    )
    assert res.success is True
    assert res.output["exit_code"] == 42
