import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.nodes import sanitize_error_message
from app.core.exceptions import AppException
from app.db.models import Run, Task, TaskStatus, Workspace
from app.tools.validators import validate_workspace_dir

logger = logging.getLogger(__name__)


class TaskService:
    @staticmethod
    async def create_task(db: AsyncSession, workspace_path: str, prompt: str) -> Task:
        resolved_path = validate_workspace_dir(workspace_path)

        query = select(Workspace).where(Workspace.root_path == str(resolved_path))
        result = await db.execute(query)
        ws = result.scalar_one_or_none()
        if not ws:
            ws = Workspace(
                id=uuid.uuid4(),
                name=Path(resolved_path).name,
                root_path=str(resolved_path),
            )
            db.add(ws)
            await db.flush()

        task_id = uuid.uuid4()
        task = Task(
            id=task_id,
            workspace_id=ws.id,
            prompt=prompt.strip(),
            status=TaskStatus.PENDING,
        )
        db.add(task)
        await db.flush()

        thread_id = f"thread-{task_id}"
        run = Run(
            id=uuid.uuid4(),
            task_id=task.id,
            thread_id=thread_id,
            status=TaskStatus.RUNNING,
            repair_count=0,
            plan=[],
        )
        db.add(run)
        await db.commit()

        return await TaskService.get_task(db, str(task.id))

    @staticmethod
    async def get_task(db: AsyncSession, task_id: str) -> Task:
        try:
            task_uuid = uuid.UUID(task_id) if isinstance(task_id, str) else task_id
        except (ValueError, AttributeError):
            raise AppException(
                status_code=404,
                message=f"Task '{task_id}' not found.",
            )

        query = (
            select(Task)
            .options(selectinload(Task.workspace), selectinload(Task.runs))
            .where(Task.id == task_uuid)
        )
        result = await db.execute(query)
        task = result.scalar_one_or_none()
        if not task:
            raise AppException(
                status_code=404,
                message=f"Task '{task_id}' not found.",
            )
        return task

    @staticmethod
    async def prepare_task_for_run(
        db: AsyncSession, task_id: str, graph: Any = None
    ) -> tuple[Task, bool]:
        """Atomically locks the task row in PostgreSQL with FOR UPDATE and verifies eligibility to start execution.

        Returns (task, should_execute):
        - If should_execute is True, caller is the exclusive runner and must execute graph.
        - If should_execute is False, task is already at approval_gate or completed.
        - Raises AppException(409) if task is currently RUNNING.
        """
        try:
            task_uuid = uuid.UUID(task_id) if isinstance(task_id, str) else task_id
        except (ValueError, AttributeError):
            raise AppException(
                status_code=404,
                message=f"Task '{task_id}' not found.",
            )

        query = (
            select(Task)
            .options(selectinload(Task.workspace), selectinload(Task.runs))
            .where(Task.id == task_uuid)
            .with_for_update()
        )
        result = await db.execute(query)
        task = result.scalar_one_or_none()
        if not task:
            raise AppException(
                status_code=404,
                message=f"Task '{task_id}' not found.",
            )

        # Reconcile if marked RUNNING in DB
        if task.status == TaskStatus.RUNNING and graph is not None:
            task = await TaskService.reconcile_task_status(db, task, graph)

        if task.status == TaskStatus.RUNNING:
            raise AppException(
                status_code=409,
                message=f"Task '{task_id}' is currently running.",
            )

        if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            await db.commit()
            return task, False

        if task.status == TaskStatus.AWAITING_APPROVAL:
            await db.commit()
            return task, False

        # Transition PENDING -> RUNNING atomically
        task.status = TaskStatus.RUNNING
        if task.runs and len(task.runs) > 0:
            task.runs[-1].status = TaskStatus.RUNNING
        db.add(task)
        await db.commit()

        return await TaskService.get_task(db, str(task.id)), True

    lock_task_for_run = prepare_task_for_run

    @staticmethod
    async def prepare_task_for_approval(db: AsyncSession, task_id: str) -> Task:
        """Fix #1: Atomically locks task row with FOR UPDATE and verifies task is AWAITING_APPROVAL."""
        try:
            task_uuid = uuid.UUID(task_id) if isinstance(task_id, str) else task_id
        except (ValueError, AttributeError):
            raise AppException(
                status_code=404,
                message=f"Task '{task_id}' not found.",
            )

        query = (
            select(Task)
            .options(selectinload(Task.workspace), selectinload(Task.runs))
            .where(Task.id == task_uuid)
            .with_for_update()
        )
        result = await db.execute(query)
        task = result.scalar_one_or_none()
        if not task:
            raise AppException(
                status_code=404,
                message=f"Task '{task_id}' not found.",
            )

        if task.status == TaskStatus.RUNNING:
            raise AppException(
                status_code=409,
                message=f"Task '{task_id}' is currently running.",
            )

        if task.status != TaskStatus.AWAITING_APPROVAL:
            raise AppException(
                status_code=400,
                message=f"Task '{task_id}' is not currently awaiting human approval.",
            )

        task.status = TaskStatus.RUNNING
        if task.runs and len(task.runs) > 0:
            task.runs[-1].status = TaskStatus.RUNNING
        db.add(task)
        await db.commit()

        return await TaskService.get_task(db, str(task.id))

    lock_task_for_approval = prepare_task_for_approval

    @staticmethod
    async def reconcile_task_status(
        db: AsyncSession, task: Task, graph: Any = None
    ) -> Task:
        """Conservatively reconciles database Task.status against checkpointed LangGraph state."""
        if task.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        ):
            return task

        if graph is None:
            try:
                from app.agent.graph import get_production_graph

                graph = get_production_graph()
            except Exception:
                return task

        try:
            config = {"configurable": {"thread_id": task.thread_id}}
            snap = await graph.aget_state(config)

            if not snap or not snap.values:
                if task.status == TaskStatus.RUNNING:
                    return await TaskService.update_task_status(
                        db,
                        task,
                        "failed",
                        error="Execution interrupted before first checkpoint.",
                    )
                return task

            if snap.next == ("approval_gate",):
                if task.status != TaskStatus.AWAITING_APPROVAL:
                    return await TaskService.update_task_status(
                        db, task, "awaiting_approval"
                    )
                return task

            if not snap.next:
                final = snap.values.get("final_result")
                if final:
                    st = getattr(final, "status", None) or (
                        final.get("status") if isinstance(final, dict) else None
                    )
                    if st == "completed" and task.status != TaskStatus.COMPLETED:
                        return await TaskService.update_task_status(
                            db, task, "completed"
                        )
                    if st == "failed" and task.status != TaskStatus.FAILED:
                        err = getattr(final, "summary", None) or (
                            final.get("summary") if isinstance(final, dict) else None
                        )
                        return await TaskService.update_task_status(
                            db, task, "failed", error=err
                        )
                    if st == "aborted" and task.status != TaskStatus.CANCELLED:
                        return await TaskService.update_task_status(
                            db, task, "cancelled"
                        )
                elif task.status == TaskStatus.RUNNING:
                    return await TaskService.update_task_status(
                        db,
                        task,
                        "failed",
                        error="Workflow ended without finalization result.",
                    )

            if task.status == TaskStatus.PENDING and snap.values:
                return await TaskService.update_task_status(db, task, "running")

        except Exception as err:
            clean_err = sanitize_error_message(err)
            logger.debug("Task status reconciliation safely deferred: %s", clean_err)

        return task

    @staticmethod
    async def update_task_status(
        db: AsyncSession, task: Task, status: str, error: str | None = None
    ) -> Task:
        status_upper = status.upper()
        if status_upper in TaskStatus.__members__:
            task.status = TaskStatus[status_upper]
        elif status_upper == "RUNNING":
            task.status = TaskStatus.RUNNING
        elif status_upper in ("COMPLETED", "SUCCESS"):
            task.status = TaskStatus.COMPLETED
        elif status_upper in ("FAILED", "ERROR"):
            task.status = TaskStatus.FAILED
        elif status_upper in ("AWAITING_APPROVAL", "APPROVAL_REQUIRED"):
            task.status = TaskStatus.AWAITING_APPROVAL
        elif status_upper in ("ABORTED", "CANCELLED"):
            task.status = TaskStatus.CANCELLED

        if task.runs and len(task.runs) > 0:
            latest_run = task.runs[-1]
            latest_run.status = task.status
            if error:
                latest_run.error_message = error
            if task.status in (
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            ):
                latest_run.finished_at = datetime.now(UTC)

        db.add(task)
        await db.commit()
        return await TaskService.get_task(db, str(task.id))
