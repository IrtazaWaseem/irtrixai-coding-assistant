import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.exceptions import AppException
from app.db.base import Base
from app.db.models import Task, TaskStatus, Workspace
from app.services.task_service import TaskService

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def event_loop_policy():
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


def init_test_git_repo(repo_path: Path) -> None:
    (repo_path / ".gitkeep").touch()
    subprocess.run(["git", "init"], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.name", "TestRunner"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@irtrixai.internal"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )


def get_test_postgres_async_uri() -> str:
    url = settings.TEST_DATABASE_URL or os.getenv("TEST_DATABASE_URL")
    if url:
        return url
    user = os.getenv("TEST_POSTGRES_USER", "postgres")
    password = os.getenv("TEST_POSTGRES_PASSWORD", "test_secure_password_123")
    host = os.getenv("TEST_POSTGRES_HOST", "localhost")
    port = os.getenv("TEST_POSTGRES_PORT", "5432")
    db = os.getenv("TEST_POSTGRES_DB", "irtrixai_test")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


def get_test_postgres_uri() -> str:
    return get_test_postgres_async_uri().replace("postgresql+asyncpg://", "postgresql://", 1)


@pytest_asyncio.fixture
async def real_postgres_session_factory():
    """Initializes schema on live PostgreSQL and yields an isolated async sessionmaker."""
    async_uri = get_test_postgres_async_uri()
    try:
        engine = create_async_engine(async_uri, poolclass=NullPool, echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(
                text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS provider VARCHAR(64);")
            )
            await conn.execute(
                text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS model VARCHAR(128);")
            )
    except Exception as exc:
        pytest.fail(f"Test PostgreSQL instance unreachable at {async_uri}. Error: {exc}")

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    yield session_factory

    await engine.dispose()


class MockSnapshot:
    def __init__(self, values: dict, next_steps: tuple):
        self.values = values
        self.next = next_steps


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_postgres_concurrent_same_task_run_prevented(
    tmp_path: Path, real_postgres_session_factory
):
    """Case 1: Proves two simultaneous /run attempts on the SAME task row cannot both acquire execution."""
    ws_path = tmp_path / "ws_real_pg_concurrency"
    ws_path.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_path)

    async with real_postgres_session_factory() as session:
        ws = Workspace(name="ws_pg_race", root_path=str(ws_path))
        session.add(ws)
        await session.flush()

        task = Task(
            workspace_id=ws.id,
            prompt="Implement race test",
            status=TaskStatus.PENDING,
        )
        session.add(task)
        await session.commit()
        task_id = str(task.id)

    start_barrier = asyncio.Event()

    class InstrumentedMockGraph:
        def __init__(self):
            self.execution_count = 0

        async def aget_state(self, config):
            return MockSnapshot({"current_step": 2}, ("coder",))

        async def ainvoke(self, state, config):
            self.execution_count += 1
            await asyncio.sleep(0.1)

    mock_graph = InstrumentedMockGraph()

    async def run_worker():
        await start_barrier.wait()
        async with real_postgres_session_factory() as db:
            try:
                task, should_run = await TaskService.prepare_task_for_run(db, task_id, mock_graph)
                if should_run:
                    await mock_graph.ainvoke(None, {"configurable": {"thread_id": task.thread_id}})
                return ("accepted", should_run)
            except AppException as exc:
                return ("rejected", exc.status_code)

    t1 = asyncio.create_task(run_worker())
    t2 = asyncio.create_task(run_worker())

    start_barrier.set()
    res1, res2 = await asyncio.gather(t1, t2)

    results = [res1, res2]
    accepted = [r for r in results if r[0] == "accepted"]
    rejected = [r for r in results if r[0] == "rejected"]

    assert len(accepted) == 1
    assert accepted[0] == ("accepted", True)

    assert len(rejected) == 1
    assert rejected[0] == ("rejected", 409)

    assert mock_graph.execution_count == 1


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_postgres_different_tasks_same_workspace_prevented(
    tmp_path: Path, real_postgres_session_factory
):
    """Case 2: Proves two DIFFERENT tasks targeting the SAME workspace cannot concurrently execute."""
    ws_path = tmp_path / "ws_real_same_ws_race"
    ws_path.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_path)

    async with real_postgres_session_factory() as session:
        ws = Workspace(name="ws_same_race", root_path=str(ws_path))
        session.add(ws)
        await session.flush()

        task1 = Task(workspace_id=ws.id, prompt="Task 1", status=TaskStatus.PENDING)
        task2 = Task(workspace_id=ws.id, prompt="Task 2", status=TaskStatus.PENDING)
        session.add_all([task1, task2])
        await session.commit()
        id1, id2 = str(task1.id), str(task2.id)

    start_barrier = asyncio.Event()

    class InstrumentedMockGraph:
        def __init__(self):
            self.execution_count = 0

        async def aget_state(self, config):
            return MockSnapshot({"current_step": 2}, ("coder",))

        async def ainvoke(self, state, config):
            self.execution_count += 1
            await asyncio.sleep(0.1)

    mock_graph = InstrumentedMockGraph()

    async def run_worker(t_id: str):
        await start_barrier.wait()
        async with real_postgres_session_factory() as db:
            try:
                task, should_run = await TaskService.prepare_task_for_run(db, t_id, mock_graph)
                if should_run:
                    await mock_graph.ainvoke(None, {"configurable": {"thread_id": task.thread_id}})
                return ("accepted", should_run)
            except AppException as exc:
                return ("rejected", exc.status_code)

    t1 = asyncio.create_task(run_worker(id1))
    t2 = asyncio.create_task(run_worker(id2))

    start_barrier.set()
    res1, res2 = await asyncio.gather(t1, t2)

    results = [res1, res2]
    accepted = [r for r in results if r[0] == "accepted"]
    rejected = [r for r in results if r[0] == "rejected"]

    assert len(accepted) == 1
    assert accepted[0] == ("accepted", True)

    assert len(rejected) == 1
    assert rejected[0] == ("rejected", 409)

    assert mock_graph.execution_count == 1


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_postgres_independent_tasks_execute_concurrently(
    tmp_path: Path, real_postgres_session_factory
):
    """Case 3: Proves Task A and Task B on DIFFERENT workspaces execute concurrently without blocking."""
    ws_path1 = tmp_path / "ws_ind_1"
    ws_path2 = tmp_path / "ws_ind_2"
    ws_path1.mkdir(parents=True, exist_ok=True)
    ws_path2.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_path1)
    init_test_git_repo(ws_path2)

    async with real_postgres_session_factory() as session:
        ws1 = Workspace(name="ws_ind_1", root_path=str(ws_path1))
        ws2 = Workspace(name="ws_ind_2", root_path=str(ws_path2))
        session.add_all([ws1, ws2])
        await session.flush()

        task1 = Task(workspace_id=ws1.id, prompt="Task 1", status=TaskStatus.PENDING)
        task2 = Task(workspace_id=ws2.id, prompt="Task 2", status=TaskStatus.PENDING)
        session.add_all([task1, task2])
        await session.commit()
        id1, id2 = str(task1.id), str(task2.id)

    class FastMockGraph:
        async def aget_state(self, config):
            return None

    mock_graph = FastMockGraph()

    async def execute_task(t_id: str):
        async with real_postgres_session_factory() as db:
            return await TaskService.prepare_task_for_run(db, t_id, mock_graph)

    res1, res2 = await asyncio.gather(execute_task(id1), execute_task(id2))

    assert res1[1] is True
    assert res2[1] is True


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_postgres_workspace_lock_held_during_approval_interruption(
    tmp_path: Path, real_postgres_session_factory
):
    """Case 4: Proves workspace remains reserved while a task is in AWAITING_APPROVAL."""
    ws_path = tmp_path / "ws_approval_held"
    ws_path.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_path)

    async with real_postgres_session_factory() as session:
        ws = Workspace(name="ws_appr_held", root_path=str(ws_path))
        session.add(ws)
        await session.flush()

        task1 = Task(workspace_id=ws.id, prompt="Task 1", status=TaskStatus.PENDING)
        task2 = Task(workspace_id=ws.id, prompt="Task 2", status=TaskStatus.PENDING)
        session.add_all([task1, task2])
        await session.commit()
        id1, id2 = str(task1.id), str(task2.id)

    # 1. Task 1 runs and reaches approval_gate
    async with real_postgres_session_factory() as db:
        t1, should_run1 = await TaskService.prepare_task_for_run(db, id1)
        assert should_run1 is True
        await TaskService.update_task_status(db, t1, "awaiting_approval")

    # 2. Task 2 attempts to run on the SAME workspace while Task 1 is awaiting approval -> REJECTED (409)
    async with real_postgres_session_factory() as db:
        with pytest.raises(AppException) as exc_info:
            await TaskService.prepare_task_for_run(db, id2)
        assert exc_info.value.status_code == 409

    # 3. Task 1 is approved and transitions to completed
    async with real_postgres_session_factory() as db:
        t1_appr = await TaskService.prepare_task_for_approval(db, id1)
        await TaskService.update_task_status(db, t1_appr, "completed")

    # 4. Now that Task 1 is completed, Task 2 can acquire the workspace
    async with real_postgres_session_factory() as db:
        t2, should_run2 = await TaskService.prepare_task_for_run(db, id2)
        assert should_run2 is True


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_postgres_terminal_task_releases_workspace(
    tmp_path: Path, real_postgres_session_factory
):
    """Case 5: Proves a completed task immediately releases workspace reservation."""
    ws_path = tmp_path / "ws_terminal_release"
    ws_path.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_path)

    async with real_postgres_session_factory() as session:
        ws = Workspace(name="ws_term_rel", root_path=str(ws_path))
        session.add(ws)
        await session.flush()

        task1 = Task(workspace_id=ws.id, prompt="Task 1", status=TaskStatus.COMPLETED)
        task2 = Task(workspace_id=ws.id, prompt="Task 2", status=TaskStatus.PENDING)
        session.add_all([task1, task2])
        await session.commit()
        id2 = str(task2.id)

    async with real_postgres_session_factory() as db:
        t2, should_run = await TaskService.prepare_task_for_run(db, id2)
        assert should_run is True


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_postgres_failed_task_releases_workspace(
    tmp_path: Path, real_postgres_session_factory
):
    """Case 6: Proves a failed task immediately releases workspace reservation."""
    ws_path = tmp_path / "ws_failed_release"
    ws_path.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_path)

    async with real_postgres_session_factory() as session:
        ws = Workspace(name="ws_fail_rel", root_path=str(ws_path))
        session.add(ws)
        await session.flush()

        task1 = Task(workspace_id=ws.id, prompt="Task 1", status=TaskStatus.FAILED)
        task2 = Task(workspace_id=ws.id, prompt="Task 2", status=TaskStatus.PENDING)
        session.add_all([task1, task2])
        await session.commit()
        id2 = str(task2.id)

    async with real_postgres_session_factory() as db:
        t2, should_run = await TaskService.prepare_task_for_run(db, id2)
        assert should_run is True


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_postgres_stale_crashed_task_recovered_and_releases_workspace(
    tmp_path: Path, real_postgres_session_factory
):
    """Case 7: Proves a crashed task in RUNNING state is reconciled and unblocks the workspace."""
    ws_path = tmp_path / "ws_stale_crash"
    ws_path.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_path)

    async with real_postgres_session_factory() as session:
        ws = Workspace(name="ws_stale_rec", root_path=str(ws_path))
        session.add(ws)
        await session.flush()

        # Task 1 was left in RUNNING when process died
        task1 = Task(workspace_id=ws.id, prompt="Task 1", status=TaskStatus.RUNNING)
        task2 = Task(workspace_id=ws.id, prompt="Task 2", status=TaskStatus.PENDING)
        session.add_all([task1, task2])
        await session.commit()
        id1, id2 = str(task1.id), str(task2.id)

    class CrashedStateGraph:
        async def aget_state(self, config):
            # Graph returns None/empty snapshot indicating no active checkpoint
            return None

    crashed_graph = CrashedStateGraph()

    async with real_postgres_session_factory() as db:
        # Task 2 calls prepare_task_for_run; it must reconcile Task 1 to FAILED and claim the workspace
        t2, should_run = await TaskService.prepare_task_for_run(db, id2, graph=crashed_graph)
        assert should_run is True

    # Verify Task 1 was reconciled to FAILED
    async with real_postgres_session_factory() as db:
        t1 = await TaskService.get_task(db, id1)
        assert t1.status == TaskStatus.FAILED
