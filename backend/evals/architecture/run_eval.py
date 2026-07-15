"""Architecture/validator eval runner — deterministic, no agent/LLM, CI-safe.

    cd backend
    uv run python -m evals.architecture.run_eval
    uv run python -m evals.architecture.run_eval --gate
    uv run python -m evals.architecture.run_eval --update-baseline
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND / "src"))
sys.path.insert(0, str(_BACKEND))

from memory.stores.csm_adapter import from_artifacts  # noqa: E402
from domain.validation.solution_validator import evaluate_solution  # noqa: E402
from evals._core import (  # noqa: E402
    compare_to_baseline,
    load_cases,
    print_table,
    run_all_sync,
    write_baseline,
    write_results,
)
from evals.architecture.judge import METRIC_KEYS, score_architecture  # noqa: E402

_DIR = Path(__file__).resolve().parent
_DATASET = _DIR / "dataset"
_RESULTS = _DIR / "results.json"
_BASELINE = _DIR / "baseline.json"

_COLUMNS = [
    ("case_id", "case"),
    ("scores.finding_recall", "find_recall"),
    ("scores.block_ok", "block_ok"),
    ("scores.repair_contract_ok", "repair_ok"),
    ("scores.n_findings", "n_find"),
]


def _run_one(case: dict) -> dict:
    brief, blueprint, wbs = case.get("brief", {}), case.get("blueprint", {}), case.get("wbs", {})
    model = from_artifacts(brief, blueprint, wbs)
    findings = evaluate_solution(brief, blueprint, wbs, model=model)
    return {"case_id": case.get("id", "unknown"), "scores": score_architecture(findings, case)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=None)
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--update-baseline", action="store_true")
    args = ap.parse_args()

    cases = load_cases(_DATASET, args.case)
    if not cases:
        print(f"No architecture cases in {_DATASET}")
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
