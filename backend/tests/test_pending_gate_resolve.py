"""MEDIUM-1 fix: pending_gate.json must not go stale after a gate is resumed.

Before this fix, nothing on the resume path (routers/chat.py) ever touched
pending_gate.json — the only `unlink` of it anywhere in the backend was in
clear_stage_markers's FRESH-run branch (tools/stage_markers.py), which the
common `preserve_artifacts=True` continuation skips entirely. Two consumers
kept reading the stale file as if the gate were still open:

  - session/artifacts.py's `_stage_artifacts` served it to the UI as
    `pending_gate` unconditionally whenever the file existed.
  - agent/middleware/phase_filter.py's `_pending_gate_tools` kept the gate's
    tool artificially available past its normal phase forever.

`resolve_pending_gate` (session/gate_decisions.py) is now called from
routers/chat.py's resume branch on approve, before Command(resume) runs. It
writes status="resolved"+resolved_at (so a reader that can't delete the file
still sees it's no longer pending) then removes it outright.
"""

from __future__ import annotations

import contextvars
import json

import backends
from session.gate_decisions import resolve_pending_gate
from tools.stage_markers import clear_stage_markers


def _bind(monkeypatch, ws):
    ws.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        backends,
        "_current_workspace",
        contextvars.ContextVar("current_workspace", default=ws),
    )


def test_resolve_pending_gate_removes_the_file(tmp_path):
    (tmp_path / "pending_gate.json").write_text(
        json.dumps({"tool": "propose_blueprint", "args": {}}), encoding="utf-8"
    )

    resolve_pending_gate(tmp_path)

    assert not (tmp_path / "pending_gate.json").exists()


def test_resolve_pending_gate_is_a_noop_when_no_file_exists(tmp_path):
    # Must not raise / must not create a file out of nothing.
    resolve_pending_gate(tmp_path)
    assert not (tmp_path / "pending_gate.json").exists()


def test_resolve_pending_gate_survives_unlink_failure_via_status(tmp_path, monkeypatch):
    """If the unlink step itself fails (permission error, file lock), the
    status=resolved write must still have landed — the two consumers check
    status, not just existence, so this alone is enough to fix both."""
    import pathlib

    (tmp_path / "pending_gate.json").write_text(
        json.dumps({"tool": "propose_blueprint", "args": {}}), encoding="utf-8"
    )
    real_unlink = pathlib.Path.unlink

    def _flaky_unlink(self, *a, **k):
        if self.name == "pending_gate.json":
            raise OSError("locked")
        return real_unlink(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "unlink", _flaky_unlink)

    resolve_pending_gate(tmp_path)  # must not raise

    data = json.loads((tmp_path / "pending_gate.json").read_text(encoding="utf-8"))
    assert data["status"] == "resolved"
    assert "resolved_at" in data


def test_stage_artifacts_hides_a_resolved_gate(monkeypatch, tmp_path):
    from session.artifacts import _stage_artifacts

    (tmp_path / "pending_gate.json").write_text(
        json.dumps({"tool": "propose_blueprint", "args": {}, "status": "resolved"}), encoding="utf-8"
    )
    out = _stage_artifacts(tmp_path)
    assert "pending_gate" not in out


def test_stage_artifacts_shows_a_pending_gate(monkeypatch, tmp_path):
    from session.artifacts import _stage_artifacts

    (tmp_path / "pending_gate.json").write_text(
        json.dumps({"tool": "propose_blueprint", "args": {}}), encoding="utf-8"
    )
    out = _stage_artifacts(tmp_path)
    assert out["pending_gate"]["tool"] == "propose_blueprint"


def test_pending_gate_tools_ignores_a_resolved_gate(monkeypatch, tmp_path):
    _bind(monkeypatch, tmp_path)
    import importlib

    import agent.middleware.phase_filter as phase_filter

    importlib.reload(phase_filter)
    (tmp_path / "pending_gate.json").write_text(
        json.dumps({"tool": "propose_blueprint", "args": {}, "status": "resolved"}), encoding="utf-8"
    )

    assert phase_filter._pending_gate_tools(tmp_path) == set()


def test_pending_gate_tools_keeps_a_pending_gate(monkeypatch, tmp_path):
    _bind(monkeypatch, tmp_path)
    import agent.middleware.phase_filter as phase_filter

    (tmp_path / "pending_gate.json").write_text(
        json.dumps({"tool": "propose_blueprint", "args": {}}), encoding="utf-8"
    )

    assert phase_filter._pending_gate_tools(tmp_path) == {"propose_blueprint"}


def test_resolve_pending_gate_called_only_on_approve_not_reject():
    """Documents the intentional asymmetry: routers/chat.py only calls
    resolve_pending_gate inside the `decision.get("type") == "approve"` branch
    — a reject/revise decision is still awaiting a decision on the SAME gate,
    so clearing the file would re-lock the agent out of re-proposing it (the
    exact bug _pending_gate_tools exists to prevent). This test greps the
    source rather than driving the full /agui endpoint (which needs a live
    AGENT + Postgres pool) to pin the call site's placement."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "src" / "routers" / "chat.py").read_text(encoding="utf-8")
    idx = src.index("resolve_pending_gate(ws)")
    preceding = src[:idx]
    # The nearest enclosing `if` before the call must be the approve+gate check.
    guard_idx = preceding.rindex('if decision.get("type") == "approve" and pending_name in GATE_TOOL_NAMES:')
    assert guard_idx > 0
    # And no dedented code (a sibling `if`/`elif` at the same indent as the
    # guard, e.g. a reject branch) sits between the guard and the call — i.e.
    # the call is nested INSIDE the approve guard's body, not a sibling of it.
    between_lines = preceding[guard_idx:].splitlines()[1:]
    guard_indent = len(preceding[guard_idx:].splitlines()[0]) - len(
        preceding[guard_idx:].splitlines()[0].lstrip()
    )
    for line in between_lines:
        if not line.strip():
            continue
        line_indent = len(line) - len(line.lstrip())
        assert line_indent > guard_indent, f"found a line back at/above the guard's indent: {line!r}"


def test_clear_stage_markers_removes_workflow_state(monkeypatch, tmp_path):
    """MEDIUM-2: workflow_state.json must be in the unconditional fresh-run
    delete list, same as artifact_manifest.json — a fresh run always degrades
    back to plain file-existence phase detection, the safest failure mode."""
    _bind(monkeypatch, tmp_path)
    (tmp_path / "workflow_state.json").write_text(
        json.dumps({"gates": {"propose_blueprint": {"status": "rejected"}}}), encoding="utf-8"
    )

    clear_stage_markers()

    assert not (tmp_path / "workflow_state.json").exists()
