"""Tests for domain.validation.semantic_gates — the spec-level I1-I4
invariants (see docs/improve/REVIEW-CODEBASE-FIT.md §1 for why these MUST run
on the render_spec, not the rendered .drawio).
"""

from __future__ import annotations

from semantic_gates import audit_spec_semantics


def _codes(findings):
    return {f.code for f in findings}


def test_finding_messages_never_look_like_dangling_edge_errors():
    """production_scorecard classifies an error as a structural "dangling
    edge" defect (zeroing relationship_correctness, a DIFFERENT scorecard
    dimension than what a blueprint-completeness gap should cost) via a
    keyword-substring check: `"edge " in message.lower()` (see
    validate_drawio.production_scorecard's `edge_struct_err`). None of our
    gate messages may contain that substring, or a plain I1/I2 finding gets
    silently mis-costed as if the renderer produced a broken connector."""
    spec = {
        "hosting": "on-prem",
        "nodes": [
            {"id": "a", "style": "shape=mxgraph.aws4.ec2;"},
            {"id": "b", "style": "shape=mxgraph.azure.function_apps;"},
            {"id": "orphan"},
        ],
        "edges": [{"from": "a", "to": "b", "label": "data"}],
    }
    findings = audit_spec_semantics(spec)
    assert findings, "fixture must actually produce findings for this test to mean anything"
    for f in findings:
        msg = f.message.lower()
        assert "edge " not in msg, (
            f"{f.code} message reads like a dangling-edge structural error: {f.message!r}"
        )
        assert "source " not in msg
        assert "target " not in msg


def test_orphan_component_is_hard_fail():
    spec = {
        "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}],
        "edges": [{"from": "a", "to": "b", "label": "reads from"}],
    }
    findings = audit_spec_semantics(spec)
    i1 = [f for f in findings if f.code == "I1"]
    assert i1 and i1[0].severity == "hard"
    assert i1[0].ids == ["c"]


def test_no_orphan_when_every_node_has_an_edge():
    spec = {
        "nodes": [{"id": "a"}, {"id": "b"}],
        "edges": [{"from": "a", "to": "b", "label": "calls via HTTPS"}],
    }
    findings = audit_spec_semantics(spec)
    assert "I1" not in _codes(findings)


def test_annotation_nodes_are_excluded_from_orphan_check():
    """A note/legend/kpi node isn't architecture — it shouldn't need an edge."""
    spec = {
        "nodes": [
            {"id": "a"},
            {"id": "b"},
            {"id": "note1", "kind": "note", "label": "Runtime responsibility"},
        ],
        "edges": [{"from": "a", "to": "b", "label": "calls via HTTPS"}],
    }
    findings = audit_spec_semantics(spec)
    assert "I1" not in _codes(findings)


def test_low_density_is_hard_fail():
    spec = {
        "nodes": [{"id": f"n{i}"} for i in range(5)],
        "edges": [{"from": "n0", "to": "n1", "label": "calls via HTTPS"}],
    }
    findings = audit_spec_semantics(spec)
    i2 = [f for f in findings if f.code == "I2"]
    assert i2 and i2[0].severity == "hard"


def test_healthy_density_passes():
    spec = {
        "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        "edges": [
            {"from": "a", "to": "b", "label": "calls via HTTPS"},
            {"from": "b", "to": "c", "label": "writes to"},
            {"from": "a", "to": "c", "label": "reads config from"},
        ],
    }
    findings = audit_spec_semantics(spec)
    assert "I2" not in _codes(findings)


def test_weak_and_empty_primary_labels_are_hard_fail():
    spec = {
        "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        "edges": [
            {"from": "a", "to": "b", "label": "data"},  # weak (exact generic word)
            {"from": "b", "to": "c", "label": ""},  # empty
        ],
    }
    findings = audit_spec_semantics(spec)
    i3 = [f for f in findings if f.code == "I3"]
    assert i3 and i3[0].severity == "hard"
    assert set(i3[0].ids) == {"a->b", "b->c"}


def test_real_labels_are_not_flagged():
    spec = {
        "nodes": [{"id": "a"}, {"id": "b"}],
        "edges": [{"from": "a", "to": "b", "label": "OIDC / JWT"}],
    }
    findings = audit_spec_semantics(spec)
    assert "I3" not in _codes(findings)


def test_monitoring_and_control_edges_are_exempt_from_label_check():
    """Side-channel classes (monitoring/control/future) are legitimately terse
    by convention — I3 should never fire on them."""
    spec = {
        "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        "edges": [
            {"from": "a", "to": "b", "label": "", "flow": "monitoring"},
            {"from": "b", "to": "c", "label": "", "flow": "control"},
        ],
    }
    findings = audit_spec_semantics(spec)
    assert "I3" not in _codes(findings)


def test_mixed_vendor_icon_families_is_hard_fail():
    spec = {
        "nodes": [
            {"id": "a", "style": "shape=mxgraph.aws4.lambda;"},
            {"id": "b", "style": "shape=mxgraph.azure.function_apps;"},
        ],
        "edges": [{"from": "a", "to": "b", "label": "invokes via HTTPS"}],
    }
    findings = audit_spec_semantics(spec)
    assert "I4" in _codes(findings)


def test_single_icon_family_passes():
    spec = {
        "nodes": [
            {"id": "a", "style": "shape=mxgraph.aws4.lambda;"},
            {"id": "b", "style": "shape=mxgraph.aws4.dynamodb;"},
        ],
        "edges": [{"from": "a", "to": "b", "label": "writes to via IAM role"}],
    }
    findings = audit_spec_semantics(spec)
    assert "I4" not in _codes(findings)


def test_aws_icons_on_onprem_hosting_is_hard_fail():
    spec = {
        "hosting": "on-prem",
        "nodes": [
            {"id": "a", "style": "shape=mxgraph.aws4.ec2;"},
            {"id": "b", "style": "shape=mxgraph.aws4.rds;"},
        ],
        "edges": [{"from": "a", "to": "b", "label": "TDS 1.4"}],
    }
    findings = audit_spec_semantics(spec)
    i4 = [f for f in findings if f.code == "I4"]
    assert i4
    assert any("credibility" in f.message.lower() for f in i4)


def test_waiver_suppresses_a_specific_finding():
    spec = {
        "nodes": [{"id": "a"}, {"id": "b"}, {"id": "orphan"}],
        "edges": [{"from": "a", "to": "b", "label": "calls via HTTPS"}],
        "waivers": [{"code": "I1", "ids": ["orphan"], "reason": "cross-cutting rail", "approved_by": "sa"}],
    }
    findings = audit_spec_semantics(spec)
    assert "I1" not in _codes(findings)


def test_waiver_is_specific_to_its_code_and_id():
    """A waiver for a different code/id must not suppress an unrelated finding."""
    spec = {
        "nodes": [{"id": "a"}, {"id": "b"}, {"id": "orphan"}],
        "edges": [{"from": "a", "to": "b", "label": "calls via HTTPS"}],
        "waivers": [{"code": "I1", "ids": ["someone-else"], "reason": "n/a", "approved_by": "sa"}],
    }
    findings = audit_spec_semantics(spec)
    assert "I1" in _codes(findings)


def test_bundling_does_not_create_false_orphans_or_density_findings():
    """Regression test for the core diagnosis-level bug in the external plan:
    layout_plan's edge bundling (_BUNDLE_EDGE_CAP) suppresses up to 40% of
    RENDERED edges for readability — a node whose every edge got folded into
    a bundle representative must still be gate-clean, because the BLUEPRINT
    (this function's only input) declared every relationship. Gating the
    rendered .drawio instead would send a correct blueprint back for "more
    edges" it already has.
    """
    from prettygraph.native.layout_plan import analyze_layout
    from prettygraph.native.topology import build_drawio_from_spec

    nodes = [{"id": "siem", "label": "SIEM", "cluster": "mon"}] + [
        {"id": f"x{i}", "label": f"Svc {i}", "cluster": "t1" if i < 3 else "t2"} for i in range(6)
    ]
    flow = [{"from": f"x{i}", "to": f"x{i + 1}", "label": f"hop {i} via HTTPS"} for i in range(5)]
    telemetry = [
        {"from": f"x{i}", "to": "siem", "label": "Telemetry export", "style": "dashed"} for i in range(6)
    ]
    spec = {
        "clusters": [
            {"id": "mon", "label": "Monitoring & Observability"},
            {"id": "t1", "label": "Tier 1"},
            {"id": "t2", "label": "Tier 2"},
        ],
        "nodes": nodes,
        "edges": flow + telemetry,
    }
    plan = analyze_layout(spec)
    assert plan.get("suppressed_edges"), (
        "fixture must actually exercise bundling for this test to mean anything"
    )
    xml, _ = build_drawio_from_spec(spec, "T", plan=plan)
    # siem's edges ARE suppressed in the rendered output...
    assert xml.count('value="Telemetry export"') < 6
    # ...but the gate (spec-level, plan-blind for I1/I2) sees every declared edge.
    findings = audit_spec_semantics(spec, plan)
    assert "I1" not in _codes(findings)
    assert "I2" not in _codes(findings)


def test_bundle_integrity_passes_when_every_suppressed_edge_is_registered():
    """I6: layout_plan's own bundles/suppressed lists are built from the same
    data (see _bundle_edges), so a real plan must always be gate-clean —
    this is the positive counterpart to the corruption test below."""
    from prettygraph.native.layout_plan import analyze_layout

    nodes = [{"id": "siem", "label": "SIEM", "cluster": "mon"}] + [
        {"id": f"x{i}", "label": f"Svc {i}", "cluster": "t1" if i < 3 else "t2"} for i in range(6)
    ]
    flow = [{"from": f"x{i}", "to": f"x{i + 1}", "label": f"hop {i} via HTTPS"} for i in range(5)]
    telemetry = [
        {"from": f"x{i}", "to": "siem", "label": "Telemetry export", "style": "dashed"} for i in range(6)
    ]
    spec = {
        "clusters": [
            {"id": "mon", "label": "Monitoring & Observability"},
            {"id": "t1", "label": "Tier 1"},
            {"id": "t2", "label": "Tier 2"},
        ],
        "nodes": nodes,
        "edges": flow + telemetry,
    }
    plan = analyze_layout(spec)
    assert plan.get("suppressed_edges")
    findings = audit_spec_semantics(spec, plan)
    assert "I6" not in _codes(findings)


def test_bundle_integrity_is_hard_fail_when_a_suppressed_edge_is_unregistered():
    """I6 has teeth: if a bundle's member list ever drifted out of sync with
    suppressed_edges (a future refactor bug), the gate must catch it instead
    of silently trusting the register."""
    spec = {
        "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        "edges": [
            {"from": "a", "to": "b", "label": "calls via HTTPS"},
            {"from": "a", "to": "c", "label": "calls via HTTPS"},
        ],
    }
    plan = {
        "edge_bundles": [{"kind": "hub", "rep": ["a", "b", "calls via HTTPS"], "members": []}],
        "suppressed_edges": [["a", "c", "calls via HTTPS"]],  # never listed in any bundle's members
    }
    findings = audit_spec_semantics(spec, plan)
    assert "I6" in _codes(findings)
