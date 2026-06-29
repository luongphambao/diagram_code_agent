"""Intake eval runner — deterministic, no agent/LLM, CI-safe.

    cd backend
    uv run python -m evals.intake.run_eval
    uv run python -m evals.intake.run_eval --gate          # fail on regression
    uv run python -m evals.intake.run_eval --update-baseline
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `from csm_adapter import ...` (src) and `from evals... import ...` (backend root).
_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND / "src"))
sys.path.insert(0, str(_BACKEND))

from csm_adapter import from_artifacts  # noqa: E402
from evals._core import (  # noqa: E402
    compare_to_baseline,
    load_cases,
    print_table,
    run_all_sync,
    write_baseline,
    write_results,
)
from evals.intake.judge import METRIC_KEYS, score_intake  # noqa: E402

_DIR = Path(__file__).resolve().parent
_DATASET = _DIR / "dataset"
_RESULTS = _DIR / "results.json"
_BASELINE = _DIR / "baseline.json"

_COLUMNS = [
    ("case_id", "case"),
    ("scores.micro_f1", "micro_f1"),
    ("scores.requirements_f1", "req_f1"),
    ("scores.assumptions_f1", "asm_f1"),
    ("scores.constraints_f1", "con_f1"),
    ("scores.must_ask_recall", "ask_rec"),
]


def _run_one(case: dict) -> dict:
    model = from_artifacts(
        case.get("brief", {}), case.get("blueprint", {}), case.get("wbs", {}),
        analysis=case.get("analysis", {}),
    )
    return {"case_id": case.get("id", "unknown"), "scores": score_intake(model, case)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=None)
    ap.add_argument("--gate", action="store_true", help="exit non-zero on regression")
    ap.add_argument("--update-baseline", action="store_true")
    args = ap.parse_args()

    cases = load_cases(_DATASET, args.case)
    if not cases:
        print(f"No intake cases in {_DATASET}")
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
