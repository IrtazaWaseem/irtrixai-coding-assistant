import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import get_production_graph
from app.agent.nodes import sanitize_error_message
from app.agent.state import create_initial_state
from app.core.config import settings
from app.core.exceptions import AppException
from app.db.models import Task, TaskStatus
from app.db.session import get_db
from app.schemas.task import (
    ApprovalRequest,
    ExecutionResponse,
    TaskAnalyticsResponse,
    TaskCreate,
    TaskResponse,
    TokenUsage,
)
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)
router = APIRouter()


def get_agent_graph() -> Any:
    """Dependency provider yielding the LangGraph production workflow."""
    try:
        return get_production_graph()
    except Exception as err:
        logger.debug("Production checkpointer not initialized: %s", err)
        return None


def _build_runnable_config(task: Task) -> dict[str, Any]:
    task_prov = getattr(task, "provider", None) or settings.PRIMARY_LLM_PROVIDER
    task_model = getattr(task, "model", None) or settings.get_provider_default_model(task_prov)

    tags = ["irtrixai", "coding-task", f"provider:{task_prov}"]
    metadata = {
        "task_id": str(task.id),
        "workspace_id": str(task.workspace_id),
        "provider": task_prov,
        "model": task_model,
    }

    config: dict[str, Any] = {
        "configurable": {"thread_id": task.thread_id},
        "run_name": f"task-{task.id}",
        "tags": tags,
        "metadata": metadata,
    }
    return config


@router.get(
    "/analytics",
    response_model=TaskAnalyticsResponse,
    summary="Get aggregate task telemetry",
)
async def get_task_analytics(
    db: AsyncSession = Depends(get_db),
) -> TaskAnalyticsResponse:
    stmt = select(
        func.count(Task.id),
        func.coalesce(func.sum(Task.prompt_tokens), 0),
        func.coalesce(func.sum(Task.completion_tokens), 0),
        func.coalesce(func.sum(Task.total_tokens), 0),
        func.coalesce(func.sum(Task.llm_calls), 0),
    )
    res = await db.execute(stmt)
    cnt, p_tokens, c_tokens, t_tokens, calls = res.one()

    prov_stmt = select(Task.provider_usage).where(Task.provider_usage.isnot(None))
    prov_res = await db.execute(prov_stmt)
    by_prov: dict[str, Any] = {}
    for (usage_dict,) in prov_res.all():
        if not isinstance(usage_dict, dict):
            continue
        for p_name, data in usage_dict.items():
            if not isinstance(data, dict):
                continue
            curr = by_prov.setdefault(
                p_name,
                {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "llm_calls": 0,
                },
            )
            curr["prompt_tokens"] += data.get("prompt_tokens", 0)
            curr["completion_tokens"] += data.get("completion_tokens", 0)
            curr["total_tokens"] += data.get("total_tokens", 0)
            curr["llm_calls"] += data.get("llm_calls", 0)

    return TaskAnalyticsResponse(
        tasks_count=cnt,
        prompt_tokens=p_tokens,
        completion_tokens=c_tokens,
        total_tokens=t_tokens,
        llm_calls=calls,
        by_provider=by_prov,
    )


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    task = await TaskService.create_task(
        db,
        prompt=payload.prompt,
        workspace_id=payload.workspace_id,
        workspace_path=payload.workspace_path,
        provider=payload.provider,
        model=payload.model,
    )
    return TaskResponse.from_task(task)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    graph: Any = Depends(get_agent_graph),
) -> TaskResponse:
    task = await TaskService.get_task(db, task_id)
    if (
        str(task.status).upper() in ("RUNNING", "TASKSTATUS.RUNNING")
        or task.status == TaskStatus.RUNNING
    ) and graph is not None:
        task = await TaskService.reconcile_task_status(db, task, graph)
    return TaskResponse.from_task(task)


@router.post("/{task_id}/run", response_model=ExecutionResponse)
async def run_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    graph: Any = Depends(get_agent_graph),
) -> ExecutionResponse:
    if graph is None:
        raise AppException(status_code=500, message="Checkpointer is not initialized.")

    task, should_execute = await TaskService.prepare_task_for_run(db, task_id, graph)
    config = _build_runnable_config(task)

    if not should_execute:
        snap = await graph.aget_state(config)
        usage_val = snap.values.get("token_usage") if snap else None
        usage = TokenUsage(**usage_val) if usage_val else None

        if task.status == TaskStatus.CANCELLED:
            return ExecutionResponse(
                task_id=str(task.id),
                status="cancelled",
                current_step=snap.values.get("current_step", 8) if snap else 8,
                token_usage=usage,
            )

        if snap and snap.next == ("approval_gate",):
            coder_prop = snap.values.get("coder_proposal")
            coder_summary = (
                coder_prop.summary
                if hasattr(coder_prop, "summary")
                else (coder_prop.get("summary") if isinstance(coder_prop, dict) else None)
            )
            return ExecutionResponse(
                task_id=str(task.id),
                status="awaiting_approval",
                current_step=snap.values.get("current_step", 4),
                next_step="approval_gate",
                token_usage=usage,
                interrupt_payload={
                    "action": "human_approval_required",
                    "pending_patch": snap.values.get("pending_patch"),
                    "coder_summary": coder_summary,
                },
            )

        final = snap.values.get("final_result") if snap else None
        status = getattr(final, "status", None) or (
            final.get("status") if isinstance(final, dict) else str(task.status).lower()
        )
        return ExecutionResponse(
            task_id=str(task.id),
            status=status,
            current_step=snap.values.get("current_step", 8) if snap else 8,
            token_usage=usage,
            final_result=(final.model_dump() if hasattr(final, "model_dump") else final),
        )

    try:
        snap = await graph.aget_state(config)
        if not snap or not snap.values:
            task_prov = getattr(task, "provider", None) or settings.PRIMARY_LLM_PROVIDER
            task_model = getattr(task, "model", None) or settings.get_provider_default_model(
                task_prov
            )
            initial_state = create_initial_state(
                task_id=str(task.id),
                workspace_path=task.workspace_path,
                thread_id=task.thread_id,
                prompt=task.prompt,
                provider=task_prov,
                model=task_model,
            )
            await TaskService.run_graph_cancellable(task.id, graph, initial_state, config)
        else:
            await TaskService.run_graph_cancellable(task.id, graph, None, config)

        post_snap = await graph.aget_state(config)
        await TaskService.sync_runtime_metrics(db, task.id, post_snap)

        usage_val = post_snap.values.get("token_usage") if post_snap else None
        usage = TokenUsage(**usage_val) if usage_val else None

        if post_snap.next == ("approval_gate",):
            updated_task = await TaskService.update_task_status(db, task, "awaiting_approval")
            if updated_task.status == TaskStatus.CANCELLED:
                return ExecutionResponse(
                    task_id=str(task.id),
                    status="cancelled",
                    current_step=post_snap.values.get("current_step", 4),
                    token_usage=usage,
                )

            coder_prop = post_snap.values.get("coder_proposal")
            coder_summary = (
                coder_prop.summary
                if hasattr(coder_prop, "summary")
                else (coder_prop.get("summary") if isinstance(coder_prop, dict) else None)
            )
            return ExecutionResponse(
                task_id=str(task.id),
                status="awaiting_approval",
                current_step=post_snap.values.get("current_step", 4),
                next_step="approval_gate",
                token_usage=usage,
                interrupt_payload={
                    "action": "human_approval_required",
                    "pending_patch": post_snap.values.get("pending_patch"),
                    "coder_summary": coder_summary,
                },
            )

        final = post_snap.values.get("final_result")
        status = getattr(final, "status", None) or (
            final.get("status") if isinstance(final, dict) else "completed"
        )
        updated_task = await TaskService.update_task_status(db, task, status)
        return ExecutionResponse(
            task_id=str(task.id),
            status=updated_task.status.value.lower(),
            current_step=post_snap.values.get("current_step", 8),
            token_usage=usage,
            final_result=(final.model_dump() if hasattr(final, "model_dump") else final),
        )
    except asyncio.CancelledError:
        logger.info("run_task coroutine cancelled for task '%s'", task_id)
        reloaded_task = await TaskService.get_task(db, task_id)
        return ExecutionResponse(
            task_id=str(reloaded_task.id),
            status=reloaded_task.status.value.lower(),
            current_step=4,
        )
    except AppException:
        raise
    except Exception as err:
        clean_err = sanitize_error_message(err)
        logger.error("Task execution error on task '%s': %s", task_id, clean_err)
        await TaskService.update_task_status(db, task, "failed", error=clean_err)
        return ExecutionResponse(task_id=str(task.id), status="failed", error=clean_err)


@router.post("/{task_id}/approval", response_model=ExecutionResponse)
async def submit_approval(
    task_id: str,
    payload: ApprovalRequest,
    db: AsyncSession = Depends(get_db),
    graph: Any = Depends(get_agent_graph),
) -> ExecutionResponse:
    task = await TaskService.prepare_task_for_approval(db, task_id)
    config = _build_runnable_config(task)

    try:
        if graph is None:
            raise RuntimeError("Checkpointer is not initialized.")

        resume_cmd = Command(resume={"approved": payload.approved, "feedback": payload.feedback})
        await TaskService.run_graph_cancellable(task.id, graph, resume_cmd, config)

        post_snap = await graph.aget_state(config)
        await TaskService.sync_runtime_metrics(db, task.id, post_snap)

        usage_val = post_snap.values.get("token_usage") if post_snap else None
        usage = TokenUsage(**usage_val) if usage_val else None

        if post_snap.next == ("approval_gate",):
            updated_task = await TaskService.update_task_status(db, task, "awaiting_approval")
            if updated_task.status == TaskStatus.CANCELLED:
                return ExecutionResponse(
                    task_id=str(task.id),
                    status="cancelled",
                    current_step=post_snap.values.get("current_step", 4),
                    token_usage=usage,
                )

            coder_prop = post_snap.values.get("coder_proposal")
            coder_summary = (
                coder_prop.summary
                if hasattr(coder_prop, "summary")
                else (coder_prop.get("summary") if isinstance(coder_prop, dict) else None)
            )
            return ExecutionResponse(
                task_id=str(task.id),
                status="awaiting_approval",
                current_step=post_snap.values.get("current_step", 4),
                next_step="approval_gate",
                token_usage=usage,
                interrupt_payload={
                    "action": "human_approval_required",
                    "pending_patch": post_snap.values.get("pending_patch"),
                    "coder_summary": coder_summary,
                },
            )

        final = post_snap.values.get("final_result")
        status = getattr(final, "status", None) or (
            final.get("status") if isinstance(final, dict) else "completed"
        )
        updated_task = await TaskService.update_task_status(db, task, status)
        return ExecutionResponse(
            task_id=str(task.id),
            status=updated_task.status.value.lower(),
            current_step=post_snap.values.get("current_step", 8),
            token_usage=usage,
            final_result=(final.model_dump() if hasattr(final, "model_dump") else final),
        )
    except asyncio.CancelledError:
        logger.info("submit_approval coroutine cancelled for task '%s'", task_id)
        reloaded_task = await TaskService.get_task(db, task_id)
        return ExecutionResponse(
            task_id=str(reloaded_task.id),
            status=reloaded_task.status.value.lower(),
            current_step=4,
        )
    except AppException:
        raise
    except Exception as err:
        clean_err = sanitize_error_message(err)
        logger.error("Task approval error on task '%s': %s", task_id, clean_err)
        await TaskService.update_task_status(db, task, "failed", error=clean_err)
        return ExecutionResponse(task_id=str(task.id), status="failed", error=clean_err)


def _format_sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/{task_id}/events")
async def stream_task_events(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    graph: Any = Depends(get_agent_graph),
) -> StreamingResponse:
    task = await TaskService.get_task(db, task_id)
    config = {"configurable": {"thread_id": task.thread_id}}

    if graph is None:
        raise AppException(status_code=500, message="Checkpointer is not initialized.")

    snap = await graph.aget_state(config)
    if not snap or not snap.values or task.status == TaskStatus.PENDING:

        async def unstarted_generator() -> AsyncGenerator[str, None]:
            yield _format_sse(
                "task_not_started",
                {
                    "task_id": str(task.id),
                    "status": "pending",
                    "message": "Task has not been started. Trigger execution via POST /run.",
                },
            )

        return StreamingResponse(unstarted_generator(), media_type="text/event-stream")

    async def event_generator() -> AsyncGenerator[str, None]:
        st = (
            task.status.value.lower() if hasattr(task.status, "value") else str(task.status).lower()
        )
        usage = snap.values.get("token_usage", {})
        yield _format_sse(
            "task_started",
            {"task_id": str(task.id), "status": st, "token_usage": usage},
        )

        try:
            if snap.values.get("workspace_summary") or snap.values.get("tech_stack"):
                yield _format_sse(
                    "workspace_inspected",
                    {
                        "step": 1,
                        "tech_stack": snap.values.get("tech_stack", []),
                    },
                )

            if snap.values.get("repository_context"):
                rc = snap.values.get("repository_context") or {}
                yield _format_sse(
                    "repository_context_ready",
                    {
                        "step": 1,
                        "files_selected": rc.get("files_included", 0),
                        "total_context_bytes": rc.get("total_context_bytes", 0),
                        "truncated": rc.get("truncated", False),
                    },
                )

            if snap.values.get("plan"):
                plan = snap.values.get("plan")
                summary = getattr(plan, "summary", None) or (
                    plan.get("summary") if isinstance(plan, dict) else ""
                )
                yield _format_sse(
                    "planning",
                    {
                        "step": 2,
                        "plan_summary": summary,
                        "token_usage": usage,
                    },
                )

            if snap.values.get("coder_proposal"):
                prop = snap.values.get("coder_proposal")
                summary = getattr(prop, "summary", None) or (
                    prop.get("summary") if isinstance(prop, dict) else ""
                )
                files = getattr(prop, "files_changed", None) or (
                    prop.get("files_changed") if isinstance(prop, dict) else []
                )
                yield _format_sse(
                    "coding",
                    {
                        "step": 3,
                        "summary": summary,
                        "files_changed": files,
                        "token_usage": usage,
                    },
                )

            if snap.values.get("applied_diff"):
                yield _format_sse(
                    "patch_applied",
                    {
                        "step": 4,
                        "has_diff": bool(snap.values.get("applied_diff")),
                    },
                )

            if snap.values.get("test_result"):
                tr = snap.values.get("test_result") or {}
                event_name = "test_passed" if tr.get("success") else "test_failed"
                yield _format_sse(
                    event_name,
                    {
                        "step": 5,
                        "exit_code": tr.get("exit_code"),
                        "command": tr.get("command"),
                    },
                )

            if snap.values.get("debugger_output"):
                yield _format_sse(
                    "repair_started",
                    {
                        "step": 6,
                        "repair_count": snap.values.get("repair_count", 0),
                    },
                )

            rev_status = snap.values.get("review_status")
            if rev_status in ("skipped_due_to_rate_limit", "skipped_due_to_llm_error"):
                yield _format_sse(
                    "review_skipped",
                    {
                        "step": 7,
                        "review_status": rev_status,
                        "advisory": snap.values.get("review_advisory", ""),
                        "token_usage": usage,
                    },
                )
            elif snap.values.get("review_summary"):
                rev = snap.values.get("review_summary")
                verdict = getattr(rev, "verdict", None) or (
                    rev.get("verdict") if isinstance(rev, dict) else "approved"
                )
                yield _format_sse(
                    "review_started",
                    {
                        "step": 7,
                        "verdict": verdict,
                        "token_usage": usage,
                    },
                )

            if snap.next == ("approval_gate",):
                coder_prop = snap.values.get("coder_proposal")
                coder_summary = (
                    coder_prop.summary
                    if hasattr(coder_prop, "summary")
                    else (coder_prop.get("summary") if isinstance(coder_prop, dict) else None)
                )
                yield _format_sse(
                    "approval_required",
                    {
                        "action": "human_approval_required",
                        "step": 4,
                        "pending_patch": snap.values.get("pending_patch"),
                        "coder_summary": coder_summary,
                    },
                )

            if not snap.next and snap.values.get("final_result"):
                fin = snap.values.get("final_result")
                fin_status = getattr(fin, "status", None) or (
                    fin.get("status") if isinstance(fin, dict) else "completed"
                )
                ev_name = "task_completed" if fin_status == "completed" else "task_failed"
                yield _format_sse(
                    ev_name,
                    {
                        "step": 8,
                        "status": fin_status,
                        "summary": getattr(fin, "summary", "")
                        or (fin.get("summary", "") if isinstance(fin, dict) else ""),
                        "token_usage": usage,
                    },
                )
        except Exception as stream_err:
            clean_err = sanitize_error_message(stream_err)
            yield _format_sse("task_failed", {"error": clean_err})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    """Cancels an active task, releases workspace lock, and marks it terminal."""
    task = await TaskService.cancel_task(db, task_id)
    return TaskResponse.from_task(task)
