"""Production-upgrade regression suite (icons / routing / labels / gates).

Covers the client-deliverable upgrade of the refined preset:
  1. icon_plan bake for EVERY provider + the never-bare-card fallback chain
  2. catalog abbreviation aliases + the generic-token wrong-icon guard
  3. remote image= URL hard-fail in the validator
  4. refined edges going through the deterministic router (ports + waypoints)
  5. icon coverage counting refined "__ic" badge cells (parented to root "1")
"""
from __future__ import annotations

import base64
import json
import xml.etree.ElementTree as ET

import pytest

from domain.diagram.drawio_catalog import load_catalog, search_icon
from prettygraph.native.topology import _resolve_node_icon, build_drawio_from_spec

# 1x1 transparent PNG
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAC"
    "hwGA60e6kgAAAABJRU5ErkJggg==")


def _refined_min_spec(**over):
    spec = {
        "style_preset": "refined", "provider": "aws", "diagram_title": "T",
        "clusters": [{"id": "z1", "label": "Edge", "number": 1},
                     {"id": "z2", "label": "App", "number": 2}],
        "nodes": [
            {"id": "waf", "cluster": "z1", "label": "AWS WAF"},
            {"id": "kms", "cluster": "z1", "label": "AWS KMS"},
            {"id": "api", "cluster": "z2", "label": "API Gateway"},
            {"id": "fund", "cluster": "z2", "label": "Fund Management Service"},
        ],
        "edges": [{"from": "waf", "to": "api", "label": "Route request",
                   "flow": "data"},
                  {"from": "kms", "to": "fund", "label": "Decrypt", "flow": "control"}],
    }
    spec.update(over)
    return spec


# ---- 1. icon_plan bake + fallback chain ---------------------------------- #

def test_bake_icon_plan_bakes_for_aws(tmp_path):
    from tools.rendering_tools import _bake_icon_plan
    icon = tmp_path / "route-53.png"
    icon.write_bytes(_PNG)
    (tmp_path / "icon_plan.json").write_text(json.dumps([
        {"label": "Route 53", "status": "FOUND", "icon": str(icon)},
    ]), encoding="utf-8")
    spec = {"provider": "aws",
            "nodes": [{"id": "r53", "label": "Route 53"},
                      {"id": "mystery", "label": "Zorbly Flux Unit"}]}
    _bake_icon_plan(spec, tmp_path)
    # AWS is no longer exempt: the plan entry becomes a data URI
    assert spec["nodes"][0]["icon_data_uri"].startswith("data:image/png;base64,")
    # never a bare card: the unresolvable node fell through to a category glyph
    assert spec["nodes"][1].get("icon")
    assert spec["_fallback_icons"] >= 1


def test_bake_icon_plan_normalized_label_match(tmp_path):
    from tools.rendering_tools import _bake_icon_plan
    icon = tmp_path / "x.png"
    icon.write_bytes(_PNG)
    (tmp_path / "icon_plan.json").write_text(json.dumps([
        {"label": "route-53", "status": "FOUND", "icon": str(icon)},
    ]), encoding="utf-8")
    spec = {"provider": "aws", "nodes": [{"id": "n1", "label": "Route 53"}]}
    _bake_icon_plan(spec, tmp_path)
    assert "icon_data_uri" in spec["nodes"][0]  # "Route 53" ~ "route-53"


def test_category_glyph_is_deterministic_and_neutral():
    from tools.rendering_tools import _category_glyph
    assert _category_glyph({"label": "Investors / Advisors"}) == "users"
    assert _category_glyph({"label": "Session Cache", "type": "cache"}) == "generic_database"
    assert _category_glyph({"label": "Payment Gateway"}) == "internet"
    assert _category_glyph({"label": "Some Unknowable Thing"}) == "generic_application"


# ---- 2. catalog aliases + generic-token guard ---------------------------- #

@pytest.mark.parametrize("label,expected", [
    ("AWS KMS", "key_management_service"),
    ("SQS FIFO Queue", "sqs"),
    ("SNS Topics", "sns"),
    ("S3 Bucket", "s3"),
    ("AWS WAF", "waf"),
    ("CloudWatch", "cloudwatch_2"),
    ("Application Load Balancer", "application_load_balancer"),
])
def test_catalog_alias_resolution(label, expected):
    cat = load_catalog()
    assert _resolve_node_icon(cat, {"label": label}, "aws") == expected


@pytest.mark.parametrize("label", [
    "Fund Management Service",   # would mis-rank to key_management_service
    "Transaction Service",
    "Payment Service",
])
def test_generic_token_guard_returns_none(label):
    cat = load_catalog()
    assert _resolve_node_icon(cat, {"label": label}, "aws") is None


def test_alias_expansion_serves_azure_gcp():
    cat = load_catalog()
    assert _resolve_node_icon(cat, {"label": "BigQuery"}, "gcp") == "gcp_bigquery"
    assert _resolve_node_icon(cat, {"label": "Pub/Sub"}, "gcp") == "gcp_pubsub"
    assert (_resolve_node_icon(cat, {"label": "Cosmos DB"}, "azure") or "").startswith("azure_")


def test_exact_token_bonus_prefers_earlier_token():
    cat = load_catalog()
    hits = search_icon(cat, "S3 Bucket", limit=2)
    assert hits[0]["name"] == "s3"  # not "bucket"


# ---- 3. remote image URL hard-fails validation --------------------------- #

def test_validator_errors_on_remote_image_url():
    import domain.validation.validate_drawio as vd
    xml = ('<mxfile><diagram name="p"><mxGraphModel><root>'
           '<mxCell id="0"/><mxCell id="1" parent="0"/>'
           '<mxCell id="c" vertex="1" parent="1" '
           'style="shape=image;image=https://icon2c.com/route53.svg;">'
           '<mxGeometry x="0" y="0" width="40" height="40" as="geometry"/></mxCell>'
           '</root></mxGraphModel></diagram></mxfile>')
    rep = vd.validate_xml(xml)
    assert any("Remote image URL" in e for e in rep["errors"])
    assert rep["ok"] is False


# ---- 4. refined edges are ROUTED (ports + not raw) ----------------------- #

def test_refined_edges_carry_router_ports():
    xml, _ = build_drawio_from_spec(_refined_min_spec(), "T")
    edges = [c for c in ET.fromstring(xml).iter("mxCell") if c.get("edge") == "1"]
    assert edges
    for e in edges:
        style = e.get("style") or ""
        assert "exitX=" in style and "entryX=" in style, style
        # class styling still appended after the routed base
        assert "endArrow=block" in style


def test_refined_label_boxes_do_not_overlap():
    """The post-routing label solver must never leave two labels overprinting."""
    spec = _refined_min_spec()
    spec["edges"].append({"from": "waf", "to": "fund",
                          "label": "Second parallel flow", "flow": "data"})
    xml, _ = build_drawio_from_spec(spec, "T")
    import domain.validation.validate_drawio as vd
    rep = vd.validate_xml(xml)
    assert (rep["layout_metrics"].get("edge_label_overlaps") or 0) == 0


# ---- 5. icon coverage counts refined __ic badges ------------------------- #

def test_icon_coverage_counts_root_parented_badges():
    uri = "data:image/png;base64," + base64.b64encode(_PNG).decode()
    spec = _refined_min_spec()
    for n in spec["nodes"]:
        n["icon_data_uri"] = uri
    xml, stats = build_drawio_from_spec(spec, "T")
    import domain.validation.validate_drawio as vd
    rep = vd.validate_xml(xml, stats=stats)
    assert rep["layout_metrics"].get("icon_coverage") == 1.0
    sc = vd.production_scorecard(rep, stats)
    assert sc["breakdown"]["iconography"] >= 8.0  # 6 coverage + structure pts
