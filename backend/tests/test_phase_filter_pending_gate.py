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
