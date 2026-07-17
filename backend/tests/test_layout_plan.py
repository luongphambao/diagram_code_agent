"""Layout analysis (layout_plan.analyze_layout) + deterministic auto-repair.

The plan must (1) recover the real flow order from a scrambled spec, (2) bundle
hub fan-out under the 40% suppression cap, (3) stay deterministic, and (4) be a
pure no-op when absent (plan=None renders byte-identically — the regression
guard that keeps every pre-plan test meaningful).
"""
from __future__ import annotations

import json

from prettygraph.native.layout_plan import analyze_layout
from prettygraph.native.repair import auto_repair, semantic_stats
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
    # 11 edges) — the group is skipped whole rather than partially bundled.
    plan = analyze_layout(_hub_spec())
    assert plan["edge_bundles"] == []
    assert plan["suppressed_edges"] == []


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
