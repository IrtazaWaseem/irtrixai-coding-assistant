import asyncio
import logging
import sys
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import settings

logger = logging.getLogger(__name__)

# On Windows, psycopg async requires SelectorEventLoop instead of default ProactorEventLoop
if sys.platform == "win32":
    try:
        if not isinstance(
            asyncio.get_event_loop_policy(), asyncio.WindowsSelectorEventLoopPolicy
        ):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass


class PostgresCheckpointerManager:
    """Manages the lifecycle of the production PostgreSQL LangGraph checkpoint saver."""

    def __init__(self, uri: str | None = None) -> None:
        raw_uri = uri or settings.postgres_uri
        # Append connect_timeout=3 query param so unreachable endpoints fail fast
        if "connect_timeout" not in raw_uri:
            sep = "&" if "?" in raw_uri else "?"
            self._uri = f"{raw_uri}{sep}connect_timeout=3"
        else:
            self._uri = raw_uri

        self._saver_cm: Any = None
        self._saver: AsyncPostgresSaver | None = None
        self._is_initialized: bool = False

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized

    async def initialize(self) -> AsyncPostgresSaver:
        """Initializes connection pool, executes checkpoint DDL migrations, and returns active saver.

        Fails closed: if PostgreSQL is unavailable, raises RuntimeError without silent fallback.
        """
        if self._is_initialized and self._saver is not None:
            return self._saver

        logger.info(
            "Initializing PostgreSQL LangGraph checkpointer (server=%s:%s, db=%s)",
            settings.POSTGRES_SERVER,
            settings.POSTGRES_PORT,
            settings.POSTGRES_DB,
        )

        try:
            self._saver_cm = AsyncPostgresSaver.from_conn_string(self._uri)
            self._saver = await self._saver_cm.__aenter__()

            await self._saver.setup()
            self._is_initialized = True
            logger.info("PostgreSQL LangGraph checkpointer successfully initialized.")
            return self._saver
        except Exception as err:
            logger.exception("Failed to initialize PostgreSQL checkpointer: %s", err)
            await self.close()
            raise RuntimeError(
                f"PostgreSQL checkpointer initialization failed: {err}"
            ) from err

    def get_checkpointer(self) -> BaseCheckpointSaver:
        """Retrieves the active checkpointer. Fails closed if not initialized."""
        if not self._is_initialized or self._saver is None:
            raise RuntimeError(
                "PostgresCheckpointerManager is not initialized. "
                "Ensure initialize() is called during application lifespan startup."
            )
        return self._saver

    async def close(self) -> None:
        """Cleanly tears down the checkpointer connection pool on application shutdown."""
        if self._saver_cm is not None:
            logger.info("Closing PostgreSQL LangGraph checkpointer connection pool.")
            try:
                await self._saver_cm.__aexit__(None, None, None)
            except Exception as err:
                logger.warning("Error closing checkpointer connection pool: %s", err)
            finally:
                self._saver_cm = None
                self._saver = None
                self._is_initialized = False


checkpointer_manager = PostgresCheckpointerManager()
