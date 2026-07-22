"""Collaboration comments routes — /comments (docx §8.6).

A thin REST surface over the append-only ``comment_log.json`` store (see
:mod:`comments`). Unlike gate decisions, a comment is authored by the *user* directly
(outside the agent stream), so these endpoints read/write the per-thread workspace
without going through the agent. The thread id selects the workspace via
``resolve_workspace`` (§4.10 per-thread isolation), so each conversation has its own
comment thread.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backends import resolve_workspace
from comments import (
    append_comment,
    new_comment_record,
    next_seq,
    read_comments,
    resolve_comment,
)
from security.auth import Identity, require_identity
from security.ownership import check_owner

router = APIRouter(prefix="/comments", tags=["comments"])


class _CommentCreate(BaseModel):
    threadId: str
    body: str
    anchor_entity_id: str = ""
    author: str = ""
    role: str = ""


class _CommentResolve(BaseModel):
    threadId: str
    commentId: str
    resolved_by: str = ""


@router.get("")
async def list_comments(
    request: Request, threadId: str = "thread-default",
    identity: Identity = Depends(require_identity),
):
    await check_owner(request.app.state.pool, threadId, identity.email)
    ws = resolve_workspace(threadId)
    return {"comments": [c.model_dump() for c in read_comments(ws)]}


@router.post("")
async def create_comment(
    body: _CommentCreate, request: Request,
    identity: Identity = Depends(require_identity),
):
    if not body.body.strip():
        return {"error": "empty comment"}
    await check_owner(request.app.state.pool, body.threadId, identity.email)
    ws = resolve_workspace(body.threadId)
    rec = new_comment_record(
        body.body.strip(),
        seq=next_seq(ws),
        anchor_entity_id=body.anchor_entity_id,
        author=body.author or identity.email,
        role=body.role or identity.role,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    append_comment(rec, ws)
    return rec.model_dump()


@router.post("/resolve")
async def resolve(
    body: _CommentResolve, request: Request,
    identity: Identity = Depends(require_identity),
):
    await check_owner(request.app.state.pool, body.threadId, identity.email)
    ws = resolve_workspace(body.threadId)
    rec = resolve_comment(
        body.commentId,
        resolved_by=body.resolved_by or identity.email,
        resolved_at=datetime.now(timezone.utc).isoformat(),
        workspace=ws,
    )
    if rec is None:
        return {"error": f"comment {body.commentId} not found"}
    return rec.model_dump()
