"""Hygiene checks for the durable, cross-thread global memory file
(agent_space/memories/AGENTS.md) — the only thing chaining this file to
reality, since prompts/_blocks.py:282-289 and memory/refine.py::_SECTIONS both
assume its shape without anything enforcing that assumption.

This file is injected into EVERY agent's system prompt on EVERY turn
(agent/builder.py, docs/agent-design.md §6), so drift here is the highest-ROI
kind: a stale line doesn't just sit unused, it actively misleads every call.
"""

from __future__ import annotations

import re
from pathlib import Path

from memory.refine import _SECTIONS

_AGENTS_MD = Path(__file__).resolve().parents[1] / "agent_space" / "memories" / "AGENTS.md"

# Vocabulary of the deprecated mingrammer/Graphviz drawer path (ADR 0003 made
# the native engine the default for architecture diagrams). Any of these in
# the global memory means it's advising the drawer to do something the native
# path prompt explicitly forbids (prompts/drawer_agent.py).
_DEPRECATED_TOKENS = (
    "diagram.py",
    "taillabel",
    "ltail",
    "lhead",
    "re-render",
    "out.nodes.json",
)

# File is injected into every system prompt every turn — keep it small.
_MAX_BYTES = 6_000
_MAX_BULLETS_PER_SECTION = 20


def _read() -> str:
    return _AGENTS_MD.read_text(encoding="utf-8")


def test_memory_file_exists():
    assert _AGENTS_MD.exists(), f"expected {_AGENTS_MD} to exist"


def test_memory_has_no_deprecated_mingrammer_vocabulary():
    text = _read().lower()
    hits = [tok for tok in _DEPRECATED_TOKENS if tok.lower() in text]
    assert not hits, (
        f"global memory still references the deprecated mingrammer/Graphviz path: {hits} "
        "— the native engine is the default (ADR 0003) and its drawer prompt forbids these."
    )


def test_memory_has_every_section_prompts_and_refine_rely_on():
    text = _read()
    missing = [h for h in _SECTIONS if h not in text]
    assert not missing, (
        f"missing section header(s) {missing} — prompts/_blocks.py (write guidance) and "
        "memory/refine.py (_SECTIONS) both anchor on these exact headers"
    )


def test_memory_file_stays_small():
    size = _AGENTS_MD.stat().st_size
    assert size <= _MAX_BYTES, (
        f"{_AGENTS_MD} is {size} bytes (cap {_MAX_BYTES}) — this file is injected into "
        "every agent's system prompt every turn; keep it a few hundred words (docs/instruction.md §1.5)"
    )


def test_memory_sections_do_not_grow_unbounded():
    text = _read()
    headers = [h for h in _SECTIONS if h in text]
    positions = sorted((text.index(h), h) for h in headers)
    for i, (start, header) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        body = text[start:end]
        bullets = re.findall(r"^- ", body, re.MULTILINE)
        assert len(bullets) <= _MAX_BULLETS_PER_SECTION, (
            f"{header!r} has {len(bullets)} bullets (cap {_MAX_BULLETS_PER_SECTION}) — "
            "matches memory/refine.py's own synthesis cap (15) with headroom for hand edits"
        )
