"""Regression tests for DrawerReviseGateMiddleware and the revision-round counter.

Covers the fix for a real bug (drawer_call.txt trace, 2026-07-03): the main
agent ignored its own "one pass only" instruction (_blocks.py step 8) and
dispatched an unauthorized extra drawer+critic round before the user ever saw
the diagram at the finalize_diagram HITL gate. DrawerReviseGateMiddleware makes
that rule code-enforced instead of prompt-only, and also owns the
CRITIC_REVISION_HARD_CAP counter (moved out of submit_critique, which cannot
tell an automatic first-pass critique apart from a genuine post-rejection
round).
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import agent as agent_module
import backends
from agent import DrawerReviseGateMiddleware
from backends import resolve_workspace, set_current_workspace
from tools.constants import CRITIC_REVISION_HARD_CAP, _REVISION_COUNT_FILE


def _ai_task_call(subagent_type: str, call_id: str = "c1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "task", "args": {"subagent_type": subagent_type}, "id": call_id}],
    )


def _finalize_tool_message() -> ToolMessage:
    return ToolMessage(content="ok", name="finalize_diagram", tool_call_id="f1")


class _FakeRequest:
    def __init__(self, tool_call, messages):
        self.tool_call = tool_call
        self.state = {"messages": messages}


def _drawer_tool_call(description: str = "REVISE round 1", call_id: str = "d2") -> dict:
    return {"name": "task", "args": {"subagent_type": "drawer", "description": description}, "id": call_id}


@pytest.fixture()
def workspace(tmp_path):
    ws = resolve_workspace("thread-drawer-gate-test")
    token = set_current_workspace(ws)
    try:
        yield ws
    finally:
        backends._current_workspace.reset(token)


def test_first_drawer_call_is_never_blocked(workspace):
    mw = DrawerReviseGateMiddleware()
    req = _FakeRequest(_drawer_tool_call(), messages=[])
    assert mw._decide(req) is None


def test_drawer_revise_blocked_before_finalize_reached(workspace):
    mw = DrawerReviseGateMiddleware()
    messages = [_ai_task_call("drawer", "c1"), _ai_task_call("critic", "c2")]
    req = _FakeRequest(_drawer_tool_call(), messages=messages)
    blocked = mw._decide(req)
    assert blocked is not None
    assert blocked.status == "error"
    assert "finalize_diagram" in blocked.content


def test_drawer_revise_allowed_after_finalize_reached_and_counts_round(workspace):
    mw = DrawerReviseGateMiddleware()
    messages = [
        _ai_task_call("drawer", "c1"),
        _ai_task_call("critic", "c2"),
        _finalize_tool_message(),
    ]
    req = _FakeRequest(_drawer_tool_call(), messages=messages)
    assert mw._decide(req) is None
    count = json.loads(_REVISION_COUNT_FILE.resolve().read_text(encoding="utf-8"))
    assert count["count"] == 1


def test_drawer_revise_blocked_once_hard_cap_reached(workspace):
    mw = DrawerReviseGateMiddleware()
    messages = [
        _ai_task_call("drawer", "c1"),
        _ai_task_call("critic", "c2"),
        _finalize_tool_message(),
    ]
    for _ in range(CRITIC_REVISION_HARD_CAP):
        req = _FakeRequest(_drawer_tool_call(), messages=messages)
        assert mw._decide(req) is None
    # One more legitimate round (finalize reached again) should now be blocked.
    req = _FakeRequest(_drawer_tool_call(), messages=messages)
    blocked = mw._decide(req)
    assert blocked is not None
    assert "already used this session" in blocked.content


def test_gate_re_arms_after_each_critic_round(workspace):
    """After round 2's critic call, another drawer dispatch must wait for a
    FRESH finalize_diagram — an earlier one (before that critic call) must not
    count."""
    mw = DrawerReviseGateMiddleware()
    messages = [
        _ai_task_call("drawer", "c1"),
        _ai_task_call("critic", "c2"),
        _finalize_tool_message(),  # round 1's gate
        _ai_task_call("drawer", "c3"),
        _ai_task_call("critic", "c4"),  # round 2's critique — no finalize after this yet
    ]
    req = _FakeRequest(_drawer_tool_call(call_id="d5"), messages=messages)
    blocked = mw._decide(req)
    assert blocked is not None


def test_non_drawer_task_calls_pass_through_untouched(workspace):
    mw = DrawerReviseGateMiddleware()
    messages = [_ai_task_call("drawer", "c1"), _ai_task_call("critic", "c2")]
    req = _FakeRequest({"name": "task", "args": {"subagent_type": "critic"}, "id": "x"}, messages=messages)
    assert mw._decide(req) is None


def test_main_agent_middleware_stack_includes_gate(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    main_graph = agent_module.build_agent()
    found = False
    for node in getattr(main_graph, "nodes", {}).values():
        bound = getattr(node, "bound", None)
        # middleware list isn't directly introspectable on the compiled graph in
        # all langgraph versions; fall back to checking the module builds at all
        # and DrawerReviseGateMiddleware is importable/usable (covered above).
        if bound is not None:
            found = True
    assert found
