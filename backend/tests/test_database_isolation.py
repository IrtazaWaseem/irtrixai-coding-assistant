import uuid

import pytest
from conftest import ORIGINAL_DEV_DATABASE_URL, get_test_database_url
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

import app.db.session as session_module
from app.core.config import settings
from app.db.models import Workspace
from app.schemas.workspace import WorkspaceCreate
from app.services.workspace_service import WorkspaceService


@pytest.mark.asyncio
async def test_01_api_created_workspace_persists_within_test(client: AsyncClient, tmp_path):
    """Verify that an API-created workspace is visible within the test itself."""
    name = f"isolation-api-{uuid.uuid4().hex[:8]}"
    res = await client.post("/api/v1/workspaces", json={"name": name, "root_path": str(tmp_path)})
    assert res.status_code == 201
    created_id = res.json()["id"]

    fetch_res = await client.get(f"/api/v1/workspaces/{created_id}")
    assert fetch_res.status_code == 200
    assert fetch_res.json()["name"] == name


@pytest.mark.asyncio
async def test_02_api_created_workspace_does_not_persist_after_test(client: AsyncClient):
    """Verify that the API-created workspace from Test 01 was rolled back completely."""
    res = await client.get("/api/v1/workspaces")
    assert res.status_code == 200
    names = [w["name"] for w in res.json()]
    leakage = [n for n in names if n.startswith("isolation-api-")]
    assert leakage == [], f"Found leaked API workspace in subsequent test: {leakage}"


@pytest.mark.asyncio
async def test_03_service_created_workspace_persists_within_test(
    db_session: AsyncSession, tmp_path
):
    """Verify WorkspaceService operations work within the savepoint."""
    name = f"isolation-srv-{uuid.uuid4().hex[:8]}"
    ws = await WorkspaceService.create_workspace(
        db_session, WorkspaceCreate(name=name, root_path=str(tmp_path))
    )
    assert ws.id is not None

    workspaces = await WorkspaceService.get_all_workspaces(db_session)
    assert any(w.id == ws.id for w in workspaces)


@pytest.mark.asyncio
async def test_04_service_created_workspace_does_not_persist_after_test(
    db_session: AsyncSession,
):
    """Verify that the service-created workspace from Test 03 was rolled back."""
    workspaces = await WorkspaceService.get_all_workspaces(db_session)
    names = [w.name for w in workspaces]
    leakage = [n for n in names if n.startswith("isolation-srv-")]
    assert leakage == [], f"Found leaked service workspace in subsequent test: {leakage}"


@pytest.mark.asyncio
async def test_05_normal_development_database_is_untouched(client: AsyncClient, tmp_path):
    """Verify that the normal development database is never committed to."""
    marker_name = f"isolation-dev-check-{uuid.uuid4().hex[:8]}"
    res = await client.post(
        "/api/v1/workspaces",
        json={"name": marker_name, "root_path": str(tmp_path)},
    )
    assert res.status_code == 201
    created_id = res.json()["id"]

    assert ORIGINAL_DEV_DATABASE_URL is not None
    dev_engine = create_async_engine(ORIGINAL_DEV_DATABASE_URL, poolclass=NullPool, echo=False)
    try:
        async with dev_engine.connect() as conn:
            result = await conn.execute(select(Workspace).where(Workspace.id == created_id))
            row = result.scalar_one_or_none()
            assert row is None, "CRITICAL: Workspace was committed to the development database!"
    finally:
        await dev_engine.dispose()


@pytest.mark.asyncio
async def test_06_background_and_langgraph_db_activity_targets_test_database():
    """Verify that background tasks and LangGraph checkpointers target the test database."""
    test_db_url = get_test_database_url()

    # 1. settings.DATABASE_URL used by LangGraph checkpointer points to test DB
    assert settings.DATABASE_URL == test_db_url

    # 2. engine used by background tasks (app.db.session.engine) points to test DB
    assert session_module.engine.url.render_as_string(hide_password=False) == str(test_db_url)

    # 3. AsyncSessionLocal binds to an engine targeting the test DB
    async with session_module.AsyncSessionLocal() as session:
        session_bind_url = session.bind.url.render_as_string(hide_password=False)
        assert session_bind_url == str(test_db_url)
        assert session_bind_url != str(ORIGINAL_DEV_DATABASE_URL)


def test_07_missing_test_database_url_fails_clearly(monkeypatch):
    """Verify that missing TEST_DATABASE_URL fails clearly without silent fallback."""
    monkeypatch.setattr(settings, "TEST_DATABASE_URL", None)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    with pytest.raises(pytest.fail.Exception, match="TEST_DATABASE_URL is not configured"):
        get_test_database_url()
