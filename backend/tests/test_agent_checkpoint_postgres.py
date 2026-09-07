import asyncio
import logging
import socket
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command

from app.agent.checkpoint import (
    PostgresCheckpointerManager,
    sanitize_postgres_error,
)
from app.agent.graph import build_agent_graph, get_production_graph
from app.agent.nodes import set_llm_gateway
from app.agent.state import create_initial_state
from app.core.config import settings
from app.main import lifespan
from app.schemas.agent_contracts import (
    CoderOutput,
    DebuggerOutput,
    PlannerOutput,
    ReviewerOutput,
)
from app.services.llm.gateway import LLMGateway


def is_postgres_available() -> bool:
    """Checks if PostgreSQL is reachable on configured port."""
    try:
        with socket.create_connection(
            (settings.POSTGRES_SERVER, settings.POSTGRES_PORT), timeout=1.0
        ):
            return True
    except (OSError, ConnectionRefusedError):
        return False


# --- Unit Tests: Invariant, Sanitization & Fail-Closed Lifecycle (Run without PostgreSQL) ---


def test_sanitize_postgres_error_redacts_credentials_and_uri():
    """Verifies that database passwords and basic-auth URIs are redacted."""
    raw_secret = settings.POSTGRES_PASSWORD
    err_message = (
        f"psycopg.OperationalError: connection to server at 'localhost', port 5432 failed: "
        f"FATAL: password authentication failed for user 'irtrixai' with password '{raw_secret}' "
        f"at postgresql://irtrixai:{raw_secret}@localhost:5432/irtrixai_db"
    )
    sanitized = sanitize_postgres_error(err_message)

    assert raw_secret not in sanitized
    assert "postgresql://irtrixai:[REDACTED]@localhost:5432/irtrixai_db" in sanitized


@pytest.mark.asyncio
async def test_postgres_initialize_sanitizes_thrown_error(caplog):
    """Proves that PostgresCheckpointerManager never leaks secrets in raised exceptions or logs."""
    fake_secret = "super_secret_pg_pwd_999"
    fake_uri = f"postgresql://irtrixai:{fake_secret}@127.0.0.1:1/irtrixai_db"

    manager = PostgresCheckpointerManager(fake_uri)
    with patch("app.agent.checkpoint.settings.POSTGRES_PASSWORD", fake_secret):
        with caplog.at_level(logging.ERROR):
            with pytest.raises(RuntimeError) as exc_info:
                await asyncio.wait_for(manager.initialize(), timeout=5.0)

            err_str = str(exc_info.value)
            assert fake_secret not in err_str
            assert "[REDACTED]" in err_str or fake_secret not in err_str
            assert fake_secret not in caplog.text


@pytest.mark.asyncio
async def test_lifespan_fails_closed_on_checkpointer_failure():
    """Proves that FastAPI lifespan raises and aborts startup when PostgreSQL checkpointer fails."""
    mock_app = MagicMock()
    with patch(
        "app.agent.checkpoint.checkpointer_manager.initialize",
        side_effect=RuntimeError("Database connection refused"),
    ):
        with pytest.raises(RuntimeError, match="Database connection refused"):
            async with lifespan(mock_app):
                pass  # Must never reach inside context


def test_build_agent_graph_default_uses_memory_saver():
    """Verifies build_agent_graph() without explicit checkpointer uses MemorySaver for unit tests."""
    graph = build_agent_graph()
    assert isinstance(graph.checkpointer, MemorySaver)


def test_get_production_graph_fails_closed_when_uninitialized():
    """Verifies get_production_graph() raises RuntimeError when checkpointer manager is uninitialized."""
    manager = PostgresCheckpointerManager()
    assert not manager.is_initialized
    with patch("app.agent.graph.checkpointer_manager", manager):
        with pytest.raises(RuntimeError, match="not initialized"):
            get_production_graph()


# --- Integration Tests: Live PostgreSQL Persistence & Multi-Thread Isolation ---


@pytest.fixture
def mock_gateway():
    """Provides isolated LLMGateway mock for checkpoint integration tests."""
    mock_gw = MagicMock(spec=LLMGateway)

    async def default_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan created for postgres checkpoint test",
                steps=["Inspect files", "Apply patch"],
                files_expected=["src/main.py"],
            )
        if response_schema is CoderOutput:
            return CoderOutput(
                summary="Code changes proposed",
                requested_changes=["Add endpoint"],
                patch="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n+test\n",
                files_changed=["src/main.py"],
            )
        if response_schema is DebuggerOutput:
            return DebuggerOutput(
                diagnosis="Test assertion failure detected",
                proposed_fix="Correct assertion value",
                files_to_change=["src/main.py"],
            )
        if response_schema is ReviewerOutput:
            return ReviewerOutput(
                verdict="approved",
                summary="Verified in checkpoint integration test",
                issues=[],
                security_concerns=[],
                required_changes=[],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=default_structured)
    set_llm_gateway(mock_gw)
    yield mock_gw
    set_llm_gateway(None)


@pytest.fixture
async def postgres_saver():
    """Manages an isolated AsyncPostgresSaver connected to the live test database."""
    if not is_postgres_available():
        pytest.skip(
            "PostgreSQL is not accessible on localhost:5432. Start database with 'docker compose up -d db'."
        )
    manager = PostgresCheckpointerManager(settings.postgres_uri)
    saver = await manager.initialize()
    yield saver
    await manager.close()


@pytest.mark.asyncio
async def test_postgres_checkpoint_persistence_across_graph_instances(
    postgres_saver: AsyncPostgresSaver, mock_gateway
):
    """Proves that a paused HITL workflow checkpointed in PostgreSQL survives graph destruction and resumes in a NEW graph instance."""
    thread_id = f"thread-pg-test-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}

    # 1. Execute Graph Instance 1 until interrupt
    graph_v1 = build_agent_graph(checkpointer=postgres_saver)
    initial_state = create_initial_state(
        task_id=f"task-{uuid.uuid4().hex[:6]}",
        workspace_path="/test/workspace",
        thread_id=thread_id,
        prompt="Add PostgreSQL checkpointer endpoint",
    )
    initial_state["test_result"] = {
        "success": True,
        "output": "1 passed",
        "is_stub": False,
    }

    await graph_v1.ainvoke(initial_state, config=config)

    state_v1 = await graph_v1.aget_state(config)
    assert state_v1.next == ("approval_gate",)
    assert len(state_v1.tasks[0].interrupts) > 0
    assert state_v1.values.get("approval") is None
    assert state_v1.values.get("final_result") is None

    # 2. Destroy Graph Instance 1
    del graph_v1

    # 3. Create NEW Graph Instance 2 using same checkpointer
    graph_v2 = build_agent_graph(checkpointer=postgres_saver)

    state_v2 = await graph_v2.aget_state(config)
    assert state_v2.next == ("approval_gate",)
    assert state_v2.values["thread_id"] == thread_id
    assert state_v2.values["current_step"] == 3

    # 4. Resume workflow on Graph Instance 2
    resumed = await graph_v2.ainvoke(Command(resume={"approved": True}), config=config)

    # 5. Verify completion
    assert resumed["approval"] is True
    assert resumed["thread_id"] == thread_id
    assert resumed["final_result"] is not None
    assert resumed["final_result"].status == "completed"

    final_state = await graph_v2.aget_state(config)
    assert final_state.next == ()


@pytest.mark.asyncio
async def test_postgres_rejection_feedback_loop_persistence(
    postgres_saver: AsyncPostgresSaver, mock_gateway
):
    """Proves that rejection with feedback persists across graph instances and safely re-interrupts."""
    thread_id = f"thread-pg-reject-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}

    graph_1 = build_agent_graph(checkpointer=postgres_saver)
    initial_state = create_initial_state(
        task_id="task-reject-1",
        workspace_path="/test/workspace",
        thread_id=thread_id,
        prompt="Initial prompt",
    )
    await graph_1.ainvoke(initial_state, config=config)
    assert (await graph_1.aget_state(config)).next == ("approval_gate",)
    del graph_1

    graph_2 = build_agent_graph(checkpointer=postgres_saver)
    await graph_2.ainvoke(
        Command(resume={"approved": False, "feedback": "Add input sanitization"}),
        config=config,
    )

    snapshot = await graph_2.aget_state(config)
    assert snapshot.next == ("approval_gate",)
    assert snapshot.values.get("feedback") == "Add input sanitization"
    assert snapshot.values.get("approval") is None


@pytest.mark.asyncio
async def test_postgres_multiple_threads_isolated(
    postgres_saver: AsyncPostgresSaver, mock_gateway
):
    """Proves that distinct thread_ids have completely isolated checkpoints in PostgreSQL."""
    thread_a = f"thread-A-{uuid.uuid4().hex[:6]}"
    thread_b = f"thread-B-{uuid.uuid4().hex[:6]}"
    config_a = {"configurable": {"thread_id": thread_a}}
    config_b = {"configurable": {"thread_id": thread_b}}

    graph = build_agent_graph(checkpointer=postgres_saver)

    state_a = create_initial_state("task-A", "/ws/a", thread_a, prompt="Task A")
    state_b = create_initial_state("task-B", "/ws/b", thread_b, prompt="Task B")

    await graph.ainvoke(state_a, config=config_a)
    await graph.ainvoke(state_b, config=config_b)

    snap_a = await graph.aget_state(config_a)
    snap_b = await graph.aget_state(config_b)

    assert snap_a.values["task_id"] == "task-A"
    assert snap_b.values["task_id"] == "task-B"
    assert snap_a.next == ("approval_gate",)
    assert snap_b.next == ("approval_gate",)

    await graph.ainvoke(Command(resume={"approved": False}), config=config_a)

    res_a = await graph.aget_state(config_a)
    res_b = await graph.aget_state(config_b)

    assert res_a.next == ()
    assert res_a.values["final_result"].status == "aborted"

    assert res_b.next == ("approval_gate",)
    assert res_b.values.get("final_result") is None
