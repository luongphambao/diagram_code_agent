"""Diagram quality eval judge (docx §4.7 "DiagramQuality" suite).

Deterministic L2 scorer built on `validate_drawio.validate_file` +
`findings_from_validation`. A golden case seeds a known drawio defect
(dangling edge, duplicate id, node overlap, wrong stencil, AWS hierarchy
advice) and asserts the matching dimension fires with a coherent repair
contract. Clean cases assert no findings are raised.
"""

from __future__ import annotations

from typing import Any

from solution_validator import AUTO_REPAIR_STRATEGIES


_VALID_REPAIR = AUTO_REPAIR_STRATEGIES | {"request_evidence", "human_decision", "none"}


def _repair_contract_ok(findings: list[Any]) -> bool:
    """Every finding must have a stable SF- id and a valid repair_strategy."""
    for f in findings:
        if not str(f.finding_id).startswith("SF-"):
            return False
        if f.repair_strategy not in _VALID_REPAIR:
            return False
    return True


def score_diagram_quality(findings: list[Any], case: dict) -> dict:
    """`findings` is the list[SolutionFinding] from findings_from_validation."""
    dims_present = {f.dimension for f in findings}
    expected = case.get("expected_dimensions", [])

    if expected:
        hit = sum(1 for d in expected if d in dims_present)
        finding_recall = round(hit / len(expected), 4)
    else:
        # Clean case: no findings expected
        finding_recall = 1.0 if not findings else 0.0

    return {
        "finding_recall": finding_recall,
        "repair_contract_ok": 1.0 if _repair_contract_ok(findings) else 0.0,
        "n_findings": len(findings),
        "dimensions": sorted(dims_present),
    }


METRIC_KEYS = ["scores.finding_recall", "scores.repair_contract_ok"]
