"""Tests for security.ownership (improvement plan §0.6).

Unit tests against the ownership-decision logic, with conversations.get_owner /
conversations.claim_owner monkeypatched to deterministic fakes — conversations.py
itself talks to a real Postgres pool and has no existing test coverage (see its
module docstring: functions silently no-op when pool is None), so exercising the
SQL here would just be an integration test with extra steps. What matters for
§0.6 is the branching: 404 on mismatch, claim-if-unowned, no-op when
unauthenticated/unpersisted.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

import conversations as conv_db
from security.ownership import check_owner, ensure_owner

_SENTINEL_POOL = object()  # anything not None; get_owner/claim_owner are faked


def _run(coro):
    return asyncio.run(coro)


class _Recorder:
    def __init__(self, owner: str | None):
        self.owner = owner
        self.claimed_with: str | None = None

    async def get_owner(self, pool, thread_id):
        return self.owner

    async def claim_owner(self, pool, thread_id, owner_email):
        self.claimed_with = owner_email


# --- check_owner --------------------------------------------------------------


def test_check_owner_noop_when_pool_is_none():
    _run(check_owner(None, "thread-1", "alice@co.com"))  # must not raise


def test_check_owner_noop_when_email_empty(monkeypatch):
    rec = _Recorder(owner="bob@co.com")
    monkeypatch.setattr(conv_db, "get_owner", rec.get_owner)
    _run(check_owner(_SENTINEL_POOL, "thread-1", ""))  # must not raise


def test_check_owner_allows_matching_owner(monkeypatch):
    rec = _Recorder(owner="alice@co.com")
    monkeypatch.setattr(conv_db, "get_owner", rec.get_owner)
    _run(check_owner(_SENTINEL_POOL, "thread-1", "alice@co.com"))  # must not raise


def test_check_owner_allows_unowned_thread(monkeypatch):
    rec = _Recorder(owner=None)
    monkeypatch.setattr(conv_db, "get_owner", rec.get_owner)
    _run(check_owner(_SENTINEL_POOL, "thread-1", "alice@co.com"))  # must not raise


def test_check_owner_rejects_different_owner_with_404(monkeypatch):
    rec = _Recorder(owner="bob@co.com")
    monkeypatch.setattr(conv_db, "get_owner", rec.get_owner)
    with pytest.raises(HTTPException) as exc_info:
        _run(check_owner(_SENTINEL_POOL, "thread-1", "alice@co.com"))
    assert exc_info.value.status_code == 404


# --- ensure_owner --------------------------------------------------------------


def test_ensure_owner_claims_unowned_thread(monkeypatch):
    rec = _Recorder(owner=None)
    monkeypatch.setattr(conv_db, "get_owner", rec.get_owner)
    monkeypatch.setattr(conv_db, "claim_owner", rec.claim_owner)
    _run(ensure_owner(_SENTINEL_POOL, "thread-1", "alice@co.com"))
    assert rec.claimed_with == "alice@co.com"


def test_ensure_owner_does_not_reclaim_owned_thread(monkeypatch):
    rec = _Recorder(owner="alice@co.com")
    monkeypatch.setattr(conv_db, "get_owner", rec.get_owner)
    monkeypatch.setattr(conv_db, "claim_owner", rec.claim_owner)
    _run(ensure_owner(_SENTINEL_POOL, "thread-1", "alice@co.com"))
    assert rec.claimed_with is None  # already owned — claim_owner not called


def test_ensure_owner_rejects_different_owner_with_404(monkeypatch):
    rec = _Recorder(owner="bob@co.com")
    monkeypatch.setattr(conv_db, "get_owner", rec.get_owner)
    monkeypatch.setattr(conv_db, "claim_owner", rec.claim_owner)
    with pytest.raises(HTTPException) as exc_info:
        _run(ensure_owner(_SENTINEL_POOL, "thread-1", "alice@co.com"))
    assert exc_info.value.status_code == 404
    assert rec.claimed_with is None


def test_ensure_owner_noop_when_pool_is_none():
    _run(ensure_owner(None, "thread-1", "alice@co.com"))  # must not raise
