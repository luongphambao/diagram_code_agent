"""Reality Sync eval runner — deterministic, no agent/LLM, CI-safe.

    cd backend
    uv run python -m evals.reality_sync.run_eval
    uv run python -m evals.reality_sync.run_eval --gate
    uv run python -m evals.reality_sync.run_eval --update-baseline
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND / "src"))
sys.path.insert(0, str(_BACKEND))

from csm import Component, SolutionModel, mint_id  # noqa: E402
from reality_sync import drift  # noqa: E402
from evals._core import (  # noqa: E402
    compare_to_baseline,
    load_cases,
    print_table,
    run_all_sync,
    write_baseline,
    write_results,
)
from evals.reality_sync.judge import METRIC_KEYS, score_reality_sync  # noqa: E402

_DIR = Path(__file__).resolve().parent
_DATASET = _DIR / "dataset"
_RESULTS = _DIR / "results.json"
_BASELINE = _DIR / "baseline.json"

_COLUMNS = [
    ("case_id", "case"),
    ("scores.design_only_recall", "design_rec"),
    ("scores.reality_only_recall", "reality_rec"),
    ("scores.matched_ok", "matched_ok"),
    ("scores.n_drift", "n_drift"),
]


def _model(names: list[str]) -> SolutionModel:
    return SolutionModel(components=[
        Component(id=mint_id("component", n), name=n) for n in names
    ])


def _run_one(case: dict) -> dict:
    desired = _model(case.get("desired_components", []))
    current = _model(case.get("current_components", []))
    report = drift(desired, current)
    return {"case_id": case.get("id", "unknown"), "scores": score_reality_sync(report, case)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=None)
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--update-baseline", action="store_true")
    args = ap.parse_args()

    cases = load_cases(_DATASET, args.case)
    if not cases:
        print(f"No reality_sync cases in {_DATASET}")
        sys.exit(1)

    results = run_all_sync(cases, _run_one)
    print_table(results, _COLUMNS)
    write_results(_RESULTS, results)

    if args.update_baseline:
        write_baseline(_BASELINE, results, METRIC_KEYS)
        print(f"Baseline updated: {_BASELINE}")
        return

    passed, regressions = compare_to_baseline(results, _BASELINE, METRIC_KEYS)
    if regressions:
        print("REGRESSIONS:")
        for r in regressions:
            print(f"  {r['metric']}: {r['baseline']} -> {r['current']} (drop {r['drop']})")
    else:
        print("No regression vs baseline." if _BASELINE.exists() else "No baseline yet.")
    if args.gate and not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
