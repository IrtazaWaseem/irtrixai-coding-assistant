import asyncio
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Task, TaskStatus, Workspace

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def event_loop_policy():
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get_test_postgres_uri() -> str:
    user = os.getenv("TEST_POSTGRES_USER", "postgres")
    password = os.getenv("TEST_POSTGRES_PASSWORD", "test_secure_password_123")
    host = os.getenv("TEST_POSTGRES_HOST", "localhost")
    port = os.getenv("TEST_POSTGRES_PORT", "15432")
    db = os.getenv("TEST_POSTGRES_DB", "irtrixai_test")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def get_test_postgres_async_uri() -> str:
    return get_test_postgres_uri().replace("postgresql://", "postgresql+asyncpg://", 1)


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


@pytest.mark.multiworker
@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_multiworker_checkpointer_concurrent_startup():
    """Proves two distinct OS processes can initialize PostgresCheckpointerManager concurrently without race conditions."""
    async_uri = get_test_postgres_async_uri()
    user = os.getenv("TEST_POSTGRES_USER", "postgres")
    password = os.getenv("TEST_POSTGRES_PASSWORD", "test_secure_password_123")
    host = os.getenv("TEST_POSTGRES_HOST", "localhost")
    db_port = os.getenv("TEST_POSTGRES_PORT", "15432")
    db_name = os.getenv("TEST_POSTGRES_DB", "irtrixai_test")

    env = {
        **os.environ,
        "PYTHONPATH": ".",
        "POSTGRES_HOST": host,
        "POSTGRES_PORT": str(db_port),
        "POSTGRES_USER": user,
        "POSTGRES_PASSWORD": password,
        "POSTGRES_DB": db_name,
        "DATABASE_URL": async_uri,
    }

    script = (
        "import sys, asyncio\n"
        "if sys.platform == 'win32':\n"
        "    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())\n"
        "from app.agent.checkpoint import PostgresCheckpointerManager\n"
        "async def run():\n"
        "    mgr = PostgresCheckpointerManager()\n"
        "    await mgr.initialize()\n"
        "    assert mgr.is_initialized\n"
        "    await mgr.close()\n"
        "asyncio.run(run())\n"
    )

    proc1 = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    proc2 = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    out1, err1 = proc1.communicate(timeout=25)
    out2, err2 = proc2.communicate(timeout=25)

    assert proc1.returncode == 0, (
        f"Process 1 failed checkpointer initialization:\n{err1.decode('utf-8', errors='replace')}"
    )
    assert proc2.returncode == 0, (
        f"Process 2 failed checkpointer initialization:\n{err2.decode('utf-8', errors='replace')}"
    )


@pytest.mark.multiworker
@pytest.mark.postgres
@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_multiworker_process_duplicate_run_protection(tmp_path: Path):
    """Proves two distinct OS uvicorn worker processes sharing PostgreSQL reject duplicate execution."""
    async_uri = get_test_postgres_async_uri()
    try:
        engine = create_async_engine(async_uri, echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for col_sql in [
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS prompt_tokens INTEGER DEFAULT 0 NOT NULL;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS completion_tokens INTEGER DEFAULT 0 NOT NULL;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS total_tokens INTEGER DEFAULT 0 NOT NULL;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS llm_calls INTEGER DEFAULT 0 NOT NULL;",
                "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS provider_usage JSONB DEFAULT '{}'::jsonb;",
                "ALTER TABLE runs ADD COLUMN IF NOT EXISTS prompt_tokens INTEGER DEFAULT 0 NOT NULL;",
                "ALTER TABLE runs ADD COLUMN IF NOT EXISTS completion_tokens INTEGER DEFAULT 0 NOT NULL;",
                "ALTER TABLE runs ADD COLUMN IF NOT EXISTS total_tokens INTEGER DEFAULT 0 NOT NULL;",
                "ALTER TABLE runs ADD COLUMN IF NOT EXISTS llm_calls INTEGER DEFAULT 0 NOT NULL;",
                "ALTER TABLE runs ADD COLUMN IF NOT EXISTS provider_usage JSONB DEFAULT '{}'::jsonb;",
            ]:
                await conn.execute(text(col_sql))
    except Exception as exc:
        pytest.fail(
            f"Test PostgreSQL not reachable for multiworker test at {async_uri}. "
            f"Ensure test container is running via 'docker-compose -f docker-compose.test.yml up -d'. Error: {exc}"
        )

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    ws_path = tmp_path / "ws_multiworker"
    ws_path.mkdir(parents=True, exist_ok=True)
    init_test_git_repo(ws_path)

    async with session_factory() as session:
        ws = Workspace(name="ws_mw", root_path=str(ws_path))
        session.add(ws)
        await session.flush()
        task = Task(workspace_id=ws.id, prompt="Multiworker test", status=TaskStatus.PENDING)
        session.add(task)
        await session.commit()
        task_id = str(task.id)

    port1 = get_free_port()
    port2 = get_free_port()

    log1 = tempfile.NamedTemporaryFile(mode="w+b", delete=False)
    log2 = tempfile.NamedTemporaryFile(mode="w+b", delete=False)

    user = os.getenv("TEST_POSTGRES_USER", "postgres")
    password = os.getenv("TEST_POSTGRES_PASSWORD", "test_secure_password_123")
    host = os.getenv("TEST_POSTGRES_HOST", "localhost")
    db_port = os.getenv("TEST_POSTGRES_PORT", "15432")
    db_name = os.getenv("TEST_POSTGRES_DB", "irtrixai_test")

    env = {
        **os.environ,
        "PYTHONPATH": ".",
        "POSTGRES_HOST": host,
        "POSTGRES_PORT": str(db_port),
        "POSTGRES_USER": user,
        "POSTGRES_PASSWORD": password,
        "POSTGRES_DB": db_name,
        "DATABASE_URL": async_uri,
    }

    worker_script = (
        "import sys, asyncio\n"
        "from unittest.mock import AsyncMock, MagicMock\n"
        "if sys.platform == 'win32':\n"
        "    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())\n"
        "from app.agent.nodes import set_llm_gateway\n"
        "from app.schemas.agent_contracts import PlannerOutput, CoderOutput\n"
        "mock_gw = MagicMock()\n"
        "async def mock_gen(prompt, response_schema, **kw):\n"
        "    await asyncio.sleep(0.3)\n"
        "    if response_schema is PlannerOutput:\n"
        "        return PlannerOutput(summary='Plan', steps=['S1'], files_expected=['a.py'])\n"
        "    if response_schema is CoderOutput:\n"
        "        return CoderOutput(summary='Code', patch='diff', files_changed=['a.py'])\n"
        "    return response_schema.model_validate({})\n"
        "mock_gw.generate_structured = AsyncMock(side_effect=mock_gen)\n"
        "set_llm_gateway(mock_gw)\n"
        "import uvicorn\n"
        "uvicorn.run('app.main:app', host='127.0.0.1', port=int(sys.argv[1]), loop='none', log_level='warning')\n"
    )

    proc1 = subprocess.Popen(
        [sys.executable, "-c", worker_script, str(port1)],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        stdout=log1,
        stderr=log1,
    )
    proc2 = subprocess.Popen(
        [sys.executable, "-c", worker_script, str(port2)],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        stdout=log2,
        stderr=log2,
    )

    try:

        async def wait_healthy(port: int) -> bool:
            async with AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=1.0) as client:
                for _ in range(60):
                    try:
                        res = await client.get("/health")
                        if res.status_code == 200:
                            return True
                    except Exception:
                        await asyncio.sleep(0.2)
            return False

        h1, h2 = await asyncio.gather(wait_healthy(port1), wait_healthy(port2))
        if not h1 or not h2:
            log1.seek(0)
            log2.seek(0)
            err1 = log1.read().decode("utf-8", errors="replace")[-1000:]
            err2 = log2.read().decode("utf-8", errors="replace")[-1000:]
            pytest.fail(
                "Backend workers failed to reach healthy state within timeout.\n"
                f"Worker 1 Output:\n{err1}\nWorker 2 Output:\n{err2}"
            )

        async with (
            AsyncClient(base_url=f"http://127.0.0.1:{port1}", timeout=15.0) as client1,
            AsyncClient(base_url=f"http://127.0.0.1:{port2}", timeout=15.0) as client2,
        ):
            r1, r2 = await asyncio.gather(
                client1.post(f"/api/v1/tasks/{task_id}/run"),
                client2.post(f"/api/v1/tasks/{task_id}/run"),
            )

        status_codes = [r1.status_code, r2.status_code]
        assert 200 in status_codes
        assert (409 in status_codes) or (status_codes.count(200) == 2 and r1.json() == r2.json())

    finally:
        for p in (proc1, proc2):
            try:
                p.terminate()
                p.wait(timeout=3)
            except Exception:
                p.kill()
        log1.close()
        log2.close()
        try:
            os.unlink(log1.name)
            os.unlink(log2.name)
        except Exception:
            pass
        await engine.dispose()
