"""CRITICAL-1 fix: a disallowed role must actually block gate approval.

Before this fix, `can_approve()`'s result was checked inside
`_persist_decision_record` — called from the streaming resume path, AFTER
`RUN_STARTED` had already been yielded — and a disallowed role only produced
a `logger.warning(...)`; nothing stopped `Command(resume=...)` from running
the gated tool (see docs/codex/multi-agent-architecture-review-2026-07-30.md
CRITICAL-1). The check now runs in `agui_endpoint` itself, BEFORE the
streaming response is constructed, so a disallowed role raises a real HTTP
403 and `AGENT.astream` (the resume) never runs at all.

These tests call `agui_endpoint` directly (bypassing the FastAPI dependency
injection for `Depends(require_identity)` — calling the underlying coroutine
directly is exactly how a decorated function behaves when invoked in-process)
with a fake `Request` and a fake `AGENT` that reports a pending
`propose_blueprint` interrupt, so no real Postgres pool or LangGraph
checkpointer is needed: `ensure_owner` no-ops when `pool is None`
(security/ownership.py), and `_pending_interrupt` only needs
`AGENT.aget_state(config)` to return an object with `.tasks`/`.interrupts`.
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

import session_state as ss
from security.auth import Identity


class _FakeApp:
    class _State:
        pool = None

    state = _State()


class _FakeRequest:
    """Enough of starlette.Request's surface for agui_endpoint's body."""

    def __init__(self, body: dict):
        self._body = body
        self.app = _FakeApp()

    async def json(self):
        return self._body


class _FakeState:
    def __init__(self, pending_name: str):
        self.tasks: list = []
        self.interrupts = [{"action_requests": [{"name": pending_name, "args": {}}]}]


class _FakeAgent:
    """Tracks whether astream (the actual resume) was ever invoked."""

    def __init__(self, pending_name: str):
        self._pending_name = pending_name
        self.astream_called = False

    async def aget_state(self, config):
        return _FakeState(self._pending_name)

    def astream(self, *a, **k):
        self.astream_called = True

        async def _gen():
            if False:
                yield None

        return _gen()


def _resume_body(thread_id: str = "thread-rbac-test", approved: bool = True) -> dict:
    return {
        "threadId": thread_id,
        "runId": "run-1",
        "messages": [
            {"role": "user", "content": "make a diagram"},
            {"role": "tool", "content": json.dumps({"approved": approved})},
        ],
    }


@pytest.fixture()
def fake_agent(monkeypatch):
    def _install(pending_name: str) -> _FakeAgent:
        agent = _FakeAgent(pending_name)
        monkeypatch.setattr(ss, "AGENT", agent)
        return agent

    return _install


async def _call_endpoint(body: dict, identity: Identity):
    from routers.chat import agui_endpoint

    return await agui_endpoint(request=_FakeRequest(body), identity=identity)


@pytest.mark.anyio
async def test_disallowed_role_is_denied_with_403_and_never_resumes(fake_agent):
    agent = fake_agent("propose_blueprint")  # restricted to architect/lead/admin

    with pytest.raises(HTTPException) as exc_info:
        await _call_endpoint(_resume_body(), Identity(email="pm@bnk.vn", role="pm"))

    assert exc_info.value.status_code == 403
    assert "propose_blueprint" in exc_info.value.detail
    assert agent.astream_called is False


@pytest.mark.anyio
async def test_empty_role_is_denied_on_a_restricted_gate(fake_agent):
    """The empty-role permissive default was removed for restricted gates —
    an unauthenticated-for-roles caller (e.g. a bare API/curl request that
    skips the frontend's role selector) must not slip through."""
    agent = fake_agent("propose_blueprint")

    with pytest.raises(HTTPException) as exc_info:
        await _call_endpoint(_resume_body(), Identity(email="x@bnk.vn", role=""))

    assert exc_info.value.status_code == 403
    assert agent.astream_called is False


@pytest.mark.anyio
async def test_allowed_role_proceeds_without_403(fake_agent):
    agent = fake_agent("propose_blueprint")

    result = await _call_endpoint(_resume_body(), Identity(email="arch@bnk.vn", role="architect"))

    from fastapi.responses import StreamingResponse

    assert isinstance(result, StreamingResponse)


@pytest.mark.anyio
async def test_unrestricted_gate_allows_any_role(fake_agent):
    """propose_deck_plan has no entry in ROLE_GATE_PERMISSIONS — open to
    anyone, including an empty role. Confirms the fix didn't over-broaden."""
    agent = fake_agent("propose_deck_plan")

    result = await _call_endpoint(_resume_body(), Identity(email="x@bnk.vn", role=""))

    from fastapi.responses import StreamingResponse

    assert isinstance(result, StreamingResponse)


@pytest.mark.anyio
async def test_reject_decision_is_never_blocked_by_role(fake_agent):
    """A reject/revise decision doesn't execute the gated tool at all, so the
    RBAC check must not fire on it regardless of role."""
    agent = fake_agent("propose_blueprint")

    result = await _call_endpoint(_resume_body(approved=False), Identity(email="pm@bnk.vn", role="pm"))

    from fastapi.responses import StreamingResponse

    assert isinstance(result, StreamingResponse)
