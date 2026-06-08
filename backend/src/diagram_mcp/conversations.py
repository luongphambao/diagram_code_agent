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
    outcomes_json TEXT        NOT NULL DEFAULT '[]'
);
"""

# Idempotent: add outcomes_json to existing tables created without it.
_ALTER_DDL = """
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS outcomes_json TEXT NOT NULL DEFAULT '[]';
"""


async def setup(pool) -> None:
    """Create the conversations table (+ idempotent column migration)."""
    if pool is None:
        return
    try:
        async with pool.connection() as conn:
            await conn.execute(_DDL)
            await conn.execute(_ALTER_DDL)
        logger.info("conversations table ready")
    except Exception as exc:  # noqa: BLE001
        logger.warning("conversations table setup failed: %s", exc)


async def list_all(pool) -> list[dict]:
    if pool is None:
        return []
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
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


async def create(pool, thread_id: str, name: str) -> dict:
    if pool is not None:
        try:
            async with pool.connection() as conn:
                await conn.execute(
                    "INSERT INTO conversations (thread_id, name) VALUES (%s, %s) "
                    "ON CONFLICT (thread_id) DO NOTHING",
                    (thread_id, name),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("create conversation failed: %s", exc)
    return {"thread_id": thread_id, "name": name}


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
            await conn.execute(
                "DELETE FROM conversations WHERE thread_id=%s", (thread_id,)
            )
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
) -> None:
    """Upsert conversation after each /agui run completes.

    - Creates the row if new (uses auto_name as the initial name).
    - Updates timestamps, last_message, messages_json, state_json on every run.
    - Does NOT overwrite a user-set name (only overwrites 'Untitled').
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
                    (thread_id, name, last_message, messages_json, state_json)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (thread_id) DO UPDATE SET
                    updated_at    = NOW(),
                    last_message  = EXCLUDED.last_message,
                    messages_json = EXCLUDED.messages_json,
                    state_json    = EXCLUDED.state_json,
                    name          = CASE
                                        WHEN conversations.name = 'Untitled'
                                        THEN EXCLUDED.name
                                        ELSE conversations.name
                                    END
                """,
                (
                    thread_id,
                    auto_name,
                    last_msg[:200],
                    json.dumps(messages, ensure_ascii=False),
                    json.dumps(state, ensure_ascii=False),
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
                    "SELECT name, messages_json, state_json "
                    "FROM conversations WHERE thread_id=%s",
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
