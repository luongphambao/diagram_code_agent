"""memory.refine — the offline learning-loop consolidator that turns reject-gate
notes (already written by code, see conversations.record_gate_outcome) into
agent_space/memories/AGENTS.md updates.

Focus: the section-boundary bug this module fixes vs. the old
scripts/refine_memory.py (synthesizing into the last _SECTIONS-listed header
silently deleted every hand-added section after it), plus the routing/
timestamp helpers, all without touching a real DB or LLM.
"""

from __future__ import annotations

import sys

from memory import refine


_FOUR_SECTION_FILE = """\
# Diagram Agent Memory

## Do Not Do
- [drawer] old rule

## Style Preferences
- old preference

## Learned Icon & Tech Notes
- old icon note

## Learned WBS Norms
- WBS estimation: size ONLY dev per leaf.
- Use the BnK 3-phase spine.
"""


def test_replace_section_preserves_a_hand_added_section_after_it():
    """Regression test for the exact bug in the old scripts/refine_memory.py:
    _SECTIONS only listed 3 headers, so synthesizing into the LAST-listed one
    ("## Learned Icon & Tech Notes") found no boundary before end-of-file and
    deleted "## Learned WBS Norms" (a real, hand-added 4th section) entirely."""
    updated = refine._replace_section(_FOUR_SECTION_FILE, "## Learned Icon & Tech Notes", "- new icon note")
    assert "- new icon note" in updated
    assert "- old icon note" not in updated
    # The section that used to get silently deleted must survive intact.
    assert "## Learned WBS Norms" in updated
    assert "- WBS estimation: size ONLY dev per leaf." in updated
    assert "- Use the BnK 3-phase spine." in updated


def test_replace_section_preserves_sections_before_and_after():
    updated = refine._replace_section(_FOUR_SECTION_FILE, "## Style Preferences", "- new preference")
    assert "- new preference" in updated
    assert "- old preference" not in updated
    assert "- [drawer] old rule" in updated  # section BEFORE, untouched
    assert "- old icon note" in updated  # section AFTER, untouched
    assert "## Learned WBS Norms" in updated


def test_replace_section_appends_a_missing_header():
    text = "# Diagram Agent Memory\n\n## Do Not Do\n- x\n"
    updated = refine._replace_section(text, "## New Section", "- y")
    assert updated.rstrip().endswith("## New Section\n- y")


def test_set_timestamp_inserts_then_updates_in_place():
    text = "# Diagram Agent Memory\n\n## Do Not Do\n- x\n"
    once = refine._set_timestamp(text)
    m1 = refine._TIMESTAMP_PATTERN.search(once)
    assert m1 is not None
    twice = refine._set_timestamp(once)
    m2 = refine._TIMESTAMP_PATTERN.search(twice)
    assert m2 is not None
    # Still exactly one watermark, not a second one appended.
    assert len(refine._TIMESTAMP_PATTERN.findall(twice)) == 1


def test_last_analyzed_absent_means_process_full_history():
    assert refine._last_analyzed("# no watermark here") is None


def test_last_analyzed_parses_a_real_watermark():
    text = "<!-- last_analyzed: 2026-01-01T00:00:00+00:00 -->\n# Memory\n"
    ts = refine._last_analyzed(text)
    assert ts is not None
    assert ts.year == 2026 and ts.month == 1 and ts.day == 1


def test_route_buckets_by_gate_and_note_keywords():
    outcomes = [
        {"gate": "finalize_diagram", "note": "too many colors, please use one accent"},
        {"gate": "propose_blueprint", "note": "wrong icon path for Lambda"},
        {"gate": "propose_wbs", "note": "off-topic, not a diagram/tech-stack gate"},
    ]
    buckets = refine._route(outcomes)
    assert outcomes[0] in buckets["## Do Not Do"]
    assert outcomes[0] in buckets["## Style Preferences"]  # "colors" keyword
    assert outcomes[1] in buckets["## Do Not Do"]
    assert outcomes[1] in buckets["## Learned Icon & Tech Notes"]  # "icon"/"path" keyword
    assert outcomes[2] not in buckets["## Do Not Do"]  # not one of the 3 routed gates


def test_fetch_outcomes_filters_by_decision_note_and_since(monkeypatch):
    """Exercise the SQL-adjacent filtering logic without a real Postgres
    connection: stub psycopg.connect to hand back canned rows."""
    import json as _json

    rows = [
        (
            "t1",
            _json.dumps(
                [
                    {
                        "decision": "reject",
                        "note": "bad layout",
                        "gate": "finalize_diagram",
                        "timestamp": "2026-06-01T00:00:00+00:00",
                    },
                    {
                        "decision": "approve",
                        "note": "",
                        "gate": "finalize_diagram",
                        "timestamp": "2026-06-01T00:00:00+00:00",
                    },
                    {
                        "decision": "reject",
                        "note": "",
                        "gate": "finalize_diagram",
                        "timestamp": "2026-06-01T00:00:00+00:00",
                    },  # no note -> no signal
                    {
                        "decision": "reject",
                        "note": "too old",
                        "gate": "finalize_diagram",
                        "timestamp": "2026-01-01T00:00:00+00:00",
                    },  # before `since`
                ]
            ),
        ),
    ]

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a, **k):
            pass

        def fetchall(self):
            return rows

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return _FakeCursor()

    class _FakePsycopg:
        @staticmethod
        def connect(*a, **k):
            return _FakeConn()

    monkeypatch.setitem(sys.modules, "psycopg", _FakePsycopg)
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/fake")

    from datetime import datetime, timezone

    since = datetime(2026, 3, 1, tzinfo=timezone.utc)
    outcomes = refine._fetch_outcomes(since)
    assert len(outcomes) == 1
    assert outcomes[0]["note"] == "bad layout"
