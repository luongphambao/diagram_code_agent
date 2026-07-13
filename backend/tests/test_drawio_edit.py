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
