"""Compliance-pack eval judge (docx §4 P2, §13.2).

Deterministic L2 scorer over `compliance.compliance_findings`. A golden case provides a
small solution (components/work/evidence/risks) plus an active pack, and asserts which
controls SHOULD surface as gaps (missing/ungrounded) and which should NOT (grounded).
"""

from __future__ import annotations

from typing import Any

from domain.validation.solution_validator import AUTO_REPAIR_STRATEGIES, requires_human

_VALID_REPAIR = AUTO_REPAIR_STRATEGIES | {"request_evidence", "human_decision", "none"}


def _repair_contract_ok(findings: list[Any]) -> bool:
    for f in findings:
        if not str(f.finding_id).startswith("SF-"):
            return False
        if f.repair_strategy not in _VALID_REPAIR:
            return False
        if requires_human(f) and f.repair_strategy in AUTO_REPAIR_STRATEGIES:
            return False
        if f.repair_strategy in AUTO_REPAIR_STRATEGIES and f.requires_human_decision:
            return False
    return True


def score_compliance(findings: list[Any], golden: dict) -> dict:
    """`findings` is the list[SolutionFinding] (dimension='compliance')."""
    gap_ids = {eid for f in findings for eid in f.entity_ids}

    expected_gaps = golden.get("expected_gap_controls", [])
    if expected_gaps:
        hit = sum(1 for cid in expected_gaps if cid in gap_ids)
        gap_recall = round(hit / len(expected_gaps), 4)
    else:
        # Clean case: no control should be flagged as a gap.
        gap_recall = 1.0 if not gap_ids else 0.0

    expected_grounded = golden.get("expected_grounded_controls", [])
    if expected_grounded:
        ok = sum(1 for cid in expected_grounded if cid not in gap_ids)
        grounded_ok = round(ok / len(expected_grounded), 4)
    else:
        grounded_ok = 1.0

    # Every compliance finding must use the compliance dimension only.
    dims_ok = all(f.dimension == "compliance" for f in findings)

    return {
        "gap_recall": gap_recall,
        "grounded_ok": grounded_ok,
        "repair_contract_ok": 1.0 if _repair_contract_ok(findings) else 0.0,
        "dims_ok": 1.0 if dims_ok else 0.0,
        "n_findings": len(findings),
    }


METRIC_KEYS = [
    "scores.gap_recall",
    "scores.grounded_ok",
    "scores.repair_contract_ok",
    "scores.dims_ok",
]
