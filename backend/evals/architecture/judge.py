"""Architecture/validator eval judge (docx §4.4, §4.5 "Architecture" suite).

Deterministic L2 scorer built directly on `solution_validator.evaluate_solution`.
A golden case seeds a defect (dangling edge, orphan WBS task, unmapped requirement,
missing decisions, zero effort) and asserts the matching validator finding fires;
clean cases assert no blocking finding is raised. This makes the validator
self-testing on realistic inputs, beyond the unit tests.
"""

from __future__ import annotations

from typing import Any

from solution_validator import is_blocking


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
        "n_findings": len(findings),
        "dimensions": sorted(dims_present),
    }


METRIC_KEYS = ["scores.finding_recall", "scores.block_ok"]
