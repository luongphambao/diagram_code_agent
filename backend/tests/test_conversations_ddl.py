"""Regression test for conversations.py's migration DDL.

Found via a real deployment: psycopg3 sends a non-parameterized conn.execute()
through PostgreSQL's extended query protocol, which only accepts a SINGLE
command per prepared statement. A semicolon-separated multi-statement string
intermittently raised "cannot insert multiple commands into a prepared
statement" — silently swallowed by setup()'s except-and-warn, so the
owner_email column never actually got added while the app kept running and
every query referencing it failed at request time. No live Postgres needed to
guard against a regression of the root cause: each migration statement must be
its own list entry, never joined into one string.
"""

from __future__ import annotations

import conversations


def test_alter_statements_are_one_command_each():
    for statement in conversations._ALTER_STATEMENTS:
        stripped = statement.strip().rstrip(";")
        assert ";" not in stripped, (
            f"multi-statement DDL will intermittently fail under psycopg3's "
            f"prepared-statement path: {statement!r}"
        )


def test_setup_executes_each_alter_statement_separately():
    """setup() must call conn.execute() once per statement, not once for a
    joined multi-statement string — assert against the actual call sequence
    rather than just the source list, so the DDL and the code that runs it
    can't drift apart again."""

    class _FakeConn:
        def __init__(self):
            self.executed: list[str] = []

        async def execute(self, sql):
            self.executed.append(sql)

    class _FakeConnCtx:
        def __init__(self, conn):
            self._conn = conn

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, *exc):
            return False

    class _FakePool:
        def __init__(self, conn):
            self._conn = conn

        def connection(self):
            return _FakeConnCtx(self._conn)

    import asyncio

    conn = _FakeConn()
    asyncio.run(conversations.setup(_FakePool(conn)))

    # _DDL (CREATE TABLE, one statement) + each entry in _ALTER_STATEMENTS.
    assert conn.executed[0] == conversations._DDL
    assert conn.executed[1:] == conversations._ALTER_STATEMENTS
