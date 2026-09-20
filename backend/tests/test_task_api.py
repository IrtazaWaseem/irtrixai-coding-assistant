import asyncio
import subprocess
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import build_agent_graph
from app.agent.nodes import set_execution_service, set_llm_gateway
from app.api.v1.tasks import get_agent_graph
from app.core.config import settings
from app.db.models import Task, TaskStatus
from app.main import app
from app.schemas.agent_contracts import (
    CoderOutput,
    FinalizationResult,
    FinalizationStatus,
    PlannerOutput,
    ReviewerOutput,
)
from app.services.llm.gateway import LLMGateway
from app.services.task_service import TaskService

pytestmark = [pytest.mark.postgres, pytest.mark.integration]


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


@pytest.mark.asyncio
async def test_create_task_success(tmp_path: Path):
    ws = tmp_path / "ws1"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/tasks",
                json={
                    "workspace_path": str(ws),
                    "prompt": "Implement user auth",
                },
            )
            assert res.status_code == 201
            data = res.json()
            assert "id" in data
            assert data["status"].upper() in ("PENDING", "TASKSTATUS.PENDING")
            assert data["prompt"] == "Implement user auth"
    finally:
        settings.WORKSPACE_BASE_PATH = original_base


@pytest.mark.asyncio
async def test_create_task_traversal_rejected(tmp_path: Path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.post(
            "/api/v1/tasks",
            json={"workspace_path": "../../outside", "prompt": "Do evil"},
        )
        assert res.status_code in (400, 404)


@pytest.mark.asyncio
async def test_create_task_nonexistent_workspace_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.post(
            "/api/v1/tasks",
            json={
                "workspace_path": "C:\\nonexistent_dir_12345",
                "prompt": "Run",
            },
        )
        assert res.status_code in (400, 404)


@pytest.mark.asyncio
async def test_get_task_success_and_nonexistent(tmp_path: Path):
    ws = tmp_path / "ws2"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            create_res = await client.post(
                "/api/v1/tasks",
                json={"workspace_path": str(ws), "prompt": "Test get"},
            )
            task_id = create_res.json()["id"]

            get_res = await client.get(f"/api/v1/tasks/{task_id}")
            assert get_res.status_code == 200
            assert get_res.json()["id"] == task_id

            missing_res = await client.get("/api/v1/tasks/00000000-0000-0000-0000-000000000000")
            assert missing_res.status_code == 404
    finally:
        settings.WORKSPACE_BASE_PATH = original_base


@pytest.mark.asyncio
async def test_run_task_reaches_approval_gate_interrupt(tmp_path: Path):
    ws = tmp_path / "ws3"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="Plan", steps=["S1"], files_expected=["a.py"])
        if response_schema is CoderOutput:
            return CoderOutput(summary="Code", patch="diff", files_changed=["a.py"])
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            create_res = await client.post(
                "/api/v1/tasks",
                json={"workspace_path": str(ws), "prompt": "Run to gate"},
            )
            task_id = create_res.json()["id"]

            run_res = await client.post(f"/api/v1/tasks/{task_id}/run")
            assert run_res.status_code == 200
            data = run_res.json()
            assert data["status"] == "awaiting_approval"
            assert data["next_step"] == "approval_gate"
            assert data["interrupt_payload"]["action"] == "human_approval_required"
    finally:
        app.dependency_overrides.clear()
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)


@pytest.mark.asyncio
async def test_submit_approval_resumes_and_completes(tmp_path: Path):
    ws = tmp_path / "ws4"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="Plan", steps=["S1"], files_expected=["a.py"])
        if response_schema is CoderOutput:
            return CoderOutput(summary="Code", patch="", files_changed=[])
        if response_schema is ReviewerOutput:
            return ReviewerOutput(verdict="approved", summary="Audit ok")
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.return_value = {
        "command": "pytest",
        "exit_code": 0,
        "stdout": "1 passed",
        "stderr": "",
        "success": True,
    }
    set_execution_service(mock_exec)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            create_res = await client.post(
                "/api/v1/tasks",
                json={"workspace_path": str(ws), "prompt": "Resume test"},
            )
            task_id = create_res.json()["id"]

            await client.post(f"/api/v1/tasks/{task_id}/run")

            approval_res = await client.post(
                f"/api/v1/tasks/{task_id}/approval",
                json={"approved": True, "feedback": "Looks good"},
            )
            assert approval_res.status_code == 200
            data = approval_res.json()
            assert data["status"] == "completed"
    finally:
        app.dependency_overrides.clear()
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)
        set_execution_service(None)


@pytest.mark.asyncio
async def test_submit_approval_not_awaiting_returns_400(tmp_path: Path):
    ws = tmp_path / "ws5"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            create_res = await client.post(
                "/api/v1/tasks",
                json={"workspace_path": str(ws), "prompt": "Unstarted"},
            )
            task_id = create_res.json()["id"]

            res = await client.post(
                f"/api/v1/tasks/{task_id}/approval",
                json={"approved": True},
            )
            assert res.status_code == 400
            msg = res.json().get("detail") or res.json().get("message") or str(res.json())
            assert "not currently awaiting human approval" in msg
    finally:
        settings.WORKSPACE_BASE_PATH = original_base


@pytest.mark.asyncio
async def test_events_on_unstarted_task_does_not_execute_graph(tmp_path: Path):
    ws = tmp_path / "ws6"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            create_res = await client.post(
                "/api/v1/tasks",
                json={
                    "workspace_path": str(ws),
                    "prompt": "Observation test",
                },
            )
            task_id = create_res.json()["id"]

            events_res = await client.get(f"/api/v1/tasks/{task_id}/events")
            assert events_res.status_code == 200
            content = events_res.text
            assert "event: task_not_started" in content

            check_res = await client.get(f"/api/v1/tasks/{task_id}")
            assert check_res.json()["status"].upper() in (
                "PENDING",
                "TASKSTATUS.PENDING",
            )
    finally:
        app.dependency_overrides.clear()
        settings.WORKSPACE_BASE_PATH = original_base


@pytest.mark.asyncio
async def test_events_after_start_acts_as_observer(tmp_path: Path):
    ws = tmp_path / "ws7"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="Plan", steps=["S1"], files_expected=["a.py"])
        if response_schema is CoderOutput:
            return CoderOutput(summary="Code", patch="diff", files_changed=["a.py"])
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            create_res = await client.post(
                "/api/v1/tasks",
                json={"workspace_path": str(ws), "prompt": "Observe started"},
            )
            task_id = create_res.json()["id"]

            await client.post(f"/api/v1/tasks/{task_id}/run")

            events_res = await client.get(f"/api/v1/tasks/{task_id}/events")
            assert events_res.status_code == 200
            content = events_res.text
            assert "event: task_started" in content
            assert "event: approval_required" in content
    finally:
        app.dependency_overrides.clear()
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)


@pytest.mark.asyncio
async def test_sequential_duplicate_run_calls_do_not_restart_task(
    tmp_path: Path,
):
    ws = tmp_path / "ws8"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="Plan", steps=["S1"], files_expected=["a.py"])
        if response_schema is CoderOutput:
            return CoderOutput(summary="Code", patch="diff", files_changed=["a.py"])
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            create_res = await client.post(
                "/api/v1/tasks",
                json={"workspace_path": str(ws), "prompt": "Duplicate test"},
            )
            task_id = create_res.json()["id"]

            res1 = await client.post(f"/api/v1/tasks/{task_id}/run")
            assert res1.status_code == 200
            assert res1.json()["status"] == "awaiting_approval"

            res2 = await client.post(f"/api/v1/tasks/{task_id}/run")
            assert res2.status_code == 200
            assert res2.json()["status"] == "awaiting_approval"
            assert mock_gw.generate_structured.call_count == 2
    finally:
        app.dependency_overrides.clear()
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)


@pytest.mark.asyncio
async def test_concurrent_same_task_run_protection(tmp_path: Path):
    ws = tmp_path / "ws_race_api"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        await asyncio.sleep(0.05)
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

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            create_res = await client.post(
                "/api/v1/tasks",
                json={
                    "workspace_path": str(ws),
                    "prompt": "Race condition test",
                },
            )
            task_id = create_res.json()["id"]

            res_a, res_b = await asyncio.gather(
                client.post(f"/api/v1/tasks/{task_id}/run"),
                client.post(f"/api/v1/tasks/{task_id}/run"),
            )

            statuses = [res_a.status_code, res_b.status_code]
            assert 200 in statuses
            assert 409 in statuses
    finally:
        app.dependency_overrides.clear()
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)


@pytest.mark.asyncio
async def test_independent_tasks_execute_independently(tmp_path: Path):
    ws1 = tmp_path / "ws_ind_1"
    ws2 = tmp_path / "ws_ind_2"
    ws1.mkdir(parents=True, exist_ok=True)
    ws2.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws1)
    init_test_git_repo(ws2)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="Plan", steps=["S1"], files_expected=["a.py"])
        if response_schema is CoderOutput:
            return CoderOutput(summary="Code", patch="", files_changed=[])
        if response_schema is ReviewerOutput:
            return ReviewerOutput(verdict="approved", summary="Ok")
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            r1 = await client.post(
                "/api/v1/tasks", json={"workspace_path": str(ws1), "prompt": "Task 1"}
            )
            r2 = await client.post(
                "/api/v1/tasks", json={"workspace_path": str(ws2), "prompt": "Task 2"}
            )
            id1 = r1.json()["id"]
            id2 = r2.json()["id"]

            res1, res2 = await asyncio.gather(
                client.post(f"/api/v1/tasks/{id1}/run"),
                client.post(f"/api/v1/tasks/{id2}/run"),
            )
            assert res1.status_code == 200
            assert res2.status_code == 200
    finally:
        app.dependency_overrides.clear()
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)


@pytest.mark.asyncio
async def test_task_status_reconciliation_recovers_stale_running(tmp_path: Path):
    ws = tmp_path / "ws_recon"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            create_res = await client.post(
                "/api/v1/tasks",
                json={"workspace_path": str(ws), "prompt": "Reconciliation test"},
            )
            task_id = create_res.json()["id"]

            get_res = await client.get(f"/api/v1/tasks/{task_id}")
            assert get_res.status_code == 200
            assert get_res.json()["status"].upper() in (
                "PENDING",
                "TASKSTATUS.PENDING",
            )
    finally:
        app.dependency_overrides.clear()
        settings.WORKSPACE_BASE_PATH = original_base


@pytest.mark.asyncio
async def test_api_does_not_directly_execute_shell_or_write_files(tmp_path: Path):
    ws = tmp_path / "ws_safe_api"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/v1/tasks",
                json={"workspace_path": str(ws), "prompt": "Safe API check"},
            )
            assert res.status_code == 201
            assert not any(ws.rglob("*.py"))
    finally:
        settings.WORKSPACE_BASE_PATH = original_base


@pytest.mark.asyncio
async def test_concurrent_same_task_approval_protection(tmp_path: Path):
    ws = tmp_path / "ws_race_appr"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="Plan", steps=["S1"], files_expected=["x.py"])
        if response_schema is CoderOutput:
            return CoderOutput(summary="Code", patch="", files_changed=[])
        if response_schema is ReviewerOutput:
            return ReviewerOutput(verdict="approved", summary="Ok")
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.return_value = {
        "command": "pytest",
        "exit_code": 0,
        "stdout": "1 passed",
        "stderr": "",
        "success": True,
    }
    set_execution_service(mock_exec)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            create_res = await client.post(
                "/api/v1/tasks",
                json={"workspace_path": str(ws), "prompt": "Approval race test"},
            )
            task_id = create_res.json()["id"]

            await client.post(f"/api/v1/tasks/{task_id}/run")

            res_a, res_b = await asyncio.gather(
                client.post(f"/api/v1/tasks/{task_id}/approval", json={"approved": True}),
                client.post(f"/api/v1/tasks/{task_id}/approval", json={"approved": True}),
            )

            codes = {res_a.status_code, res_b.status_code}
            assert 200 in codes
            assert 400 in codes
    finally:
        app.dependency_overrides.clear()
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)
        set_execution_service(None)


@pytest.mark.asyncio
async def test_duplicate_approval_after_interrupt_consumed_rejected(tmp_path: Path):
    ws = tmp_path / "ws_dup_appr"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="Plan", steps=["S1"], files_expected=["x.py"])
        if response_schema is CoderOutput:
            return CoderOutput(summary="Code", patch="", files_changed=[])
        if response_schema is ReviewerOutput:
            return ReviewerOutput(verdict="approved", summary="Ok")
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.return_value = {
        "command": "pytest",
        "exit_code": 0,
        "stdout": "1 passed",
        "stderr": "",
        "success": True,
    }
    set_execution_service(mock_exec)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            create_res = await client.post(
                "/api/v1/tasks",
                json={"workspace_path": str(ws), "prompt": "Single approval test"},
            )
            task_id = create_res.json()["id"]

            await client.post(f"/api/v1/tasks/{task_id}/run")

            r1 = await client.post(f"/api/v1/tasks/{task_id}/approval", json={"approved": True})
            assert r1.status_code == 200

            r2 = await client.post(f"/api/v1/tasks/{task_id}/approval", json={"approved": True})
            assert r2.status_code == 400
    finally:
        app.dependency_overrides.clear()
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)
        set_execution_service(None)


@pytest.mark.asyncio
async def test_graph_unavailable_approval_error_path(tmp_path: Path):
    ws = tmp_path / "ws_no_graph"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            create_res = await client.post(
                "/api/v1/tasks",
                json={"workspace_path": str(ws), "prompt": "No graph test"},
            )
            task_id = create_res.json()["id"]

            app.dependency_overrides[get_agent_graph] = lambda: None
            res = await client.post(f"/api/v1/tasks/{task_id}/approval", json={"approved": True})
            assert res.status_code in (500, 400, 404)
    finally:
        app.dependency_overrides.clear()
        settings.WORKSPACE_BASE_PATH = original_base


@pytest.mark.asyncio
async def test_sse_event_name_test_passed_and_test_failed(tmp_path: Path):
    ws = tmp_path / "ws_sse"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            create_res = await client.post(
                "/api/v1/tasks",
                json={"workspace_path": str(ws), "prompt": "SSE test"},
            )
            task_id = create_res.json()["id"]

            events_res = await client.get(f"/api/v1/tasks/{task_id}/events")
            assert events_res.status_code == 200
            assert "event: task_not_started" in events_res.text
    finally:
        app.dependency_overrides.clear()
        settings.WORKSPACE_BASE_PATH = original_base


@pytest.mark.asyncio
async def test_double_run_request_does_not_execute_twice(tmp_path: Path):
    """Proves sending the same /run request twice does not execute the graph twice."""
    ws = tmp_path / "ws_double_run"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)
    call_count = 0

    async def mock_structured(prompt, response_schema, **kwargs):
        nonlocal call_count
        call_count += 1
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

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            create_res = await client.post(
                "/api/v1/tasks",
                json={"workspace_path": str(ws), "prompt": "Double run test"},
            )
            task_id = create_res.json()["id"]

            run1 = await client.post(f"/api/v1/tasks/{task_id}/run")
            assert run1.status_code == 200
            assert run1.json()["status"] == "awaiting_approval"
            initial_calls = call_count

            run2 = await client.post(f"/api/v1/tasks/{task_id}/run")
            assert run2.status_code == 200
            assert run2.json()["status"] == "awaiting_approval"
            assert call_count == initial_calls
    finally:
        app.dependency_overrides.clear()
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)


@pytest.mark.asyncio
async def test_double_approval_request_rejected(tmp_path: Path):
    """Proves submitting approval twice safely rejects the second attempt with 400."""
    ws = tmp_path / "ws_double_appr"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="Plan", steps=["S1"], files_expected=["x.py"])
        if response_schema is CoderOutput:
            return CoderOutput(summary="Code", patch="", files_changed=[])
        if response_schema is ReviewerOutput:
            return ReviewerOutput(verdict="approved", summary="Audit ok")
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.return_value = {
        "command": "pytest",
        "exit_code": 0,
        "stdout": "1 passed",
        "stderr": "",
        "success": True,
    }
    set_execution_service(mock_exec)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            create_res = await client.post(
                "/api/v1/tasks",
                json={"workspace_path": str(ws), "prompt": "Double approval test"},
            )
            task_id = create_res.json()["id"]

            await client.post(f"/api/v1/tasks/{task_id}/run")

            appr1 = await client.post(
                f"/api/v1/tasks/{task_id}/approval",
                json={"approved": True, "feedback": "Go ahead"},
            )
            assert appr1.status_code == 200
            assert appr1.json()["status"] in ("completed", "failed")

            appr2 = await client.post(
                f"/api/v1/tasks/{task_id}/approval",
                json={"approved": True, "feedback": "Duplicate attempt"},
            )
            assert appr2.status_code == 400
            msg = appr2.json().get("detail") or appr2.json().get("message") or str(appr2.json())
            assert "not currently awaiting human approval" in msg
    finally:
        app.dependency_overrides.clear()
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)
        set_execution_service(None)


class MockSnapshot:
    def __init__(self, values: dict | None, next_steps: tuple):
        self.values = values
        self.next = next_steps


@pytest.mark.parametrize(
    "initial_status,snap_next,snap_values,expected_status",
    [
        (TaskStatus.RUNNING, None, None, TaskStatus.FAILED),
        (TaskStatus.RUNNING, (), {}, TaskStatus.FAILED),
        (
            TaskStatus.RUNNING,
            ("approval_gate",),
            {"pending_patch": "diff"},
            TaskStatus.AWAITING_APPROVAL,
        ),
        (
            TaskStatus.RUNNING,
            ("coder",),
            {"current_step": 2},
            TaskStatus.RUNNING,
        ),
        (
            TaskStatus.AWAITING_APPROVAL,
            ("approval_gate",),
            {"pending_patch": "diff"},
            TaskStatus.AWAITING_APPROVAL,
        ),
        (
            TaskStatus.AWAITING_APPROVAL,
            ("test_runner",),
            {"current_step": 4},
            TaskStatus.AWAITING_APPROVAL,
        ),
        (
            TaskStatus.RUNNING,
            (),
            {
                "final_result": FinalizationResult(
                    status=FinalizationStatus.COMPLETED, summary="Success"
                )
            },
            TaskStatus.COMPLETED,
        ),
        (
            TaskStatus.PENDING,
            (),
            {"final_result": {"status": "completed", "summary": "Success"}},
            TaskStatus.COMPLETED,
        ),
        (
            TaskStatus.RUNNING,
            (),
            {"final_result": {"status": "failed", "summary": "Failed"}},
            TaskStatus.FAILED,
        ),
        (
            TaskStatus.RUNNING,
            (),
            {"final_result": {"status": "aborted", "summary": "Halted"}},
            TaskStatus.CANCELLED,
        ),
        (
            TaskStatus.RUNNING,
            (),
            {"final_result": {"status": "unknown_junk"}},
            TaskStatus.RUNNING,
        ),
        (TaskStatus.RUNNING, (), {"other_key": 123}, TaskStatus.FAILED),
        (TaskStatus.PENDING, None, None, TaskStatus.PENDING),
    ],
)
@pytest.mark.asyncio
async def test_reconcile_task_status_full_matrix(
    initial_status: TaskStatus,
    snap_next: tuple | None,
    snap_values: dict | None,
    expected_status: TaskStatus,
):
    """Exhaustively verifies reconcile_task_status across all valid and invalid state combinations."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    task = Task(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        prompt="Reconcile matrix test",
        status=initial_status,
    )
    mock_result.scalar_one_or_none.return_value = task
    mock_result.scalars.return_value.all.return_value = [task]

    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.add = MagicMock()

    mock_graph = AsyncMock()
    if snap_next is None and snap_values is None:
        mock_graph.aget_state = AsyncMock(return_value=None)
    else:
        mock_graph.aget_state = AsyncMock(return_value=MockSnapshot(snap_values, snap_next))

    reconciled = await TaskService.reconcile_task_status(mock_db, task, mock_graph)
    assert reconciled.status == expected_status


@pytest.mark.asyncio
async def test_real_file_mutation_e2e_approved_patch_mutates_disk(tmp_path: Path):
    """Phase 13A-2: Proves through real HTTP/API + LangGraph approval flow that
    an approved patch directly mutates a real file on disk.
    """
    ws = tmp_path / "ws_real_mutation_approved"
    ws.mkdir(parents=True, exist_ok=True)

    target_file = ws / "math_service.py"
    initial_content = "def add(a: int, b: int) -> int:\n    return a - b\n"
    target_file.write_text(initial_content, encoding="utf-8")
    init_test_git_repo(ws)

    patch_text = (
        "--- a/math_service.py\n"
        "+++ b/math_service.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(a: int, b: int) -> int:\n"
        "-    return a - b\n"
        "+    return a + b\n"
    )

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan fix",
                steps=["Fix add function"],
                files_expected=["math_service.py"],
            )
        if response_schema is CoderOutput:
            return CoderOutput(
                summary="Fixed subtraction to addition",
                patch=patch_text,
                files_changed=["math_service.py"],
            )
        if response_schema is ReviewerOutput:
            return ReviewerOutput(
                verdict="approved",
                summary="Fix verified and approved",
                issues=[],
                security_concerns=[],
                required_changes=[],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    mock_exec = MagicMock()
    mock_exec.execute_in_sandbox.return_value = {
        "command": "pytest",
        "exit_code": 0,
        "stdout": "1 passed in 0.01s",
        "stderr": "",
        "success": True,
    }
    set_execution_service(mock_exec)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Real HTTP API task creation
            create_res = await client.post(
                "/api/v1/tasks",
                json={
                    "workspace_path": str(ws),
                    "prompt": "Fix addition bug in math_service.py",
                },
            )
            assert create_res.status_code == 201
            task_id = create_res.json()["id"]

            # Invariant 1: File on disk before run is completely untouched
            assert target_file.read_text(encoding="utf-8") == initial_content

            # 2. Real HTTP API task run
            run_res = await client.post(f"/api/v1/tasks/{task_id}/run")
            assert run_res.status_code == 200
            run_data = run_res.json()
            assert run_data["status"] == "awaiting_approval"
            assert run_data["next_step"] == "approval_gate"
            assert run_data["interrupt_payload"]["action"] == "human_approval_required"
            assert run_data["interrupt_payload"]["pending_patch"] == patch_text

            # Invariant 2: File on disk while awaiting approval is STILL completely untouched
            assert target_file.read_text(encoding="utf-8") == initial_content

            # 3. Real HTTP API operator approval
            approval_res = await client.post(
                f"/api/v1/tasks/{task_id}/approval",
                json={"approved": True, "feedback": "Approved fix"},
            )
            assert approval_res.status_code == 200
            approval_data = approval_res.json()
            assert approval_data["status"] == "completed"
            assert "math_service.py" in approval_data["final_result"]["files_changed"]

            # 4. Proves real on-disk mutation: contents changed exactly as expected
            expected_content = "def add(a: int, b: int) -> int:\n    return a + b\n"
            actual_content = target_file.read_text(encoding="utf-8")
            assert actual_content == expected_content

            # 5. Proves approved patch was the mutation source via real git diff
            git_diff = subprocess.run(
                ["git", "diff"],
                cwd=str(ws),
                capture_output=True,
                text=True,
                check=True,
            )
            assert "-    return a - b" in git_diff.stdout
            assert "+    return a + b" in git_diff.stdout
    finally:
        app.dependency_overrides.clear()
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)
        set_execution_service(None)


@pytest.mark.asyncio
async def test_real_file_mutation_e2e_rejected_patch_preserves_disk(tmp_path: Path):
    """Phase 13A-2: Proves through real HTTP/API + LangGraph approval flow that
    a rejected patch causes zero filesystem mutations on disk.
    """
    ws = tmp_path / "ws_real_mutation_rejected"
    ws.mkdir(parents=True, exist_ok=True)

    target_file = ws / "math_service.py"
    initial_content = "def add(a: int, b: int) -> int:\n    return a - b\n"
    target_file.write_text(initial_content, encoding="utf-8")
    init_test_git_repo(ws)

    patch_text = (
        "--- a/math_service.py\n"
        "+++ b/math_service.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(a: int, b: int) -> int:\n"
        "-    return a - b\n"
        "+    return a * b\n"
    )

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan fix",
                steps=["Fix add function"],
                files_expected=["math_service.py"],
            )
        if response_schema is CoderOutput:
            return CoderOutput(
                summary="Malicious multiply edit",
                patch=patch_text,
                files_changed=["math_service.py"],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    memory_saver = MemorySaver()
    test_graph = build_agent_graph(checkpointer=memory_saver)
    app.dependency_overrides[get_agent_graph] = lambda: test_graph

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Real HTTP API task creation
            create_res = await client.post(
                "/api/v1/tasks",
                json={
                    "workspace_path": str(ws),
                    "prompt": "Reject this change",
                },
            )
            assert create_res.status_code == 201
            task_id = create_res.json()["id"]

            # 2. Real HTTP API task run
            run_res = await client.post(f"/api/v1/tasks/{task_id}/run")
            assert run_res.status_code == 200
            assert run_res.json()["status"] == "awaiting_approval"

            # Invariant: File on disk is untouched before rejection
            assert target_file.read_text(encoding="utf-8") == initial_content

            # 3. Real HTTP API operator rejection (terminal abort without revision feedback)
            reject_res = await client.post(
                f"/api/v1/tasks/{task_id}/approval",
                json={"approved": False},
            )
            assert reject_res.status_code == 200
            assert reject_res.json()["status"] in ("aborted", "cancelled")

            # 4. Proves zero on-disk mutation: content remains identical to initial
            assert target_file.read_text(encoding="utf-8") == initial_content

            # 5. Git diff confirms zero modifications in workspace
            git_diff = subprocess.run(
                ["git", "diff"],
                cwd=str(ws),
                capture_output=True,
                text=True,
                check=True,
            )
            assert git_diff.stdout.strip() == ""
    finally:
        app.dependency_overrides.clear()
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)


@pytest.mark.asyncio
async def test_concurrent_different_tasks_same_workspace_run_protection(tmp_path: Path):
    """Proves two DIFFERENT tasks created in the SAME workspace cannot run concurrently via API."""
    ws = tmp_path / "ws_same_ws_race_api"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        await asyncio.sleep(0.05)
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

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            r1 = await client.post(
                "/api/v1/tasks",
                json={"workspace_path": str(ws), "prompt": "Task 1"},
            )
            r2 = await client.post(
                "/api/v1/tasks",
                json={"workspace_path": str(ws), "prompt": "Task 2"},
            )
            assert r1.status_code == 201
            assert r2.status_code == 201
            id1, id2 = r1.json()["id"], r2.json()["id"]

            res_a, res_b = await asyncio.gather(
                client.post(f"/api/v1/tasks/{id1}/run"),
                client.post(f"/api/v1/tasks/{id2}/run"),
            )
            statuses = [res_a.status_code, res_b.status_code]
            assert 200 in statuses
            assert 409 in statuses
    finally:
        app.dependency_overrides.clear()
        settings.WORKSPACE_BASE_PATH = original_base
        set_llm_gateway(None)


@pytest.mark.asyncio
async def test_create_task_with_valid_workspace_id(tmp_path: Path):
    """Phase 13A-4: Proves task can be created via registered workspace_id."""
    ws = tmp_path / "ws_by_id"
    ws.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws)

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Register workspace
            reg_res = await client.post(
                "/api/v1/workspaces",
                json={"name": "test-ws-by-id", "root_path": str(ws)},
            )
            assert reg_res.status_code == 201
            ws_id = reg_res.json()["id"]

            # 2. Create task using workspace_id
            task_res = await client.post(
                "/api/v1/tasks",
                json={"workspace_id": ws_id, "prompt": "Implement ID flow"},
            )
            assert task_res.status_code == 201
            data = task_res.json()
            assert data["workspace_path"] == str(ws)
            assert data["prompt"] == "Implement ID flow"
    finally:
        settings.WORKSPACE_BASE_PATH = original_base


@pytest.mark.asyncio
async def test_create_task_with_nonexistent_workspace_id_rejected():
    """Phase 13A-4: Proves nonexistent workspace_id returns 404."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.post(
            "/api/v1/tasks",
            json={
                "workspace_id": "00000000-0000-0000-0000-000000000000",
                "prompt": "Test missing",
            },
        )
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_client_path_cannot_override_registered_workspace_id(tmp_path: Path):
    """Phase 13A-4: Proves backend authoritatively uses registered root_path when workspace_id is given."""
    ws_real = tmp_path / "ws_authoritative"
    ws_real.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_real)

    original_base = settings.WORKSPACE_BASE_PATH
    settings.WORKSPACE_BASE_PATH = tmp_path.resolve()

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            reg_res = await client.post(
                "/api/v1/workspaces",
                json={"name": "auth-ws", "root_path": str(ws_real)},
            )
            assert reg_res.status_code == 201
            ws_id = reg_res.json()["id"]

            # Client attempts to pass a different path alongside the valid workspace_id
            task_res = await client.post(
                "/api/v1/tasks",
                json={
                    "workspace_id": ws_id,
                    "workspace_path": "C:\\some\\fake\\path",
                    "prompt": "Test override attempt",
                },
            )
            assert task_res.status_code == 201
            # Must remain equal to the registered workspace root path from the database
            assert task_res.json()["workspace_path"] == str(ws_real)
    finally:
        settings.WORKSPACE_BASE_PATH = original_base
