"""PostgreSQL checkpointer manager for LangGraph agent persistence."""

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlparse

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import settings
from app.core.exceptions import ToolExecutionException

logger = logging.getLogger(__name__)

POSTGRES_CREDENTIAL_PATTERN = re.compile(
    r"(postgresql(?:\+[a-z0-9]+)?://)([^:/\s]+):(.+)@([^/@\s]+(?::\d+)?(?:/|\?|$))",
    re.IGNORECASE,
)

# Fixed deterministic 64-bit integer identifier for checkpointer setup advisory lock
CHECKPOINTER_SETUP_LOCK_KEY: int = (
    7596528766795491435  # int.from_bytes(b"irtx_chk", "big", signed=True)
)


def sanitize_postgres_error(error: Exception | str) -> str:
    """Sanitizes PostgreSQL errors and URIs, ensuring user and password credentials never leak."""
    raw = str(error)
    if (
        hasattr(settings, "POSTGRES_PASSWORD")
        and settings.POSTGRES_PASSWORD
        and len(settings.POSTGRES_PASSWORD) >= 4
    ):
        raw = raw.replace(settings.POSTGRES_PASSWORD, "[REDACTED_PASSWORD]")
    sanitized = POSTGRES_CREDENTIAL_PATTERN.sub(r"\1[REDACTED_USER]:[REDACTED_PASSWORD]@\4", raw)
    return sanitized


class PostgresCheckpointerManager:
    """Manages the production checkpointer backed strictly by PostgreSQL."""

    def __init__(self) -> None:
        self._checkpointer: Any | None = None
        self._initialized: bool = False
        self._pool: AsyncConnectionPool | None = None

    @property
    def is_initialized(self) -> bool:
        return self._initialized and self._checkpointer is not None

    def get_checkpointer(self) -> Any:
        if not self.is_initialized:
            raise ToolExecutionException(
                "Production checkpointer is not initialized. "
                "The application must run inside lifespan with a healthy PostgreSQL instance."
            )
        return self._checkpointer

    async def initialize(self) -> None:
        """Initializes AsyncConnectionPool and AsyncPostgresSaver with cross-process advisory locking."""
        uri = settings.postgres_uri
        parsed = urlparse(uri)
        logger.info(
            "Initializing PostgreSQL checkpointer on %s:%s/%s",
            parsed.hostname,
            parsed.port,
            parsed.path.lstrip("/"),
        )

        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            pool = AsyncConnectionPool(
                conninfo=uri,
                max_size=20,
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                open=False,
            )
            await pool.open()
            self._pool = pool

            # Acquire a dedicated connection from the pool for session-scoped advisory locking.
            # We use non-blocking pg_try_advisory_lock with an async sleep retry loop rather
            # than blocking pg_advisory_lock. Why: AsyncPostgresSaver.setup() issues
            # CREATE INDEX CONCURRENTLY, which waits for all concurrent virtual transactions to
            # complete. A blocking pg_advisory_lock call holds an open virtual transaction while
            # waiting, which causes PostgreSQL to detect a mutual deadlock between the index
            # build and the advisory lock. Non-blocking polling avoids holding a virtual transaction
            # while waiting.
            async with pool.connection() as conn:
                acquired = False
                for _ in range(300):  # Poll up to 30 seconds (300 * 0.1s)
                    res = await conn.execute(
                        "SELECT pg_try_advisory_lock(%s);",
                        (CHECKPOINTER_SETUP_LOCK_KEY,),
                    )
                    row = await res.fetchone()
                    if row:
                        val = row.get("pg_try_advisory_lock") if isinstance(row, dict) else row[0]
                        if val:
                            acquired = True
                            break
                    await asyncio.sleep(0.1)

                if not acquired:
                    raise ToolExecutionException(
                        "Timed out waiting for PostgreSQL checkpointer setup advisory lock."
                    )

                try:
                    setup_saver = AsyncPostgresSaver(conn)
                    await setup_saver.setup()
                finally:
                    try:
                        await conn.execute(
                            "SELECT pg_advisory_unlock(%s);",
                            (CHECKPOINTER_SETUP_LOCK_KEY,),
                        )
                    except Exception as unlock_err:
                        logger.warning(
                            "Failed to release checkpointer setup advisory lock: %s",
                            sanitize_postgres_error(unlock_err),
                        )

            self._checkpointer = AsyncPostgresSaver(pool)
            self._initialized = True
            logger.info("PostgreSQL checkpointer initialized and migrations verified.")
        except Exception as err:
            self._initialized = False
            self._checkpointer = None
            if self._pool is not None:
                try:
                    await self._pool.close()
                except Exception:
                    pass
                self._pool = None

            clean_err = sanitize_postgres_error(err)
            logger.error("Failed to initialize PostgreSQL checkpointer: %s", clean_err)
            raise ToolExecutionException(
                f"Failed to initialize PostgreSQL checkpointer: {clean_err}"
            ) from err

    async def close(self) -> None:
        """Closes the underlying async connection pool."""
        if self._pool is not None:
            try:
                await self._pool.close()
                logger.info("PostgreSQL checkpointer pool closed.")
            except Exception as err:
                logger.warning("Error closing checkpointer pool: %s", sanitize_postgres_error(err))
            finally:
                self._pool = None
                self._checkpointer = None
                self._initialized = False


checkpointer_manager = PostgresCheckpointerManager()
