import subprocess
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.agent.graph import build_agent_graph
from app.agent.nodes import set_execution_service, set_llm_gateway
from app.api.v1.tasks import get_agent_graph
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.schemas.agent_contracts import (
    CoderOutput,
    PlannerOutput,
    ReviewerOutput,
)
from app.services.llm.gateway import LLMGateway


def init_test_git_repo(repo_path: Path) -> None:
    """Initializes local git repository in test directory with baseline commit."""
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
    subprocess.run(
        ["git", "add", "."], cwd=str(repo_path), capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )


@pytest.fixture(autouse=True)
async def override_db_session():
    """Overrides get_db with NullPool so asyncpg connections do not cross asyncio event loops."""
    test_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    test_session_maker = async_sessionmaker(
        test_engine, expire_on_commit=False, class_=AsyncSession
    )

    async def _get_test_db():
        async with test_session_maker() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = _get_test_db
    yield
    app.dependency_overrides.pop(get_db, None)
    await test_engine.dispose()


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_create_task_success(async_client: AsyncClient, tmp_path: Path):
    """Proves POST /api/v1/tasks persists task and returns safe metadata."""
    ws = tmp_path / "valid_ws"
    ws.mkdir(parents=True, exist_ok=True)

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        response = await async_client.post(
            "/api/v1/tasks",
            json={
                "workspace_path": str(ws),
                "prompt": "Implement factorial in math.py",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["workspace_path"] == str(ws.resolve())
        assert data["prompt"] == "Implement factorial in math.py"
        assert data["status"].upper() == "PENDING"
        assert data["thread_id"] == f"thread-{data['id']}"
    finally:
        settings.WORKSPACE_BASE_PATH = original_base


@pytest.mark.asyncio
async def test_create_task_traversal_rejected(
    async_client: AsyncClient, tmp_path: Path
):
    """Proves path traversal attempts in workspace_path return 400/404 errors."""
    response = await async_client.post(
        "/api/v1/tasks",
        json={
            "workspace_path": str(tmp_path / "../outside"),
            "prompt": "Exfiltrate /etc/passwd",
        },
    )
    assert response.status_code in (400, 404)


@pytest.mark.asyncio
async def test_create_task_nonexistent_workspace_rejected(
    async_client: AsyncClient, tmp_path: Path
):
    """Proves non-existent workspace path fails closed with 404."""
    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        response = await async_client.post(
            "/api/v1/tasks",
            json={"workspace_path": str(tmp_path / "missing_dir"), "prompt": "Do work"},
        )
        assert response.status_code == 404
        assert "does not exist" in response.text.lower()
    finally:
        settings.WORKSPACE_BASE_PATH = original_base


@pytest.mark.asyncio
async def test_get_task_success_and_nonexistent(
    async_client: AsyncClient, tmp_path: Path
):
    """Proves GET /api/v1/tasks/{task_id} returns task and rejects nonexistent IDs."""
    ws = tmp_path / "ws_lookup"
    ws.mkdir(parents=True, exist_ok=True)

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        create_res = await async_client.post(
            "/api/v1/tasks",
            json={"workspace_path": str(ws), "prompt": "Write hello world"},
        )
        task_id = create_res.json()["id"]

        get_res = await async_client.get(f"/api/v1/tasks/{task_id}")
        assert get_res.status_code == 200
        assert get_res.json()["id"] == task_id

        # Nonexistent lookup
        bad_res = await async_client.get("/api/v1/tasks/nonexistent-task-id-1234")
        assert bad_res.status_code == 404
        assert "not found" in bad_res.text.lower()
    finally:
        settings.WORKSPACE_BASE_PATH = original_base


@pytest.mark.asyncio
async def test_run_task_reaches_approval_gate_interrupt(
    async_client: AsyncClient, tmp_path: Path
):
    """Proves POST /api/v1/tasks/{task_id}/run executes graph and returns awaiting_approval."""
    ws = tmp_path / "ws_run"
    ws.mkdir(parents=True, exist_ok=True)
    target = ws / "core.py"
    target.write_text("x = 1\n", encoding="utf-8")
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)
    patch_text = "--- a/core.py\n+++ b/core.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan", steps=["S1"], files_expected=["core.py"]
            )
        if response_schema is CoderOutput:
            return CoderOutput(
                summary="Modify core", patch=patch_text, files_changed=["core.py"]
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        create_res = await async_client.post(
            "/api/v1/tasks",
            json={"workspace_path": str(ws), "prompt": "Update core"},
        )
        task_id = create_res.json()["id"]

        run_res = await async_client.post(f"/api/v1/tasks/{task_id}/run")
        assert run_res.status_code == 200
        run_data = run_res.json()
        assert run_data["status"] == "awaiting_approval"
        assert run_data["next_step"] == "approval_gate"
        assert run_data["interrupt_payload"]["action"] == "human_approval_required"
        assert run_data["interrupt_payload"]["pending_patch"] == patch_text

        # File remains unmodified on disk before operator approval
        assert target.read_text(encoding="utf-8") == "x = 1\n"
    finally:
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)
        app.dependency_overrides.pop(get_agent_graph, None)


@pytest.mark.asyncio
async def test_submit_approval_resumes_and_completes(
    async_client: AsyncClient, tmp_path: Path
):
    """Proves POST /api/v1/tasks/{task_id}/approval resumes graph and applies approved changes."""
    ws = tmp_path / "ws_approve"
    ws.mkdir(parents=True, exist_ok=True)
    target = ws / "feature.py"
    target.write_text("enabled = False\n", encoding="utf-8")
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)
    patch_text = "--- a/feature.py\n+++ b/feature.py\n@@ -1 +1 @@\n-enabled = False\n+enabled = True\n"

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan", steps=["S1"], files_expected=["feature.py"]
            )
        if response_schema is CoderOutput:
            return CoderOutput(
                summary="Enable feature",
                patch=patch_text,
                files_changed=["feature.py"],
            )
        if response_schema is ReviewerOutput:
            return ReviewerOutput(
                verdict="approved",
                summary="Verified",
                issues=[],
                security_concerns=[],
                required_changes=[],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.return_value = {
        "exit_code": 0,
        "stdout": "1 passed",
        "stderr": "",
        "command": ["pytest"],
        "duration_seconds": 0.5,
        "success": True,
    }
    set_execution_service(mock_exec)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        create_res = await async_client.post(
            "/api/v1/tasks",
            json={"workspace_path": str(ws), "prompt": "Enable feature"},
        )
        task_id = create_res.json()["id"]

        # Run until approval_gate
        await async_client.post(f"/api/v1/tasks/{task_id}/run")

        # Submit approval
        approve_res = await async_client.post(
            f"/api/v1/tasks/{task_id}/approval",
            json={"approved": True, "feedback": "Approved by reviewer"},
        )
        assert approve_res.status_code == 200
        approve_data = approve_res.json()
        assert approve_data["status"] == "completed"

        # File is authoritatively modified after approval
        assert target.read_text(encoding="utf-8") == "enabled = True\n"
    finally:
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)
        set_execution_service(None)
        app.dependency_overrides.pop(get_agent_graph, None)


@pytest.mark.asyncio
async def test_submit_approval_not_awaiting_returns_400(
    async_client: AsyncClient, tmp_path: Path
):
    """Proves submitting approval for a task that is not awaiting approval returns 400 error."""
    ws = tmp_path / "ws_reject"
    ws.mkdir(parents=True, exist_ok=True)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        create_res = await async_client.post(
            "/api/v1/tasks",
            json={"workspace_path": str(ws), "prompt": "Idle task"},
        )
        task_id = create_res.json()["id"]

        # Attempt approval before running
        approve_res = await async_client.post(
            f"/api/v1/tasks/{task_id}/approval",
            json={"approved": True},
        )
        assert approve_res.status_code == 400
        assert "not currently awaiting" in approve_res.text.lower()
    finally:
        settings.WORKSPACE_BASE_PATH = original_base
        app.dependency_overrides.pop(get_agent_graph, None)


@pytest.mark.asyncio
async def test_stream_task_events_sse_format(async_client: AsyncClient, tmp_path: Path):
    """Proves GET /api/v1/tasks/{task_id}/events streams SSE events conforming to text/event-stream."""
    ws = tmp_path / "ws_sse"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan", steps=["S1"], files_expected=["main.py"]
            )
        if response_schema is CoderOutput:
            return CoderOutput(summary="Code", patch="diff", files_changed=["main.py"])
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        create_res = await async_client.post(
            "/api/v1/tasks",
            json={"workspace_path": str(ws), "prompt": "Stream task"},
        )
        task_id = create_res.json()["id"]

        sse_res = await async_client.get(f"/api/v1/tasks/{task_id}/events")
        assert sse_res.status_code == 200
        assert "text/event-stream" in sse_res.headers["content-type"]
        body = sse_res.text

        assert "event: task_started" in body
        assert "event: workspace_inspected" in body
        assert "event: planning" in body
        assert "event: coding" in body
        assert "event: approval_required" in body
    finally:
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)
        app.dependency_overrides.pop(get_agent_graph, None)


@pytest.mark.asyncio
async def test_api_does_not_directly_execute_shell_or_write_files(
    async_client: AsyncClient, tmp_path: Path
):
    """Proves API endpoints carry zero direct filesystem authority and route all mutations via LangGraph."""
    ws = tmp_path / "ws_invariant"
    ws.mkdir(parents=True, exist_ok=True)
    canary = ws / "canary.txt"
    canary.write_text("unaltered\n", encoding="utf-8")

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        res = await async_client.post(
            "/api/v1/tasks",
            json={
                "workspace_path": str(ws),
                "prompt": "Attempt to touch canary directly",
            },
        )
        assert res.status_code == 201
        assert canary.read_text(encoding="utf-8") == "unaltered\n"
        assert len(list(ws.iterdir())) == 1
    finally:
        settings.WORKSPACE_BASE_PATH = original_base
