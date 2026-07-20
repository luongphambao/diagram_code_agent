"""read_drawio / edit_drawio: the in-place fix loop on the native out.drawio."""

import contextvars

import backends
import pytest

from prettygraph.native.topology import build_drawio_from_spec
from tools.rendering_tools import (
    DrawioOp,
    _DRAWIO_EDIT_CAP,
    edit_drawio,
    read_drawio,
)

from test_native_engine import _GCP_SPEC


def _bind(monkeypatch, ws):
    ws.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        backends, "_current_workspace",
        contextvars.ContextVar("current_workspace", default=ws),
    )


@pytest.fixture
def ws(tmp_path, monkeypatch):
    w = tmp_path / "ws"
    _bind(monkeypatch, w)
    xml, _ = build_drawio_from_spec(_GCP_SPEC, "t")
    (w / "out.drawio").write_text(xml, encoding="utf-8")
    # keep tests hermetic: no draw.io CLI dependency, no PNG in tool replies
    monkeypatch.setattr("tools.rendering_tools._render_drawio_png",
                        lambda *a, **k: False)
    monkeypatch.setenv("RENDER_INCLUDES_IMAGE", "0")
    return w


def test_read_drawio_inventory(ws):
    inv = read_drawio.func()
    assert "V mgmt" in inv and "E " in inv          # vertices + edges listed
    assert "Validator:" in inv                       # findings appended
    assert f"edit_drawio batches left: {_DRAWIO_EDIT_CAP}" in inv


def test_edit_drawio_ops_roundtrip(ws):
    msg = edit_drawio.func(ops=[
        DrawioOp(op="set_style", id="mgmt", key="fillColor", value="#EEF1F5"),
        DrawioOp(op="set_label", id="api", value="<b>API v2</b>"),
        DrawioOp(op="move", id="api", dx=10, dy=0),
        DrawioOp(op="add_edge", id="e_new", source="cb", target="api",
                 label="deploy", dashed=True, color="#64748B"),
        DrawioOp(op="set_style", id="ghost", key="fillColor", value="#fff"),
    ], tool_call_id="t1")
    assert msg.status == "success"
    assert "Applied 4 op(s)" in msg.content
    assert "ghost: unknown id" in msg.content
    assert "Lint:" in msg.content                    # auto re-validated
    xml = (ws / "out.drawio").read_text(encoding="utf-8")
    assert "fillColor=#EEF1F5" in xml
    assert 'source="cb" target="api"' in xml or ('source="cb"' in xml and "e_new" in xml)


def test_edit_drawio_delete_drops_dependents(ws):
    msg = edit_drawio.func(ops=[DrawioOp(op="delete", id="api")], tool_call_id="t1")
    assert msg.status == "success"
    xml = (ws / "out.drawio").read_text(encoding="utf-8")
    assert 'id="api"' not in xml
    assert 'id="api__ic"' not in xml                 # child icon removed
    assert 'source="api"' not in xml and 'target="api"' not in xml  # edges removed


def test_edit_drawio_budget_cap(ws):
    op = [DrawioOp(op="move", id="api", dx=1)]
    for i in range(_DRAWIO_EDIT_CAP):
        assert edit_drawio.func(ops=op, tool_call_id=f"t{i}").status == "success"
    blocked = edit_drawio.func(ops=op, tool_call_id="tx")
    assert blocked.status == "error"
    assert "EDIT BUDGET EXHAUSTED" in blocked.content


def test_edit_budget_resets_on_fresh_export(ws, monkeypatch):
    op = [DrawioOp(op="move", id="api", dx=1)]
    for i in range(_DRAWIO_EDIT_CAP):
        edit_drawio.func(ops=op, tool_call_id=f"t{i}")
    from tools.rendering_tools import _render_native_from_spec
    _render_native_from_spec(dict(_GCP_SPEC, presentation_style="diagram"), ws)
    assert edit_drawio.func(ops=op, tool_call_id="t9").status == "success"


def test_inspect_render_quality_budget_cap_and_reset(ws, monkeypatch):
    from tools.rendering_tools import (_ENGINEER_INSPECT_CAP,
                                       inspect_render_quality)
    import json
    (ws / "out.native_stats.json").write_text(
        json.dumps({"nodes": 5, "edges": 3}), encoding="utf-8")
    for i in range(_ENGINEER_INSPECT_CAP):
        msg = inspect_render_quality.func(tool_call_id=f"i{i}")
        assert msg.status == "success", msg.content
        assert "Production scorecard" in msg.content
        assert f"{i + 1}/{_ENGINEER_INSPECT_CAP}" in msg.content
    blocked = inspect_render_quality.func(tool_call_id="ix")
    assert blocked.status == "error"
    assert "budget exhausted" in blocked.content.lower()
    # A fresh export resets the engineer budget together with the edit budget.
    from tools.rendering_tools import _render_native_from_spec
    _render_native_from_spec(dict(_GCP_SPEC, presentation_style="diagram"), ws)
    assert inspect_render_quality.func(tool_call_id="i9").status == "success"


def test_render_native_writes_engineer_artifacts(ws):
    # engineer_report.json comes from the icon preset's deterministic auto_repair
    # (the refined default skips it), so pin this to the icon path explicitly.
    from tools.rendering_tools import _render_native_from_spec
    _render_native_from_spec(
        dict(_GCP_SPEC, presentation_style="diagram", style_preset="icon"), ws)
    assert (ws / "layout_plan.json").exists()
    assert (ws / "engineer_report.json").exists()
    import json
    rep = json.loads((ws / "engineer_report.json").read_text(encoding="utf-8"))
    assert rep["iterations"] and rep["chosen"]
