import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.db.models import Run, Task, TaskStatus, Workspace
from app.services.task_service import TaskService


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_awaiting_approval_cancel_releases_workspace(
    tmp_path: Path, db_session, client: AsyncClient
):
    """1, 3 & 4: Awaiting approval task cancels cleanly and immediately frees the workspace."""
    ws_dir = tmp_path / f"ws_cancel_{uuid.uuid4().hex[:8]}"
    ws_dir.mkdir(parents=True, exist_ok=True)

    ws = Workspace(
        id=uuid.uuid4(),
        name="ws-cancel-test",
        root_path=str(ws_dir.resolve()),
    )
    db_session.add(ws)
    await db_session.flush()

    task1 = Task(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        prompt="Initial task awaiting approval",
        status=TaskStatus.AWAITING_APPROVAL,
    )
    db_session.add(task1)
    run1 = Run(
        id=uuid.uuid4(),
        task_id=task1.id,
        thread_id=f"thread-{task1.id}",
        status=TaskStatus.RUNNING,
    )
    db_session.add(run1)
    await db_session.commit()

    # Cancel task1 via the API
    res = await client.post(f"/api/v1/tasks/{task1.id}/cancel")
    assert res.status_code == 200
    assert res.json()["status"].upper() == TaskStatus.CANCELLED.value

    # Verify task1 in DB is CANCELLED and not deleted
    t1_db = await TaskService.get_task(db_session, str(task1.id))
    assert t1_db.status == TaskStatus.CANCELLED
    assert t1_db.runs[0].status == TaskStatus.CANCELLED

    # Create task2 in the same workspace - must NOT be blocked with 409
    task2 = await TaskService.create_task(db_session, prompt="New second task", workspace_id=ws.id)
    assert task2.status == TaskStatus.PENDING

    # Lock task2 for run - should succeed without conflict
    locked_task2, should_run = await TaskService.prepare_task_for_run(db_session, str(task2.id))
    assert should_run is True
    assert locked_task2.status == TaskStatus.RUNNING


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_running_task_cancellation_and_terminal_state(
    tmp_path: Path, db_session, client: AsyncClient
):
    """2: A running task transitions directly to CANCELLED and records finished_at."""
    ws_dir = tmp_path / f"ws_run_{uuid.uuid4().hex[:8]}"
    ws_dir.mkdir(parents=True, exist_ok=True)

    ws = Workspace(
        id=uuid.uuid4(),
        name="ws-running",
        root_path=str(ws_dir.resolve()),
    )
    db_session.add(ws)
    await db_session.flush()

    task = Task(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        prompt="Running task",
        status=TaskStatus.RUNNING,
    )
    db_session.add(task)
    run = Run(
        id=uuid.uuid4(),
        task_id=task.id,
        thread_id=f"thread-{task.id}",
        status=TaskStatus.RUNNING,
    )
    db_session.add(run)
    await db_session.commit()

    res = await client.post(f"/api/v1/tasks/{task.id}/cancel")
    assert res.status_code == 200
    assert res.json()["status"].upper() == TaskStatus.CANCELLED.value

    t_db = await TaskService.get_task(db_session, str(task.id))
    assert t_db.status == TaskStatus.CANCELLED
    assert t_db.runs[0].finished_at is not None


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_repeated_cancellation_is_idempotent(tmp_path: Path, db_session, client: AsyncClient):
    """5: Repeated cancellation calls return 200 OK and maintain CANCELLED status."""
    ws_dir = tmp_path / f"ws_idemp_{uuid.uuid4().hex[:8]}"
    ws_dir.mkdir(parents=True, exist_ok=True)

    ws = Workspace(
        id=uuid.uuid4(),
        name="ws-idempotent",
        root_path=str(ws_dir.resolve()),
    )
    db_session.add(ws)
    await db_session.flush()

    task = Task(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        prompt="Idempotent task",
        status=TaskStatus.RUNNING,
    )
    db_session.add(task)
    await db_session.commit()

    res1 = await client.post(f"/api/v1/tasks/{task.id}/cancel")
    assert res1.status_code == 200
    assert res1.json()["status"].upper() == TaskStatus.CANCELLED.value

    res2 = await client.post(f"/api/v1/tasks/{task.id}/cancel")
    assert res2.status_code == 200
    assert res2.json()["status"].upper() == TaskStatus.CANCELLED.value


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_completed_task_not_corrupted_by_cancellation(
    tmp_path: Path, db_session, client: AsyncClient
):
    """6: A completed task cannot be altered into a cancelled state."""
    ws_dir = tmp_path / f"ws_comp_{uuid.uuid4().hex[:8]}"
    ws_dir.mkdir(parents=True, exist_ok=True)

    ws = Workspace(
        id=uuid.uuid4(),
        name="ws-completed",
        root_path=str(ws_dir.resolve()),
    )
    db_session.add(ws)
    await db_session.flush()

    task = Task(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        prompt="Done task",
        status=TaskStatus.COMPLETED,
    )
    db_session.add(task)
    await db_session.commit()

    res = await client.post(f"/api/v1/tasks/{task.id}/cancel")
    assert res.status_code == 200
    # Status remains COMPLETED
    assert res.json()["status"].upper() == TaskStatus.COMPLETED.value

    t_db = await TaskService.get_task(db_session, str(task.id))
    assert t_db.status == TaskStatus.COMPLETED


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_stale_approval_cannot_resume_cancelled_task(
    tmp_path: Path, db_session, client: AsyncClient
):
    """7: Approval submission on a cancelled task is rejected with HTTP 400."""
    ws_dir = tmp_path / f"ws_stale_{uuid.uuid4().hex[:8]}"
    ws_dir.mkdir(parents=True, exist_ok=True)

    ws = Workspace(
        id=uuid.uuid4(),
        name="ws-stale-appr",
        root_path=str(ws_dir.resolve()),
    )
    db_session.add(ws)
    await db_session.flush()

    task = Task(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        prompt="Task to cancel",
        status=TaskStatus.AWAITING_APPROVAL,
    )
    db_session.add(task)
    await db_session.commit()

    # Cancel task
    await TaskService.cancel_task(db_session, task.id)

    # Attempt approval submission on cancelled task
    res = await client.post(f"/api/v1/tasks/{task.id}/approval", json={"approved": True})
    assert res.status_code == 400
    res_data = res.json()
    err_text = str(res_data.get("detail") or res_data.get("message") or res_data)
    assert "not currently awaiting human approval" in err_text


@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_execution_finishing_after_cancellation_cannot_overwrite_cancelled_state(
    tmp_path: Path, db_session
):
    """8: A lagging agent execution cannot overwrite a CANCELLED task back into COMPLETED."""
    ws_dir = tmp_path / f"ws_race_{uuid.uuid4().hex[:8]}"
    ws_dir.mkdir(parents=True, exist_ok=True)

    ws = Workspace(
        id=uuid.uuid4(),
        name="ws-race-test",
        root_path=str(ws_dir.resolve()),
    )
    db_session.add(ws)
    await db_session.flush()

    task = Task(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        prompt="Task with lagging worker",
        status=TaskStatus.RUNNING,
    )
    db_session.add(task)
    await db_session.commit()

    # Operator cancels task while worker is running
    await TaskService.cancel_task(db_session, task.id)

    # Lagging worker completes and attempts to update status to COMPLETED
    updated = await TaskService.update_task_status(db_session, task, "completed")
    assert updated.status == TaskStatus.CANCELLED

    # Verify DB record remains CANCELLED
    t_db = await TaskService.get_task(db_session, str(task.id))
    assert t_db.status == TaskStatus.CANCELLED
