"""domain.diagram.template_library — harvesting an approved diagram into a
client-name-free learned template (§4.3 memory), and the loader that mixes
those learned templates in with the hand-authored repo ones.
"""

from __future__ import annotations

import json

import pytest

import backends
from domain.diagram import template_library as tl


_SPEC = {
    "provider": "aws",
    "style_preset": "refined",
    "layout_intent": "left_to_right_pipeline",
    "diagram_title": "Acme Corp Checkout Platform",  # must never survive harvesting
    "clusters": [
        {"id": "edge", "label": "Acme Edge Zone", "tier": "frontend", "accent": "blue", "number": 1},
        {"id": "app", "label": "Acme Core Services", "tier": "backend", "accent": "violet", "number": 2},
    ],
    "nodes": [
        {"id": "cdn", "label": "Acme Global CDN", "tech": "CloudFront", "cluster": "edge", "type": "cdn"},
        {"id": "api1", "label": "Checkout API", "tech": "API Gateway", "cluster": "app", "type": "gateway"},
        {"id": "svc1", "label": "Payments Service", "tech": "Lambda", "cluster": "app", "type": "service"},
        {"id": "svc2", "label": "Fraud Service", "tech": "Lambda", "cluster": "app", "type": "service"},
    ],
    "edges": [
        {"from": "cdn", "to": "api1", "label": "checkout request", "flow": "data"},
        {"from": "api1", "to": "svc1", "label": "process payment", "flow": "data"},
        {"from": "api1", "to": "svc2", "label": "fraud check", "flow": "control", "style": "dashed"},
    ],
}

_PLAN = {"schema": 1, "band_order": ["edge", "app"], "sidebar_roots": [], "target_ratio": 1.6}


def test_harvest_strips_every_client_specific_label():
    learned = tl.harvest_learned_template(_SPEC, _PLAN, 91.5)
    assert learned is not None
    dumped = json.dumps(learned)
    assert "Acme" not in dumped  # the whole point: no client name survives
    assert "Checkout" not in dumped
    assert "Fraud" not in dumped
    assert "Payments" not in dumped
    # Structural fields ARE kept.
    assert learned["provider"] == "aws"
    assert learned["style_preset"] == "refined"
    assert learned["plan"] == _PLAN
    assert learned["scorecard"] == 91.5
    assert learned["source"] == "learned"


def test_harvest_generic_node_labels_derive_from_type_not_free_text():
    learned = tl.harvest_learned_template(_SPEC, _PLAN, 91.5)
    labels_by_id = {n["id"]: n["label"] for n in learned["nodes"]}
    assert labels_by_id["cdn"] == "CDN"
    assert labels_by_id["api1"] == "Gateway"
    # Two "service"-type nodes -> disambiguated with a counter, still generic.
    assert {labels_by_id["svc1"], labels_by_id["svc2"]} == {"Service 1", "Service 2"}


def test_harvest_generic_cluster_labels_come_from_tier_not_free_text():
    learned = tl.harvest_learned_template(_SPEC, _PLAN, 91.5)
    labels_by_id = {c["id"]: c["label"] for c in learned["clusters"]}
    assert labels_by_id["edge"] == "Frontend"
    assert labels_by_id["app"] == "Backend"


def test_harvest_edge_labels_come_from_flow_class():
    learned = tl.harvest_learned_template(_SPEC, _PLAN, 91.5)
    edge_labels = {(e["from"], e["to"]): e["label"] for e in learned["edges"]}
    assert edge_labels[("cdn", "api1")] == "Data"
    assert edge_labels[("api1", "svc2")] == "Control"


def test_harvest_drops_diagram_title_and_returns_none_without_nodes():
    learned = tl.harvest_learned_template(_SPEC, _PLAN, 91.5)
    assert "diagram_title" not in learned
    assert "subtitle" not in learned
    assert tl.harvest_learned_template({"nodes": []}, None, 90.0) is None


def test_harvest_refuses_to_guess_an_unmappable_node_type():
    """An unmappable type is a reason to walk away, not a reason to guess —
    the WHOLE diagram is skipped, not just that one node."""
    spec = json.loads(json.dumps(_SPEC))  # deep copy
    spec["nodes"][0]["type"] = "acme_proprietary_widget"
    assert tl.harvest_learned_template(spec, _PLAN, 91.5) is None


def test_harvest_is_deterministic_and_content_derived_name():
    a = tl.harvest_learned_template(_SPEC, _PLAN, 91.5)
    b = tl.harvest_learned_template(_SPEC, _PLAN, 91.5)
    assert a["_meta"]["name"] == b["_meta"]["name"]  # no timestamp/random suffix


@pytest.fixture()
def _isolated_outputs_dir(tmp_path, monkeypatch):
    """template_library._load_learned() resolves OUTPUTS_DIR via a DEFERRED
    `from backends import OUTPUTS_DIR` (re-read every call), so patching the
    backends module attribute is enough to redirect it — unlike
    tools/stage_markers.py, which binds OUTPUTS_DIR at import time (see that
    module's own tests/fixtures if this ever needs to cover the write side too)."""
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    monkeypatch.setattr(backends, "OUTPUTS_DIR", outputs)
    tl._load_all.cache_clear()
    yield outputs
    tl._load_all.cache_clear()


def _write_learned(outputs_dir, folder, scorecard, name=None):
    d = outputs_dir / folder
    d.mkdir()
    tpl = tl.harvest_learned_template(_SPEC, _PLAN, scorecard)
    if name:
        tpl["_meta"]["name"] = name
    (d / "template.json").write_text(json.dumps(tpl), encoding="utf-8")


def test_load_all_mixes_in_learned_templates(_isolated_outputs_dir):
    _write_learned(_isolated_outputs_dir, "20260101_000000", 88.0)
    names = {t["_meta"]["name"] for t in tl._load_all()}
    assert any(n.startswith("learned_aws_") for n in names)


def test_load_learned_caps_and_ranks_by_scorecard(_isolated_outputs_dir, monkeypatch):
    monkeypatch.setattr(tl, "_MAX_LEARNED_TEMPLATES", 2)
    _write_learned(_isolated_outputs_dir, "a", 70.0, name="low")
    _write_learned(_isolated_outputs_dir, "b", 95.0, name="high")
    _write_learned(_isolated_outputs_dir, "c", 85.0, name="mid")
    learned = tl._load_learned()
    assert len(learned) == 2
    assert [t["_meta"]["name"] for t in learned] == ["high", "mid"]  # low (70.0) dropped by the cap


def test_find_template_breaks_ties_toward_higher_scorecard(_isolated_outputs_dir):
    _write_learned(_isolated_outputs_dir, "a", 70.0, name="low_score_variant")
    _write_learned(_isolated_outputs_dir, "b", 99.0, name="high_score_variant")
    # Both templates share identical topology/tags, so token-overlap score
    # against this query ties -> the scorecard tiebreak must decide the order.
    hits = tl.find_template("aws refined checkout gateway service cdn", limit=2)
    names = [h["_meta"]["name"] for h in hits]
    assert names.index("high_score_variant") < names.index("low_score_variant")
