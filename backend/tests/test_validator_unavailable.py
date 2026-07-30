"""MEDIUM-5 fix: a validator crash must read as `unavailable`, never as a pass.

Before this fix, four spots in rendering_tools.py wrapped their validator/
scorecard calls in a bare ``except Exception: pass``:

  - semantic_stats() (~line 1058): a crash left ``stats["semantic"]`` absent,
    and production_scorecard's ``sem.get("node_recall", 1.0)`` default then
    read the ABSENT key as 100% recall — a crashed check scored as a perfect
    pass.
  - the out.native_stats.json write (~line 1076): a crash silently starved
    every downstream reader (finalize_diagram, _diagram_gate_note,
    inspect_render_quality) of stats with zero trace of why.
  - the lint/production_scorecard block in export_drawio_native (~line 1140):
    a crash left `lint=""`, indistinguishable from "validated, zero findings".
  - the scorecard block in finalize_diagram (~line 2519): a crash left
    quality_note={} and the human approver saw no scorecard at all, silently.

These tests pin the new contract: `pass | fail | unavailable`, and
`unavailable` must never render or score as `pass`.
"""

from __future__ import annotations

import contextvars
import json

import pytest

import backends
from domain.validation.validate_drawio import production_scorecard
from prettygraph.native.topology import build_drawio_from_spec
from test_native_engine import _GCP_SPEC


def _bind(monkeypatch, ws):
    ws.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        backends,
        "_current_workspace",
        contextvars.ContextVar("current_workspace", default=ws),
    )


@pytest.fixture
def ws(tmp_path, monkeypatch):
    w = tmp_path / "ws"
    _bind(monkeypatch, w)
    # Keep tests hermetic: no draw.io CLI dependency.
    monkeypatch.setattr("tools.rendering_tools._render_drawio_png", lambda *a, **k: False)
    monkeypatch.setenv("RENDER_INCLUDES_IMAGE", "0")
    return w


def test_production_scorecard_fails_closed_on_unavailable_semantic():
    """The scoring function itself must not default a crashed check to 100%."""
    unavailable_sem = {"status": "unavailable", "node_recall": 0.0, "edge_recall": 0.0}
    sc = production_scorecard({"errors": [], "error_count": 0, "ok": True}, {"semantic": unavailable_sem})
    assert sc["node_recall"] == 0.0
    assert sc["edge_recall"] == 0.0
    assert sc["pass"] is False
    assert sc["breakdown"]["semantic_completeness"] == 0.0


def test_semantic_stats_crash_fails_closed_not_100pct(ws, monkeypatch):
    def _raise(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr("prettygraph.native.repair.semantic_stats", _raise)
    from tools.rendering_tools import _render_native_from_spec

    stats = _render_native_from_spec(dict(_GCP_SPEC, presentation_style="diagram"), ws)
    assert stats["semantic"] == {"status": "unavailable", "node_recall": 0.0, "edge_recall": 0.0}


def test_native_stats_write_failure_is_logged_not_swallowed(ws, monkeypatch, caplog):
    import pathlib

    real_write_text = pathlib.Path.write_text

    def _flaky_write_text(self, *a, **k):
        if self.name == "out.native_stats.json":
            raise OSError("disk full")
        return real_write_text(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "write_text", _flaky_write_text)
    from tools.rendering_tools import _render_native_from_spec

    with caplog.at_level("ERROR", logger="diagram-agent"):
        _render_native_from_spec(dict(_GCP_SPEC, presentation_style="diagram"), ws)
    assert any("out.native_stats.json" in rec.message for rec in caplog.records)


def test_export_drawio_native_reports_unavailable_on_scorecard_crash(ws, monkeypatch):
    from tools.rendering_tools import export_drawio_native

    (ws / "render_spec.json").write_text(json.dumps(_GCP_SPEC), encoding="utf-8")
    monkeypatch.setattr(
        "domain.validation.validate_drawio.validate_file",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("validator exploded")),
    )
    msg = export_drawio_native.func()
    assert "VALIDATION UNAVAILABLE" in msg
    assert "Production scorecard" not in msg  # no fabricated score alongside it


def test_finalize_diagram_reports_unavailable_on_scorecard_crash(ws, monkeypatch):
    from tools.rendering_tools import _render_native_from_spec, finalize_diagram

    _render_native_from_spec(dict(_GCP_SPEC, presentation_style="diagram"), ws)
    assert (ws / "out.png").exists() is False  # PNG rendering is patched off in `ws`
    # finalize_diagram only hard-requires out.png; write a stub so we reach the
    # scorecard block under test (out.drawio is already real from the render above).
    (ws / "out.png").write_bytes(b"\x89PNG\r\n")

    monkeypatch.setattr(
        "domain.validation.validate_drawio.production_scorecard",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("scorecard exploded")),
    )
    msg = finalize_diagram.func(kind="architecture")
    assert "UNAVAILABLE" in msg
    assert "PASS" not in msg
