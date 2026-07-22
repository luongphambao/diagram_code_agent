"""Conversation metadata stored in a project-owned Postgres table.

The actual LangGraph checkpoint data lives in the langgraph_* tables managed
by AsyncPostgresSaver/AsyncPostgresStore.  This module stores only the
display-layer data:
  - name, timestamps, last-message preview  (for the sidebar list)
  - messages_json  (wire-message array → restore full chat history)
  - state_json     (AgentState snapshot → restore diagram / logs view)

All functions accept `pool` which may be None (in-memory dev mode); in that
case they are silently no-ops / return empty data.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger("diagram-agent")

_DDL = """
CREATE TABLE IF NOT EXISTS conversations (
    thread_id     TEXT PRIMARY KEY,
    name          TEXT        NOT NULL DEFAULT 'Untitled',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_message  TEXT        NOT NULL DEFAULT '',
    messages_json TEXT        NOT NULL DEFAULT '[]',
    state_json    TEXT        NOT NULL DEFAULT '{}',
    outcomes_json TEXT        NOT NULL DEFAULT '[]',
    owner_email   TEXT        NOT NULL DEFAULT ''
);
"""

# Idempotent: add columns to existing tables created without them.
# owner_email (improvement plan §0.6): the first authenticated caller to touch a
# thread claims it (see security/ownership.py). '' means unowned — either a
# legacy row from before this migration, or a thread nobody has claimed yet;
# unowned rows stay visible to every caller rather than locking out existing
# users the moment this ships (see list_all/get_owner/claim_owner below).
#
# ONE statement per list entry, executed via separate conn.execute() calls
# below — NOT joined into one semicolon-separated string. psycopg3 sends a
# non-parameterized execute() through PostgreSQL's extended query protocol
# (Parse/Bind/Execute), which only accepts a SINGLE command per prepared
# statement; a multi-statement string intermittently raises "cannot insert
# multiple commands into a prepared statement" depending on the connection's
# prior state (observed in production: silently swallowed by setup()'s own
# except-and-warn, so outcomes_json's ALTER (added first, alone) had already
# succeeded on an earlier deploy while owner_email's (added later, as a
# second statement in the same string) never actually ran — the column stayed
# missing while every query referencing it failed at request time instead).
_ALTER_STATEMENTS = [
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS outcomes_json TEXT NOT NULL DEFAULT '[]';",
    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS owner_email TEXT NOT NULL DEFAULT '';",
]


async def setup(pool) -> None:
    """Create the conversations table (+ idempotent column migration)."""
    if pool is None:
        return
    try:
        async with pool.connection() as conn:
            await conn.execute(_DDL)
            for statement in _ALTER_STATEMENTS:
                await conn.execute(statement)
        logger.info("conversations table ready")
    except Exception as exc:  # noqa: BLE001
        logger.warning("conversations table setup failed: %s", exc)


async def list_all(pool, owner_email: str = "") -> list[dict]:
    """List conversations visible to *owner_email*: rows it owns, plus unowned
    (legacy/unclaimed) rows. An empty *owner_email* (unauthenticated dev mode)
    returns everything, matching the pre-§0.6 behavior."""
    if pool is None:
        return []
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                if owner_email:
                    await cur.execute(
                        "SELECT thread_id, name, created_at, updated_at, last_message "
                        "FROM conversations WHERE owner_email = %s OR owner_email = '' "
                        "ORDER BY updated_at DESC",
                        (owner_email,),
                    )
                else:
                    await cur.execute(
                        "SELECT thread_id, name, created_at, updated_at, last_message "
                        "FROM conversations ORDER BY updated_at DESC"
                    )
                rows = await cur.fetchall()
        return [
            {
                "thread_id": r[0],
                "name": r[1],
                "created_at": r[2].isoformat() if r[2] else None,
                "updated_at": r[3].isoformat() if r[3] else None,
                "last_message": r[4],
            }
            for r in rows
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("list_all conversations failed: %s", exc)
        return []


async def create(pool, thread_id: str, name: str, owner_email: str = "") -> dict:
    """Create *thread_id* (no-op if it already exists) and, if it is currently
    unowned, claim it for *owner_email* — covers both "brand-new thread" and "an
    /agui run touched this thread_id before the user explicitly named it"
    without overwriting an existing owner or name."""
    if pool is not None:
        try:
            async with pool.connection() as conn:
                await conn.execute(
                    "INSERT INTO conversations (thread_id, name, owner_email) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (thread_id) DO UPDATE SET "
                    "owner_email = CASE WHEN conversations.owner_email = '' "
                    "THEN EXCLUDED.owner_email ELSE conversations.owner_email END",
                    (thread_id, name, owner_email),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("create conversation failed: %s", exc)
    return {"thread_id": thread_id, "name": name}


async def get_owner(pool, thread_id: str) -> str | None:
    """Return the owner email for *thread_id*, or None if the thread doesn't
    exist yet or has no persistence layer (in-memory dev mode)."""
    if pool is None:
        return None
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT owner_email FROM conversations WHERE thread_id=%s",
                    (thread_id,),
                )
                row = await cur.fetchone()
        if row is None:
            return None
        return row[0] or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_owner failed: %s", exc)
        return None


async def claim_owner(pool, thread_id: str, owner_email: str) -> None:
    """Bind *thread_id* to *owner_email*, creating the row if it doesn't exist
    yet. No-op if the row already has a (different) owner — first claim wins."""
    if pool is None or not owner_email:
        return
    try:
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO conversations (thread_id, owner_email) VALUES (%s, %s) "
                "ON CONFLICT (thread_id) DO UPDATE SET "
                "owner_email = CASE WHEN conversations.owner_email = '' "
                "THEN EXCLUDED.owner_email ELSE conversations.owner_email END",
                (thread_id, owner_email),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("claim_owner failed: %s", exc)


async def rename(pool, thread_id: str, name: str) -> None:
    if pool is None:
        return
    try:
        async with pool.connection() as conn:
            await conn.execute(
                "UPDATE conversations SET name=%s, updated_at=NOW() WHERE thread_id=%s",
                (name, thread_id),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("rename conversation failed: %s", exc)


async def delete(pool, thread_id: str) -> None:
    if pool is None:
        return
    try:
        async with pool.connection() as conn:
            await conn.execute("DELETE FROM conversations WHERE thread_id=%s", (thread_id,))
    except Exception as exc:  # noqa: BLE001
        logger.warning("delete conversation failed: %s", exc)


async def upsert_run(
    pool,
    *,
    thread_id: str,
    messages: list,
    state: dict,
    last_msg: str,
    auto_name: str,
    owner_email: str = "",
) -> None:
    """Upsert conversation after each /agui run completes.

    - Creates the row if new (uses auto_name as the initial name).
    - Updates timestamps, last_message, messages_json, state_json on every run.
    - Does NOT overwrite a user-set name (only overwrites 'Untitled').
    - Claims the row for *owner_email* if it is currently unowned (§0.6); does
      NOT overwrite an existing (different) owner.
    """
    if pool is None:
        return
    # Don't store the png_base64 in messages; keep it only in state_json to
    # avoid bloating the messages column (state already has it).
    try:
        async with pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO conversations
                    (thread_id, name, last_message, messages_json, state_json, owner_email)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (thread_id) DO UPDATE SET
                    updated_at    = NOW(),
                    last_message  = EXCLUDED.last_message,
                    messages_json = EXCLUDED.messages_json,
                    state_json    = EXCLUDED.state_json,
                    name          = CASE
                                        WHEN conversations.name = 'Untitled'
                                        THEN EXCLUDED.name
                                        ELSE conversations.name
                                    END,
                    owner_email   = CASE
                                        WHEN conversations.owner_email = ''
                                        THEN EXCLUDED.owner_email
                                        ELSE conversations.owner_email
                                    END
                """,
                (
                    thread_id,
                    auto_name,
                    last_msg[:200],
                    json.dumps(messages, ensure_ascii=False),
                    json.dumps(state, ensure_ascii=False),
                    owner_email,
                ),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("upsert_run failed: %s", exc)


async def record_gate_outcome(
    pool,
    *,
    thread_id: str,
    gate: str,
    decision: str,
    note: str = "",
) -> None:
    """Append one gate decision to outcomes_json for a conversation.

    Each entry: ``{gate, decision, note, timestamp}``.
    ``decision`` is "approve" or "reject".  ``note`` is the user's feedback
    text (empty string when none given).  Silently no-ops when pool is None.
    """
    if pool is None:
        return
    import datetime

    entry = {
        "gate": gate,
        "decision": decision,
        "note": note,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }
    try:
        async with pool.connection() as conn:
            # Read current array, append, write back.
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT outcomes_json FROM conversations WHERE thread_id=%s",
                    (thread_id,),
                )
                row = await cur.fetchone()
            existing: list = json.loads(row[0]) if row and row[0] else []
            existing.append(entry)
            await conn.execute(
                "UPDATE conversations SET outcomes_json=%s WHERE thread_id=%s",
                (json.dumps(existing), thread_id),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("record_gate_outcome failed: %s", exc)


async def get_history(pool, thread_id: str) -> dict | None:
    """Return the stored messages + state for a past conversation, or None."""
    if pool is None:
        return None
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT name, messages_json, state_json FROM conversations WHERE thread_id=%s",
                    (thread_id,),
                )
                row = await cur.fetchone()
        if row is None:
            return None
        return {
            "name": row[0],
            "messages": json.loads(row[1]) if row[1] else [],
            "state": json.loads(row[2]) if row[2] else {},
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_history failed: %s", exc)
        return None
