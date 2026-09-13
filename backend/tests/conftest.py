import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import engine


@pytest.fixture(autouse=True)
async def reset_db_engine():
    """Ensures database engine state is fresh across async test loops."""
    yield
    if isinstance(engine, AsyncEngine):
        await engine.dispose()
