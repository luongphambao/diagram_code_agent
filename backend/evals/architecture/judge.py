"""Architecture/validator eval judge (docx §4.4, §4.5 "Architecture" suite).

Deterministic L2 scorer built directly on `solution_validator.evaluate_solution`.
A golden case seeds a defect (dangling edge, orphan WBS task, unmapped requirement,
missing decisions, zero effort) and asserts the matching validator finding fires;
clean cases assert no blocking finding is raised. This makes the validator
self-testing on realistic inputs, beyond the unit tests.
"""

from __future__ import annotations

from typing import Any

from solution_validator import (
    AUTO_REPAIR_STRATEGIES,
    is_blocking,
    requires_human,
)

# Every finding must carry a real repair contract (docx §4.3): a stable id and a
# repair_strategy that routes to the right owner.
_VALID_REPAIR = AUTO_REPAIR_STRATEGIES | {"request_evidence", "human_decision", "none"}


def _repair_contract_ok(findings: list[Any]) -> bool:
    """True when every finding has a stable SF- id and a coherent repair_strategy.

    A human-routed finding (requires_human) must NOT claim a mechanical patch_* strategy,
    and an auto-repair strategy must NOT be flagged as needing a human — otherwise the
    gate's 3-outcome routing (pass / auto-repair / human-decision) is inconsistent.
    """
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


def score_architecture(findings: list[Any], golden: dict) -> dict:
    """`findings` is the list[SolutionFinding] from evaluate_solution."""
    dims_present = {f.dimension for f in findings}
    expected = golden.get("expected_dimensions", [])

    # Recall over the dimensions the seeded case should surface.
    if expected:
        hit = sum(1 for d in expected if d in dims_present)
        finding_recall = round(hit / len(expected), 4)
    else:
        finding_recall = 1.0

    has_block = any(is_blocking(f) for f in findings)
    # Clean cases must not raise a blocking finding; defect cases should match expect_block.
    if golden.get("expect_clean"):
        block_ok = not has_block
    else:
        block_ok = (has_block == golden.get("expect_block", has_block))

    return {
        "finding_recall": finding_recall,
        "block_ok": 1.0 if block_ok else 0.0,
        "repair_contract_ok": 1.0 if _repair_contract_ok(findings) else 0.0,
        "n_findings": len(findings),
        "dimensions": sorted(dims_present),
    }


METRIC_KEYS = ["scores.finding_recall", "scores.block_ok", "scores.repair_contract_ok"]
