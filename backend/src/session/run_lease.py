"""Per-thread run leases backed by PostgreSQL advisory locks.

The lock is held on a dedicated pool connection for the lifetime of one SSE
response. PostgreSQL releases it automatically if the backend process or DB
connection dies, so no separate TTL sweeper is required.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

logger = logging.getLogger("diagram-agent")

_DEV_GUARD = Lock()
_DEV_LEASES: dict[tuple[str, str], str] = {}


def advisory_lock_key(tenant_id: str, thread_id: str) -> int:
    """Map a tenant/thread pair to PostgreSQL's signed bigint lock key."""
    digest = hashlib.blake2b(f"{tenant_id}\0{thread_id}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


@dataclass
class RunLease:
    tenant_id: str
    thread_id: str
    run_id: str
    _connection_context: Any = None
    _connection: Any = None
    _lock_key: int | None = None
    _dev_key: tuple[str, str] | None = None
    _released: bool = False
    _release_guard: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def release(self) -> None:
        """Release exactly once; safe from both disconnect and normal completion."""
        async with self._release_guard:
            if self._released:
                return
            self._released = True
            try:
                if self._connection is not None and self._lock_key is not None:
                    await self._connection.execute("SELECT pg_advisory_unlock(%s)", (self._lock_key,))
                elif self._dev_key is not None:
                    with _DEV_GUARD:
                        if _DEV_LEASES.get(self._dev_key) == self.run_id:
                            _DEV_LEASES.pop(self._dev_key, None)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "failed to release run lease thread=%s run=%s: %s",
                    self.thread_id,
                    self.run_id,
                    exc,
                )
            finally:
                if self._connection_context is not None:
                    try:
                        await self._connection_context.__aexit__(None, None, None)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "failed to return run-lease connection thread=%s run=%s: %s",
                            self.thread_id,
                            self.run_id,
                            exc,
                        )
                    self._connection_context = None
                    self._connection = None


async def try_acquire_run_lease(
    pool: Any,
    *,
    tenant_id: str,
    thread_id: str,
    run_id: str,
) -> RunLease | None:
    """Acquire a session-scoped advisory lock without waiting.

    ``pool is None`` is the documented in-memory development mode. It still
    gets process-local exclusion so local testing does not retain the original
    same-thread race, while production gets cross-process exclusion from
    PostgreSQL.
    """
    if pool is None:
        dev_key = (tenant_id, thread_id)
        with _DEV_GUARD:
            if dev_key in _DEV_LEASES:
                return None
            _DEV_LEASES[dev_key] = run_id
        return RunLease(tenant_id, thread_id, run_id, _dev_key=dev_key)

    lock_key = advisory_lock_key(tenant_id, thread_id)
    connection_context = pool.connection()
    connection = await connection_context.__aenter__()
    try:
        cursor = await connection.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,))
        row = await cursor.fetchone()
        acquired = bool(row and row[0])
    except Exception:
        await connection_context.__aexit__(None, None, None)
        raise
    if not acquired:
        await connection_context.__aexit__(None, None, None)
        return None
    logger.info("acquired run lease thread=%s run=%s", thread_id, run_id)
    return RunLease(
        tenant_id,
        thread_id,
        run_id,
        _connection_context=connection_context,
        _connection=connection,
        _lock_key=lock_key,
    )
