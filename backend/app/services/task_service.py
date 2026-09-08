import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException
from app.db.models import Run, Task, TaskStatus, Workspace
from app.tools.validators import validate_workspace_dir


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
