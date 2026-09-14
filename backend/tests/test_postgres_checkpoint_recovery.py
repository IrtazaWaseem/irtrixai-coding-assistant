import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agent.graph import build_agent_graph
from app.agent.nodes import set_execution_service, set_llm_gateway
from app.agent.state import create_initial_state
from app.db.base import Base
from app.db.models import Task, TaskStatus, Workspace
from app.schemas.agent_contracts import (
    CoderOutput,
    FinalizationStatus,
    PlannerOutput,
    ReviewerOutput,
)
from app.services.llm.gateway import LLMGateway
from app.services.task_service import TaskService

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def event_loop_policy():
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


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


def get_test_postgres_uri() -> str:
    user = os.getenv("TEST_POSTGRES_USER", "postgres")
    password = os.getenv("TEST_POSTGRES_PASSWORD", "test_secure_password_123")
    host = os.getenv("TEST_POSTGRES_HOST", "localhost")
    port = os.getenv("TEST_POSTGRES_PORT", "15432")
    db = os.getenv("TEST_POSTGRES_DB", "irtrixai_test")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def get_test_postgres_async_uri() -> str:
    return get_test_postgres_uri().replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest_asyncio.fixture
async def live_postgres_pool():
    """Sets up an AsyncConnectionPool and initializes LangGraph checkpoint tables in real PostgreSQL."""
    uri = get_test_postgres_uri()
    pool = AsyncConnectionPool(
        conninfo=uri,
        max_size=10,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=False,
    )
    try:
        await pool.open()
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
    except Exception as exc:
        if pool is not None:
            await pool.close()
        pytest.fail(
            f"Failed to connect to test PostgreSQL checkpointer at {uri}. "
            f"Ensure test container is running via 'docker-compose -f docker-compose.test.yml up -d'. Error: {exc}"
        )

    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def live_db_session_factory():
    """Provides sessionmaker for real PostgreSQL task tables."""
    async_uri = get_test_postgres_async_uri()
    try:
        engine = create_async_engine(async_uri, echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        pytest.fail(
            f"Failed to connect to test PostgreSQL database at {async_uri}. "
            f"Ensure test container is running via 'docker-compose -f docker-compose.test.yml up -d'. Error: {exc}"
        )

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_postgres_checkpoint_persistence_across_graph_instances(
    tmp_path: Path, live_postgres_pool
):
    """Proves Graph Instance B recovers exact state written by discarded Graph Instance A."""
    ws_path = tmp_path / "ws_pg_chk_persist"
    ws_path.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_path)

    thread_id = f"thread-persist-{uuid.uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="Plan", steps=["S1"], files_expected=["a.py"])
        if response_schema is CoderOutput:
            return CoderOutput(summary="Code", patch="diff", files_changed=["a.py"])
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

    try:
        saver_a = AsyncPostgresSaver(live_postgres_pool)
        graph_a = build_agent_graph(checkpointer=saver_a)

        initial_state = create_initial_state("task-persist-1", str(ws_path), thread_id)
        await graph_a.ainvoke(initial_state, config=config)

        snap_a = await graph_a.aget_state(config)
        assert snap_a.next == ("approval_gate",)
        assert snap_a.values["task_id"] == "task-persist-1"

        del graph_a
        del saver_a

        saver_b = AsyncPostgresSaver(live_postgres_pool)
        graph_b = build_agent_graph(checkpointer=saver_b)

        snap_b = await graph_b.aget_state(config)
        assert snap_b is not None
        assert snap_b.next == ("approval_gate",)
        assert snap_b.values["task_id"] == "task-persist-1"
        assert snap_b.values.get("pending_patch") == "diff"

        resume_cmd = Command(resume={"approved": True, "feedback": "Approved on B"})
        await graph_b.ainvoke(resume_cmd, config=config)

        post_resume_snap = await graph_b.aget_state(config)
        assert post_resume_snap.next == ()
        assert post_resume_snap.values["final_result"].status == FinalizationStatus.COMPLETED
    finally:
        set_llm_gateway(None)
        set_execution_service(None)


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_postgres_reconciliation_integration(
    tmp_path: Path, live_db_session_factory, live_postgres_pool
):
    """Proves reconcile_task_status updates real PostgreSQL task rows based on checkpoint data."""
    ws_path = tmp_path / "ws_real_recon"
    ws_path.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_path)

    saver = AsyncPostgresSaver(live_postgres_pool)
    graph = build_agent_graph(checkpointer=saver)

    async with live_db_session_factory() as session:
        ws = Workspace(name="ws_recon_test", root_path=str(ws_path))
        session.add(ws)
        await session.flush()

        task = Task(workspace_id=ws.id, prompt="Test reconciliation", status=TaskStatus.RUNNING)
        session.add(task)
        await session.commit()
        t_id = str(task.id)

    # 1. Stale RUNNING task with no checkpoint -> reconciles to FAILED
    async with live_db_session_factory() as session:
        db_task = await TaskService.get_task(session, t_id)
        reconciled = await TaskService.reconcile_task_status(session, db_task, graph)
        assert reconciled.status == TaskStatus.FAILED

    # 2. Reconcile with active graph execution at approval_gate
    thread_id = db_task.thread_id
    config = {"configurable": {"thread_id": thread_id}}

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="Plan", steps=["S1"], files_expected=["a.py"])
        if response_schema is CoderOutput:
            return CoderOutput(summary="Code", patch="diff", files_changed=["a.py"])
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

    try:
        init_state = create_initial_state(t_id, str(ws_path), thread_id)
        await graph.ainvoke(init_state, config=config)

        async with live_db_session_factory() as session:
            db_task = await TaskService.get_task(session, t_id)
            db_task.status = TaskStatus.RUNNING
            await session.commit()

            reconciled = await TaskService.reconcile_task_status(session, db_task, graph)
            assert reconciled.status == TaskStatus.AWAITING_APPROVAL

        # 3. Resume graph to completion (completed checkpoint -> reconciles to COMPLETED)
        resume_cmd = Command(resume={"approved": True, "feedback": "Proceed"})
        await graph.ainvoke(resume_cmd, config=config)

        snap_completed = await graph.aget_state(config)
        assert snap_completed is not None
        assert snap_completed.next == ()

        async with live_db_session_factory() as session:
            db_task = await TaskService.get_task(session, t_id)
            db_task.status = TaskStatus.RUNNING
            await session.commit()

            reconciled = await TaskService.reconcile_task_status(session, db_task, graph)
            assert reconciled.status == TaskStatus.COMPLETED

        # 4. Checkpoint with aborted final_result -> reconciles to CANCELLED
        await graph.aupdate_state(
            config,
            {"final_result": {"status": "aborted", "summary": "Halted"}},
            as_node="finalize",
        )

        snap_aborted = await graph.aget_state(config)
        assert snap_aborted is not None
        assert snap_aborted.next == ()
        assert snap_aborted.values.get("final_result") == {
            "status": "aborted",
            "summary": "Halted",
        }

        async with live_db_session_factory() as session:
            db_task = await TaskService.get_task(session, t_id)
            db_task.status = TaskStatus.RUNNING
            await session.commit()

            reconciled = await TaskService.reconcile_task_status(session, db_task, graph)
            assert reconciled.status == TaskStatus.CANCELLED
    finally:
        set_llm_gateway(None)
        set_execution_service(None)
