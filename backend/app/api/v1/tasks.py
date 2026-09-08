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
    return get_production_graph()


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
) -> TaskResponse:
    """Retrieves metadata and status of an existing task."""
    task = await TaskService.get_task(db, task_id)
    return TaskResponse.from_task(task)


@router.post("/{task_id}/run", response_model=ExecutionResponse)
async def run_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    graph=Depends(get_agent_graph),
) -> ExecutionResponse:
    """Executes or continues execution of a task inside the agent graph."""
    task = await TaskService.get_task(db, task_id)
    config = {"configurable": {"thread_id": task.thread_id}}

    try:
        snap = await graph.aget_state(config)

        if not snap.values:
            initial_state = create_initial_state(
                task_id=str(task.id),
                workspace_path=task.workspace_path,
                thread_id=task.thread_id,
                prompt=task.prompt,
            )
            await TaskService.update_task_status(db, task, "running")
            await graph.ainvoke(initial_state, config=config)
        elif snap.next == ("approval_gate",):
            await TaskService.update_task_status(db, task, "awaiting_approval")
            coder_prop = snap.values.get("coder_proposal")
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
                current_step=snap.values.get("current_step", 4),
                next_step="approval_gate",
                interrupt_payload={
                    "action": "human_approval_required",
                    "pending_patch": snap.values.get("pending_patch"),
                    "coder_summary": coder_summary,
                },
            )
        elif not snap.next:
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
        else:
            await graph.ainvoke(None, config=config)

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
    task = await TaskService.get_task(db, task_id)
    config = {"configurable": {"thread_id": task.thread_id}}

    snap = await graph.aget_state(config)
    if snap.next != ("approval_gate",):
        raise AppException(
            status_code=400,
            message=f"Task '{task_id}' is not currently awaiting human approval.",
        )

    try:
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
    """Streams safe, high-level task execution events via Server-Sent Events (SSE)."""
    task = await TaskService.get_task(db, task_id)
    config = {"configurable": {"thread_id": task.thread_id}}

    async def event_generator() -> AsyncGenerator[str, None]:
        yield _format_sse(
            "task_started", {"task_id": str(task.id), "status": "running"}
        )

        try:
            snap = await graph.aget_state(config)
            input_val = None
            if not snap.values:
                input_val = create_initial_state(
                    task_id=str(task.id),
                    workspace_path=task.workspace_path,
                    thread_id=task.thread_id,
                    prompt=task.prompt,
                )

            async for node_chunk in graph.astream(
                input_val, config=config, stream_mode="updates"
            ):
                for node_name, updates in node_chunk.items():
                    if not isinstance(updates, dict):
                        continue

                    if node_name == "inspect_workspace":
                        yield _format_sse(
                            "workspace_inspected",
                            {
                                "step": updates.get("current_step", 1),
                                "tech_stack": updates.get("tech_stack", []),
                            },
                        )
                    elif node_name == "planner":
                        plan = updates.get("plan")
                        summary = getattr(plan, "summary", None) or (
                            plan.get("summary") if isinstance(plan, dict) else None
                        )
                        yield _format_sse(
                            "planning",
                            {
                                "step": updates.get("current_step", 2),
                                "plan_summary": summary,
                            },
                        )
                    elif node_name == "coder":
                        prop = updates.get("coder_proposal")
                        summary = getattr(prop, "summary", None) or (
                            prop.get("summary") if isinstance(prop, dict) else None
                        )
                        files = getattr(prop, "files_changed", None) or (
                            prop.get("files_changed") if isinstance(prop, dict) else []
                        )
                        yield _format_sse(
                            "coding",
                            {
                                "step": updates.get("current_step", 3),
                                "summary": summary,
                                "files_changed": files,
                            },
                        )
                    elif node_name == "approval_gate":
                        yield _format_sse(
                            "approval_required",
                            {
                                "step": updates.get("current_step", 4),
                                "pending_patch": updates.get("pending_patch"),
                            },
                        )
                    elif node_name == "apply_approved_patch":
                        yield _format_sse(
                            "patch_applied",
                            {
                                "step": updates.get("current_step", 4),
                                "has_diff": bool(updates.get("applied_diff")),
                            },
                        )
                    elif node_name == "test_runner":
                        tr = updates.get("test_result") or {}
                        event_name = (
                            "test_started" if tr.get("success") else "test_failed"
                        )
                        yield _format_sse(
                            event_name,
                            {
                                "step": updates.get("current_step", 5),
                                "exit_code": tr.get("exit_code"),
                                "command": tr.get("command"),
                            },
                        )
                    elif node_name == "debugger":
                        yield _format_sse(
                            "repair_started",
                            {
                                "step": updates.get("current_step", 6),
                                "repair_count": updates.get("repair_count"),
                            },
                        )
                    elif node_name == "reviewer":
                        rev = updates.get("review_summary")
                        verdict = getattr(rev, "verdict", None) or (
                            rev.get("verdict") if isinstance(rev, dict) else None
                        )
                        yield _format_sse(
                            "review_started",
                            {
                                "step": updates.get("current_step", 7),
                                "verdict": verdict,
                            },
                        )
                    elif node_name == "finalize":
                        fin = updates.get("final_result")
                        st = getattr(fin, "status", None) or (
                            fin.get("status") if isinstance(fin, dict) else "completed"
                        )
                        ev_name = (
                            "task_completed" if st == "completed" else "task_failed"
                        )
                        yield _format_sse(
                            ev_name,
                            {
                                "step": updates.get("current_step", 8),
                                "status": st,
                                "summary": getattr(fin, "summary", "")
                                or (
                                    fin.get("summary", "")
                                    if isinstance(fin, dict)
                                    else ""
                                ),
                            },
                        )

            final_snap = await graph.aget_state(config)
            if final_snap.next == ("approval_gate",):
                coder_prop = final_snap.values.get("coder_proposal")
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
                        "pending_patch": final_snap.values.get("pending_patch"),
                        "coder_summary": coder_summary,
                    },
                )
        except Exception as stream_err:
            clean_err = sanitize_error_message(stream_err)
            yield _format_sse("task_failed", {"error": clean_err})

    return StreamingResponse(event_generator(), media_type="text/event-stream")
