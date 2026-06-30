"""Deck eval runner — deterministic, no agent/LLM, CI-safe.

    cd backend
    uv run python -m evals.deck.run_eval
    uv run python -m evals.deck.run_eval --gate
    uv run python -m evals.deck.run_eval --update-baseline
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_BACKEND / "src"))
sys.path.insert(0, str(_BACKEND))

from csm import Evidence  # noqa: E402
from csm_adapter import from_artifacts  # noqa: E402
from deck import DeckPlan, build_deck_plan, validate_deck  # noqa: E402
from evals._core import (  # noqa: E402
    compare_to_baseline,
    load_cases,
    print_table,
    run_all_sync,
    write_baseline,
    write_results,
)
from evals.deck.judge import METRIC_KEYS, score_deck  # noqa: E402

_DIR = Path(__file__).resolve().parent
_DATASET = _DIR / "dataset"
_RESULTS = _DIR / "results.json"
_BASELINE = _DIR / "baseline.json"

_COLUMNS = [
    ("case_id", "case"),
    ("scores.finding_recall", "recall"),
    ("scores.match", "match"),
    ("scores.n_findings", "n_find"),
]


def _build_plan(case: dict) -> tuple[DeckPlan, object]:
    """Build the model + storyboard for a case, applying any seeded-defect directives."""
    brief = case.get("brief", {})
    blueprint = case.get("blueprint", {})
    wbs = case.get("wbs", {})
    model = from_artifacts(brief, blueprint, wbs, tech_stack=case.get("tech_stack", {}))

    # Inject grounded evidence (evidence lives in evidence_log, not the artifacts).
    for i, ev in enumerate(case.get("evidence", []), start=1):
        model.evidence.append(Evidence(id=ev.get("id", f"EVD-{i}"),
                                       claim=ev.get("claim", ""),
                                       source_url=ev.get("source_url", "")))

    plan = build_deck_plan(model, wbs=wbs, brief=brief,
                           has_diagram=case.get("has_diagram", True))

    # Seeded-defect directives (keep golden cases tiny).
    if case.get("append_ghost_ref"):
        for s in plan.slides:
            if s.source_refs:
                s.source_refs.append("COMP-ghost-does-not-exist")
                break
    if case.get("drop_required_roles"):
        drop = set(case["drop_required_roles"])
        plan.slides = [s for s in plan.slides if s.narrative_role not in drop]
    return plan, model


def _run_one(case: dict) -> dict:
    plan, model = _build_plan(case)
    findings = validate_deck(plan, model)
    return {"case_id": case.get("id", "unknown"), "scores": score_deck(findings, case)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=None)
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--update-baseline", action="store_true")
    args = ap.parse_args()

    cases = load_cases(_DATASET, args.case)
    if not cases:
        print(f"No deck cases in {_DATASET}")
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
