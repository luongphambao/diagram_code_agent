"""CRITICAL-2 fix: no subagent may write `/global-memories/*`.

Every deepagents subagent gets the FULL filesystem toolset (write_file,
edit_file) regardless of its declared ``tools`` list — a fact the repo
already documented via the icon_resolver / brd_writer FilesystemPermission
denies (agent/subagents/icon_resolver.py, agent/subagents/brd_writer.py).
`/global-memories/` is a plain writable FilesystemBackend (backends.py), and
before this fix "don't edit memory" for drawer/critic was prompt-text only
(prompts/drawer_agent.py:199, prompts/critic_agent.py:26) — unenforced.

agent/builder.py now prepends a repo-wide deny rule to every subagent's
``permissions`` in the compile loop, so this is a property that must hold for
every subagent present *and future*, not a per-spec opt-in.
"""

from __future__ import annotations

import pytest
from deepagents.middleware.filesystem import _check_fs_permission

import agent as agent_module
import agent.builder as agent_builder
from agent.builder import _GLOBAL_MEMORY_WRITE_DENY


@pytest.fixture()
def fake_llm_keys(monkeypatch):
    """build_agent() instantiates real LLM clients; dummy keys satisfy them."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("MIMO_API_KEY", "test-key")


def test_deny_rule_blocks_write_and_edit_on_global_memories():
    # write_file and edit_file both map to the "write" FilesystemOperation
    # (deepagents/middleware/filesystem.py: _DEFAULT_FS_TOOL_OPS), so a single
    # operations=["write"] rule covers both tools.
    for path in ("/global-memories/AGENTS.md", "/global-memories/nested/lesson.md"):
        assert _check_fs_permission([_GLOBAL_MEMORY_WRITE_DENY], "write", path) == "deny"
    # Reads must still work — this is a write-only deny, not a full lockout.
    assert _check_fs_permission([_GLOBAL_MEMORY_WRITE_DENY], "read", "/global-memories/AGENTS.md") == "allow"
    # Unrelated paths (e.g. the per-thread workspace) are untouched.
    assert _check_fs_permission([_GLOBAL_MEMORY_WRITE_DENY], "write", "/workspace/blueprint.json") == "allow"


def test_every_subagent_gets_the_deny_rule_but_main_keeps_write_access(monkeypatch, fake_llm_keys):
    # Same monkeypatch pattern as test_general_purpose_disabled.py: intercept
    # agent_builder.create_deep_agent (the module-local binding builder.py
    # actually calls) and record the `permissions` kwarg of every call.
    real_create = agent_builder.create_deep_agent
    calls: list[dict] = []

    def recording_create(*args, **kwargs):
        calls.append(kwargs)
        return real_create(*args, **kwargs)

    monkeypatch.setattr(agent_builder, "create_deep_agent", recording_create)
    agent_module.build_agent()

    # 7 create_deep_agent calls: icon_resolver, drawer, critic, wbs_planner,
    # ppt_generator, brd_writer, then main (see test_general_purpose_disabled.py).
    assert len(calls) == 7, [c.get("model") for c in calls]

    subagent_calls, main_call = calls[:6], calls[6]

    for kwargs in subagent_calls:
        perms = kwargs.get("permissions") or []
        assert _GLOBAL_MEMORY_WRITE_DENY in perms, (
            "every subagent must carry the global-memory write-deny rule"
        )

    # The main agent is the one deliberately allowed to curate global memory
    # (prompts/_blocks.py instructs it to edit_file("/global-memories/AGENTS.md"));
    # it must NOT receive the deny rule.
    assert "permissions" not in main_call or not main_call.get("permissions")
