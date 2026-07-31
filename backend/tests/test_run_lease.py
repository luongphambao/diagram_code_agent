from __future__ import annotations

import pytest

from session.run_lease import advisory_lock_key, try_acquire_run_lease


class _Cursor:
    def __init__(self, acquired: bool):
        self.acquired = acquired

    async def fetchone(self):
        return (self.acquired,)


class _Connection:
    def __init__(self, acquired: bool):
        self.acquired = acquired
        self.queries: list[tuple[str, tuple]] = []

    async def execute(self, query: str, params: tuple):
        self.queries.append((query, params))
        return _Cursor(self.acquired)


class _ConnectionContext:
    def __init__(self, connection: _Connection):
        self.connection = connection
        self.exited = False

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        self.exited = True


class _Pool:
    def __init__(self, acquired: bool):
        self.context = _ConnectionContext(_Connection(acquired))

    def connection(self):
        return self.context


def test_advisory_lock_key_is_stable_and_tenant_scoped():
    assert advisory_lock_key("tenant-a", "thread-1") == advisory_lock_key("tenant-a", "thread-1")
    assert advisory_lock_key("tenant-a", "thread-1") != advisory_lock_key("tenant-b", "thread-1")


@pytest.mark.anyio
async def test_postgres_lease_holds_connection_until_release():
    pool = _Pool(acquired=True)
    lease = await try_acquire_run_lease(pool, tenant_id="tenant-a", thread_id="thread-1", run_id="run-1")

    assert lease is not None
    assert pool.context.exited is False
    assert "pg_try_advisory_lock" in pool.context.connection.queries[0][0]

    await lease.release()
    assert "pg_advisory_unlock" in pool.context.connection.queries[1][0]
    assert pool.context.exited is True


@pytest.mark.anyio
async def test_busy_postgres_lease_returns_none_and_releases_connection():
    pool = _Pool(acquired=False)
    lease = await try_acquire_run_lease(pool, tenant_id="tenant-a", thread_id="thread-1", run_id="run-2")
    assert lease is None
    assert pool.context.exited is True


@pytest.mark.anyio
async def test_dev_lease_rejects_same_thread_until_release():
    first = await try_acquire_run_lease(None, tenant_id="tenant-a", thread_id="dev-thread", run_id="run-1")
    second = await try_acquire_run_lease(None, tenant_id="tenant-a", thread_id="dev-thread", run_id="run-2")
    assert first is not None
    assert second is None
    await first.release()
    third = await try_acquire_run_lease(None, tenant_id="tenant-a", thread_id="dev-thread", run_id="run-3")
    assert third is not None
    await third.release()
