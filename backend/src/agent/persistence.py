"""Session persistence: checkpointer + store, Postgres in production, in-memory
in dev."""

from __future__ import annotations

import logging
import os

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

logger = logging.getLogger(__name__)


async def make_persistence():
    """Build session persistence: ``(checkpointer, store, aclose, pool)``.

    Sessions (conversation/thread state + HITL interrupts) are checkpointed so a
    thread survives a server restart. With ``DATABASE_URL`` set we use Postgres
    (durable, the production path); without it we fall back to in-memory (dev only,
    lost on restart). ``aclose`` is an async callable to close the pool on shutdown.
    ``pool`` is the raw AsyncConnectionPool (or None in dev mode) — exposed so the
    server can reuse it for the conversations metadata table.
    """
    db = os.getenv("DATABASE_URL", "").strip()
    if not db:
        logger.warning("DATABASE_URL not set — using IN-MEMORY sessions (NOT durable; dev only).")

        async def _noop():
            return None

        return MemorySaver(), InMemoryStore(), _noop, None

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.store.postgres.aio import AsyncPostgresStore
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(
        conninfo=db,
        max_size=20,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await pool.open()
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()  # idempotent: creates tables on first run
    store = AsyncPostgresStore(pool)
    await store.setup()
    logger.info("Postgres session persistence ready (checkpointer + store).")

    async def _aclose():
        await pool.close()

    return checkpointer, store, _aclose, pool
