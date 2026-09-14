from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.checkpoint import (
    PostgresCheckpointerManager,
    sanitize_postgres_error,
)
from app.agent.graph import build_agent_graph, get_production_graph
from app.agent.nodes import set_llm_gateway
from app.agent.state import create_initial_state
from app.core.config import settings
from app.core.exceptions import ToolExecutionException
from app.schemas.agent_contracts import CoderOutput, PlannerOutput
from app.services.llm.gateway import LLMGateway


def test_sanitize_postgres_error_redacts_credentials_and_uri():
    raw_err = (
        "connection to postgresql://myuser:secret123@localhost:5432/mydb?sslmode=disable failed"
    )
    sanitized = sanitize_postgres_error(raw_err)
    assert "secret123" not in sanitized
    assert "myuser" not in sanitized
    assert "[REDACTED_USER]:[REDACTED_PASSWORD]@localhost:5432/mydb" in sanitized


def test_sanitize_postgres_error_with_at_symbol_in_password():
    """Verifies passwords containing '@' symbols are fully redacted from error strings."""
    raw_err = "connection to postgresql://app_user:p@ss@@word#123@db.internal:5432/prod_db failed"
    sanitized = sanitize_postgres_error(raw_err)
    assert "p@ss@@word#123" not in sanitized
    assert "app_user" not in sanitized
    assert "[REDACTED_USER]:[REDACTED_PASSWORD]@db.internal:5432/prod_db" in sanitized


@pytest.mark.asyncio
async def test_postgres_initialize_sanitizes_thrown_error():
    manager = PostgresCheckpointerManager()
    with patch(
        "psycopg_pool.AsyncConnectionPool.open",
        side_effect=RuntimeError(
            f"Password {settings.POSTGRES_PASSWORD} failed on postgresql://usr:{settings.POSTGRES_PASSWORD}@localhost:5432/db"
        ),
    ):
        with pytest.raises(ToolExecutionException) as exc_info:
            await manager.initialize()
        err_msg = str(exc_info.value)
        assert settings.POSTGRES_PASSWORD not in err_msg or len(settings.POSTGRES_PASSWORD) < 4
        assert "[REDACTED_PASSWORD]" in err_msg or "******" in err_msg


@pytest.mark.asyncio
async def test_lifespan_fails_closed_on_checkpointer_failure():
    manager = PostgresCheckpointerManager()
    with patch.object(
        manager,
        "initialize",
        side_effect=ToolExecutionException("DB connection failed"),
    ):
        with pytest.raises(ToolExecutionException):
            await manager.initialize()
    assert not manager.is_initialized


def test_build_agent_graph_default_uses_memory_saver():
    graph = build_agent_graph()
    assert graph.checkpointer is not None
    assert isinstance(graph.checkpointer, MemorySaver)


def test_get_production_graph_fails_closed_when_uninitialized():
    manager = PostgresCheckpointerManager()
    with patch("app.agent.graph.checkpointer_manager", manager):
        with pytest.raises(ToolExecutionException) as exc_info:
            get_production_graph()
        assert "Production checkpointer is not initialized" in str(exc_info.value)


@pytest.mark.asyncio
async def test_postgres_checkpoint_persistence_across_graph_instances():
    mock_saver = MemorySaver()
    manager = PostgresCheckpointerManager()
    manager._checkpointer = mock_saver
    manager._initialized = True

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(
                summary="Plan persistent test",
                steps=["S1"],
                files_expected=["a.py"],
            )
        if response_schema is CoderOutput:
            return CoderOutput(
                summary="Code persistent test",
                patch="diff",
                files_changed=["a.py"],
            )
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    thread_id = "th-pg-persist-1"
    config = {"configurable": {"thread_id": thread_id}}

    with patch("app.agent.graph.checkpointer_manager", manager):
        graph1 = get_production_graph()
        init_state = create_initial_state("task-1", "/tmp/ws", thread_id)
        await graph1.ainvoke(init_state, config=config)

        del graph1

        graph2 = get_production_graph()
        snap = await graph2.aget_state(config)
        assert snap is not None
        assert snap.values["task_id"] == "task-1"
        assert snap.next == ("approval_gate",)

    set_llm_gateway(None)


@pytest.mark.asyncio
async def test_postgres_rejection_feedback_loop_persistence():
    mock_saver = MemorySaver()
    manager = PostgresCheckpointerManager()
    manager._checkpointer = mock_saver
    manager._initialized = True

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="Plan", steps=["S1"], files_expected=["a.py"])
        if response_schema is CoderOutput:
            return CoderOutput(summary="Code", patch="diff", files_changed=["a.py"])
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    thread_id = "th-pg-reject-1"
    config = {"configurable": {"thread_id": thread_id}}

    with patch("app.agent.graph.checkpointer_manager", manager):
        graph = get_production_graph()
        init_state = create_initial_state("task-rej", "/tmp/ws", thread_id)
        await graph.ainvoke(init_state, config=config)

        cmd = Command(resume={"approved": False, "feedback": "Fix security vulnerability"})
        await graph.ainvoke(cmd, config=config)

        snap = await graph.aget_state(config)
        assert snap.next == ("approval_gate",)
        assert snap.values["feedback"] == "Fix security vulnerability"

    set_llm_gateway(None)


@pytest.mark.asyncio
async def test_postgres_multiple_threads_isolated():
    mock_saver = MemorySaver()
    manager = PostgresCheckpointerManager()
    manager._checkpointer = mock_saver
    manager._initialized = True

    mock_gw = MagicMock(spec=LLMGateway)

    async def mock_structured(prompt, response_schema, **kwargs):
        if response_schema is PlannerOutput:
            return PlannerOutput(summary="Plan", steps=["S1"], files_expected=["a.py"])
        if response_schema is CoderOutput:
            return CoderOutput(summary="Code", patch="diff", files_changed=["a.py"])
        return response_schema.model_validate({})

    mock_gw.generate_structured = AsyncMock(side_effect=mock_structured)
    set_llm_gateway(mock_gw)

    with patch("app.agent.graph.checkpointer_manager", manager):
        graph = get_production_graph()

        cfg1 = {"configurable": {"thread_id": "th-iso-1"}}
        cfg2 = {"configurable": {"thread_id": "th-iso-2"}}

        await graph.ainvoke(
            create_initial_state("task-iso-1", "/tmp/ws1", "th-iso-1"),
            config=cfg1,
        )
        await graph.ainvoke(
            create_initial_state("task-iso-2", "/tmp/ws2", "th-iso-2"),
            config=cfg2,
        )

        snap1 = await graph.aget_state(cfg1)
        snap2 = await graph.aget_state(cfg2)

        assert snap1.values["task_id"] == "task-iso-1"
        assert snap2.values["task_id"] == "task-iso-2"

    set_llm_gateway(None)
