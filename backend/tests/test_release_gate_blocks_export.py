"""HIGH-4 fix: the release gate must block BEFORE writing out.pdf/out.pptx,
not just append a "do NOT send this to the client" sentence after the file
is already on disk.

Before this fix, `_solution_gate_note("pdf_export", block=True)` /
`("ppt_export", block=True)` were called AFTER `generate_report(...)` /
`generate_ppt_proposal_file(...)` already wrote the deliverable
(reporting_gates.py), and a validator crash was swallowed into an empty
string (gates.py's old bare `except Exception: return ""`) — i.e. fail-OPEN
on the one code path meant to protect the client. `run_solution_gate` now
returns `(blocked, note)` and reporting_gates.py checks `blocked` BEFORE
calling the writer.
"""

from __future__ import annotations

import contextvars
import json

import backends
import domain.reporting.reporting as reporting
import tools
from tools.analysis.gates import run_solution_gate


def _use_workspace(monkeypatch, tmp_path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        backends,
        "_current_workspace",
        contextvars.ContextVar("current_workspace", default=tmp_path),
    )


def _write_broken_solution(tmp_path) -> None:
    """A blueprint with an edge to an undeclared node — a genuine "high"
    severity / BLOCK-level defect (dangling reference), not a fabricated one."""
    (tmp_path / "architecture_analysis.json").write_text(
        json.dumps({"application_type": "web_application", "scale_level": "large"}), encoding="utf-8"
    )
    (tmp_path / "diagram_brief.json").write_text(
        json.dumps({"objective": "Broken fixture.", "functional_requirements": ["Users access the portal"]}),
        encoding="utf-8",
    )
    (tmp_path / "tech_stack.json").write_text(
        json.dumps({"frontend": {"choice": "React", "rationale": "x", "alternatives": []}}), encoding="utf-8"
    )
    (tmp_path / "blueprint.json").write_text(
        json.dumps(
            {
                "slide_title": "Broken",
                "pattern": "three_tier",
                "pattern_rationale": "x",
                "clusters": [{"id": "app", "label": "App", "tier": "backend"}],
                "nodes": [{"id": "api", "label": "API", "tech": "FastAPI", "cluster": "app"}],
                # "portal" is never declared as a node — dangling edge reference.
                "edges": [{"from": "portal", "to": "api", "label": "HTTPS", "protocol": "HTTP"}],
            }
        ),
        encoding="utf-8",
    )
    reporting.record_report_step(tmp_path, "test_step", summary="Evidence captured.")


def test_run_solution_gate_blocks_on_high_severity_finding(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    _write_broken_solution(tmp_path)

    blocked, note = run_solution_gate("pdf_export", block=True)

    assert blocked is True
    assert "BLOCK" in note


def test_run_solution_gate_advisory_call_never_blocks(monkeypatch, tmp_path):
    """The blueprint/wbs-stage advisory call site (block=False) must keep
    returning a plain note, never a blocking tuple element that matters."""
    _use_workspace(monkeypatch, tmp_path)
    _write_broken_solution(tmp_path)

    blocked, note = run_solution_gate("blueprint", block=False)

    assert blocked is False  # block=False never blocks, regardless of findings
    assert isinstance(note, str)


def test_run_solution_gate_fails_closed_when_validator_crashes(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    _write_broken_solution(tmp_path)
    monkeypatch.setattr(
        "tools.analysis.gates.build_solution_model",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("csm build exploded")),
    )

    blocked, note = run_solution_gate("pdf_export", block=True)

    assert blocked is True
    assert "UNAVAILABLE" in note

    # And the advisory (block=False) call site must NOT be affected by a crash
    # — it fails open to an empty note, same as before this fix.
    blocked_advisory, note_advisory = run_solution_gate("blueprint", block=False)
    assert blocked_advisory is False
    assert note_advisory == ""


def test_generate_pdf_report_blocked_finding_writes_no_file(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    _write_broken_solution(tmp_path)

    result = tools.generate_pdf_report.func(include_sections=["diagram"])

    assert "RELEASE GATE BLOCKED" in result
    assert not (tmp_path / "out.pdf").exists()
    assert not (tmp_path / "out.report.html").exists()


def test_generate_ppt_proposal_blocked_finding_writes_no_file(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    _write_broken_solution(tmp_path)

    result = tools.generate_ppt_proposal.func(include_sections=["cover", "architecture_diagram"])

    assert "RELEASE GATE BLOCKED" in result
    assert not (tmp_path / "out.pptx").exists()


def test_generate_pdf_report_blocked_when_validator_unavailable(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    _write_broken_solution(tmp_path)
    monkeypatch.setattr(
        "tools.analysis.gates.build_solution_model",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("csm build exploded")),
    )

    result = tools.generate_pdf_report.func(include_sections=["diagram"])

    assert "RELEASE GATE BLOCKED" in result
    assert "UNAVAILABLE" in result
    assert not (tmp_path / "out.pdf").exists()
