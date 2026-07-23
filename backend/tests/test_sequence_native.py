"""True UML Sequence Diagram — improvement plan MVP-3 phase 2 (the pilot
vertical slice proving the typed-diagram foundation).

Covers: the SequenceSpec schema, the native lifeline/activation/fragment
renderer (prettygraph.native.sequence), its registration into
prettygraph.native.registry + dispatch through topology.build_tree, the
sequence structural linter, the code-first `Sequence` DSL
(prettygraph.sequence_dsl), and the render_typed_diagram tool end-to-end
(code-first authoring, per the mid-implementation pivot away from a
one-tool-per-kind structured gate — see the plan's "Pivot" section).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

import backends
from prettygraph.native.registry import RENDERERS
from prettygraph.native.sequence import build_sequence_tree, sequence_semantic_ids
from prettygraph.native.topology import build_drawio_from_spec, build_tree
from prettygraph.sequence_dsl import Sequence
from tools.analysis.sequence_tools import _build_sequence_render_spec, lint_sequence
from tools.rendering_tools import render_typed_diagram
from tools.schemas.sequence import SequenceSpec


def _login_spec_dict() -> dict:
    """The proposal §3 magic-link login walkthrough as a render_spec dict."""
    return {
        "kind": "sequence",
        "title": "Magic Link Login",
        "participants": [
            {"id": "user", "label": "User", "kind": "actor"},
            {"id": "fe", "label": "Frontend", "kind": "frontend"},
            {"id": "be", "label": "Backend", "kind": "service"},
            {"id": "supa", "label": "Supabase", "kind": "database"},
        ],
        "messages": [
            {"order": 1, "from": "user", "to": "fe", "label": "Login", "kind": "sync"},
            {"order": 2, "from": "fe", "to": "be", "label": "POST /login", "kind": "sync"},
            {"order": 3, "from": "be", "to": "supa", "label": "Create link", "kind": "sync"},
            {"order": 4, "from": "supa", "to": "be", "label": "link created", "kind": "return"},
            {"order": 5, "from": "be", "to": "fe", "label": "session", "kind": "return"},
            {"order": 6, "from": "fe", "to": "user", "label": "redirect dashboard", "kind": "async"},
        ],
        "fragments": [{"kind": "alt", "condition": "link valid", "start_order": 3, "end_order": 5}],
        "activations": [
            {"participant": "be", "start_order": 2, "end_order": 5},
            {"participant": "supa", "start_order": 3, "end_order": 4},
        ],
    }


# --------------------------------------------------------------------------- #
# schema
# --------------------------------------------------------------------------- #


def test_schema_from_alias_and_defaults():
    spec = SequenceSpec(
        participants=[{"id": "user", "label": "User", "kind": "actor"}],
        messages=[{"order": 1, "from": "user", "to": "user", "label": "self"}],
    )
    assert spec.kind == "sequence"
    assert spec.messages[0].from_ == "user"
    assert spec.messages[0].kind == "sync"  # default


def test_render_spec_projection_uses_plain_from_key():
    spec = SequenceSpec(
        participants=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        messages=[{"order": 1, "from": "a", "to": "b", "label": "hi"}],
    )
    render_spec = _build_sequence_render_spec(spec)
    assert render_spec["kind"] == "sequence"
    assert render_spec["messages"][0]["from"] == "a"
    assert render_spec["messages"][0]["to"] == "b"


# --------------------------------------------------------------------------- #
# registry dispatch — the foundation this phase proves
# --------------------------------------------------------------------------- #


def test_sequence_registered_as_native_renderer():
    entry = RENDERERS.get("sequence")
    assert entry is not None
    assert entry.backend == "native"
    assert entry.tree_builder is build_sequence_tree
    assert entry.lint_kind == "sequence"


def test_build_tree_dispatches_to_sequence_for_registered_kind():
    d, root = build_tree(_login_spec_dict())
    assert root["kind"] == "sequence"
    assert set(root["participants"]) == {"user", "fe", "be", "supa"}


def test_build_tree_without_kind_is_unaffected_by_registry():
    """A plain architecture spec (no "kind" key — every existing Blueprint
    caller) must NEVER be diverted by the new registry hook."""
    spec = {
        "provider": "aws",
        "pattern": "microservices",
        "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        "clusters": [],
        "edges": [{"from": "a", "to": "b", "label": "calls"}],
    }
    d, _ = build_tree(spec)
    xml = d.mxfile("Architecture")
    assert "umlLifeline" not in xml
    assert "shape=umlFrame" not in xml


# --------------------------------------------------------------------------- #
# renderer geometry
# --------------------------------------------------------------------------- #


def test_renders_native_uml_shapes_and_valid_xml():
    xml, stats = build_drawio_from_spec(_login_spec_dict(), "Magic Link Login")
    assert stats["style_preset"] == "sequence"
    assert "umlLifeline" in xml
    assert "umlActor" in xml
    assert "shape=umlFrame" in xml
    root = ET.fromstring(xml)  # must parse as valid XML
    assert root.tag == "mxfile"


def test_messages_render_as_exactly_horizontal_lines():
    """The whole point of bypassing the A*/nudge router: every message's
    exitY/entryY fraction must match exactly, since all lifelines share the
    same y0/height — anything else means the line isn't horizontal."""
    xml, _ = build_drawio_from_spec(_login_spec_dict(), "Magic Link Login")
    root = ET.fromstring(xml)
    found = 0
    for cell in root.iter("mxCell"):
        if not (cell.get("id") or "").startswith("msg_"):
            continue
        style = cell.get("style") or ""
        styles = dict(kv.split("=", 1) for kv in style.split(";") if "=" in kv)
        assert pytest.approx(float(styles["exitY"]), abs=1e-6) == float(styles["entryY"])
        found += 1
    assert found == 6


def test_actor_registered_geometry_matches_emitted_xml_geometry():
    """Regression for a real bug: draw.io computes exitY/entryY anchor points
    against the CELL'S REAL EMITTED geometry, not any bookkeeping kept only
    in `Diagram.R` — a participant whose registered rect diverges from what
    was actually written to the XML renders its messages at the wrong pixel
    row (this exact bug made every message touching the actor draw as a
    diagonal line instead of horizontal, even though the exitY==entryY
    fraction check above still passed). The actor's message-anchor cell
    (`pid`) must span the full lifeline height in BOTH `d.R` and the XML; the
    visible stick-figure glyph is a separate, shorter, decorative cell."""
    d, _ = build_sequence_tree(_login_spec_dict())
    xml = d.mxfile("Magic Link Login")
    root = ET.fromstring(xml)

    def _geometry(cell_id):
        cell = next(c for c in root.iter("mxCell") if c.get("id") == cell_id)
        geom = cell.find("mxGeometry")
        return {k: float(geom.get(k)) for k in ("x", "y", "width", "height")}

    user_r = d.R["user"]
    user_geom = _geometry("user")
    assert user_geom["height"] == pytest.approx(user_r["h"])
    assert user_geom["y"] == pytest.approx(user_r["y"])
    # The anchor cell spans the full timeline, distinct from the short glyph.
    glyph_geom = _geometry("user_glyph")
    assert glyph_geom["height"] < user_geom["height"]


def test_activation_bars_and_fragment_frame_present():
    xml, _ = build_drawio_from_spec(_login_spec_dict(), "Magic Link Login")
    root = ET.fromstring(xml)
    ids = {c.get("id") for c in root.iter("mxCell")}
    assert any(i and i.startswith("act_") for i in ids)
    assert any(i and i.startswith("frag_") for i in ids)


def test_self_message_gets_a_waypoint_loop():
    spec = _login_spec_dict()
    spec["messages"] = [{"order": 1, "from": "be", "to": "be", "label": "validate", "kind": "sync"}]
    spec["fragments"] = []
    spec["activations"] = []
    xml, _ = build_drawio_from_spec(spec, "Self message")
    root = ET.fromstring(xml)
    msg = next(c for c in root.iter("mxCell") if c.get("id") == "msg_1")
    assert msg.find(".//Array[@as='points']") is not None


def test_destroy_message_draws_x_marker():
    spec = _login_spec_dict()
    spec["messages"] = [{"order": 1, "from": "fe", "to": "be", "label": "bye", "kind": "destroy"}]
    spec["fragments"] = []
    spec["activations"] = []
    xml, _ = build_drawio_from_spec(spec, "Destroy")
    assert 'value="X"' in xml


def test_semantic_ids_cover_participants_and_message_pairs():
    ids, edges = sequence_semantic_ids(_login_spec_dict())
    assert set(ids) == {"user", "fe", "be", "supa"}
    assert ("user", "fe") in edges
    assert ("supa", "be") in edges
    assert len(edges) == 6


# --------------------------------------------------------------------------- #
# structural lint (proposal §3's validation list)
# --------------------------------------------------------------------------- #


def test_lint_clean_spec_has_no_errors():
    report = lint_sequence(_login_spec_dict())
    assert not report.has_errors


def test_lint_catches_dangling_participant_ref():
    spec = _login_spec_dict()
    spec["messages"][0]["to"] = "does_not_exist"
    report = lint_sequence(spec)
    assert any(f.code == "unknown_participant" for f in report.errors)


def test_lint_catches_duplicate_order():
    spec = _login_spec_dict()
    spec["messages"][1]["order"] = spec["messages"][0]["order"]
    report = lint_sequence(spec)
    assert any(f.code == "duplicate_order" for f in report.errors)


def test_lint_catches_empty_fragment():
    spec = _login_spec_dict()
    spec["fragments"] = [{"kind": "opt", "condition": "", "start_order": 100, "end_order": 200}]
    report = lint_sequence(spec)
    assert any(f.code == "empty_fragment" for f in report.findings)


def test_lint_catches_fragment_start_after_end():
    spec = _login_spec_dict()
    spec["fragments"] = [{"kind": "alt", "condition": "", "start_order": 5, "end_order": 2}]
    report = lint_sequence(spec)
    assert any(f.code == "invalid_fragment_range" for f in report.errors)


def test_lint_catches_activation_ending_before_it_starts():
    spec = _login_spec_dict()
    spec["activations"] = [{"participant": "be", "start_order": 5, "end_order": 1}]
    report = lint_sequence(spec)
    assert any(f.code == "invalid_activation_range" for f in report.errors)


def test_lint_catches_orphan_participant():
    spec = _login_spec_dict()
    spec["participants"].append({"id": "ghost", "label": "Nobody calls me", "kind": "service"})
    report = lint_sequence(spec)
    assert any(f.code == "orphan_participant" and f.ref == "ghost" for f in report.findings)


def test_lint_catches_unpaired_return():
    spec = _login_spec_dict()
    spec["messages"].append(
        {"order": 7, "from": "supa", "to": "user", "label": "orphan return", "kind": "return"}
    )
    report = lint_sequence(spec)
    assert any(f.code == "unpaired_return" for f in report.findings)


def test_lint_catches_duplicate_participant_id():
    spec = _login_spec_dict()
    spec["participants"].append({"id": "user", "label": "User again", "kind": "actor"})
    report = lint_sequence(spec)
    assert any(f.code == "duplicate_participant" for f in report.errors)


# --------------------------------------------------------------------------- #
# Sequence() DSL — code-first authoring surface (no sandbox: exercises the
# class directly, matching how a generated script uses it)
# --------------------------------------------------------------------------- #


def test_dsl_auto_increments_order_and_writes_spec_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seq = Sequence(title="Magic Link Login")
    seq.actor("user", "User")
    seq.frontend("fe", "Frontend")
    seq.sync("user", "fe", "Login")
    seq.async_("fe", "user", "redirect dashboard")
    seq.render("out")

    spec = json.loads((tmp_path / "out.typed_spec.json").read_text())
    assert spec["kind"] == "sequence"
    assert [p["id"] for p in spec["participants"]] == ["user", "fe"]
    assert [m["order"] for m in spec["messages"]] == [1, 2]
    assert spec["messages"][1]["kind"] == "async"


def test_dsl_activation_and_fragment_context_managers_track_order(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seq = Sequence()
    seq.service("be", "Backend")
    seq.database("supa", "Supabase")
    seq.sync("be", "supa", "warmup")  # order 1, outside any block
    with seq.alt("link valid"):
        with seq.activation("supa"):
            seq.sync("be", "supa", "Create link")  # order 2
            seq.ret("supa", "be", "link created")  # order 3
    seq.render("out")

    spec = json.loads((tmp_path / "out.typed_spec.json").read_text())
    assert spec["fragments"] == [{"kind": "alt", "condition": "link valid", "start_order": 2, "end_order": 3}]
    assert spec["activations"] == [{"participant": "supa", "start_order": 2, "end_order": 3}]


def test_dsl_spec_round_trips_through_validation_and_lint(tmp_path, monkeypatch):
    """The DSL's JSON output must be exactly what SequenceSpec/lint_sequence
    expect — the same contract render_typed_diagram relies on server-side."""
    monkeypatch.chdir(tmp_path)
    seq = Sequence(title="Round trip")
    seq.actor("user", "User")
    seq.service("be", "Backend")
    seq.sync("user", "be", "hi")
    seq.render("out")

    raw = json.loads((tmp_path / "out.typed_spec.json").read_text())
    validated = SequenceSpec(**raw)
    render_spec = _build_sequence_render_spec(validated)
    report = lint_sequence(render_spec)
    assert not report.has_errors


# --------------------------------------------------------------------------- #
# render_typed_diagram tool, end to end (real sandbox subprocess — proves the
# DSL is actually importable where the LLM's script runs)
# --------------------------------------------------------------------------- #

_LOGIN_SCRIPT = """
from prettygraph.sequence_dsl import Sequence

seq = Sequence(title="Magic Link Login")
seq.actor("user", "User")
seq.frontend("fe", "Frontend")
seq.service("be", "Backend")
seq.database("supa", "Supabase")

seq.sync("user", "fe", "Login")
seq.sync("fe", "be", "POST /login")
with seq.activation("be"):
    seq.sync("be", "supa", "Create link")
    seq.ret("supa", "be", "link created")
    seq.ret("be", "fe", "session")
seq.async_("fe", "user", "redirect dashboard")

seq.render("out")
"""


def test_render_typed_diagram_requires_brief_first(tmp_path):
    token = backends.set_current_workspace(tmp_path)
    try:
        result = render_typed_diagram.func(kind="sequence", code=_LOGIN_SCRIPT)
        assert "propose_diagram_brief" in result
        assert not (tmp_path / "out.drawio").exists()
    finally:
        backends.reset_current_workspace(token)


def test_render_typed_diagram_end_to_end(tmp_path, monkeypatch):
    # Force the same-process LocalDevRunner (matches test_sandbox_runners.py's
    # convention) — the default provider is real Modal, whose diagram image
    # only bakes prettygraph/*.py at image-build time, so a locally-added DSL
    # module wouldn't be visible there without a redeploy.
    monkeypatch.setenv("SANDBOX_PROVIDER", "local")
    monkeypatch.setenv("APP_ENV", "development")
    token = backends.set_current_workspace(tmp_path)
    try:
        (tmp_path / "diagram_brief.json").write_text("{}", encoding="utf-8")
        result = render_typed_diagram.func(kind="sequence", code=_LOGIN_SCRIPT)
        assert "Rendered sequence diagram" in result, result
        assert (tmp_path / "out.drawio").exists()
        stats = json.loads((tmp_path / "out.native_stats.json").read_text())
        assert stats["style_preset"] == "sequence"
        assert stats["semantic"]["node_recall"] == 1.0
        assert stats["semantic"]["edge_recall"] == 1.0
        assert stats["lint"]["errors"] == []
    finally:
        backends.reset_current_workspace(token)


def test_render_typed_diagram_surfaces_lint_findings_without_blocking(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_PROVIDER", "local")
    monkeypatch.setenv("APP_ENV", "development")
    token = backends.set_current_workspace(tmp_path)
    try:
        (tmp_path / "diagram_brief.json").write_text("{}", encoding="utf-8")
        script = (
            "from prettygraph.sequence_dsl import Sequence\n"
            "seq = Sequence()\n"
            "seq.service('a', 'A')\n"
            "seq.sync('a', 'missing', 'x')\n"
            "seq.render('out')\n"
        )
        result = render_typed_diagram.func(kind="sequence", code=script)
        # Non-blocking: the tool still succeeds and reports the finding, same
        # convention as propose_blueprint's WAF/NFR validators.
        assert "Rendered sequence diagram" in result, result
        assert "unknown_participant" in result or "not a declared participant" in result
        assert (tmp_path / "out.drawio").exists()
    finally:
        backends.reset_current_workspace(token)
