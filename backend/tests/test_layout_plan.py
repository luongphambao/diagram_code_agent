"""Layout analysis (layout_plan.analyze_layout) + deterministic auto-repair.

The plan must (1) recover the real flow order from a scrambled spec, (2) bundle
hub fan-out under the 40% suppression cap, (3) stay deterministic, and (4) be a
pure no-op when absent (plan=None renders byte-identically — the regression
guard that keeps every pre-plan test meaningful).
"""
from __future__ import annotations

import json
from pathlib import Path

from prettygraph.native.layout_plan import analyze_layout
from prettygraph.native.repair import auto_repair, semantic_stats, _variants_for
from prettygraph.native.topology import build_drawio_from_spec


def _chain_spec():
    """Real flow c -> a -> d -> b, declared in scrambled order a,b,c,d."""
    return {
        "provider": "gcp",
        "clusters": [{"id": x, "label": f"Tier {x.upper()}"} for x in "abcd"],
        "nodes": [{"id": f"n{x}{i}", "label": f"Node {x}{i}", "cluster": x}
                  for x in "abcd" for i in range(2)],
        "edges": ([{"from": "nc0", "to": "na0", "label": "ingest"}] * 3
                  + [{"from": "na0", "to": "nd0", "label": "process"}] * 3
                  + [{"from": "nd1", "to": "nb0", "label": "serve"}] * 3),
    }


def _hub_spec():
    """A monitoring hub collecting the same dashed edge from 6 nodes across 2
    tiers, plus enough real flow edges that the 40% cap has headroom."""
    nodes = ([{"id": "siem", "label": "SIEM", "cluster": "mon"}]
             + [{"id": f"x{i}", "label": f"Svc {i}",
                 "cluster": "t1" if i < 3 else "t2"} for i in range(6)])
    flow = [{"from": f"x{i}", "to": f"x{i + 1}", "label": f"step {i}"}
            for i in range(5)]
    telemetry = [{"from": f"x{i}", "to": "siem", "label": "Telemetry",
                  "style": "dashed"} for i in range(6)]
    return {
        "clusters": [{"id": "mon", "label": "Monitoring & Observability"},
                     {"id": "t1", "label": "Tier 1"},
                     {"id": "t2", "label": "Tier 2"}],
        "nodes": nodes,
        "edges": flow + telemetry,  # 11 edges -> cap = 4 suppressible
    }


def test_band_order_recovers_flow_from_scrambled_spec():
    plan = analyze_layout(_chain_spec())
    assert plan["band_order"] == ["c", "a", "d", "b"]


def test_analyze_layout_is_deterministic():
    a = analyze_layout(_chain_spec())
    b = analyze_layout(_chain_spec())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_hub_fanout_respects_suppression_cap():
    # 6 telemetry edges would need drop=5, but only 4 may be suppressed (40% of
    # 11 edges) — the HUB group is skipped whole rather than partially bundled.
    # The zone-pair pass may still fully collapse each per-tier channel
    # (3 t1->mon + 3 t2->mon), which fits the cap exactly (2+2 dropped).
    plan = analyze_layout(_hub_spec())
    assert all(b["kind"] == "pair" for b in plan["edge_bundles"])
    assert len(plan["suppressed_edges"]) <= 4  # the cap still binds
    # every pair bundle collapses its whole channel — no half-bundled pairs
    for b in plan["edge_bundles"]:
        assert len(b["members"]) == 2  # 3 edges per tier -> 1 rep + 2 members


def test_hub_fanout_bundles_when_cap_allows():
    spec = _hub_spec()
    # Pad with more real flow edges so the cap (40%) can absorb drop=5.
    spec["edges"] += [{"from": "x0", "to": f"x{i}", "label": f"call {i}"}
                      for i in range(2, 6)]  # 15 edges -> cap = 6
    plan = analyze_layout(spec)
    assert len(plan["edge_bundles"]) == 1
    assert len(plan["suppressed_edges"]) == 5  # 6 telemetry -> 1 rep + 5 dropped
    rep = plan["edge_bundles"][0]["rep"]
    assert rep[2] == "Telemetry"
    # Monitoring cluster is cross-cutting -> sidebar, never a main band.
    assert "mon" in plan["sidebar_roots"]
    assert "mon" not in plan["band_order"]


def test_suppressed_edges_are_skipped_and_rep_labeled():
    spec = _hub_spec()
    spec["edges"] += [{"from": "x0", "to": f"x{i}", "label": f"call {i}"}
                      for i in range(2, 6)]
    plan = analyze_layout(spec)
    xml, _ = build_drawio_from_spec(spec, "T", plan=plan)
    assert xml.count('value="Telemetry (all layers)"') == 1
    # 5 suppressed members are gone; only the representative remains.
    assert xml.count('value="Telemetry"') == 0


def test_semantic_stats_counts_bundled_edges_as_preserved():
    spec = _hub_spec()
    spec["edges"] += [{"from": "x0", "to": f"x{i}", "label": f"call {i}"}
                      for i in range(2, 6)]
    plan = analyze_layout(spec)
    xml, _ = build_drawio_from_spec(spec, "T", plan=plan)
    sem = semantic_stats(spec, xml, plan)
    assert sem["edge_recall"] == 1.0
    assert sem["node_recall"] == 1.0
    assert sem["bundled_edges"] == 5

def test_refined_support_edges_bundle_across_support_zones():
    spec = {
        "style_preset": "refined",
        "clusters": [
            {"id": "integration", "label": "Secure Integration Zone"},
            {"id": "workflow", "label": "LC Control Workflow"},
            {"id": "data", "label": "Transaction & Evidence Data", "tier": "data"},
            {"id": "controls", "label": "Security & Governance"},
            {"id": "operations", "label": "Platform & Operations"},
        ],
        "nodes": [
            {"id": "gw", "label": "Integration Gateway", "cluster": "integration"},
            {"id": "event_backbone", "label": "Event Backbone", "cluster": "integration"},
            {"id": "case_api", "label": "Case API", "cluster": "workflow"},
            {"id": "workflow_engine", "label": "Workflow Engine", "cluster": "workflow"},
            {"id": "audit_service", "label": "Audit Ledger", "cluster": "data"},
            {"id": "enterprise_iam", "label": "Enterprise IAM", "cluster": "controls"},
            {"id": "policy_engine", "label": "Policy Engine", "cluster": "controls"},
            {"id": "secrets_hsm", "label": "Secrets & HSM", "cluster": "controls"},
            {"id": "observability", "label": "Observability", "cluster": "operations"},
        ],
        "edges": [
            {"from": "enterprise_iam", "to": "case_api", "label": "identity claims", "flow": "security"},
            {"from": "policy_engine", "to": "workflow_engine", "label": "authorization gate", "flow": "security"},
            {"from": "secrets_hsm", "to": "gw", "label": "keys / secrets", "flow": "security"},
            {"from": "workflow_engine", "to": "audit_service", "label": "decision event", "flow": "monitoring"},
            {"from": "case_api", "to": "audit_service", "label": "user action", "flow": "monitoring"},
            {"from": "observability", "to": "workflow_engine", "label": "metrics / traces", "flow": "monitoring"},
            {"from": "observability", "to": "event_backbone", "label": "health telemetry", "flow": "monitoring"},
            {"from": "gw", "to": "event_backbone", "label": "durable events", "flow": "data"},
            {"from": "event_backbone", "to": "case_api", "label": "case event", "flow": "data"},
            {"from": "case_api", "to": "workflow_engine", "label": "review action", "flow": "control"},
            {"from": "workflow_engine", "to": "case_api", "label": "case update", "flow": "control"},
            {"from": "gw", "to": "case_api", "label": "query", "flow": "serving"},
            {"from": "event_backbone", "to": "workflow_engine", "label": "workflow event", "flow": "data"},
        ],
    }
    plan = analyze_layout(spec)
    suppressed = {tuple(x) for x in plan["suppressed_edges"]}
    assert ("enterprise_iam", "case_api", "identity claims") in suppressed
    assert ("case_api", "audit_service", "user action") in suppressed
    assert ("observability", "event_backbone", "health telemetry") in suppressed
    assert any(b["rep"][2] == "authorization gate" for b in plan["edge_bundles"])

def _dense_inner_zone_spec() -> dict:
    return {
        "provider": "gcp",
        "style_preset": "refined",
        "clusters": [
            {"id": "cloud", "label": "Google Cloud", "zone": "cloud"},
            {"id": "ingest", "label": "Ingestion", "parent": "cloud"},
            {"id": "app", "label": "Application Services", "parent": "cloud"},
            {"id": "data", "label": "Data Services", "parent": "cloud"},
        ],
        "nodes": [
            {"id": "in1", "label": "Input A", "cluster": "ingest"},
            {"id": "in2", "label": "Input B", "cluster": "ingest"},
            {"id": "api", "label": "API", "cluster": "app"},
            {"id": "worker", "label": "Worker", "cluster": "app"},
            {"id": "db", "label": "Database", "cluster": "data"},
            {"id": "audit", "label": "Audit Store", "cluster": "data"},
        ],
        "edges": [
            {"from": "in1", "to": "api", "label": "event", "flow": "data"},
            {"from": "in2", "to": "worker", "label": "event", "flow": "data"},
            {"from": "api", "to": "db", "label": "write", "flow": "data"},
            {"from": "worker", "to": "audit", "label": "append", "flow": "registry"},
            {"from": "api", "to": "audit", "label": "audit", "flow": "registry"},
            {"from": "worker", "to": "db", "label": "update", "flow": "data"},
        ],
    }

def test_aggressive_bundling_collapses_inner_zone_pairs_and_preserves_semantics():
    spec = _dense_inner_zone_spec()
    default_plan = analyze_layout(spec)
    aggressive = analyze_layout(spec, aggressive_bundles=True)
    assert len(aggressive["suppressed_edges"]) > len(default_plan["suppressed_edges"])
    assert aggressive["aggressive_bundles"] is True
    xml, _ = build_drawio_from_spec(spec, "Dense", plan=aggressive)
    sem = semantic_stats(spec, xml, aggressive)
    assert sem["node_recall"] == 1.0
    assert sem["edge_recall"] == 1.0
    assert sem["bundled_edges"] == len(aggressive["suppressed_edges"])

def test_auto_repair_variants_include_aggressive_only_for_poor_arrows():
    spec = _dense_inner_zone_spec()
    plan = analyze_layout(spec)
    bad = {"arrow_clarity": {"arrow_clarity_score": 60.0,
                             "crossings_per_edge": 0.8,
                             "long_edge_ratio": 0.2,
                             "edge_label_overlaps": 0}}
    labels = [label for label, _ in _variants_for(plan, spec, bad)]
    assert "aggressive-bundles" in labels
    good = {"arrow_clarity": {"arrow_clarity_score": 95.0,
                              "crossings_per_edge": 0.0,
                              "long_edge_ratio": 0.0,
                              "edge_label_overlaps": 0}}
    assert "aggressive-bundles" not in [label for label, _ in _variants_for(plan, spec, good)]

def test_current_arrow_regression_gets_more_aggressive_bundling():
    path = Path(__file__).resolve().parents[2] / "artifacts/thread-mrsw4q6c-fnwhr/render_spec.json"
    if not path.exists():
        return
    from domain.validation.validate_drawio import validate_xml, production_scorecard
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec["style_preset"] = "refined"
    default_plan = analyze_layout(spec)
    aggressive = analyze_layout(spec, aggressive_bundles=True)
    default_visible = len(spec["edges"]) - len(default_plan["suppressed_edges"])
    aggressive_visible = len(spec["edges"]) - len(aggressive["suppressed_edges"])
    assert len(default_plan["suppressed_edges"]) == 3
    assert len(aggressive["suppressed_edges"]) >= 27
    assert aggressive_visible <= 18
    assert aggressive_visible < default_visible

    default_xml, default_stats = build_drawio_from_spec(spec, "Regression", plan=default_plan)
    default_stats["semantic"] = semantic_stats(spec, default_xml, default_plan)
    default_report = validate_xml(default_xml, stats=default_stats)
    default_score = production_scorecard(default_report, default_stats)

    aggressive_xml, aggressive_stats = build_drawio_from_spec(spec, "Regression", plan=aggressive)
    aggressive_stats["semantic"] = semantic_stats(spec, aggressive_xml, aggressive)
    aggressive_report = validate_xml(aggressive_xml, stats=aggressive_stats)
    aggressive_score = production_scorecard(aggressive_report, aggressive_stats)

    assert aggressive_stats["semantic"]["node_recall"] == 1.0
    assert aggressive_stats["semantic"]["edge_recall"] == 1.0
    assert aggressive_stats["semantic"]["bundled_edges"] == len(aggressive["suppressed_edges"])
    assert aggressive_score["breakdown"]["connector_readability"] > (
        default_score["breakdown"]["connector_readability"]
    )


def test_plan_none_is_byte_identical():
    spec = _chain_spec()
    xml_a, _ = build_drawio_from_spec(spec, "T")
    xml_b, _ = build_drawio_from_spec(spec, "T", plan=None)
    assert xml_a == xml_b


def test_auto_repair_never_worse_than_baseline():
    spec = _chain_spec()
    plan = analyze_layout(spec)
    best_plan, report = auto_repair(spec, "T", plan)
    scores = [it["score"] for it in report["iterations"] if "score" in it]
    assert scores, "auto_repair produced no scored candidates"
    assert report["final_score"] == max(scores)


def test_auto_repair_skips_variants_when_baseline_passes():
    # A tiny clean spec should PASS at baseline -> exactly one iteration.
    spec = {
        "provider": "aws",
        "clusters": [{"id": "a", "label": "App"}],
        "nodes": [{"id": "n1", "label": "API", "cluster": "a"},
                  {"id": "n2", "label": "Web", "cluster": "a"}],
        "edges": [{"from": "n2", "to": "n1", "label": "REST"}],
    }
    _, report = auto_repair(spec, "T", analyze_layout(spec))
    if report["iterations"][0].get("pass"):
        assert len(report["iterations"]) == 1
