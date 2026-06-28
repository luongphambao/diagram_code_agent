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
