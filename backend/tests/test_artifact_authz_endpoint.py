"""Tier D3 / H-2 fix: artifact downloads must be authorized, not just TTL-limited.

Before this fix, ``runtime/src/index.ts``'s ``/api/artifacts/*`` route read no
auth header at all -- anyone holding the ``threadId:field:hash`` key could
download within its 30-minute TTL. HMAC-signing the URL would only prove the
key wasn't forged, not authenticate the requester. This reuses the identity +
ownership stack ``/agui`` already uses: ``GET /conversations/{thread_id}/artifact-authz``
calls the same read-only ``check_owner`` (not ``ensure_owner``, which would
wrongly CLAIM an unowned thread on a passive download check) that
``routers/conversations.py``'s other endpoints already use.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import conversations as conv_db
from security.auth import Identity

_SENTINEL_POOL = object()


class _FakeApp:
    class _State:
        pool = _SENTINEL_POOL

    state = _State()


class _FakeRequest:
    def __init__(self):
        self.app = _FakeApp()


class _Recorder:
    def __init__(self, owner):
        self.owner = owner

    async def get_owner(self, pool, thread_id):
        return self.owner


async def _call(thread_id: str, identity: Identity):
    from routers.conversations import check_artifact_authz

    return await check_artifact_authz(thread_id, _FakeRequest(), identity)


@pytest.mark.anyio
async def test_owner_is_authorized(monkeypatch):
    monkeypatch.setattr(conv_db, "get_owner", _Recorder(owner="alice@bnk.vn").get_owner)
    result = await _call("thread-1", Identity(email="alice@bnk.vn", role="architect"))
    assert result == {"ok": True}


@pytest.mark.anyio
async def test_unowned_thread_is_authorized(monkeypatch):
    """Matches check_owner's existing permissive default for a legacy/unclaimed
    thread -- no regression versus today's fully-open behavior."""
    monkeypatch.setattr(conv_db, "get_owner", _Recorder(owner=None).get_owner)
    result = await _call("thread-1", Identity(email="alice@bnk.vn", role="architect"))
    assert result == {"ok": True}


@pytest.mark.anyio
async def test_different_identity_is_denied(monkeypatch):
    """The exact test the Codex review and the Explore agent both called out as
    missing: thread owned by A, request as B -> denied."""
    monkeypatch.setattr(conv_db, "get_owner", _Recorder(owner="alice@bnk.vn").get_owner)
    with pytest.raises(HTTPException) as exc_info:
        await _call("thread-1", Identity(email="mallory@evil.com", role="architect"))
    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_dev_mode_no_pool_is_authorized(monkeypatch):
    """AUTH_MODE=none / no Postgres pool degrades exactly like check_owner's
    existing no-op — no regression for local dev."""

    class _NoPoolApp:
        class _State:
            pool = None

        state = _State()

    class _NoPoolRequest:
        def __init__(self):
            self.app = _NoPoolApp()

    from routers.conversations import check_artifact_authz

    result = await check_artifact_authz(
        "thread-1", _NoPoolRequest(), Identity(email="", role="")
    )
    assert result == {"ok": True}
