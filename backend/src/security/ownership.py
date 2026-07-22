"""Thread-ownership checks (improvement plan §0.6).

``threadId`` used to be the entire isolation boundary (see
``runtime/backends.py``'s per-thread workspace) with no binding to *who* may use a
given thread id — any caller supplying a known/guessed ``threadId`` could read,
resume, comment on, or approve HITL gates for it. This module adds a thin
ownership layer on top of the existing ``conversations`` table (see
``conversations.py``'s ``owner_email`` column).

A row with no owner recorded (``owner_email == ""`` — either a legacy row from
before this migration, or the in-memory dev mode where ``pool`` is ``None`` and
nothing is persisted at all) is treated as unowned: the first authenticated
caller to touch it claims it, rather than every pre-existing thread suddenly
locking its original users out.
"""

from __future__ import annotations

from fastapi import HTTPException

import conversations as conv_db


async def check_owner(pool, thread_id: str, email: str) -> None:
    """Raise 404 if *thread_id* exists and is owned by someone other than *email*.

    404 (not 403) so a non-owner probing thread ids cannot distinguish "not
    yours" from "doesn't exist". A no-op when *pool* is None (in-memory dev mode,
    where ownership cannot be persisted) or *email* is empty.
    """
    if pool is None or not email:
        return
    owner = await conv_db.get_owner(pool, thread_id)
    if owner and owner != email:
        raise HTTPException(status_code=404, detail="Conversation not found")


async def ensure_owner(pool, thread_id: str, email: str) -> None:
    """Like :func:`check_owner`, but also claims *thread_id* for *email* if it is
    currently unowned (used on ``/agui``, which is the usual first-touch path for
    a brand-new thread id, before any explicit ``POST /conversations`` call)."""
    if pool is None or not email:
        return
    owner = await conv_db.get_owner(pool, thread_id)
    if owner and owner != email:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not owner:
        await conv_db.claim_owner(pool, thread_id, email)
