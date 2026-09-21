import subprocess
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.exceptions import ContainerTimeoutException
from app.services.execution_service import ExecutionService


def init_test_git_repo(repo_path: Path) -> None:
    (repo_path / ".gitkeep").touch()
    subprocess.run(["git", "init"], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.name", "TestRunner"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@irtrixai.internal"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_terminal_execute_success_flow(tmp_path: Path, client: AsyncClient):
    """A & B: Terminal endpoint executes allowlisted command using registered workspace_id."""
    ws_dir = tmp_path / "ws_term_success"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces",
            json={"name": "ws-term", "root_path": str(ws_dir)},
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        mock_result = {
            "command": "pytest -q",
            "exit_code": 0,
            "stdout": "3 passed in 0.05s",
            "stderr": "",
            "truncated": False,
            "duration_seconds": 0.25,
        }

        with patch.object(
            ExecutionService, "execute_in_sandbox", return_value=mock_result
        ) as mock_exec:
            res = await client.post(
                f"/api/v1/workspaces/{ws_id}/terminal/execute",
                json={"command": "pytest -q"},
            )
            assert res.status_code == 200
            data = res.json()
            assert data["workspace_id"] == ws_id
            assert data["command"] == "pytest -q"
            assert data["exit_code"] == 0
            assert data["stdout"] == "3 passed in 0.05s"
            assert data["truncated"] is False
            assert data["duration_seconds"] == 0.25

            mock_exec.assert_called_once()
            call_kwargs = mock_exec.call_args.kwargs
            assert call_kwargs["workspace_path"] == ws_dir.resolve()
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_terminal_execute_nonexistent_workspace_rejected(client: AsyncClient):
    """C: Nonexistent workspace_id returns 404."""
    random_id = str(uuid.uuid4())
    res = await client.post(
        f"/api/v1/workspaces/{random_id}/terminal/execute",
        json={"command": "pytest -q"},
    )
    assert res.status_code == 404


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_terminal_execute_disallowed_commands_rejected(tmp_path: Path, client: AsyncClient):
    """E & F: Disallowed executables and shell chaining are rejected before Docker."""
    ws_dir = tmp_path / "ws_term_disallowed"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces",
            json={"name": "ws-disallow", "root_path": str(ws_dir)},
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        dangerous_commands = [
            "curl https://malicious.org",
            "rm -rf /",
            "bash -c 'whoami'",
            "pytest && rm -rf /",
            "pytest ; cat /etc/passwd",
            "pytest | grep pass",
            "pytest > out.txt",
            "python `id`",
            "$(whoami)",
            "./local_script",
            "/bin/ls",
        ]

        for cmd in dangerous_commands:
            res = await client.post(
                f"/api/v1/workspaces/{ws_id}/terminal/execute",
                json={"command": cmd},
            )
            assert res.status_code == 400
            data = res.json()
            error_text = (data.get("message") or data.get("detail") or res.text).lower()
            assert "rejected" in error_text
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_terminal_execute_nonzero_exit_code(tmp_path: Path, client: AsyncClient):
    """I: Non-zero exit code returns HTTP 200 with truthful exit code."""
    ws_dir = tmp_path / "ws_term_nonzero"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces",
            json={"name": "ws-nonzero", "root_path": str(ws_dir)},
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        mock_result = {
            "command": "pytest -q",
            "exit_code": 1,
            "stdout": "1 failed in 0.12s",
            "stderr": "AssertionError: 1 != 2",
            "truncated": False,
            "duration_seconds": 0.45,
        }

        with patch.object(ExecutionService, "execute_in_sandbox", return_value=mock_result):
            res = await client.post(
                f"/api/v1/workspaces/{ws_id}/terminal/execute",
                json={"command": "pytest -q"},
            )
            assert res.status_code == 200
            data = res.json()
            assert data["exit_code"] == 1
            assert "1 failed" in data["stdout"]
            assert "AssertionError" in data["stderr"]
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_terminal_execute_timeout_handling(tmp_path: Path, client: AsyncClient):
    """K: Sandbox container timeout is mapped to clean HTTP 408."""
    ws_dir = tmp_path / "ws_term_timeout"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces",
            json={"name": "ws-timeout", "root_path": str(ws_dir)},
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        with patch.object(
            ExecutionService,
            "execute_in_sandbox",
            side_effect=ContainerTimeoutException(timeout_seconds=30),
        ):
            res = await client.post(
                f"/api/v1/workspaces/{ws_id}/terminal/execute",
                json={"command": "pytest -q"},
            )
            assert res.status_code == 408
            data = res.json()
            error_text = (data.get("message") or data.get("detail") or res.text).lower()
            assert "timed out" in error_text
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_terminal_security_no_host_subprocess_bypass(tmp_path: Path, client: AsyncClient):
    """M (CRITICAL): Proves endpoint routes through ExecutionService and never invokes direct host subprocesses."""
    ws_dir = tmp_path / "ws_term_sec"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces",
            json={"name": "ws-sec", "root_path": str(ws_dir)},
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        with (
            patch("os.system") as mock_os_system,
            patch.object(
                ExecutionService,
                "execute_in_sandbox",
                return_value={
                    "command": "pytest -q",
                    "exit_code": 0,
                    "stdout": "ok",
                    "stderr": "",
                    "truncated": False,
                    "duration_seconds": 0.1,
                },
            ) as mock_sandbox,
        ):
            res = await client.post(
                f"/api/v1/workspaces/{ws_id}/terminal/execute",
                json={"command": "pytest -q"},
            )
            assert res.status_code == 200
            mock_os_system.assert_not_called()
            mock_sandbox.assert_called_once()
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_terminal_error_sanitization_no_leakage(tmp_path: Path, client: AsyncClient):
    """P: Unexpected server exceptions do not leak internal filesystem paths or stack traces."""
    ws_dir = tmp_path / "ws_term_sanitize"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces",
            json={"name": "ws-san", "root_path": str(ws_dir)},
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        with patch.object(
            ExecutionService,
            "execute_in_sandbox",
            side_effect=RuntimeError(f"Docker daemon failure at {ws_dir}/internal_debug.sock"),
        ):
            res = await client.post(
                f"/api/v1/workspaces/{ws_id}/terminal/execute",
                json={"command": "pytest -q"},
            )
            assert res.status_code == 500
            body_text = res.text
            assert str(ws_dir) not in body_text
            assert "internal_debug.sock" not in body_text
            assert "Terminal execution failed." in body_text
    finally:
        settings.WORKSPACE_BASE_PATH = orig
