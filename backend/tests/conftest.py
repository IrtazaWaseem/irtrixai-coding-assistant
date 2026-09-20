import os
from collections.abc import AsyncGenerator

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

import app.db.session as session_module
from app.core.config import settings
from app.db.base import Base
from app.db.models import Workspace
from app.db.session import get_db
from app.main import app

ORIGINAL_DEV_DATABASE_URL = settings.DATABASE_URL


def get_test_database_url() -> str:
    """
    Returns the configured TEST_DATABASE_URL.
    Fails clearly if TEST_DATABASE_URL is not set, preventing database tests
    from ever running against or polluting the development database.
    """
    url = settings.TEST_DATABASE_URL or os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "TEST_DATABASE_URL is not configured. Database tests require a dedicated "
            "test database (e.g. postgresql+asyncpg://.../irtrixai_test) to prevent "
            "polluting development data. Set TEST_DATABASE_URL in .env.",
            pytrace=False,
        )
    return url


# Rebind globals at test session load time so background tasks and imports target test DB
_initial_test_url = settings.TEST_DATABASE_URL or os.environ.get("TEST_DATABASE_URL")
if _initial_test_url:
    settings.DATABASE_URL = _initial_test_url
    _parsed = make_url(_initial_test_url)
    if _parsed.database:
        settings.POSTGRES_DB = _parsed.database
    if _parsed.username:
        settings.POSTGRES_USER = _parsed.username
    if _parsed.password:
        settings.POSTGRES_PASSWORD = _parsed.password
    if _parsed.host:
        settings.POSTGRES_SERVER = _parsed.host
    if _parsed.port:
        settings.POSTGRES_PORT = _parsed.port

    session_module.engine = create_async_engine(
        _initial_test_url,
        poolclass=NullPool,
        echo=False,
        future=True,
    )
    session_module.AsyncSessionLocal = async_sessionmaker(
        bind=session_module.engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def ensure_test_database_exists(test_db_url: str) -> None:
    """Ensure the target test database exists on the PostgreSQL server."""
    parsed = make_url(test_db_url)
    db_name = parsed.database
    if not db_name:
        return

    try:
        conn = await asyncpg.connect(
            user=parsed.username,
            password=parsed.password,
            host=parsed.host,
            port=parsed.port or 5432,
            database=db_name,
        )
        await conn.close()
    except asyncpg.InvalidCatalogNameError:
        sys_conn = None
        for maint_db in ("postgres", "template1", "irtrixai_db"):
            try:
                sys_conn = await asyncpg.connect(
                    user=parsed.username,
                    password=parsed.password,
                    host=parsed.host,
                    port=parsed.port or 5432,
                    database=maint_db,
                )
                break
            except (asyncpg.PostgresError, OSError):
                continue

        if sys_conn:
            try:
                await sys_conn.execute(f'CREATE DATABASE "{db_name}"')
            finally:
                await sys_conn.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_database():
    """
    Session-level fixture to create schema in test database once.
    Uses NullPool so no open connections are leaked across async loops.
    """
    test_url = settings.TEST_DATABASE_URL or os.environ.get("TEST_DATABASE_URL")
    if not test_url:
        yield
        return

    await ensure_test_database_exists(test_url)

    init_engine = create_async_engine(test_url, poolclass=NullPool, echo=False)
    async with init_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await init_engine.dispose()

    yield

    if session_module.engine:
        await session_module.engine.dispose()


@pytest.fixture(autouse=True)
def guard_database_url_in_tests(request):
    """
    Guarantees that any test requesting database fixtures or marked as database integration
    fails immediately if TEST_DATABASE_URL is not set.
    """
    db_fixtures = {"db_session", "client", "sample_workspace"}
    requires_db = any(f in request.fixturenames for f in db_fixtures) or (
        request.node.get_closest_marker("postgres") is not None
        or request.node.get_closest_marker("integration") is not None
    )
    if requires_db:
        get_test_database_url()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Provides an isolated AsyncSession bound to a nested savepoint transaction.
    Inner commits release savepoints; test teardown rolls back the outer transaction.
    """
    get_test_database_url()
    async with session_module.engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )

        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Provides an HTTP client where FastAPI get_db dependency uses the test's
    transactional savepoint session.
    """

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def sample_workspace(db_session: AsyncSession, tmp_path) -> Workspace:
    import uuid

    ws = Workspace(
        id=str(uuid.uuid4()),
        name="test-workspace",
        root_path=str(tmp_path),
    )
    db_session.add(ws)
    await db_session.commit()
    await db_session.refresh(ws)
    return ws
