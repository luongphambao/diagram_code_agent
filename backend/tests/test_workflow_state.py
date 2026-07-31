"""session/workflow_state.py + its consumption in agent/middleware/phase_filter.py
(MEDIUM-2 fix: explicit gate-decision state on top of file-existence phase
detection). See docs/codex/multi-agent-architecture-review-2026-07-30.md.

Two groups of tests:
  - backward-compat: every fixture in test_phase_filter_pending_gate.py /
    test_phase_prompt_filter.py / test_brd_registration.py must still resolve
    to the SAME phase with no workflow_state.json present, and a corrupt state
    file must never narrow the allowed toolset (fail-open).
  - the new behavior: partial/corrupt artifacts don't advance phase, and a
    rejected propose_tech_stack/propose_blueprint holds the phase back while
    restoring the upstream revise toolset.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from session.workflow_state import artifact_ready, read_state, record_gate_decision


def _load_phase_filter_module():
    path = Path(__file__).resolve().parents[1] / "src" / "agent" / "middleware" / "phase_filter.py"
    spec = importlib.util.spec_from_file_location("phase_filter_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class _Tool:
    def __init__(self, name: str):
        self.name = name


def _patch_backends(monkeypatch, tmp_path):
    monkeypatch.setitem(
        sys.modules,
        "backends",
        SimpleNamespace(current_workspace=lambda: tmp_path),
    )


# ---------------------------------------------------------------------------
# Backward compatibility: no state file, or a corrupt one, never changes
# behavior relative to plain file-existence detection.
# ---------------------------------------------------------------------------


def test_no_state_file_matches_legacy_detection(tmp_path):
    phase_filter = _load_phase_filter_module()
    assert phase_filter._detect_phase(tmp_path) == "intake"

    (tmp_path / "tech_stack.json").write_text("[]", encoding="utf-8")
    assert phase_filter._detect_phase(tmp_path) == "blueprint"

    (tmp_path / "blueprint.json").write_text('{"nodes": []}', encoding="utf-8")
    assert phase_filter._detect_phase(tmp_path) == "draw"

    (tmp_path / "wbs.json").write_text("{}", encoding="utf-8")
    assert phase_filter._detect_phase(tmp_path) == "wbs"

    (tmp_path / "deck_plan.json").write_text("{}", encoding="utf-8")
    assert phase_filter._detect_phase(tmp_path) == "ppt"

    (tmp_path / "out.pdf").write_bytes(b"report")
    assert phase_filter._detect_phase(tmp_path) == "report"

    (tmp_path / "out.brd.docx").write_bytes(b"x")
    assert phase_filter._detect_phase(tmp_path) == "brd"


def test_corrupt_state_file_fails_open(monkeypatch, tmp_path):
    phase_filter = _load_phase_filter_module()
    (tmp_path / "tech_stack.json").write_text("[]", encoding="utf-8")
    (tmp_path / "blueprint.json").write_text('{"nodes": []}', encoding="utf-8")
    (tmp_path / "workflow_state.json").write_text("not json{", encoding="utf-8")
    _patch_backends(monkeypatch, tmp_path)

    assert phase_filter._detect_phase(tmp_path) == "draw"

    tools = [_Tool("finalize_diagram"), _Tool("propose_blueprint"), _Tool("propose_tech_stack")]
    names = {t.name for t in phase_filter.PhaseToolFilterMiddleware()._filtered_tools(tools)}
    assert names  # a broken state file must never lock the agent out of every tool
    assert "finalize_diagram" in names


def test_unknown_status_and_unknown_gate_key_are_ignored(tmp_path):
    phase_filter = _load_phase_filter_module()
    (tmp_path / "tech_stack.json").write_text("[]", encoding="utf-8")
    (tmp_path / "blueprint.json").write_text('{"nodes": []}', encoding="utf-8")
    (tmp_path / "workflow_state.json").write_text(
        json.dumps(
            {"gates": {"propose_blueprint": {"status": "banana"}, "nonsense_gate": {"status": "rejected"}}}
        ),
        encoding="utf-8",
    )
    assert phase_filter._detect_phase(tmp_path) == "draw"


def test_trivial_but_valid_content_is_ready(tmp_path):
    """Regression fence: the exact fixture bytes test_phase_filter_pending_gate.py
    and test_brd_registration.py already write must all count as ready."""
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "b.json").write_text("[]", encoding="utf-8")
    (tmp_path / "c.json").write_text('{"nodes": []}', encoding="utf-8")
    (tmp_path / "d.png").write_bytes(b"stale-render")
    (tmp_path / "e.pdf").write_bytes(b"report")
    (tmp_path / "f.docx").write_bytes(b"x")

    for name in ("a.json", "b.json", "c.json", "d.png", "e.pdf", "f.docx"):
        assert artifact_ready(tmp_path, name) is True, name


def test_workflow_state_does_not_import_backends():
    """Canary: workflow_state.py must take `workspace` as a parameter, never
    import `backends`, because test_phase_filter_pending_gate.py's importlib
    loader monkeypatches sys.modules["backends"] with a fake that only has
    current_workspace() -- a real import elsewhere would bypass that fake."""
    src = Path(__file__).resolve().parents[1] / "src" / "session" / "workflow_state.py"
    text = src.read_text(encoding="utf-8")
    assert "import backends" not in text
    assert "from backends" not in text


# ---------------------------------------------------------------------------
# Partial/corrupt artifact guard
# ---------------------------------------------------------------------------


def test_zero_byte_artifact_does_not_advance_phase(tmp_path):
    phase_filter = _load_phase_filter_module()
    (tmp_path / "out.pdf").write_bytes(b"")
    (tmp_path / "wbs.json").write_text("{}", encoding="utf-8")
    assert phase_filter._detect_phase(tmp_path) == "wbs"


def test_truncated_json_artifact_does_not_advance_phase(tmp_path):
    phase_filter = _load_phase_filter_module()
    (tmp_path / "blueprint.json").write_text('{"nodes": [', encoding="utf-8")
    (tmp_path / "tech_stack.json").write_text("[]", encoding="utf-8")
    assert phase_filter._detect_phase(tmp_path) == "blueprint"


def test_invalid_artifact_keeps_its_producer_tool(monkeypatch, tmp_path):
    phase_filter = _load_phase_filter_module()
    (tmp_path / "tech_stack.json").write_text("", encoding="utf-8")  # zero-byte = not ready
    _patch_backends(monkeypatch, tmp_path)

    assert "propose_tech_stack" in phase_filter._missing_artifact_tools(tmp_path)


# ---------------------------------------------------------------------------
# Rejected / retry / waived
# ---------------------------------------------------------------------------


def test_rejected_blueprint_gate_holds_phase_back(tmp_path):
    phase_filter = _load_phase_filter_module()
    (tmp_path / "tech_stack.json").write_text("[]", encoding="utf-8")
    (tmp_path / "blueprint.json").write_text('{"nodes": []}', encoding="utf-8")

    record_gate_decision(tmp_path, "propose_blueprint", "reject", note="use Kafka not SQS")
    assert phase_filter._detect_phase(tmp_path) == "blueprint"

    record_gate_decision(tmp_path, "propose_blueprint", "approve")
    assert phase_filter._detect_phase(tmp_path) == "draw"


def test_rejected_gate_restores_upstream_revise_tools(monkeypatch, tmp_path):
    phase_filter = _load_phase_filter_module()
    (tmp_path / "tech_stack.json").write_text("[]", encoding="utf-8")
    (tmp_path / "blueprint.json").write_text('{"nodes": []}', encoding="utf-8")
    record_gate_decision(tmp_path, "propose_blueprint", "reject")
    _patch_backends(monkeypatch, tmp_path)

    tools = [_Tool("propose_tech_stack"), _Tool("web_research"), _Tool("generate_pdf_report")]
    names = {t.name for t in phase_filter.PhaseToolFilterMiddleware()._filtered_tools(tools)}
    assert "propose_tech_stack" in names
    assert "web_research" in names
    assert "generate_pdf_report" not in names


def test_rejected_phase_does_not_skip_a_higher_ready_phase(tmp_path):
    """Veto is one rung, not a cliff: if a higher phase's evidence is
    independently ready, that higher phase still wins even though "draw" is
    blocked (state can only ever hold detection back, never force it forward
    past what a rejection actually blocks)."""
    phase_filter = _load_phase_filter_module()
    (tmp_path / "tech_stack.json").write_text("[]", encoding="utf-8")
    (tmp_path / "blueprint.json").write_text('{"nodes": []}', encoding="utf-8")
    (tmp_path / "deck_plan.json").write_text("{}", encoding="utf-8")
    record_gate_decision(tmp_path, "propose_blueprint", "reject")

    assert phase_filter._detect_phase(tmp_path) == "ppt"


def test_non_blocking_gate_reject_is_recorded_but_inert(tmp_path):
    phase_filter = _load_phase_filter_module()
    (tmp_path / "out.png").write_bytes(b"rendered-diagram")
    record_gate_decision(tmp_path, "finalize_diagram", "reject")

    assert phase_filter._detect_phase(tmp_path) == "draw"
    assert read_state(tmp_path)["gates"]["finalize_diagram"]["status"] == "rejected"


def test_attempts_and_history_accumulate(tmp_path):
    record_gate_decision(tmp_path, "propose_blueprint", "reject")
    record_gate_decision(tmp_path, "propose_blueprint", "reject")
    record_gate_decision(tmp_path, "propose_blueprint", "approve")

    state = read_state(tmp_path)
    assert state["gates"]["propose_blueprint"]["status"] == "approved"
    assert state["gates"]["propose_blueprint"]["attempts"] == 3
    assert len(state["history"]) == 3


def test_history_is_capped(tmp_path):
    for _ in range(30):
        record_gate_decision(tmp_path, "propose_blueprint", "reject")

    assert len(read_state(tmp_path)["history"]) == 20


def test_waived_artifact_drops_its_backfill_tool(monkeypatch, tmp_path):
    from session.workflow_state import record_waiver

    phase_filter = _load_phase_filter_module()
    _patch_backends(monkeypatch, tmp_path)

    assert "propose_diagram_brief" in phase_filter._missing_artifact_tools(tmp_path)
    record_waiver(tmp_path, "diagram_brief.json", note="no brief for this POC")
    assert "propose_diagram_brief" not in phase_filter._missing_artifact_tools(tmp_path)


# ---------------------------------------------------------------------------
# Durability
# ---------------------------------------------------------------------------


def test_write_is_atomic_and_leaves_no_tmp(tmp_path):
    record_gate_decision(tmp_path, "propose_blueprint", "approve")

    assert list(tmp_path.glob("*.tmp")) == []
    state = json.loads((tmp_path / "workflow_state.json").read_text(encoding="utf-8"))
    assert state["gates"]["propose_blueprint"]["status"] == "approved"
