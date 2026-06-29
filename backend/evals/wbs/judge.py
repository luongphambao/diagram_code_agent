"""WBS eval judge (docx §4.6, §4.5 "WBS" suite).

Deterministic L1/L2 scorer over the WBS delivery model: task coverage, dependency
validity, critical-path correctness and rollup arithmetic — built on the same
`wbs_effort.rollup` / `wbs_effort.critical_path` the agent uses, so the gate watches
the real scheduling math, not a re-implementation.
"""

from __future__ import annotations

from typing import Any

from wbs_effort import critical_path, rollup
from evals._core import soft_match


def _norm_set(refs: list[str]) -> set[str]:
    return {str(r).strip() for r in refs if str(r).strip()}


def score_wbs(case: dict) -> dict:
    items = case.get("items", [])
    ref_codes = _norm_set([it.get("ref_code", "") for it in items])

    # 1. Task coverage — every requirement soft-matches at least one leaf name.
    reqs = case.get("requirements", [])
    names = [it.get("name", "") for it in items]
    if reqs:
        tp, _fp, fn = soft_match(names, reqs)
        coverage = tp / (tp + fn) if (tp + fn) else 1.0
    else:
        coverage = 1.0
    coverage_ok = coverage >= case.get("min_coverage", 1.0)

    # 2. Dependency validity — every predecessor ref points to a real leaf.
    all_known = all(
        str(p).strip() in ref_codes
        for it in items for p in (it.get("predecessors") or [])
    )
    dependency_ok = (all_known == case.get("expect_dependency_valid", True))

    # 3. Critical path — matches the expected set, or is empty when there are no deps.
    cp = critical_path(items)
    cp_refs = _norm_set(cp.get("critical_path_ref_codes", []))
    if "expected_critical_path" in case:
        critical_path_ok = cp_refs == _norm_set(case["expected_critical_path"])
    else:
        has_deps = any(it.get("predecessors") for it in items)
        critical_path_ok = bool(cp_refs) if has_deps else not cp_refs

    # 4. Rollup arithmetic — the aggregate total equals the sum of leaf totals.
    roll = rollup(items)
    expected_total = round(sum(float(it.get("total", 0) or 0) for it in items), 4)
    rollup_ok = abs(roll["total_mandays"] - expected_total) < 0.01

    checks = [coverage_ok, dependency_ok, critical_path_ok, rollup_ok]
    return {
        "coverage_ok": 1.0 if coverage_ok else 0.0,
        "dependency_ok": 1.0 if dependency_ok else 0.0,
        "critical_path_ok": 1.0 if critical_path_ok else 0.0,
        "rollup_ok": 1.0 if rollup_ok else 0.0,
        "micro": round(sum(checks) / len(checks), 4),
        "project_duration_md": cp.get("project_duration_md", 0.0),
    }


METRIC_KEYS = [
    "scores.micro",
    "scores.coverage_ok",
    "scores.dependency_ok",
    "scores.critical_path_ok",
    "scores.rollup_ok",
]
