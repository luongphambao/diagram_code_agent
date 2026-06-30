"""Reality Sync eval judge (docx §5.2).

Deterministic scorer over `reality_sync.drift`. A golden case lists the desired and the
observed (current-state) component names and asserts which land in the design-only and
reality-only buckets. Headline metrics are the recall over each drift bucket.
"""

from __future__ import annotations

from typing import Any


def _recall(expected: list[str], got: set[str]) -> float:
    if not expected:
        return 1.0 if not got else 0.0
    hit = sum(1 for x in expected if x in got)
    return round(hit / len(expected), 4)


def score_reality_sync(report: dict, golden: dict) -> dict:
    design_only = {e["name"] for e in report["in_design_not_in_reality"]}
    reality_only = {e["name"] for e in report["in_reality_not_in_design"]}
    matched = {e["name"] for e in report["matched"]}

    design_recall = _recall(golden.get("expected_design_only", []), design_only)
    reality_recall = _recall(golden.get("expected_reality_only", []), reality_only)
    matched_ok = 1.0 if set(golden.get("expected_matched", [])) <= matched else 0.0

    return {
        "design_only_recall": design_recall,
        "reality_only_recall": reality_recall,
        "matched_ok": matched_ok,
        "n_drift": len(design_only) + len(reality_only),
    }


METRIC_KEYS = [
    "scores.design_only_recall",
    "scores.reality_only_recall",
    "scores.matched_ok",
]
