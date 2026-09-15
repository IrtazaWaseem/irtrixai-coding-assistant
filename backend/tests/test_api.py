import uuid
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.main import app
from app.services.workspace_service import WorkspaceService


@pytest.fixture
def test_dir(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace_api_test"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "src").mkdir(exist_ok=True)
    (ws / "src" / "main.py").write_text("print('hello')", encoding="utf-8")
    (ws / "README.md").write_text("# Test", encoding="utf-8")
    return ws


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "irtrixai-backend"


@pytest.mark.asyncio
async def test_v1_status_endpoint():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"
        assert data["version"] == "0.1.0"
        assert data["environment"] == settings.ENVIRONMENT


@pytest.mark.asyncio
async def test_cors_headers():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


@pytest.mark.postgres
@pytest.mark.integration
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
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Non-existent workspace
        resp = await client.post(
            "/api/v1/workspaces",
            json={"name": "bad", "root_path": "/nonexistent/path/never/exists"},
        )
        assert resp.status_code == 400

        # Path traversal attempt outside workspace base path
        resp = await client.post(
            "/api/v1/workspaces",
            json={"name": "traversal", "root_path": "../../etc"},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_llm_info_endpoint():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/llm/info")
        assert resp.status_code == 200
        data = resp.json()
        assert "primary_provider" in data
        assert "models" in data
