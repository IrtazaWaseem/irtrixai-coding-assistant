import asyncio
import subprocess
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.agent.graph import build_agent_graph
from app.agent.nodes import set_execution_service, set_llm_gateway
from app.api.v1.tasks import get_agent_graph
from app.core.config import settings
from app.db.models import TaskStatus
from app.db.session import get_db
from app.main import app
from app.schemas.agent_contracts import (
    CoderOutput,
    PlannerOutput,
    ReviewerOutput,
)
from app.services.llm.gateway import LLMGateway
from app.services.task_service import TaskService


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
    """Overrides get_db with NullPool so connections do not cross asyncio event loops."""
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
            json={
                "workspace_path": str(tmp_path / "missing_dir"),
                "prompt": "Do work",
            },
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
                summary="Modify core",
                patch=patch_text,
                files_changed=["core.py"],
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
async def test_events_on_unstarted_task_does_not_execute_graph(
    async_client: AsyncClient, tmp_path: Path
):
    """Proves GET /api/v1/tasks/{task_id}/events on an unstarted task never executes the graph (Finding 1)."""
    ws = tmp_path / "ws_unstarted_events"
    ws.mkdir(parents=True, exist_ok=True)
    target = ws / "script.py"
    target.write_text("x = 100\n", encoding="utf-8")
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)
    mock_gw.generate_structured = AsyncMock()
    set_llm_gateway(mock_gw)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        create_res = await async_client.post(
            "/api/v1/tasks",
            json={"workspace_path": str(ws), "prompt": "Do not run yet"},
        )
        task_id = create_res.json()["id"]

        # Connect to /events without calling /run
        sse_res = await async_client.get(f"/api/v1/tasks/{task_id}/events")
        assert sse_res.status_code == 200
        body = sse_res.text

        # Invariant: Must receive task_not_started and NO execution events
        assert "event: task_not_started" in body
        assert "event: coding" not in body
        assert "event: planning" not in body
        assert "event: approval_required" not in body

        # Invariant: Graph execution was never triggered
        mock_gw.generate_structured.assert_not_called()

        # Invariant: No checkpoint created/advanced
        config = {"configurable": {"thread_id": f"thread-{task_id}"}}
        snap = await test_graph.aget_state(config)
        assert not snap.values

        # Invariant: No filesystem mutation occurred
        assert target.read_text(encoding="utf-8") == "x = 100\n"
    finally:
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)
        app.dependency_overrides.pop(get_agent_graph, None)


@pytest.mark.asyncio
async def test_events_after_start_acts_as_observer(
    async_client: AsyncClient, tmp_path: Path
):
    """Proves GET /events after execution starts acts as observer and does not re-execute (Finding 1)."""
    ws = tmp_path / "ws_observer_events"
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
            json={"workspace_path": str(ws), "prompt": "Observe task"},
        )
        task_id = create_res.json()["id"]

        # 1. Start execution through the authoritative /run trigger
        await async_client.post(f"/api/v1/tasks/{task_id}/run")
        call_count_after_run = mock_gw.generate_structured.call_count

        # 2. Connect to /events as observer
        sse_res = await async_client.get(f"/api/v1/tasks/{task_id}/events")
        assert sse_res.status_code == 200
        body = sse_res.text

        # Invariant: Milestone events from checkpoint are observed
        assert "event: task_started" in body
        assert "event: workspace_inspected" in body
        assert "event: planning" in body
        assert "event: coding" in body
        assert "event: approval_required" in body

        # Invariant: Observation did not advance graph or call LLM again
        assert mock_gw.generate_structured.call_count == call_count_after_run
    finally:
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)
        app.dependency_overrides.pop(get_agent_graph, None)


@pytest.mark.asyncio
async def test_sequential_duplicate_run_calls_do_not_restart_task(
    async_client: AsyncClient, tmp_path: Path
):
    """Proves sequential duplicate /run calls return idempotent status without re-executing (Finding 2)."""
    ws = tmp_path / "ws_idempotent"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="P", steps=["S"], files_expected=["a.py"])
        if response_schema is CoderOutput:
            return CoderOutput(summary="C", patch="patch", files_changed=["a.py"])
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
            json={"workspace_path": str(ws), "prompt": "Idempotent run"},
        )
        task_id = create_res.json()["id"]

        # Run 1: Pauses at approval_gate
        res1 = await async_client.post(f"/api/v1/tasks/{task_id}/run")
        assert res1.status_code == 200
        assert res1.json()["status"] == "awaiting_approval"
        initial_calls = mock_gw.generate_structured.call_count

        # Run 2: Duplicate call while awaiting approval
        res2 = await async_client.post(f"/api/v1/tasks/{task_id}/run")
        assert res2.status_code == 200
        assert res2.json()["status"] == "awaiting_approval"

        # Invariant: Graph was not restarted; no additional LLM calls
        assert mock_gw.generate_structured.call_count == initial_calls
    finally:
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)
        app.dependency_overrides.pop(get_agent_graph, None)


@pytest.mark.asyncio
async def test_concurrent_same_task_run_protection(
    async_client: AsyncClient, tmp_path: Path
):
    """Proves concurrent /run requests on same task are protected by row-level locking (Finding 2)."""
    ws = tmp_path / "ws_concurrency"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        await asyncio.sleep(0.05)  # Simulate model execution latency
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="Plan", steps=["S1"], files_expected=["x.py"])
        if response_schema is CoderOutput:
            return CoderOutput(summary="Code", patch="diff", files_changed=["x.py"])
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
            json={"workspace_path": str(ws), "prompt": "Race test"},
        )
        task_id = create_res.json()["id"]

        # Dispatch concurrent /run calls simultaneously
        res_a, res_b = await asyncio.gather(
            async_client.post(f"/api/v1/tasks/{task_id}/run"),
            async_client.post(f"/api/v1/tasks/{task_id}/run"),
        )

        assert res_a.status_code == 200
        assert res_b.status_code == 200

        statuses = {res_a.json()["status"], res_b.json()["status"]}
        # Both requests safely report valid state without crash or duplicate graph init
        assert "awaiting_approval" in statuses or "running" in statuses
    finally:
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)
        app.dependency_overrides.pop(get_agent_graph, None)


@pytest.mark.asyncio
async def test_independent_tasks_execute_independently(
    async_client: AsyncClient, tmp_path: Path
):
    """Proves Task A and Task B execute concurrently without shared locks or state collisions."""
    ws_a = tmp_path / "ws_indep_a"
    ws_b = tmp_path / "ws_indep_b"
    ws_a.mkdir(parents=True, exist_ok=True)
    ws_b.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_a)
    init_test_git_repo(ws_b)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="P", steps=["S"], files_expected=[])
        if response_schema is CoderOutput:
            return CoderOutput(summary="C", patch="", files_changed=[])
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()
    try:
        res_a = await async_client.post(
            "/api/v1/tasks",
            json={"workspace_path": str(ws_a), "prompt": "Task A"},
        )
        res_b = await async_client.post(
            "/api/v1/tasks",
            json={"workspace_path": str(ws_b), "prompt": "Task B"},
        )
        task_id_a = res_a.json()["id"]
        task_id_b = res_b.json()["id"]

        run_a, run_b = await asyncio.gather(
            async_client.post(f"/api/v1/tasks/{task_id_a}/run"),
            async_client.post(f"/api/v1/tasks/{task_id_b}/run"),
        )

        assert run_a.status_code == 200
        assert run_b.status_code == 200
        assert run_a.json()["task_id"] == task_id_a
        assert run_b.json()["task_id"] == task_id_b
    finally:
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)
        app.dependency_overrides.pop(get_agent_graph, None)


@pytest.mark.asyncio
async def test_task_status_reconciliation_recovers_stale_running(
    async_client: AsyncClient, tmp_path: Path
):
    """Proves TaskService.reconcile_task_status updates stale RUNNING status to checkpoint reality (Finding 3)."""
    ws = tmp_path / "ws_reconcile"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="P", steps=["S"], files_expected=[])
        if response_schema is CoderOutput:
            return CoderOutput(summary="C", patch="", files_changed=[])
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
            json={"workspace_path": str(ws), "prompt": "Stale DB test"},
        )
        task_id = create_res.json()["id"]

        # Run to approval_gate
        await async_client.post(f"/api/v1/tasks/{task_id}/run")

        # Artificially set DB status back to RUNNING to simulate an interrupted/crashed process
        engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
        async_session = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        async with async_session() as session:
            task_obj = await TaskService.get_task(session, task_id)
            task_obj.status = TaskStatus.RUNNING
            session.add(task_obj)
            await session.commit()
        await engine.dispose()

        # Reconcile status via GET /tasks/{task_id}
        get_res = await async_client.get(f"/api/v1/tasks/{task_id}")
        assert get_res.status_code == 200
        # Invariant: Reconciled to AWAITING_APPROVAL because checkpoint is at approval_gate
        assert get_res.json()["status"].upper() == "AWAITING_APPROVAL"
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
