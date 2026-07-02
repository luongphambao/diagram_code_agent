"""Tests for the cross-artifact validator + traceability sidecar (Slice 1)."""

import json

from solution_validator import (
    evaluate_solution,
    validate_solution,
    format_validation,
    coverage_ratio,
    is_blocking,
)
from traceability import build_trace_links, write_trace_links


# --- representative broken workspace ----------------------------------------

BRIEF = {
    "functional_requirements": [
        "OCR Service extracts text from uploaded documents",
        "Provide real-time fraud scoring",
    ],
    "non_functional_requirements": ["99.9% availability"],
}
BLUEPRINT = {
    "nodes": [
        {"id": "api_gw", "label": "API Gateway", "cluster": "edge"},
        {"id": "ocr_svc", "label": "OCR Service", "cluster": "ghost"},  # cluster missing
    ],
    "clusters": [{"id": "edge", "label": "Edge"}],
    "edges": [{"from": "api_gw", "to": "nowhere"}],  # dangling
    "key_decisions": [],  # none
}
WBS = {
    "items": [
        {"id": "1.1", "name": "OCR Service implementation"},
        {"id": "9.9", "name": "Internal tooling spike"},  # orphan
    ],
    "effort_totals": {"total_mandays": 0},  # zero effort
}


def test_evaluate_flags_every_seeded_defect():
    findings = evaluate_solution(BRIEF, BLUEPRINT, WBS)
    dims = {f.dimension for f in findings}
    # dangling edge + zero effort are correctness/completeness; coverage + traceability present
    assert {"correctness", "completeness", "coverage", "traceability"} <= dims

    titles = " || ".join(f.title for f in findings).lower()
    assert "missing component" in titles          # dangling edge
    assert "zero total effort" in titles          # rollup not run
    assert "missing cluster" in titles            # ghost cluster
    assert "no recorded key decisions" in titles  # empty decisions
    assert "traces to no requirement" in titles   # orphan WBS task


def test_high_severity_blocks_release():
    findings = evaluate_solution(BRIEF, BLUEPRINT, WBS)
    assert any(is_blocking(f) for f in findings)
    assert format_validation(findings, block=True).startswith("VALIDATION: BLOCK")
    # block=False does not hard-block, but HUMAN-DECISION tier fires before WARN
    result = format_validation(findings, block=False)
    assert result.startswith(("VALIDATION: WARN", "VALIDATION: HUMAN-DECISION", "VALIDATION: AUTO-REPAIR"))


def test_clean_workspace_passes():
    brief = {"functional_requirements": ["API Gateway routes requests"]}
    blueprint = {
        "nodes": [{"id": "api_gw", "label": "API Gateway", "cluster": "edge"}],
        "clusters": [{"id": "edge", "label": "Edge"}],
        "edges": [],
        "key_decisions": ["Use a managed API gateway for routing and auth."],
    }
    wbs = {"items": [{"id": "1.1", "name": "API Gateway setup"}],
           "effort_totals": {"total_mandays": 12}}
    findings = evaluate_solution(brief, blueprint, wbs)
    assert findings == []
    assert format_validation(findings) == "VALIDATION: PASS (no cross-artifact contradictions found)"


def test_coverage_ratio_reflects_unmapped():
    findings = evaluate_solution(BRIEF, BLUEPRINT, WBS)
    # 3 requirements, at least the two non-OCR ones are unmapped -> ratio < 1
    assert coverage_ratio(findings, total_requirements=3) < 1.0


def test_validate_solution_reads_workspace(tmp_path):
    (tmp_path / "diagram_brief.json").write_text(json.dumps(BRIEF))
    (tmp_path / "blueprint.json").write_text(json.dumps(BLUEPRINT))
    (tmp_path / "wbs.json").write_text(json.dumps(WBS))
    findings, summary = validate_solution(tmp_path, block=True)
    assert findings
    assert summary.startswith("VALIDATION: BLOCK")


def test_evaluate_solution_model_none_backcompat():
    """The pure path (no model) keeps the original titles and empty semantic ids."""
    findings = evaluate_solution(BRIEF, BLUEPRINT, WBS, model=None)
    unmapped = [f for f in findings if f.dimension == "coverage"]
    assert unmapped and all(f.entity_ids == [] for f in unmapped)


def test_validate_solution_uses_csm_ids(tmp_path):
    (tmp_path / "diagram_brief.json").write_text(json.dumps(BRIEF))
    (tmp_path / "blueprint.json").write_text(json.dumps(BLUEPRINT))
    (tmp_path / "wbs.json").write_text(json.dumps(WBS))
    findings, _ = validate_solution(tmp_path)
    # building the CSM is a side effect of validate_solution
    assert (tmp_path / "solution_model.json").exists()
    ids = {i for f in findings for i in f.entity_ids}
    assert any(i.startswith("REQ-") for i in ids)   # unmapped requirement anchored
    assert any(i.startswith("WBS-") for i in ids)   # orphan WBS anchored


def test_write_trace_links_projects_csm(tmp_path):
    """The core 1.3 goal: ids in trace_links.json all exist in solution_model.json."""
    (tmp_path / "diagram_brief.json").write_text(json.dumps(BRIEF))
    (tmp_path / "blueprint.json").write_text(json.dumps(BLUEPRINT))
    (tmp_path / "wbs.json").write_text(json.dumps(WBS))
    graph = write_trace_links(tmp_path)

    model = json.loads((tmp_path / "solution_model.json").read_text(encoding="utf-8"))
    model_ids = {
        e["id"]
        for group in ("requirements", "constraints", "assumptions", "decisions",
                      "components", "risks", "work_items")
        for e in model.get(group, [])
    }
    endpoints = {l["from"] for l in graph["links"]} | {l["to"] for l in graph["links"]}
    assert endpoints, "expected at least one trace link"
    assert endpoints <= model_ids


def test_write_trace_links_fallback(tmp_path, monkeypatch):
    """If the CSM can't be built, the legacy artifact path still emits the file."""
    import csm_adapter

    def _boom(*_a, **_k):
        raise RuntimeError("CSM unavailable")

    monkeypatch.setattr(csm_adapter, "build_solution_model", _boom)
    (tmp_path / "diagram_brief.json").write_text(json.dumps(BRIEF))
    (tmp_path / "blueprint.json").write_text(json.dumps(BLUEPRINT))
    (tmp_path / "wbs.json").write_text(json.dumps(WBS))
    graph = write_trace_links(tmp_path)
    assert (tmp_path / "trace_links.json").exists()
    assert graph["links"]


# --- traceability sidecar ----------------------------------------------------

def test_trace_links_connect_req_to_component_and_wbs():
    graph = build_trace_links(BRIEF, BLUEPRINT, WBS)
    relations = {(l["from"], l["relation"], l["to"]) for l in graph["links"]}
    # the OCR requirement is satisfied by the OCR Service component
    assert any(r == "satisfies" and "COMP-ocr_svc" == t for (_f, r, t) in relations)
    # the OCR WBS task implements the OCR component
    assert any(f.startswith("WBS-") and r == "implements" for (f, r, _t) in relations)
    assert graph["coverage"]["requirements_total"] == 3


def test_write_trace_links_emits_file(tmp_path):
    (tmp_path / "diagram_brief.json").write_text(json.dumps(BRIEF))
    (tmp_path / "blueprint.json").write_text(json.dumps(BLUEPRINT))
    (tmp_path / "wbs.json").write_text(json.dumps(WBS))
    graph = write_trace_links(tmp_path)
    assert (tmp_path / "trace_links.json").exists()
    assert graph["links"]


# ─── Rule 10: Feasibility (resource leveling overload) ───────────────────────

_CLEAN_BRIEF = {"functional_requirements": ["Build core platform"]}
_CLEAN_BLUEPRINT = {
    "nodes": [{"id": "api", "label": "API Service", "cluster": "app"}],
    "clusters": [{"id": "app", "label": "Application"}],
    "edges": [],
    "key_decisions": ["Use REST API"],
}


def test_feasibility_finding_when_overloads_present():
    wbs_overloaded = {
        "items": [{"id": "1.1", "name": "API implementation", "be": 30, "total": 30,
                   "assigned_sprint": 1}],
        "effort_totals": {"total_mandays": 30},
        "resource_leveling": {
            "overloads": [
                {"sprint": 1, "role": "dev", "demand_md": 30.0,
                 "capacity_md": 10.0, "overflow_md": 20.0}
            ]
        },
    }
    findings = evaluate_solution(_CLEAN_BRIEF, _CLEAN_BLUEPRINT, wbs_overloaded)
    feas = [f for f in findings if f.dimension == "feasibility"]
    assert feas, "Rule 10 should fire when resource_leveling.overloads is non-empty"
    assert feas[0].severity == "high"
    assert feas[0].requires_human_decision is True
    assert feas[0].repair_strategy == "human_decision"
    assert is_blocking(feas[0])


def test_feasibility_no_finding_when_overloads_empty():
    wbs_balanced = {
        "items": [{"id": "1.1", "name": "API implementation", "be": 5, "total": 5}],
        "effort_totals": {"total_mandays": 5},
        "resource_leveling": {"overloads": []},
    }
    findings = evaluate_solution(_CLEAN_BRIEF, _CLEAN_BLUEPRINT, wbs_balanced)
    assert not any(f.dimension == "feasibility" for f in findings)


def test_feasibility_no_finding_when_no_resource_leveling_key():
    """Old eval format without resource_leveling key must not regress."""
    wbs_old = {
        "items": [{"id": "1.1", "name": "API implementation", "be": 5, "total": 5}],
        "effort_totals": {"total_mandays": 5},
    }
    findings = evaluate_solution(_CLEAN_BRIEF, _CLEAN_BLUEPRINT, wbs_old)
    assert not any(f.dimension == "feasibility" for f in findings)


def test_feasibility_detail_names_worst_sprint():
    wbs_overloaded = {
        "items": [],
        "effort_totals": {"total_mandays": 0},
        "resource_leveling": {
            "overloads": [
                {"sprint": 2, "role": "dev", "demand_md": 25.0, "capacity_md": 10.0, "overflow_md": 15.0},
                {"sprint": 3, "role": "ba", "demand_md": 12.0, "capacity_md": 5.0, "overflow_md": 7.0},
            ]
        },
    }
    findings = evaluate_solution(_CLEAN_BRIEF, _CLEAN_BLUEPRINT, wbs_overloaded)
    feas = [f for f in findings if f.dimension == "feasibility"]
    assert feas
    assert "sprint 2" in feas[0].detail.lower() or "2" in feas[0].detail
    # title/entity_ids must stay stable across re-runs (which sprints are overloaded
    # is a detail, not identity) so waive_finding's status survives; see finding_store.py.
    assert feas[0].title == "Schedule not deliverable: sprint(s) overloaded"
    assert feas[0].entity_ids == []


def test_feasibility_finding_id_stable_when_overload_set_shrinks():
    """Waiving must survive a gate re-run where a partial fix drops one overload.

    Regression for a bug where the overload count lived in the finding's title,
    so finding_id (a hash of dimension/entity_ids/title) changed on every re-run
    with a different overload count, silently discarding a waived/resolved status
    (docx §4.3) and re-blocking the release gate forever.
    """
    def _feas_finding(overloads):
        wbs = {
            "items": [],
            "effort_totals": {"total_mandays": 0},
            "resource_leveling": {"overloads": overloads},
        }
        findings = evaluate_solution(_CLEAN_BRIEF, _CLEAN_BLUEPRINT, wbs)
        return next(f for f in findings if f.dimension == "feasibility")

    before = _feas_finding([
        {"sprint": 2, "role": "dev", "demand_md": 25.0, "capacity_md": 10.0, "overflow_md": 15.0},
        {"sprint": 3, "role": "ba", "demand_md": 12.0, "capacity_md": 5.0, "overflow_md": 7.0},
    ])
    after = _feas_finding([
        {"sprint": 2, "role": "dev", "demand_md": 20.0, "capacity_md": 10.0, "overflow_md": 10.0},
    ])
    assert before.finding_id == after.finding_id
