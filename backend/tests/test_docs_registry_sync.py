"""MEDIUM-4 fix: docs/agent-design.md and docs/architecture.md must not drift
from the actual tool/gate/subagent registry.

Before this fix, docs said 41 MAIN_TOOLS / 13 gates / 5 subagents while the
code had 47 / 16 / 6 — caught by manual audit
(docs/codex/multi-agent-architecture-review-2026-07-30.md MEDIUM-4), not by
any test. These regex-extract the specific numbers the docs state and compare
them against the live registries, so the NEXT tool/gate/subagent added
without a doc update fails CI instead of silently rotting for months.

Deliberately narrow (specific known sentences, not a fuzzy doc-wide scan):
broadening this to catch every possible drift would be a fragile,
high-maintenance parser for prose that changes for unrelated reasons. This
catches the exact numbers a past audit found wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent.subagents import build_subagent_specs
from tools import GATE_TOOL_NAMES, MAIN_TOOLS

_DOCS = Path(__file__).resolve().parents[2] / "docs"


def _read(name: str) -> str:
    path = _DOCS / name
    assert path.exists(), f"expected doc file at {path}"
    return path.read_text(encoding="utf-8")


def _live_subagent_count() -> int:
    specs = build_subagent_specs(
        workdir="/workspace",
        icons_root="/icons",
        manifest="manifest.json",
        style="pretty",
        drawer_vision_relay=False,
    )
    return len(specs)


def test_agent_design_doc_tool_count_matches_registry():
    text = _read("agent-design.md")
    m = re.search(r"`MAIN_TOOLS`\s+(\d+)\s+mục", text)
    assert m, "docs/agent-design.md: couldn't find the '`MAIN_TOOLS` N mục' sentence to check"
    assert int(m.group(1)) == len(MAIN_TOOLS), (
        f"docs/agent-design.md claims MAIN_TOOLS has {m.group(1)} entries, "
        f"actual is {len(MAIN_TOOLS)} — update the doc (or this test, if the doc's wording moved)"
    )


def test_agent_design_doc_gate_count_matches_registry():
    text = _read("agent-design.md")
    m = re.search(r"(\d+)\s+gate liệt kê ở `GATE_TOOL_NAMES`", text)
    assert m, "docs/agent-design.md: couldn't find the 'N gate liệt kê ở `GATE_TOOL_NAMES`' sentence"
    assert int(m.group(1)) == len(GATE_TOOL_NAMES), (
        f"docs/agent-design.md claims {m.group(1)} gates, actual GATE_TOOL_NAMES "
        f"has {len(GATE_TOOL_NAMES)} — update the doc"
    )


def test_agent_design_doc_subagent_count_matches_registry():
    text = _read("agent-design.md")
    m = re.search(r"(\d+)\s+subagent đã compile", text)
    assert m, "docs/agent-design.md: couldn't find the 'N subagent đã compile' sentence"
    assert int(m.group(1)) == _live_subagent_count(), (
        f"docs/agent-design.md claims {m.group(1)} subagents, actual is {_live_subagent_count()}"
    )


def test_architecture_doc_subagent_count_matches_registry():
    text = _read("architecture.md")
    m = re.search(r"(\d+)\s+`SubagentSpec`", text)
    assert m, "docs/architecture.md: couldn't find the 'N `SubagentSpec`' sentence"
    assert int(m.group(1)) == _live_subagent_count(), (
        f"docs/architecture.md claims {m.group(1)} SubagentSpecs, actual is {_live_subagent_count()}"
    )


def test_domain_glossary_gate_count_matches_registry():
    text = _read("domain-glossary.md")
    m = re.search(r"run dừng lại, frontend hiện thẻ duyệt\.\s*(\d+)\s+gate", text)
    assert m, "docs/domain-glossary.md: couldn't find the gate-count sentence"
    assert int(m.group(1)) == len(GATE_TOOL_NAMES)
