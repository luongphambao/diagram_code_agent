"""Conversation management routes — /conversations CRUD."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import conversations as conv_db
from security.auth import Identity, require_identity
from security.ownership import check_owner

router = APIRouter(prefix="/conversations", tags=["conversations"])


class _ConvCreate(BaseModel):
    thread_id: str | None = None
    name: str = "Untitled"


class _ConvRename(BaseModel):
    name: str


@router.get("")
async def list_conversations(request: Request, identity: Identity = Depends(require_identity)):
    return await conv_db.list_all(request.app.state.pool, identity.email)


@router.post("")
async def create_conversation(
    body: _ConvCreate, request: Request, identity: Identity = Depends(require_identity)
):
    tid = body.thread_id or f"thread-{uuid.uuid4().hex[:12]}"
    return await conv_db.create(request.app.state.pool, tid, body.name, identity.email)


@router.patch("/{thread_id}")
async def rename_conversation(
    thread_id: str,
    body: _ConvRename,
    request: Request,
    identity: Identity = Depends(require_identity),
):
    await check_owner(request.app.state.pool, thread_id, identity.email)
    await conv_db.rename(request.app.state.pool, thread_id, body.name)
    return {"ok": True}


@router.delete("/{thread_id}")
async def delete_conversation(
    thread_id: str, request: Request, identity: Identity = Depends(require_identity)
):
    await check_owner(request.app.state.pool, thread_id, identity.email)
    await conv_db.delete(request.app.state.pool, thread_id)
    return {"ok": True}


@router.get("/{thread_id}/history")
async def get_conversation_history(
    thread_id: str, request: Request, identity: Identity = Depends(require_identity)
):
    await check_owner(request.app.state.pool, thread_id, identity.email)
    hist = await conv_db.get_history(request.app.state.pool, thread_id)
    if hist is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return hist


@router.get("/{thread_id}/artifact-authz")
async def check_artifact_authz(
    thread_id: str, request: Request, identity: Identity = Depends(require_identity)
):
    """Tier D3 / H-2: called by the Node runtime before serving an artifact download
    (``/api/artifacts/*`` in ``runtime/src/index.ts``), which previously read no auth
    header at all — anyone holding the ``threadId:field:hash`` key could download
    within its 30-minute TTL. Reuses the exact identity+ownership check ``/agui``
    and the rest of this router already use (``check_owner`` — read-only, does not
    claim an unowned thread, unlike ``ensure_owner``) instead of inventing HMAC
    URL-signing, which would only prove the key wasn't forged and would not
    authenticate the requester.

    200 on success (same permissive default as ``check_owner``: an unowned thread,
    or no pool in dev mode, is allowed); ``check_owner`` raises 404 on a mismatch,
    which the runtime treats as "deny"."""
    await check_owner(request.app.state.pool, thread_id, identity.email)
    return {"ok": True}
