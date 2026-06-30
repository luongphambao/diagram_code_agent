"""Run every deterministic eval suite and gate as one (docx §4.5, §9 Phase-1 Evals).

These suites need no API key or renderer — they score the adapter/validator/WBS
math against committed baselines, so they are the CI-safe regression gate that
enforces "no prompt/model change ships without an eval artifact". The diagram suite
(LLM/vision) stays opt-in and is intentionally NOT run here.

    cd backend
    uv run python -m evals.run_all            # run + report
    uv run python -m evals.run_all --gate     # exit non-zero on any regression
    uv run python -m evals.run_all --update-baseline
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND / "src"))
sys.path.insert(0, str(_BACKEND))

from evals._core import (  # noqa: E402
    compare_to_baseline,
    load_cases,
    run_all_sync,
    write_baseline,
    write_results,
)

# Each suite: (name, dataset_dir, run_one_fn, metric_keys). Deterministic only.
from evals.intake.judge import METRIC_KEYS as INTAKE_KEYS  # noqa: E402
from evals.intake.run_eval import _run_one as intake_run  # noqa: E402
from evals.architecture.judge import METRIC_KEYS as ARCH_KEYS  # noqa: E402
from evals.architecture.run_eval import _run_one as arch_run  # noqa: E402
from evals.wbs.judge import METRIC_KEYS as WBS_KEYS  # noqa: E402
from evals.wbs.run_eval import _run_one as wbs_run  # noqa: E402
from evals.deck.judge import METRIC_KEYS as DECK_KEYS  # noqa: E402
from evals.deck.run_eval import _run_one as deck_run  # noqa: E402

_SUITES = [
    ("intake", _BACKEND / "evals" / "intake", intake_run, INTAKE_KEYS),
    ("architecture", _BACKEND / "evals" / "architecture", arch_run, ARCH_KEYS),
    ("wbs", _BACKEND / "evals" / "wbs", wbs_run, WBS_KEYS),
    ("deck", _BACKEND / "evals" / "deck", deck_run, DECK_KEYS),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--update-baseline", action="store_true")
    args = ap.parse_args()

    any_regression = False
    print(f"\n{'suite':<16}{'cases':>7}{'gate-metric (mean)':>24}{'status':>12}")
    print("-" * 60)
    for name, sdir, run_one, keys in _SUITES:
        cases = load_cases(sdir / "dataset")
        results = run_all_sync(cases, run_one)
        write_results(sdir / "results.json", results)
        baseline = sdir / "baseline.json"

        if args.update_baseline:
            write_baseline(baseline, results, keys)
            print(f"{name:<16}{len(cases):>7}{'(baseline updated)':>24}{'OK':>12}")
            continue

        passed, regressions = compare_to_baseline(results, baseline, keys)
        # First metric key is the suite's headline number.
        from evals._core import aggregate
        headline = aggregate(results, [keys[0]]).get(keys[0], float("nan"))
        status = "OK" if passed else "REGRESSED"
        if not passed:
            any_regression = True
        print(f"{name:<16}{len(cases):>7}{headline:>24.3f}{status:>12}")
        for r in regressions:
            print(f"    - {r['metric']}: {r['baseline']} -> {r['current']} (drop {r['drop']})")
    print()

    if args.gate and any_regression:
        sys.exit(1)


if __name__ == "__main__":
    main()
