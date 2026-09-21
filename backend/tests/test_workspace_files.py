import hashlib
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
async def test_canonical_route_and_content_hash(tmp_path: Path, client: AsyncClient):
    """P0-1 & P0-2: Canonical route works and returns exact SHA-256 content hash."""
    ws_dir = tmp_path / "ws_canon"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    target_file = ws_dir / "app.py"
    target_text = "def hello():\n    return 'world'\n"
    target_file.write_text(target_text, encoding="utf-8", newline="")
    expected_hash = hashlib.sha256(target_text.encode("utf-8")).hexdigest()

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces", json={"name": "ws-canon", "root_path": str(ws_dir)}
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        res = await client.get(f"/api/v1/workspaces/{ws_id}/files/app.py")
        assert res.status_code == 200
        data = res.json()
        assert data["path"] == "app.py"
        assert data["content"] == target_text
        assert data["content_hash"] == expected_hash
        assert data["truncated"] is False
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_removed_query_param_routes_return_404(tmp_path: Path, client: AsyncClient):
    """P0-1: Old query-param endpoints are removed and return 404."""
    ws_dir = tmp_path / "ws_removed_routes"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    (ws_dir / "sample.py").write_text("x = 1\n", encoding="utf-8", newline="")

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces", json={"name": "ws-old", "root_path": str(ws_dir)}
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        get_old = await client.get(f"/api/v1/workspaces/{ws_id}/file", params={"path": "sample.py"})
        assert get_old.status_code == 404

        put_old = await client.put(
            f"/api/v1/workspaces/{ws_id}/file",
            params={"path": "sample.py"},
            json={"content": "x = 2"},
        )
        assert put_old.status_code == 404
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_optimistic_concurrency_fresh_save_succeeds(tmp_path: Path, client: AsyncClient):
    """P0-2: Saving with valid matching expected_content_hash succeeds."""
    ws_dir = tmp_path / "ws_save_match"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    initial_text = "VERSION = 1\n"
    (ws_dir / "config.py").write_text(initial_text, encoding="utf-8", newline="")
    initial_hash = hashlib.sha256(initial_text.encode("utf-8")).hexdigest()

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces", json={"name": "ws-save", "root_path": str(ws_dir)}
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        new_text = "VERSION = 2\n"
        res = await client.put(
            f"/api/v1/workspaces/{ws_id}/files/config.py",
            json={"content": new_text, "expected_content_hash": initial_hash},
        )
        assert res.status_code == 200
        data = res.json()
        expected_new_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
        assert data["content_hash"] == expected_new_hash
        assert (ws_dir / "config.py").read_text(encoding="utf-8") == new_text
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_optimistic_concurrency_stale_save_conflict(tmp_path: Path, client: AsyncClient):
    """P0-2: Stale save when file was modified externally returns 409 and protects disk."""
    ws_dir = tmp_path / "ws_conflict"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    target_file = ws_dir / "document.py"
    target_file.write_text("ORIGINAL CONTENT\n", encoding="utf-8", newline="")
    original_hash = hashlib.sha256(b"ORIGINAL CONTENT\n").hexdigest()

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces", json={"name": "ws-conflict", "root_path": str(ws_dir)}
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        target_file.write_text("EXTERNAL MODIFICATION\n", encoding="utf-8", newline="")

        res = await client.put(
            f"/api/v1/workspaces/{ws_id}/files/document.py",
            json={"content": "OVERWRITE ATTEMPT", "expected_content_hash": original_hash},
        )
        assert res.status_code == 409
        body = res.json()
        error_msg = body.get("message") or body.get("detail") or str(body)
        assert "modified" in error_msg.lower() or "conflict" in error_msg.lower()

        assert target_file.read_text(encoding="utf-8") == "EXTERNAL MODIFICATION\n"
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_new_file_creation_concurrency(tmp_path: Path, client: AsyncClient):
    """P0-2: New file requires expected_content_hash=null; existing file with null is rejected."""
    ws_dir = tmp_path / "ws_new_files"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces", json={"name": "ws-new", "root_path": str(ws_dir)}
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        res_new = await client.put(
            f"/api/v1/workspaces/{ws_id}/files/src/new_module.py",
            json={"content": "def new_func(): pass\n", "expected_content_hash": None},
        )
        assert res_new.status_code == 200
        assert res_new.json()["is_new_file"] is True

        res_existing = await client.put(
            f"/api/v1/workspaces/{ws_id}/files/src/new_module.py",
            json={"content": "def overwrite(): pass\n", "expected_content_hash": None},
        )
        assert res_existing.status_code == 409
        assert "already exists" in res_existing.text.lower()
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_large_file_under_limit_not_truncated(tmp_path: Path, client: AsyncClient):
    """P0-3: File > 50KB but <= 1MB returns full content with truncated=False and preserves data on save."""
    ws_dir = tmp_path / "ws_large_not_trunc"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    large_line = "# Comment line of reasonable length for source code testing\n"
    target_content = large_line * 1200
    assert len(target_content.encode("utf-8")) > 55_000

    target_file = ws_dir / "large_service.py"
    target_file.write_text(target_content, encoding="utf-8", newline="")
    expected_hash = hashlib.sha256(target_content.encode("utf-8")).hexdigest()

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces", json={"name": "ws-large", "root_path": str(ws_dir)}
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        res_read = await client.get(f"/api/v1/workspaces/{ws_id}/files/large_service.py")
        assert res_read.status_code == 200
        data = res_read.json()
        assert data["truncated"] is False
        assert data["content_hash"] == expected_hash
        assert data["content"] == target_content

        res_save = await client.put(
            f"/api/v1/workspaces/{ws_id}/files/large_service.py",
            json={"content": target_content, "expected_content_hash": expected_hash},
        )
        assert res_save.status_code == 200
        assert target_file.read_text(encoding="utf-8") == target_content
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_sanitized_errors_do_not_leak_absolute_paths(tmp_path: Path, client: AsyncClient):
    """P0-4: Error responses never expose internal paths, stack traces, or temp file paths."""
    ws_dir = tmp_path / "ws_sanitize"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces", json={"name": "ws-san", "root_path": str(ws_dir)}
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        res = await client.get(f"/api/v1/workspaces/{ws_id}/files/non_existent.py")
        assert res.status_code == 404
        assert str(ws_dir) not in res.text

        res_trav = await client.get(f"/api/v1/workspaces/{ws_id}/files/../../etc/passwd")
        assert res_trav.status_code in (400, 404)
        assert str(ws_dir) not in res_trav.text
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_write_size_exceeding_max_write_limit_rejected(tmp_path: Path, client: AsyncClient):
    """P0-5: Writes exceeding MAX_WRITE_FILE_BYTES are rejected with 413."""
    ws_dir = tmp_path / "ws_write_size"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces", json={"name": "ws-ws", "root_path": str(ws_dir)}
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        huge_payload = "A" * (settings.MAX_WRITE_FILE_BYTES + 1024)
        res = await client.put(
            f"/api/v1/workspaces/{ws_id}/files/huge.txt",
            json={"content": huge_payload, "expected_content_hash": None},
        )
        assert res.status_code == 413
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_protected_and_binary_files_rejected(tmp_path: Path, client: AsyncClient):
    """Preserves security invariants: .env and binary files are rejected."""
    ws_dir = tmp_path / "ws_sec_inv"
    ws_dir.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_dir)

    (ws_dir / ".env").write_text("SECRET=123\n", encoding="utf-8", newline="")
    (ws_dir / "app.bin").write_bytes(b"MZ\x00\x01data")

    orig = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        reg = await client.post(
            "/api/v1/workspaces", json={"name": "ws-sec", "root_path": str(ws_dir)}
        )
        assert reg.status_code == 201
        ws_id = reg.json()["id"]

        res_prot = await client.get(f"/api/v1/workspaces/{ws_id}/files/.env")
        assert res_prot.status_code == 403

        res_bin = await client.get(f"/api/v1/workspaces/{ws_id}/files/app.bin")
        assert res_bin.status_code == 400
        assert "binary" in res_bin.text.lower()
    finally:
        settings.WORKSPACE_BASE_PATH = orig


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_cross_workspace_isolation_maintained(tmp_path: Path, client: AsyncClient):
    """Workspace A cannot read files from Workspace B."""
    ws_a = tmp_path / "ws_tenant_a"
    ws_b = tmp_path / "ws_tenant_b"
    ws_a.mkdir(parents=True, exist_ok=True)
    ws_b.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_a)
    init_test_git_repo(ws_b)

    (ws_b / "private_b.py").write_text("SECRET_B = 999\n", encoding="utf-8", newline="")

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

        res = await client.get(f"/api/v1/workspaces/{ws_a_id}/files/private_b.py")
        assert res.status_code == 404
    finally:
        settings.WORKSPACE_BASE_PATH = orig
