"""Diagram-flow tests for the drawio-ai-kit port (catalog → .drawio → validate).

These cover the pieces added when porting drawio-ai-kit to Python:
  - drawio_catalog: ground-truth stencil names + verbatim styles + search.
  - validate_drawio: stencil-name validation + design audits (advice).

They build native draw.io XML straight from the catalog (no Graphviz `dot`
needed) and lint it, so the whole flow runs deterministically in CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import drawio_catalog as dc
import validate_drawio as vd

_REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #

def test_catalog_loads_real_aws_stencils():
    cat = dc.load_catalog()
    assert cat.valid_names, "catalog should not be empty"
    # Common AWS resource/group names must be present (ground truth).
    for name in ("ec2", "s3", "lambda", "group_vpc", "group_subnet"):
        assert name in cat.valid_names, f"{name!r} missing from catalog"


def test_style_for_icon_emits_native_resicon():
    cat = dc.load_catalog()
    style = dc.style_for_icon(cat, "s3")["style"]
    # Native stencil → resIcon (vector), not an embedded base64 image.
    assert "resIcon=mxgraph.aws4.s3" in style
    assert "data:image/png" not in style
    assert dc.style_for_icon(cat, "this_name_does_not_exist") is None


def test_search_icon_ranks_exact_match_first():
    cat = dc.load_catalog()
    hits = dc.search_icon(cat, "kubernetes", limit=3)
    assert hits and hits[0]["name"] == "kubernetes"


# --------------------------------------------------------------------------- #
# Build a minimal native AWS diagram from the catalog and lint it
# --------------------------------------------------------------------------- #

def _cell(cid: str, parent: str, style: str, x: int, y: int, w: int, h: int,
          value: str = "") -> str:
    return (f'<mxCell id="{cid}" value="{value}" style="{style}" vertex="1" '
            f'parent="{parent}"><mxGeometry x="{x}" y="{y}" width="{w}" '
            f'height="{h}" as="geometry"/></mxCell>')


def _build_native_drawio() -> str:
    """AWS Cloud → VPC → Subnet → EC2, plus managed S3 and one edge."""
    cat = dc.load_catalog()
    cloud = dc.style_for_group(cat, "group_aws_cloud_alt")["style"]
    vpc = dc.style_for_group(cat, "group_vpc")["style"]
    subnet = dc.style_for_group(cat, "group_subnet")["style"]
    ec2 = dc.style_for_icon(cat, "ec2")["style"]
    s3 = dc.style_for_icon(cat, "s3")["style"]
    cells = [
        # geometry is parent-relative; sizes are generous so nothing spills
        _cell("cloud", "1", cloud, 40, 40, 520, 320, "AWS Cloud"),
        _cell("vpc", "cloud", vpc, 20, 30, 300, 260, "VPC"),
        _cell("subnet", "vpc", subnet, 20, 30, 200, 200, "Private Subnet"),
        _cell("ec2", "subnet", ec2, 60, 60, 48, 48, "App"),
        _cell("s3", "cloud", s3, 400, 120, 48, 48, "S3"),
        ('<mxCell id="e1" value="store" '
         'style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;" edge="1" '
         'parent="1" source="ec2" target="s3"><mxGeometry relative="1" '
         'as="geometry"/></mxCell>'),
    ]
    return (
        '<mxfile host="app.diagrams.net"><diagram name="t" id="d1">'
        '<mxGraphModel dx="800" dy="600" grid="0" page="1" pageScale="1" '
        'pageWidth="800" pageHeight="600"><root>'
        '<mxCell id="0"/><mxCell id="1" parent="0"/>'
        + "".join(cells) +
        '</root></mxGraphModel></diagram></mxfile>'
    )


def test_native_diagram_validates_clean(tmp_path):
    path = tmp_path / "native.drawio"
    path.write_text(_build_native_drawio(), encoding="utf-8")
    report = vd.validate_file(str(path))
    assert report["ok"], f"expected clean diagram, got errors: {report['errors']}"
    assert report["error_count"] == 0
    # every stencil name is real → no "not found" errors
    assert not any("not found in catalog" in e for e in report["errors"])


def test_validator_flags_invented_stencil(tmp_path):
    xml = _build_native_drawio().replace("resIcon=mxgraph.aws4.s3",
                                         "resIcon=mxgraph.aws4.totally_made_up")
    path = tmp_path / "bad.drawio"
    path.write_text(xml, encoding="utf-8")
    report = vd.validate_file(str(path))
    assert not report["ok"]
    assert any("totally_made_up" in e and "not found" in e for e in report["errors"])
    # it should suggest near matches
    assert any("suggestions:" in e for e in report["errors"])


def test_audit_profile_generic_skips_aws_conventions(tmp_path):
    import re
    cat = dc.load_catalog()
    ec2_style = dc.style_for_icon(cat, "ec2")["style"]
    # Recolor the icon away from its standard category color (replace, don't append:
    # the audit reads the first fillColor in the style string).
    recolored = re.sub(r"fillColor=#[0-9A-Fa-f]+", "fillColor=#123456", ec2_style, count=1)
    assert recolored != ec2_style, "ec2 style should contain a fillColor to replace"
    xml = _build_native_drawio().replace(ec2_style, recolored)
    path = tmp_path / "recolor.drawio"
    path.write_text(xml, encoding="utf-8")
    aws = vd.validate_file(str(path), profile="aws_native")
    generic = vd.validate_file(str(path), profile="generic")
    assert any("recolored" in a for a in aws["advice"])
    assert not any("recolored" in a for a in generic["advice"])


# --------------------------------------------------------------------------- #
# Audits on the committed AWS sample (regression against known findings)
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# _write_sidecar: stencil_name resolution
# --------------------------------------------------------------------------- #

def test_sidecar_stencil_name_for_known_icon(tmp_path):
    """_write_sidecar should emit stencil_name when the icon stem is in the catalog."""
    from prettygraph.graph_builder import Pretty

    # Create a fake icon whose stem matches a real catalog entry.
    icon_dir = tmp_path / "icons"
    icon_dir.mkdir()
    (icon_dir / "ec2.png").write_bytes(b"")

    g = Pretty("Test", icons_root=str(icon_dir))
    g.box("n1", "EC2 Instance", kind="compute", icon="ec2.png")
    g.box("n2", "Unknown Node", kind="process", icon="some_unknown_icon.png")
    g.box("n3", "No Icon", kind="neutral")

    sidecar_path = tmp_path / "out.nodes.json"
    g._write_sidecar(str(sidecar_path))

    import json
    data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    nodes = data["nodes"]

    assert nodes["n1"]["stencil_name"] == "ec2", (
        "ec2.png stem should resolve to catalog entry 'ec2'"
    )
    assert nodes["n2"]["stencil_name"] is None, (
        "unknown icon should produce stencil_name=None"
    )
    assert nodes["n3"]["stencil_name"] is None, (
        "node with no icon should produce stencil_name=None"
    )


def test_sidecar_fuzzy_stencil_name_bridges_hyphens(tmp_path):
    """Icon stems that differ only by hyphen-vs-underscore still resolve (Tier 1.1)."""
    from prettygraph.graph_builder import Pretty

    cat = dc.load_catalog()
    # Pick a real multi-word catalog icon and present it as a hyphenated file stem
    # (the mingrammer naming style) — the fuzzy fallback must map it back.
    target = next(n for n, e in cat.by_name.items()
                  if e.get("kind") == "icon" and n.count("_") >= 2)
    hyphen_stem = target.replace("_", "-")

    icon_dir = tmp_path / "icons"
    icon_dir.mkdir()
    (icon_dir / f"{hyphen_stem}.png").write_bytes(b"")

    g = Pretty("Test", icons_root=str(icon_dir))
    g.box("n1", "Some Service", kind="compute", icon=f"{hyphen_stem}.png")

    sidecar_path = tmp_path / "out.nodes.json"
    g._write_sidecar(str(sidecar_path))
    import json
    data = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert data["nodes"]["n1"]["stencil_name"] == target


def test_sidecar_cluster_group_name(tmp_path):
    """A cluster labelled like an AWS container gets a group_name (Tier 1.2)."""
    from prettygraph.graph_builder import Pretty
    import json

    g = Pretty("Test")
    g.cluster("c_vpc", "Production VPC", "Network")
    g.cluster("c_sub", "Private Subnet", "Network", parent="c_vpc")
    g.cluster("c_plain", "Business Logic", "Compute")

    sidecar_path = tmp_path / "out.nodes.json"
    g._write_sidecar(str(sidecar_path))
    clusters = json.loads(sidecar_path.read_text(encoding="utf-8"))["clusters"]
    assert clusters["c_vpc"]["group_name"] == "group_vpc"
    assert clusters["c_sub"]["group_name"] == "group_subnet"
    assert clusters["c_plain"]["group_name"] is None


def _gv_with_cluster() -> str:
    import json
    return json.dumps({
        "bb": "0,0,400,300",
        "objects": [
            {"_gvid": 0, "name": "clustervpc", "bb": "10,10,390,290"},
            {"_gvid": 1, "name": "n1", "pos": "200,150", "width": "0.7", "height": "0.7"},
        ],
        "edges": [],
    })


def _fake_gv(monkeypatch, gv_json: str) -> None:
    import subprocess
    def _fake_run(cmd, **kw):
        class _R:
            stdout = gv_json
            returncode = 0
        return _R()
    monkeypatch.setattr(subprocess, "run", _fake_run)


def test_dot_to_drawio_native_group_when_aws_native(tmp_path, monkeypatch):
    """Clusters render as native grIcon frames when the diagram is AWS-stencil-native (1.2)."""
    import json
    from prettygraph.drawio import dot_to_drawio

    _fake_gv(monkeypatch, _gv_with_cluster())
    sidecar = {
        "nodes": {"n1": {"label": "EC2", "sublabel": None, "kind": "compute",
                         "fill": "#eee", "stroke": "#999", "icon": None,
                         "shadow": 0, "stencil_name": "ec2"}},
        "clusters": {"vpc": {"label": "VPC", "fill": "#eee", "stroke": "#999",
                             "group_name": "group_vpc"}},
        "style": {},
    }
    sp = tmp_path / "out.nodes.json"
    sp.write_text(json.dumps(sidecar), encoding="utf-8")
    xml = dot_to_drawio("fake.dot", str(sp), str(tmp_path / "out.drawio"))
    assert "grIcon=mxgraph.aws4.group_vpc" in xml
    assert "resIcon=mxgraph.aws4.ec2" in xml


def test_dot_to_drawio_no_native_group_when_not_aws_native(tmp_path, monkeypatch):
    """Without any native node stencil, a cluster stays a plain box (no aws4 group leak)."""
    import json
    from prettygraph.drawio import dot_to_drawio

    _fake_gv(monkeypatch, _gv_with_cluster())
    sidecar = {
        "nodes": {"n1": {"label": "Thing", "sublabel": None, "kind": "process",
                         "fill": "#eee", "stroke": "#999", "icon": None,
                         "shadow": 0, "stencil_name": None}},
        "clusters": {"vpc": {"label": "VPC", "fill": "#eee", "stroke": "#999",
                             "group_name": "group_vpc"}},
        "style": {},
    }
    sp = tmp_path / "out.nodes.json"
    sp.write_text(json.dumps(sidecar), encoding="utf-8")
    xml = dot_to_drawio("fake.dot", str(sp), str(tmp_path / "out.drawio"))
    assert "grIcon" not in xml


def test_audit_flags_floating_arrowhead(tmp_path):
    """An edge anchored to a transparent (fillColor=none) leaf is flagged (Tier 1.4)."""
    ghost = ('<mxCell id="ghost" value="" style="rounded=0;fillColor=none;'
             'strokeColor=none;html=1;" vertex="1" parent="1">'
             '<mxGeometry x="300" y="300" width="60" height="60" as="geometry"/></mxCell>')
    xml = _build_native_drawio().replace(
        '</root>',
        ghost + '<mxCell id="ef" value="" style="edgeStyle=orthogonalEdgeStyle;html=1;" '
                'edge="1" parent="1" source="s3" target="ghost">'
                '<mxGeometry relative="1" as="geometry"/></mxCell></root>')
    path = tmp_path / "float.drawio"
    path.write_text(xml, encoding="utf-8")
    advice = vd.validate_file(str(path))["advice"]
    assert any("invisible leaf" in a for a in advice)


def test_audit_no_floating_flag_for_solid_nodes(tmp_path):
    """A clean native diagram (solid icons) raises no invisible-leaf advice."""
    path = tmp_path / "clean.drawio"
    path.write_text(_build_native_drawio(), encoding="utf-8")
    advice = vd.validate_file(str(path))["advice"]
    assert not any("invisible leaf" in a for a in advice)


def test_dot_to_drawio_uses_native_stencil(tmp_path, monkeypatch):
    """dot_to_drawio should emit resIcon stencil style when sidecar has stencil_name."""
    import json
    import subprocess
    from prettygraph.drawio import dot_to_drawio

    # Minimal Graphviz JSON output for one node (pos in pts, bb in pts).
    gv_json = json.dumps({
        "bb": "0,0,200,100",
        "objects": [
            {"_gvid": 1, "name": "n1", "pos": "100,50", "width": "1.5", "height": "0.8"}
        ],
        "edges": [],
    })

    # Patch subprocess so no real Graphviz is needed.
    def _fake_run(cmd, **kw):
        class _R:
            stdout = gv_json
            returncode = 0
        return _R()

    monkeypatch.setattr(subprocess, "run", _fake_run)

    sidecar = {
        "nodes": {
            "n1": {
                "label": "EC2", "sublabel": None, "kind": "compute",
                "fill": "#f0f0f0", "stroke": "#aaaaaa", "icon": None,
                "shadow": 0, "stencil_name": "ec2",
            }
        },
        "clusters": {},
        "style": {},
    }
    sidecar_path = tmp_path / "out.nodes.json"
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    out_path = tmp_path / "out.drawio"

    xml = dot_to_drawio("fake.dot", str(sidecar_path), str(out_path))

    # Native stencil must appear; base64 must not.
    assert "resIcon=mxgraph.aws4.ec2" in xml, "native resIcon not found in output XML"
    assert "data:image/png" not in xml, "base64 embed should not appear for stencil node"


def test_dot_to_drawio_fallback_to_b64(tmp_path, monkeypatch):
    """dot_to_drawio falls back to base64 when stencil_name is absent."""
    import json
    import subprocess
    from prettygraph.drawio import dot_to_drawio

    gv_json = json.dumps({
        "bb": "0,0,200,100",
        "objects": [
            {"_gvid": 1, "name": "n1", "pos": "100,50", "width": "1.5", "height": "0.8"}
        ],
        "edges": [],
    })

    def _fake_run(cmd, **kw):
        class _R:
            stdout = gv_json
            returncode = 0
        return _R()

    monkeypatch.setattr(subprocess, "run", _fake_run)

    # Write a minimal 1-byte fake PNG so _b64 can read it.
    fake_icon = tmp_path / "custom.png"
    fake_icon.write_bytes(b"\x89PNG")

    sidecar = {
        "nodes": {
            "n1": {
                "label": "Custom", "sublabel": None, "kind": "process",
                "fill": "#f0f0f0", "stroke": "#aaaaaa", "icon": str(fake_icon),
                "shadow": 0, "stencil_name": None,
            }
        },
        "clusters": {},
        "style": {},
    }
    sidecar_path = tmp_path / "out.nodes.json"
    sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
    out_path = tmp_path / "out.drawio"

    xml = dot_to_drawio("fake.dot", str(sidecar_path), str(out_path))

    assert "data:image/png" in xml, "base64 fallback expected when no stencil_name"
    assert "resIcon" not in xml


def test_audits_on_committed_sample():
    sample = _REPO_ROOT / "out_aws_drawio.drawio"
    if not sample.exists():
        pytest.skip("out_aws_drawio.drawio sample not present")
    report = vd.validate_file(str(sample))
    # The sample uses invented stencils → known errors, and has design issues.
    assert report["error_count"] >= 1
    assert report["advice_count"] >= 5
    joined = " ".join(report["advice"])
    assert "recolored" in joined          # AWS convention audit
    assert "fan-in" in joined             # geometry audit
    assert "light-dark" in joined         # aesthetics audit
