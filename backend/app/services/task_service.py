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
    async def create_task(
        db: AsyncSession,
        prompt: str,
        workspace_id: str | uuid.UUID | None = None,
        workspace_path: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> Task:
        from app.core.config import settings

        # 1. Authoritative provider & model resolution and validation
        prov = (
            provider.strip().lower()
            if provider and provider.strip()
            else settings.PRIMARY_LLM_PROVIDER.strip().lower()
        )
        if prov not in ("gemini", "groq", "ollama"):
            raise AppException(
                status_code=400,
                message=f"Unsupported LLM provider '{prov}'. Allowed: 'gemini', 'groq', 'ollama'.",
            )

        mod = (
            model.strip() if model and model.strip() else settings.get_provider_default_model(prov)
        )
        if not mod:
            raise AppException(
                status_code=400,
                message=f"Model identifier cannot be empty for provider '{prov}'.",
            )

        # 2. Verify provider credential availability
        api_key, _ = settings.get_provider_credentials(prov)
        if prov in ("gemini", "groq") and not (api_key and api_key.strip()):
            raise AppException(
                status_code=400,
                message=f"Provider '{prov}' is unavailable: {prov.capitalize()} API key is not configured.",
            )

        # 3. Workspace resolution
        ws: Workspace | None = None
        if workspace_id:
            try:
                ws_uuid = uuid.UUID(workspace_id) if isinstance(workspace_id, str) else workspace_id
            except (ValueError, AttributeError) as err:
                raise AppException(
                    status_code=404,
                    message=f"Workspace '{workspace_id}' not found.",
                ) from err

            ws_query = select(Workspace).where(Workspace.id == ws_uuid)
            ws_result = await db.execute(ws_query)
            ws = ws_result.scalar_one_or_none()
            if not ws:
                raise AppException(
                    status_code=404,
                    message=f"Workspace '{workspace_id}' not found.",
                )
            validate_workspace_dir(ws.root_path)

        elif workspace_path:
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
        else:
            raise AppException(
                status_code=400,
                message="Either 'workspace_id' or 'workspace_path' must be provided.",
            )

        task_id = uuid.uuid4()
        task = Task(
            id=task_id,
            workspace_id=ws.id,
            prompt=prompt.strip(),
            provider=prov,
            model=mod,
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
        except (ValueError, AttributeError) as err:
            raise AppException(
                status_code=404,
                message=f"Task '{task_id}' not found.",
            ) from err

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
        - Raises AppException(409) if task is currently RUNNING or if another task is active in this workspace.
        """
        try:
            task_uuid = uuid.UUID(task_id) if isinstance(task_id, str) else task_id
        except (ValueError, AttributeError) as err:
            raise AppException(
                status_code=404,
                message=f"Task '{task_id}' not found.",
            ) from err

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

        # 1. Same-task duplicate protection
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

        # 2. Workspace-level concurrency protection: lock workspace row across workers
        ws_stmt = select(Workspace).where(Workspace.id == task.workspace_id).with_for_update()
        ws_res = await db.execute(ws_stmt)
        workspace = ws_res.scalar_one_or_none()

        # Check for any other active task in the same physical workspace
        active_stmt = (
            select(Task)
            .options(selectinload(Task.workspace), selectinload(Task.runs))
            .where(
                Task.workspace_id == task.workspace_id,
                Task.id != task.id,
                Task.status.in_([TaskStatus.RUNNING, TaskStatus.AWAITING_APPROVAL]),
            )
            .with_for_update()
        )
        active_res = await db.execute(active_stmt)
        other_active_tasks = active_res.scalars().all()

        for other_task in other_active_tasks:
            if other_task.status == TaskStatus.RUNNING and graph is not None:
                other_task = await TaskService.reconcile_task_status(db, other_task, graph)

            if other_task.status in (TaskStatus.RUNNING, TaskStatus.AWAITING_APPROVAL):
                ws_name = workspace.root_path if workspace else str(task.workspace_id)
                raise AppException(
                    status_code=409,
                    message=(
                        f"Workspace '{ws_name}' is currently in use by task "
                        f"'{other_task.id}' (status: {other_task.status.value.lower()})."
                    ),
                )

        # Transition PENDING -> RUNNING atomically under the lock
        task.status = TaskStatus.RUNNING
        if "runs" in task.__dict__ and task.runs and len(task.runs) > 0:
            task.runs[-1].status = TaskStatus.RUNNING
        db.add(task)
        await db.commit()

        return await TaskService.get_task(db, str(task.id)), True

    lock_task_for_run = prepare_task_for_run

    @staticmethod
    async def prepare_task_for_approval(db: AsyncSession, task_id: str) -> Task:
        """Atomically locks task row with FOR UPDATE and verifies task is AWAITING_APPROVAL."""
        try:
            task_uuid = uuid.UUID(task_id) if isinstance(task_id, str) else task_id
        except (ValueError, AttributeError) as err:
            raise AppException(
                status_code=404,
                message=f"Task '{task_id}' not found.",
            ) from err

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

        if task.status != TaskStatus.AWAITING_APPROVAL:
            raise AppException(
                status_code=400,
                message=f"Task '{task_id}' is not currently awaiting human approval.",
            )

        # Lock workspace row to ensure serialized access
        ws_stmt = select(Workspace).where(Workspace.id == task.workspace_id).with_for_update()
        ws_res = await db.execute(ws_stmt)
        workspace = ws_res.scalar_one_or_none()

        # Verify no other task has claimed the workspace
        active_stmt = (
            select(Task)
            .options(selectinload(Task.workspace), selectinload(Task.runs))
            .where(
                Task.workspace_id == task.workspace_id,
                Task.id != task.id,
                Task.status.in_([TaskStatus.RUNNING, TaskStatus.AWAITING_APPROVAL]),
            )
            .with_for_update()
        )
        active_res = await db.execute(active_stmt)
        other_active = active_res.scalars().first()
        if other_active:
            ws_name = workspace.root_path if workspace else str(task.workspace_id)
            raise AppException(
                status_code=409,
                message=(
                    f"Workspace '{ws_name}' is currently in use by task "
                    f"'{other_active.id}' (status: {other_active.status.value.lower()})."
                ),
            )

        task.status = TaskStatus.RUNNING
        if "runs" in task.__dict__ and task.runs and len(task.runs) > 0:
            task.runs[-1].status = TaskStatus.RUNNING
        db.add(task)
        await db.commit()

        return await TaskService.get_task(db, str(task.id))

    lock_task_for_approval = prepare_task_for_approval

    @staticmethod
    async def reconcile_task_status(db: AsyncSession, task: Task, graph: Any = None) -> Task:
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
                    # If the task has an active run started within the last 5 seconds,
                    # it is actively executing its first step and has not yet checkpointed.
                    # Do not prematurely mark it as failed.
                    is_recently_started = False
                    if "runs" in task.__dict__ and task.runs and len(task.runs) > 0:
                        latest_run = task.runs[-1]
                        if latest_run.started_at:
                            delta = (datetime.now(UTC) - latest_run.started_at).total_seconds()
                            if delta < 5.0:
                                is_recently_started = True

                    if not is_recently_started:
                        return await TaskService.update_task_status(
                            db,
                            task,
                            "failed",
                            error="Execution interrupted before first checkpoint.",
                        )
                return task

            if snap.next == ("approval_gate",):
                if task.status != TaskStatus.AWAITING_APPROVAL:
                    return await TaskService.update_task_status(db, task, "awaiting_approval")
                return task

            if not snap.next:
                final = snap.values.get("final_result")
                if final:
                    st = getattr(final, "status", None) or (
                        final.get("status") if isinstance(final, dict) else None
                    )
                    if st == "completed" and task.status != TaskStatus.COMPLETED:
                        return await TaskService.update_task_status(db, task, "completed")
                    if st == "failed" and task.status != TaskStatus.FAILED:
                        err = getattr(final, "summary", None) or (
                            final.get("summary") if isinstance(final, dict) else None
                        )
                        return await TaskService.update_task_status(db, task, "failed", error=err)
                    if st == "aborted" and task.status != TaskStatus.CANCELLED:
                        return await TaskService.update_task_status(db, task, "cancelled")
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

        if "runs" in task.__dict__ and task.runs and len(task.runs) > 0:
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

    @staticmethod
    async def sync_runtime_metrics(
        db: AsyncSession, task_id: str | uuid.UUID, state_or_snap: Any
    ) -> None:
        """Idempotently syncs cumulative token telemetry from LangGraph state to Task & Run records."""
        try:
            task_uuid = uuid.UUID(str(task_id))
        except (ValueError, AttributeError):
            return

        if isinstance(state_or_snap, dict):
            values = state_or_snap
        elif hasattr(state_or_snap, "values"):
            v = state_or_snap.values
            values = v() if callable(v) else v
        else:
            values = {}

        if not isinstance(values, dict):
            values = {}

        usage = values.get("token_usage", {}) or {}
        if not isinstance(usage, dict) or not usage:
            return

        p_tokens = int(usage.get("prompt_tokens", 0) or 0)
        c_tokens = int(usage.get("completion_tokens", 0) or 0)
        t_tokens = int(usage.get("total_tokens", p_tokens + c_tokens) or (p_tokens + c_tokens))
        calls = int(usage.get("llm_calls", 0) or 0)
        by_prov = usage.get("by_provider", {}) or {}

        task_stmt = select(Task).options(selectinload(Task.runs)).where(Task.id == task_uuid)
        res = await db.execute(task_stmt)
        task = res.scalar_one_or_none()
        if not task:
            return

        task.prompt_tokens = p_tokens
        task.completion_tokens = c_tokens
        task.total_tokens = t_tokens
        task.llm_calls = calls
        task.provider_usage = by_prov

        if task.runs and len(task.runs) > 0:
            latest_run = task.runs[-1]
            latest_run.prompt_tokens = p_tokens
            latest_run.completion_tokens = c_tokens
            latest_run.total_tokens = t_tokens
            latest_run.llm_calls = calls
            latest_run.provider_usage = by_prov

        db.add(task)
        await db.commit()
