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
        backends,
        "_current_workspace",
        contextvars.ContextVar("current_workspace", default=ws),
    )


@pytest.fixture
def ws(tmp_path, monkeypatch):
    w = tmp_path / "ws"
    _bind(monkeypatch, w)
    xml, _ = build_drawio_from_spec(_GCP_SPEC, "t")
    (w / "out.drawio").write_text(xml, encoding="utf-8")
    # keep tests hermetic: no draw.io CLI dependency, no PNG in tool replies
    monkeypatch.setattr("tools.rendering_tools._render_drawio_png", lambda *a, **k: False)
    monkeypatch.setenv("RENDER_INCLUDES_IMAGE", "0")
    return w


def test_read_drawio_inventory(ws):
    inv = read_drawio.func()
    assert "V mgmt" in inv and "E " in inv  # vertices + edges listed
    assert "Validator:" in inv  # findings appended
    assert f"edit_drawio batches left: {_DRAWIO_EDIT_CAP}" in inv


def test_edit_drawio_ops_roundtrip(ws):
    msg = edit_drawio.func(
        ops=[
            DrawioOp(op="set_style", id="mgmt", key="fillColor", value="#EEF1F5"),
            DrawioOp(op="set_label", id="api", value="<b>API v2</b>"),
            DrawioOp(op="move", id="api", dx=10, dy=0),
            DrawioOp(
                op="add_edge",
                id="e_new",
                source="cb",
                target="api",
                label="deploy",
                dashed=True,
                color="#64748B",
            ),
            DrawioOp(op="set_style", id="ghost", key="fillColor", value="#fff"),
        ],
        tool_call_id="t1",
    )
    assert msg.status == "success"
    assert "Applied 4 op(s)" in msg.content
    assert "ghost: unknown id" in msg.content
    assert "Lint:" in msg.content  # auto re-validated
    xml = (ws / "out.drawio").read_text(encoding="utf-8")
    assert "fillColor=#EEF1F5" in xml
    assert 'source="cb" target="api"' in xml or ('source="cb"' in xml and "e_new" in xml)


def test_edit_drawio_delete_drops_dependents(ws):
    msg = edit_drawio.func(ops=[DrawioOp(op="delete", id="api")], tool_call_id="t1")
    assert msg.status == "success"
    xml = (ws / "out.drawio").read_text(encoding="utf-8")
    assert 'id="api"' not in xml
    assert 'id="api__ic"' not in xml  # child icon removed
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
    from tools.rendering_tools import _ENGINEER_INSPECT_CAP, inspect_render_quality
    import json

    (ws / "out.native_stats.json").write_text(json.dumps({"nodes": 5, "edges": 3}), encoding="utf-8")
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

    _render_native_from_spec(dict(_GCP_SPEC, presentation_style="diagram", style_preset="icon"), ws)
    assert (ws / "layout_plan.json").exists()
    assert (ws / "engineer_report.json").exists()
    import json

    rep = json.loads((ws / "engineer_report.json").read_text(encoding="utf-8"))
    assert rep["iterations"] and rep["chosen"]


def test_edit_drawio_reverts_on_score_regression(ws, monkeypatch):
    """A batch that makes the production score meaningfully worse must be
    reverted in place (out.drawio restored byte-for-byte) and must NOT consume
    an edit-budget round — the native tier-0 repair already guarantees "never
    worse than baseline" (prettygraph/native/repair.py); this is the same
    guarantee for the LLM edit tier, which previously had none."""
    import domain.validation.validate_drawio as vd
    from tools.rendering_tools import _drawio_edit_rounds

    real_scorecard = vd.production_scorecard
    calls = {"n": 0}

    def fake_scorecard(report, stats=None):
        calls["n"] += 1
        sc = real_scorecard(report, stats)
        if calls["n"] == 2:  # 1st call = before-snapshot, 2nd = post-edit
            sc = {**sc, "total": max(0.0, sc["total"] - 20.0)}
        return sc

    monkeypatch.setattr(vd, "production_scorecard", fake_scorecard)

    before_xml = (ws / "out.drawio").read_text(encoding="utf-8")
    msg = edit_drawio.func(
        ops=[DrawioOp(op="set_style", id="mgmt", key="fillColor", value="#EEF1F5")],
        tool_call_id="t1",
    )
    assert msg.status == "error"
    assert "REVERTED" in msg.content
    assert "NOT counted against your edit budget" in msg.content
    after_xml = (ws / "out.drawio").read_text(encoding="utf-8")
    assert after_xml == before_xml
    assert _drawio_edit_rounds() == 0


def test_semantic_loss_diff_ignores_explicit_deletes():
    """Unit test for the pure diff edit_drawio's revert guard runs on: a
    vertex/edge that vanished via an explicit `delete` op is NOT a loss; one
    that vanished with no matching deleted_id IS — this is what makes the
    revert-on-corruption branch fire without needing a real corrupting op
    sequence (which the public DrawioOp API deliberately makes hard to
    construct, since every removal path is supposed to go through `delete`)."""
    from tools.rendering_tools import _semantic_loss_diff

    before_v = {"mgmt", "cb", "api"}
    before_e = {("api", "cb")}
    # "cb" was legitimately deleted (in deleted_ids) -> not a loss.
    lost_v, lost_e = _semantic_loss_diff(
        before_v, before_e, after_v={"mgmt", "api"}, after_e={("api", "cb")}, deleted_ids={"cb"}
    )
    assert lost_v == set() and lost_e == set()

    # "mgmt" vanished with NO matching delete -> flagged as a loss.
    lost_v, lost_e = _semantic_loss_diff(
        before_v, before_e, after_v={"cb", "api"}, after_e=set(), deleted_ids=set()
    )
    assert lost_v == {"mgmt"}
    assert lost_e == {("api", "cb")}


def test_export_drawio_native_budget_cap(ws, monkeypatch):
    """export_drawio_native/upgrade_drawio are code-capped per round — without
    this, "never re-export hoping for a different geometry" (prompts/
    drawer_agent.py) was prose-only: a drawer hitting EDIT/ENGINEER BUDGET
    EXHAUSTED could just re-export to silently refill both those counters."""
    import json

    from tools.constants import _NATIVE_EXPORT_CAP, _RENDER_SPEC_FILE
    from tools.rendering_tools import export_drawio_native

    _RENDER_SPEC_FILE.resolve().write_text(json.dumps(_GCP_SPEC), encoding="utf-8")
    for _ in range(_NATIVE_EXPORT_CAP):
        result = export_drawio_native.func()
        assert "NATIVE EXPORT BUDGET EXHAUSTED" not in result, result
    blocked = export_drawio_native.func()
    assert "NATIVE EXPORT BUDGET EXHAUSTED" in blocked


@pytest.fixture()
def _isolated_outputs_dir(tmp_path, monkeypatch):
    """finalize_diagram's archive (§4.3) writes under tools.stage_markers.OUTPUTS_DIR
    — bound at import time (`from backends import OUTPUTS_DIR`), so the module
    attribute itself must be patched, not backends.OUTPUTS_DIR (a plain
    monkeypatch on backends would be invisible to stage_markers' already-bound
    name)."""
    import tools.stage_markers as stage_markers_mod

    outputs = tmp_path / "outputs"
    outputs.mkdir()
    monkeypatch.setattr(stage_markers_mod, "OUTPUTS_DIR", outputs)
    return outputs


def _prep_finalize_fixture(ws):
    """finalize_diagram needs out.png to exist, plus render_spec.json/
    layout_plan.json/out.native_stats.json for the archive+harvest step to
    have something real to read."""
    import json

    (ws / "out.png").write_bytes(b"\x89PNG\r\n")  # existence check only, content unused
    (ws / "render_spec.json").write_text(json.dumps(_GCP_SPEC), encoding="utf-8")
    (ws / "layout_plan.json").write_text(json.dumps({"band_order": ["ops", "app", "data"]}), encoding="utf-8")
    (ws / "out.native_stats.json").write_text(
        json.dumps({"style_preset": "icon", "nodes": len(_GCP_SPEC["nodes"])}), encoding="utf-8"
    )


def test_finalize_diagram_archives_and_harvests_on_pass(ws, _isolated_outputs_dir, monkeypatch):
    import json

    import domain.validation.validate_drawio as vd
    from tools.rendering_tools import finalize_diagram

    _prep_finalize_fixture(ws)
    monkeypatch.setattr(
        vd,
        "production_scorecard",
        lambda report, stats=None: {"total": 92.0, "pass": True, "breakdown": {"composition": 10.0}},
    )

    finalize_diagram.func(kind="architecture")

    archives = list(_isolated_outputs_dir.iterdir())
    assert len(archives) == 1
    dest = archives[0]
    meta = json.loads((dest / "meta.json").read_text(encoding="utf-8"))
    assert meta["scorecard_total"] == 92.0
    assert meta["scorecard_pass"] is True
    assert meta["provider"] == _GCP_SPEC["provider"]
    assert meta["style_preset"] == "icon"
    assert meta["node_count"] == len(_GCP_SPEC["nodes"])
    assert meta["band_count"] == 3
    assert (dest / "render_spec.json").exists()  # extended _SESSION_ARTIFACTS
    assert (dest / "layout_plan.json").exists()

    learned = json.loads((dest / "template.json").read_text(encoding="utf-8"))
    assert learned["source"] == "learned"
    assert learned["scorecard"] == 92.0
    assert "Cloud Monitoring" not in json.dumps(learned)  # _GCP_SPEC's real node labels stripped


def test_finalize_diagram_does_not_harvest_below_gate(ws, _isolated_outputs_dir, monkeypatch):
    import domain.validation.validate_drawio as vd
    from tools.rendering_tools import finalize_diagram

    _prep_finalize_fixture(ws)
    monkeypatch.setattr(
        vd,
        "production_scorecard",
        lambda report, stats=None: {"total": 60.0, "pass": False, "breakdown": {}},
    )

    finalize_diagram.func(kind="architecture")

    dest = next(_isolated_outputs_dir.iterdir())
    assert not (dest / "template.json").exists()  # archived, but NOT harvested — below gate
