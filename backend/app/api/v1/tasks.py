import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import get_production_graph
from app.agent.nodes import sanitize_error_message
from app.agent.state import create_initial_state
from app.core.exceptions import AppException
from app.db.models import TaskStatus
from app.db.session import get_db
from app.schemas.task import (
    ApprovalRequest,
    ExecutionResponse,
    TaskCreate,
    TaskResponse,
)
from app.services.task_service import TaskService

logger = logging.getLogger(__name__)

router = APIRouter()


def get_agent_graph():
    """Resolves production agent graph. Fails closed if checkpointer is uninitialized."""
    try:
        return get_production_graph()
    except Exception as err:
        logger.debug("Production checkpointer not initialized: %s", err)
        return None


def _format_sse(event: str, data: dict[str, Any]) -> str:
    """Formats payload adhering to Server-Sent Events standard."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    """Creates and persists a new coding task."""
    task = await TaskService.create_task(
        db, workspace_path=payload.workspace_path, prompt=payload.prompt
    )
    return TaskResponse.from_task(task)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    graph=Depends(get_agent_graph),
) -> TaskResponse:
    """Retrieves metadata and status of an existing task."""
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
    graph=Depends(get_agent_graph),
) -> ExecutionResponse:
    """Executes or continues execution of a task inside the agent graph.

    Protected against concurrent same-task race conditions via row-level locks.
    """
    task, should_start = await TaskService.lock_task_for_run(db, task_id)
    config = {"configurable": {"thread_id": task.thread_id}}

    try:
        snap = await graph.aget_state(config)

        # Reconcile if graph is already in a non-initial state or already executed
        if not should_start:
            if task.status == TaskStatus.RUNNING:
                return ExecutionResponse(
                    task_id=str(task.id),
                    status="running",
                    current_step=(
                        snap.values.get("current_step", 1)
                        if snap and snap.values
                        else 1
                    ),
                )

            if snap.next == ("approval_gate",):
                await TaskService.update_task_status(db, task, "awaiting_approval")
                coder_prop = snap.values.get("coder_proposal")
                coder_summary = (
                    coder_prop.summary
                    if hasattr(coder_prop, "summary")
                    else (
                        coder_prop.get("summary")
                        if isinstance(coder_prop, dict)
                        else None
                    )
                )
                return ExecutionResponse(
                    task_id=str(task.id),
                    status="awaiting_approval",
                    current_step=snap.values.get("current_step", 4),
                    next_step="approval_gate",
                    interrupt_payload={
                        "action": "human_approval_required",
                        "pending_patch": snap.values.get("pending_patch"),
                        "coder_summary": coder_summary,
                    },
                )

            if not snap.next and snap.values:
                final = snap.values.get("final_result")
                status = getattr(final, "status", None) or (
                    final.get("status") if isinstance(final, dict) else "completed"
                )
                return ExecutionResponse(
                    task_id=str(task.id),
                    status=status,
                    current_step=snap.values.get("current_step", 8),
                    final_result=(
                        final.model_dump() if hasattr(final, "model_dump") else final
                    ),
                )

        # Initial execution execution pathway
        initial_state = create_initial_state(
            task_id=str(task.id),
            workspace_path=task.workspace_path,
            thread_id=task.thread_id,
            prompt=task.prompt,
        )
        await graph.ainvoke(initial_state, config=config)

        post_snap = await graph.aget_state(config)

        if post_snap.next == ("approval_gate",):
            await TaskService.update_task_status(db, task, "awaiting_approval")
            coder_prop = post_snap.values.get("coder_proposal")
            coder_summary = (
                coder_prop.summary
                if hasattr(coder_prop, "summary")
                else (
                    coder_prop.get("summary") if isinstance(coder_prop, dict) else None
                )
            )
            return ExecutionResponse(
                task_id=str(task.id),
                status="awaiting_approval",
                current_step=post_snap.values.get("current_step", 4),
                next_step="approval_gate",
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
        await TaskService.update_task_status(db, task, status)
        return ExecutionResponse(
            task_id=str(task.id),
            status=status,
            current_step=post_snap.values.get("current_step", 8),
            final_result=(
                final.model_dump() if hasattr(final, "model_dump") else final
            ),
        )

    except Exception as err:
        clean_err = sanitize_error_message(err)
        logger.error("Task execution error on task '%s': %s", task_id, clean_err)
        await TaskService.update_task_status(db, task, "failed", error=clean_err)
        return ExecutionResponse(
            task_id=str(task.id),
            status="failed",
            error=clean_err,
        )


@router.post("/{task_id}/approval", response_model=ExecutionResponse)
async def submit_approval(
    task_id: str,
    payload: ApprovalRequest,
    db: AsyncSession = Depends(get_db),
    graph=Depends(get_agent_graph),
) -> ExecutionResponse:
    """Submits operator decision for an awaiting-approval task and resumes execution."""
    task = await TaskService.prepare_task_for_approval(db, task_id)
    config = {"configurable": {"thread_id": task.thread_id}}

    try:
        if graph is None:
            raise RuntimeError("Checkpointer is not initialized.")

        snap = await graph.aget_state(config)
        if not snap or snap.next != ("approval_gate",):
            await TaskService.reconcile_task_status(db, task, graph)
            raise AppException(
                status_code=400,
                message=f"Task '{task_id}' is not currently awaiting human approval.",
            )

        resume_cmd = Command(
            resume={"approved": payload.approved, "feedback": payload.feedback}
        )
        await graph.ainvoke(resume_cmd, config=config)

        post_snap = await graph.aget_state(config)

        if post_snap.next == ("approval_gate",):
            await TaskService.update_task_status(db, task, "awaiting_approval")
            coder_prop = post_snap.values.get("coder_proposal")
            coder_summary = (
                coder_prop.summary
                if hasattr(coder_prop, "summary")
                else (
                    coder_prop.get("summary") if isinstance(coder_prop, dict) else None
                )
            )
            return ExecutionResponse(
                task_id=str(task.id),
                status="awaiting_approval",
                current_step=post_snap.values.get("current_step", 4),
                next_step="approval_gate",
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
        await TaskService.update_task_status(db, task, status)
        return ExecutionResponse(
            task_id=str(task.id),
            status=status,
            current_step=post_snap.values.get("current_step", 8),
            final_result=(
                final.model_dump() if hasattr(final, "model_dump") else final
            ),
        )
    except AppException:
        raise
    except Exception as err:
        clean_err = sanitize_error_message(err)
        logger.error("Task approval error on task '%s': %s", task_id, clean_err)
        await TaskService.update_task_status(db, task, "failed", error=clean_err)
        return ExecutionResponse(
            task_id=str(task.id),
            status="failed",
            error=clean_err,
        )


@router.get("/{task_id}/events")
async def stream_task_events(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    graph=Depends(get_agent_graph),
) -> StreamingResponse:
    """Streams safe, high-level task execution events via Server-Sent Events (SSE).

    CRITICAL INVARIANT: This is strictly an observation endpoint.
    It NEVER initiates execution or advances checkpoints for an unstarted task.
    """
    task = await TaskService.get_task(db, task_id)
    config = {"configurable": {"thread_id": task.thread_id}}

    if graph is None:
        raise AppException(
            status_code=500,
            message="Checkpointer is not initialized.",
        )

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
            task.status.value.lower()
            if hasattr(task.status, "value")
            else str(task.status).lower()
        )
        yield _format_sse("task_started", {"task_id": str(task.id), "status": st})

        try:
            if snap.values.get("workspace_summary") or snap.values.get("tech_stack"):
                yield _format_sse(
                    "workspace_inspected",
                    {
                        "step": 1,
                        "tech_stack": snap.values.get("tech_stack", []),
                    },
                )

            if snap.values.get("plan"):
                plan = snap.values.get("plan")
                summary = getattr(plan, "summary", None) or (
                    plan.get("summary") if isinstance(plan, dict) else None
                )
                yield _format_sse(
                    "planning",
                    {
                        "step": 2,
                        "plan_summary": summary,
                    },
                )

            if snap.values.get("coder_proposal"):
                prop = snap.values.get("coder_proposal")
                summary = getattr(prop, "summary", None) or (
                    prop.get("summary") if isinstance(prop, dict) else None
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

            if snap.values.get("review_summary"):
                rev = snap.values.get("review_summary")
                verdict = getattr(rev, "verdict", None) or (
                    rev.get("verdict") if isinstance(rev, dict) else None
                )
                yield _format_sse(
                    "review_started",
                    {
                        "step": 7,
                        "verdict": verdict,
                    },
                )

            if snap.next == ("approval_gate",):
                coder_prop = snap.values.get("coder_proposal")
                coder_summary = (
                    coder_prop.summary
                    if hasattr(coder_prop, "summary")
                    else (
                        coder_prop.get("summary")
                        if isinstance(coder_prop, dict)
                        else None
                    )
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
                ev_name = (
                    "task_completed" if fin_status == "completed" else "task_failed"
                )
                yield _format_sse(
                    ev_name,
                    {
                        "step": 8,
                        "status": fin_status,
                        "summary": getattr(fin, "summary", "")
                        or (fin.get("summary", "") if isinstance(fin, dict) else ""),
                    },
                )
        except Exception as stream_err:
            clean_err = sanitize_error_message(stream_err)
            yield _format_sse("task_failed", {"error": clean_err})

    return StreamingResponse(event_generator(), media_type="text/event-stream")
