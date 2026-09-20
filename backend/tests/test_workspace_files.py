import subprocess
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.config import settings


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
async def test_read_workspace_file_success(tmp_path: Path, client: AsyncClient):
    """Phase 13A-6: Registered workspace + valid relative path returns content."""
    ws_dir = tmp_path / "ws_read_ok"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    target = ws_dir / "service.py"
    target.write_text("def ping():\n    return 'pong'\n", encoding="utf-8")

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces", json={"name": "ws-ok", "root_path": str(ws_dir)}
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        res = await client.get(f"/api/v1/workspaces/{ws_id}/files/service.py")
        assert res.status_code == 200
        data = res.json()
        assert data["path"] == "service.py"
        assert "def ping():" in data["content"]
        assert data["size"] > 0
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_read_workspace_file_path_traversal_rejected(tmp_path: Path, client: AsyncClient):
    """Phase 13A-6: Path traversal outside workspace boundary is rejected."""
    ws_dir = tmp_path / "ws_traversal"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces", json={"name": "ws-trav", "root_path": str(ws_dir)}
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        res = await client.get(
            f"/api/v1/workspaces/{ws_id}/file", params={"path": "../../escape.txt"}
        )
        assert res.status_code in (400, 403, 404)
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_read_workspace_file_protected_file_rejected(tmp_path: Path, client: AsyncClient):
    """Phase 13A-6: Reading protected files like .env is strictly forbidden."""
    ws_dir = tmp_path / "ws_protected"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    env_file = ws_dir / ".env"
    env_file.write_text("SECRET=my_key\n", encoding="utf-8")

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces", json={"name": "ws-prot", "root_path": str(ws_dir)}
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        res = await client.get(f"/api/v1/workspaces/{ws_id}/files/.env")
        assert res.status_code == 403
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_read_workspace_file_oversized_rejected(tmp_path: Path, client: AsyncClient):
    """Phase 13A-6: Files exceeding MAX_READ_FILE_BYTES are rejected."""
    ws_dir = tmp_path / "ws_oversized"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    big_file = ws_dir / "huge.txt"
    big_file.write_bytes(b"A" * (1_048_576 + 1024))

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces", json={"name": "ws-big", "root_path": str(ws_dir)}
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        res = await client.get(f"/api/v1/workspaces/{ws_id}/files/huge.txt")
        assert res.status_code == 413
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_read_workspace_binary_file_rejected(tmp_path: Path, client: AsyncClient):
    """Phase 13A-6: Binary files containing null bytes are rejected with clean error."""
    ws_dir = tmp_path / "ws_binary"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    bin_file = ws_dir / "app.bin"
    bin_file.write_bytes(b"MZ\x00\x01\x02binary")

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces", json={"name": "ws-bin", "root_path": str(ws_dir)}
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        res = await client.get(f"/api/v1/workspaces/{ws_id}/files/app.bin")
        assert res.status_code == 400
        assert "binary" in res.text.lower()
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_workspace_isolation_cross_workspace_read_prevented(
    tmp_path: Path, client: AsyncClient
):
    """Phase 13A-6: Workspace A cannot read files from Workspace B."""
    ws_a = tmp_path / "ws_tenant_a"
    ws_b = tmp_path / "ws_tenant_b"
    ws_a.mkdir(parents=True, exist_ok=True)
    ws_b.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_a)
    init_test_git_repo(ws_b)

    (ws_b / "secret_b.py").write_text("CONFIDENTIAL = 123\n", encoding="utf-8")

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg_a = await client.post(
            "/api/v1/workspaces", json={"name": "ws-a", "root_path": str(ws_a)}
        )
        reg_b = await client.post(
            "/api/v1/workspaces", json={"name": "ws-b", "root_path": str(ws_b)}
        )
        assert reg_a.status_code == 201
        assert reg_b.status_code == 201
        ws_a_id = reg_a.json()["id"]

        res = await client.get(f"/api/v1/workspaces/{ws_a_id}/files/secret_b.py")
        assert res.status_code == 404
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_write_workspace_file_atomic_success(tmp_path: Path, client: AsyncClient):
    """Phase 13A-6: Explicit save writes atomically to disk."""
    ws_dir = tmp_path / "ws_write"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces", json={"name": "ws-write", "root_path": str(ws_dir)}
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        res = await client.put(
            f"/api/v1/workspaces/{ws_id}/files/src/main.py",
            json={"content": "def main():\n    print('Saved from Monaco')\n"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["bytes_written"] > 0
        assert data["is_new_file"] is True

        saved_file = ws_dir / "src" / "main.py"
        assert saved_file.is_file()
        assert "Saved from Monaco" in saved_file.read_text(encoding="utf-8")
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_write_workspace_file_protected_rejected(tmp_path: Path, client: AsyncClient):
    """Phase 13A-6: Writing to protected files like .env or .git is rejected."""
    ws_dir = tmp_path / "ws_write_prot"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces", json={"name": "ws-wprot", "root_path": str(ws_dir)}
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        res = await client.put(
            f"/api/v1/workspaces/{ws_id}/files/.env",
            json={"content": "ATTACK = 1"},
        )
        assert res.status_code == 403
    finally:
        settings.WORKSPACE_BASE_PATH = orig
