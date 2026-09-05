import tempfile
import uuid
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from app.core.exceptions import SecurityViolationException
from app.core.security import resolve_safe_path
from app.db.session import AsyncSessionLocal
from app.main import app
from app.services.workspace_service import WorkspaceService


@pytest.fixture
def test_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir).resolve()
        (base / "src").mkdir()
        (base / "src" / "index.ts").write_text("console.log('hello');", encoding="utf-8")
        (base / "README.md").write_text("# Test Workspace", encoding="utf-8")
        yield base


@pytest.mark.asyncio
async def test_health_endpoint():
    """Verify GET /health returns 200 OK and expected structure."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "irtrixai-backend"


@pytest.mark.asyncio
async def test_v1_status_endpoint():
    """Verify GET /api/v1/status returns 200 OK and active status."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "active"
        assert data["api_version"] == "v1"


@pytest.mark.asyncio
async def test_cors_headers():
    """Verify CORS middleware allows requests from Vite frontend."""
    transport = ASGITransport(app=app)
    headers = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.options("/api/v1/workspaces", headers=headers)
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


@pytest.mark.asyncio
async def test_workspace_lifecycle_and_persistence(test_dir):
    """Verify workspace creation, DB persistence, and tree inspection via API."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create Workspace
        create_payload = {
            "name": "smoke-test-workspace",
            "root_path": str(test_dir),
        }
        create_resp = await client.post("/api/v1/workspaces", json=create_payload)
        assert create_resp.status_code == 201
        created_data = create_resp.json()
        workspace_id = created_data["id"]
        assert created_data["name"] == "smoke-test-workspace"
        assert created_data["root_path"] == str(test_dir)

        # 2. Retrieve Workspace by ID (verifying DB persistence)
        get_resp = await client.get(f"/api/v1/workspaces/{workspace_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == workspace_id

        # 3. Retrieve Workspace Tree
        tree_resp = await client.get(f"/api/v1/workspaces/{workspace_id}/tree?max_depth=3")
        assert tree_resp.status_code == 200
        tree_data = tree_resp.json()
        assert tree_data["workspace_id"] == workspace_id
        assert tree_data["total_entries"] >= 2
        file_names = [n["name"] for n in tree_data["tree"]]
        assert "src" in file_names
        assert "README.md" in file_names

        # Cleanup created entity from DB
        async with AsyncSessionLocal() as session:
            ws = await WorkspaceService.get_workspace_by_id(session, uuid.UUID(workspace_id))
            await session.delete(ws)
            await session.commit()


@pytest.mark.asyncio
async def test_invalid_and_traversal_paths_rejected():
    """Verify API and security boundaries reject nonexistent and traversal paths."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Nonexistent path
        resp = await client.post(
            "/api/v1/workspaces",
            json={"name": "fake", "root_path": "/nonexistent/path/xyz_987"},
        )
        assert resp.status_code == 400

    # Path traversal validation
    with (
        tempfile.TemporaryDirectory() as tmpdir,
        pytest.raises(SecurityViolationException),
    ):
        resolve_safe_path(tmpdir, "../outside.txt")


@pytest.mark.asyncio
async def test_llm_info_endpoint():
    """Verify GET /api/v1/llm/info returns active model metadata without secrets."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/llm/info")
        assert response.status_code == 200
        data = response.json()
        assert "provider" in data
        assert "model" in data
        assert "display_name" in data
        assert "capabilities" in data
        assert "api_key" not in data
        assert "secret" not in data
