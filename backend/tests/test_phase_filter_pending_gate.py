from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


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


def test_pending_gate_keeps_tool_even_after_phase_advances(monkeypatch, tmp_path):
    phase_filter = _load_phase_filter_module()
    (tmp_path / "out.png").write_bytes(b"stale-render")
    (tmp_path / "architecture_analysis.json").write_text("{}", encoding="utf-8")
    (tmp_path / "diagram_brief.json").write_text("{}", encoding="utf-8")
    (tmp_path / "tech_stack.json").write_text("[]", encoding="utf-8")
    (tmp_path / "pending_gate.json").write_text(
        json.dumps({"tool": "propose_blueprint", "args": {}}),
        encoding="utf-8",
    )
    monkeypatch.setitem(
        sys.modules,
        "backends",
        SimpleNamespace(current_workspace=lambda: tmp_path),
    )

    tools = [
        _Tool("read_file"),
        _Tool("finalize_diagram"),
        _Tool("propose_blueprint"),
        _Tool("propose_tech_stack"),
    ]

    names = {tool.name for tool in phase_filter.PhaseToolFilterMiddleware()._filtered_tools(tools)}

    assert "finalize_diagram" in names
    assert "propose_blueprint" in names
    assert "propose_tech_stack" not in names


def test_draw_phase_keeps_wbs_deliverable_tools(monkeypatch, tmp_path):
    phase_filter = _load_phase_filter_module()
    (tmp_path / "out.png").write_bytes(b"rendered-diagram")
    monkeypatch.setitem(
        sys.modules,
        "backends",
        SimpleNamespace(current_workspace=lambda: tmp_path),
    )

    tools = [
        _Tool("finalize_diagram"),
        _Tool("propose_wbs_skeleton"),
        _Tool("propose_wbs"),
        _Tool("export_wbs_excel"),
        _Tool("propose_deck_plan"),
        _Tool("send_email"),
        _Tool("propose_tech_stack"),
    ]

    names = {tool.name for tool in phase_filter.PhaseToolFilterMiddleware()._filtered_tools(tools)}

    assert "finalize_diagram" in names
    assert "propose_wbs_skeleton" in names
    assert "propose_wbs" in names
    assert "export_wbs_excel" in names
    assert "propose_deck_plan" in names
    assert "send_email" in names
    assert "propose_tech_stack" in names  # kept for missing foundational artifact backfill


def test_wbs_phase_keeps_send_email_tool(monkeypatch, tmp_path):
    """Regression test: right after a WBS is created (wbs.json exists, but no
    out.pdf/out.png yet), phase is inferred as "wbs". send_email must stay
    available there, else the model has no tool to email the WBS deliverable
    and falls back to calling export_wbs_excel() again (regenerating it)."""
    phase_filter = _load_phase_filter_module()
    (tmp_path / "wbs.json").write_text("{}", encoding="utf-8")
    monkeypatch.setitem(
        sys.modules,
        "backends",
        SimpleNamespace(current_workspace=lambda: tmp_path),
    )

    tools = [
        _Tool("propose_wbs_skeleton"),
        _Tool("propose_wbs"),
        _Tool("export_wbs_excel"),
        _Tool("send_email"),
        _Tool("web_research"),
    ]

    names = {tool.name for tool in phase_filter.PhaseToolFilterMiddleware()._filtered_tools(tools)}

    assert "send_email" in names
    assert "export_wbs_excel" in names


def test_report_phase_keeps_wbs_reexport_tool(monkeypatch, tmp_path):
    phase_filter = _load_phase_filter_module()
    (tmp_path / "out.pdf").write_bytes(b"report")
    (tmp_path / "wbs.json").write_text("{}", encoding="utf-8")
    monkeypatch.setitem(
        sys.modules,
        "backends",
        SimpleNamespace(current_workspace=lambda: tmp_path),
    )

    tools = [
        _Tool("generate_pdf_report"),
        _Tool("export_wbs_excel"),
        _Tool("propose_wbs"),
        _Tool("send_email"),
        _Tool("propose_deck_plan"),
    ]

    names = {tool.name for tool in phase_filter.PhaseToolFilterMiddleware()._filtered_tools(tools)}

    assert "generate_pdf_report" in names
    assert "export_wbs_excel" in names
    assert "propose_wbs" in names
    assert "send_email" in names
    assert "propose_deck_plan" not in names


def test_report_phase_reinstates_stale_deck_plan_tool(monkeypatch, tmp_path):
    """Tier D1 / H-3+M-2: deck_plan.json recorded as derived from blueprint.json,
    then blueprint.json changes after out.pdf exists (phase="report", which
    normally hides propose_deck_plan) -- the tool must come back so the model
    can actually rebuild the now-stale deck instead of it being silently wrong."""
    from session.artifact_manifest import record_artifact

    phase_filter = _load_phase_filter_module()
    (tmp_path / "out.pdf").write_bytes(b"report")
    (tmp_path / "wbs.json").write_text("{}", encoding="utf-8")
    (tmp_path / "blueprint.json").write_text('{"nodes": []}', encoding="utf-8")
    bp_rev = record_artifact(tmp_path, "blueprint.json")
    (tmp_path / "deck_plan.json").write_text("{}", encoding="utf-8")
    record_artifact(tmp_path, "deck_plan.json", derived_from=[("blueprint.json", bp_rev)])
    (tmp_path / "blueprint.json").write_text('{"nodes": [{"id": "a"}]}', encoding="utf-8")
    record_artifact(tmp_path, "blueprint.json")
    monkeypatch.setitem(
        sys.modules,
        "backends",
        SimpleNamespace(current_workspace=lambda: tmp_path),
    )

    tools = [
        _Tool("generate_pdf_report"),
        _Tool("propose_deck_plan"),
        _Tool("send_email"),
    ]

    names = {tool.name for tool in phase_filter.PhaseToolFilterMiddleware()._filtered_tools(tools)}

    assert "propose_deck_plan" in names


def test_report_phase_no_manifest_keeps_deck_plan_hidden(monkeypatch, tmp_path):
    """Backward compat: a workspace with no artifact_manifest.json at all (every
    workspace before this Tier D change) behaves exactly as before -- no
    staleness can be proven, so nothing is reinstated."""
    phase_filter = _load_phase_filter_module()
    (tmp_path / "out.pdf").write_bytes(b"report")
    (tmp_path / "wbs.json").write_text("{}", encoding="utf-8")
    (tmp_path / "deck_plan.json").write_text("{}", encoding="utf-8")
    monkeypatch.setitem(
        sys.modules,
        "backends",
        SimpleNamespace(current_workspace=lambda: tmp_path),
    )

    tools = [_Tool("generate_pdf_report"), _Tool("propose_deck_plan")]
    names = {tool.name for tool in phase_filter.PhaseToolFilterMiddleware()._filtered_tools(tools)}

    assert "propose_deck_plan" not in names
