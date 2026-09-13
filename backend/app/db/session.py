import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from app.core.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=settings.DEBUG,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency yielding asynchronous database sessions with robust error rollbacks."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as err:
            logger.error(
                "Database session encountered an unhandled exception. Rolling back: %s",
                err,
            )
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager equivalent of get_db for background workflows and lifespan tasks."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as err:
            logger.error(
                "Database context session encountered an error. Rolling back: %s", err
            )
            await session.rollback()
            raise
        finally:
            await session.close()
