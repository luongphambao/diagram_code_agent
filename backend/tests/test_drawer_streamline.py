"""Drawer toolset streamlining: 3 tools, audit merged into render_diagram as a
pre-flight gate, and style/fit plans pre-computed code-side."""

import contextvars
import json

import backends
from tools import DRAWER_TOOLS
from tools.rendering_tools import (
    _audit_code,
    render_diagram,
    write_style_and_fit_plans,
)


def _bind(monkeypatch, ws):
    ws.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        backends, "_current_workspace",
        contextvars.ContextVar("current_workspace", default=ws),
    )


def test_drawer_toolset():
    # render-refine loop (declare_poster_grid, render_diagram, export_drawio) plus
    # the native default path (export_drawio_native), the upgrade-existing-.drawio
    # path (upgrade_drawio), and the in-place fix loop (read_drawio / edit_drawio).
    assert [t.name for t in DRAWER_TOOLS] == [
        "declare_poster_grid", "render_diagram", "export_drawio",
        "export_drawio_native", "upgrade_drawio", "read_drawio", "edit_drawio",
    ]


def test_preflight_audit_blocks_bad_script_without_budget(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    _bind(monkeypatch, ws)
    (ws / "blueprint.json").write_text("{}", encoding="utf-8")

    bad = "from diagrams import Diagram\nwith Diagram('x'):\n    pass\n"
    assert _audit_code(bad)["verdict"] == "REVISE"  # missing filename/outformat

    msg = render_diagram.func(code=bad, tool_call_id="t1")
    assert msg.status == "error"
    assert "PRE-FLIGHT AUDIT" in msg.content
    assert "output_filename" in msg.content
    # No render budget consumed and no script written.
    assert not (ws / "render_count.json").exists()
    assert not (ws / "diagram.py").exists()


def test_write_style_and_fit_plans_from_render_spec(tmp_path, monkeypatch):
    ws = tmp_path / "ws2"
    _bind(monkeypatch, ws)
    spec = {
        "presentation_style": "slide",
        "density": "detailed",
        "nodes": [
            {"id": "api", "label": "API Gateway", "tech": "Kong"},
            {"id": "db", "label": "A Very Long PostgreSQL Database Node Label Indeed",
             "tech": "PostgreSQL 16"},
        ],
        "edges": [{"from": "api", "to": "db",
                   "label": "a very long edge label with too many words"}],
    }
    write_style_and_fit_plans(spec)

    plan = json.loads((ws / "style_plan.json").read_text(encoding="utf-8"))
    assert plan["node_count"] == 2
    assert "pretty_kwargs" in plan and "node_width=" in plan["pretty_kwargs"]

    fits = json.loads((ws / "label_fits.json").read_text(encoding="utf-8"))
    assert len(fits["nodes"]) == 2
    long_entry = next(n for n in fits["nodes"] if not n["fits"])
    assert "suggestion" in long_entry or long_entry.get("still_too_long")
    assert fits["edges"] and fits["edges"][0]["fits"] is False


def test_poster_density_maps_to_poster_output(tmp_path, monkeypatch):
    ws = tmp_path / "ws3"
    _bind(monkeypatch, ws)
    spec = {"presentation_style": "slide", "density": "poster",
            "nodes": [{"id": f"n{i}", "label": f"Node {i}", "tech": ""} for i in range(30)],
            "edges": []}
    write_style_and_fit_plans(spec)
    plan = json.loads((ws / "style_plan.json").read_text(encoding="utf-8"))
    assert plan["output"] == "poster"
