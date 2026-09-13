import asyncio
import os
from pathlib import Path
import subprocess
import sys

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


def get_test_postgres_uri() -> str:
    user = os.getenv("TEST_POSTGRES_USER", "postgres")
    password = os.getenv("TEST_POSTGRES_PASSWORD", "test_secure_password_123")
    host = os.getenv("TEST_POSTGRES_HOST", "localhost")
    port = os.getenv("TEST_POSTGRES_PORT", "15432")
    db = os.getenv("TEST_POSTGRES_DB", "irtrixai_test")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def get_test_postgres_async_uri() -> str:
    return get_test_postgres_uri().replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest_asyncio.fixture
async def real_postgres_session_factory():
    """Initializes schema on live PostgreSQL and yields an isolated async sessionmaker."""
    async_uri = get_test_postgres_async_uri()
    try:
        engine = create_async_engine(async_uri, echo=False, pool_pre_ping=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        pytest.fail(
            f"Test PostgreSQL instance unreachable at {async_uri}. "
            f"Ensure test PostgreSQL is running with 'docker-compose -f docker-compose.test.yml up -d'. Error: {exc}"
        )

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    yield session_factory

    await engine.dispose()


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_postgres_concurrent_same_task_run_prevented(
    tmp_path: Path, real_postgres_session_factory
):
    """Proves two simultaneous /run attempts on the SAME task row cannot both acquire execution."""
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

    class MockSnapshot:
        def __init__(self, values: dict, next_steps: tuple):
            self.values = values
            self.next = next_steps

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

    async with real_postgres_session_factory() as verify_session:
        final_task = await TaskService.get_task(verify_session, task_id)
        assert final_task.status == TaskStatus.RUNNING


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_postgres_independent_tasks_execute_concurrently(
    tmp_path: Path, real_postgres_session_factory
):
    """Proves Task A and Task B execute concurrently without global database lock contention."""
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
