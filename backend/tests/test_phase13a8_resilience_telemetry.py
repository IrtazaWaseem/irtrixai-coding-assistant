import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.agent.nodes import finalize, merge_token_usage, reviewer
from app.core.exceptions import (
    LLMAuthenticationException,
    LLMInvalidModelException,
    LLMRateLimitException,
)
from app.schemas.agent_contracts import (
    ReviewerOutput,
    ReviewerVerdict,
)
from app.services.llm.gateway import LLMGateway
from app.services.task_service import TaskService


@pytest.mark.asyncio
async def test_reviewer_rate_limit_skip_with_successful_tests():
    """Requirement A & Acceptance Test A: Rate limited reviewer degrades gracefully without failing task."""
    state = {
        "test_result": {"success": True, "output": "1 passed"},
        "coder_proposal": {"patch": "diff", "files_changed": ["a.py"]},
        "token_usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "llm_calls": 1,
        },
    }

    mock_gateway = MagicMock(spec=LLMGateway)
    mock_gateway.generate_structured = AsyncMock(
        side_effect=LLMRateLimitException("429 ResourceExhausted: rate limit exceeded")
    )

    with patch("app.agent.nodes._resolve_gateway", return_value=mock_gateway):
        result = await reviewer(state)

        assert result["error"] is None
        assert result["review_status"] == "skipped_due_to_rate_limit"
        assert "rate-limited" in result["review_advisory"].lower()
        assert result["review_summary"] is None


@pytest.mark.asyncio
async def test_finalize_completes_after_skipped_review():
    """Requirement B: Finalize completes task when tests pass and review is skipped."""
    state = {
        "approval": True,
        "test_result": {"success": True, "is_stub": False},
        "review_status": "skipped_due_to_rate_limit",
        "review_advisory": "Skipped due to 429",
        "review_summary": None,
        "error": None,
    }

    res = await finalize(state)
    final = res["final_result"]
    assert final.status == "completed"
    assert "Optional code review was skipped" in final.summary
    assert final.metadata["review_status"] == "skipped_due_to_rate_limit"


@pytest.mark.asyncio
async def test_reviewer_rejection_still_prevents_completion():
    """Requirement B: Reviewer rejection still fails the task."""
    state = {
        "approval": True,
        "test_result": {"success": True, "is_stub": False},
        "review_status": "completed",
        "review_summary": ReviewerOutput(
            verdict=ReviewerVerdict.REJECTED,
            summary="Security flaw detected",
            issues=["Flaw"],
            security_concerns=["Dangerous code"],
            required_changes=["Fix it"],
        ),
        "error": None,
    }

    res = await finalize(state)
    assert res["final_result"].status == "failed"


@pytest.mark.asyncio
async def test_invalid_model_primary_uses_fallback():
    """Requirement D & Acceptance Test B: 404/InvalidModel falls back when configured."""
    primary = MagicMock()
    primary.provider_name = "groq"
    primary.model = "invalid-model"
    primary.capabilities = {"supports_structured_output": True}
    primary.generate_structured = AsyncMock(
        side_effect=LLMInvalidModelException("Model does not exist")
    )

    fallback = MagicMock()
    fallback.provider_name = "ollama"
    fallback.model = "qwen"
    fallback.capabilities = {"supports_structured_output": True}
    fallback.last_usage = {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70}
    fallback.generate_structured = AsyncMock(return_value={"status": "ok"})

    gateway = LLMGateway(primary_provider=primary, fallback_provider=fallback)
    result = await gateway.generate_structured("prompt", MagicMock, allow_fallback=True)

    assert result == {"status": "ok"}
    assert gateway.last_used_provider == "ollama"


@pytest.mark.asyncio
async def test_authentication_error_does_not_fallback():
    """Requirement D: Authentication error (401) aborts immediately without fallback."""
    primary = MagicMock()
    primary.provider_name = "gemini"
    primary.capabilities = {"supports_structured_output": True}
    primary.generate_structured = AsyncMock(
        side_effect=LLMAuthenticationException("Invalid API key")
    )

    fallback = MagicMock()
    gateway = LLMGateway(primary_provider=primary, fallback_provider=fallback)

    with pytest.raises(LLMAuthenticationException):
        await gateway.generate_structured("prompt", MagicMock, allow_fallback=True)

    fallback.generate_structured.assert_not_called()


def test_token_accumulation_logic():
    """Requirement G & Acceptance Test C: Cumulative state usage adds up cleanly."""
    state_usage = None
    call_1 = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
    call_2 = {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300}
    call_3 = {"prompt_tokens": 150, "completion_tokens": 75, "total_tokens": 225}

    s = merge_token_usage(state_usage, call_1, "gemini")
    s = merge_token_usage(s, call_2, "gemini")
    s = merge_token_usage(s, call_3, "ollama")

    assert s["prompt_tokens"] == 450
    assert s["completion_tokens"] == 225
    assert s["total_tokens"] == 675
    assert s["llm_calls"] == 3
    assert s["by_provider"]["gemini"]["llm_calls"] == 2
    assert s["by_provider"]["ollama"]["llm_calls"] == 1


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_database_runtime_metric_persistence_and_idempotency(db_session):
    """Requirement I & Acceptance Test C: Metrics sync to PostgreSQL idempotently."""
    from app.db.models import Run, Task, TaskStatus, Workspace

    ws = Workspace(id=uuid.uuid4(), name="ws-test", root_path="/tmp/ws_test")
    db_session.add(ws)
    await db_session.flush()

    task = Task(
        id=uuid.uuid4(), workspace_id=ws.id, prompt="test prompt", status=TaskStatus.RUNNING
    )
    db_session.add(task)
    await db_session.flush()

    run = Run(
        id=uuid.uuid4(), task_id=task.id, thread_id=f"thread-{task.id}", status=TaskStatus.RUNNING
    )
    db_session.add(run)
    await db_session.commit()

    snap_state = {
        "token_usage": {
            "prompt_tokens": 450,
            "completion_tokens": 225,
            "total_tokens": 675,
            "llm_calls": 3,
            "by_provider": {"gemini": {"total_tokens": 450}},
        }
    }

    # Call 1
    await TaskService.sync_runtime_metrics(db_session, task.id, snap_state)
    t1 = await TaskService.get_task(db_session, str(task.id))
    assert t1.total_tokens == 675
    assert t1.llm_calls == 3

    # Call 2 (Idempotency verification: should NOT double to 1350)
    await TaskService.sync_runtime_metrics(db_session, task.id, snap_state)
    t2 = await TaskService.get_task(db_session, str(task.id))
    assert t2.total_tokens == 675
    assert t2.llm_calls == 3


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_analytics_api_endpoint(client: AsyncClient):
    """Requirement K: GET /api/v1/tasks/analytics aggregates metrics from PostgreSQL."""
    res = await client.get("/api/v1/tasks/analytics")
    assert res.status_code == 200
    data = res.json()
    assert "tasks_count" in data
    assert "prompt_tokens" in data
    assert "total_tokens" in data
    assert "llm_calls" in data
