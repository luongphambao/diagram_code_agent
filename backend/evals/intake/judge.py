"""Intake eval judge (docx §4.2, §4.5 "Requirement intake" suite).

Deterministic L1 scorer: given a golden brief (+ optional analysis tags), project it
to a CSM and check the *epistemic classification* — did requirements, assumptions and
constraints land in the right buckets? Reuses the shared `soft_match`, so "covered"
means the same thing it does in the diagram suite and the validator.

No LLM is needed: this scores the adapter's classification, which is exactly what we
want a regression gate to watch when prompts/models change upstream.
"""

from __future__ import annotations

from typing import Any

from evals._core import f1, soft_match


def _prf(produced: list[str], expected: list[str]) -> dict[str, float]:
    tp, fp, fn = soft_match(produced, expected)
    precision = tp / (tp + fp) if (tp + fp) else (1.0 if not expected else 0.0)
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1(tp, fp, fn), 4),
        "tp": tp, "fp": fp, "fn": fn,
    }


def score_intake(model: Any, golden: dict) -> dict:
    """Score one case. `model` is a SolutionModel projected from the golden brief."""
    es = model.epistemic_summary()
    produced_reqs = [r.statement for r in model.requirements]
    produced_asm = [a["statement"] for a in es["assumptions_needing_confirmation"]]
    produced_con = [c["statement"] for c in es["constraints"]]

    reqs = _prf(produced_reqs, golden.get("expected_requirements", []))
    asm = _prf(produced_asm, golden.get("expected_assumptions", []))
    con = _prf(produced_con, golden.get("expected_constraints", []))

    # Micro-F1 pools the counts across all three buckets (one number to gate on).
    tp = reqs["tp"] + asm["tp"] + con["tp"]
    fp = reqs["fp"] + asm["fp"] + con["fp"]
    fn = reqs["fn"] + asm["fn"] + con["fn"]

    # Missing-question detection: every pending assumption is a "needs confirmation"
    # item; reward surfacing the ones the golden case says must be asked.
    must_ask = golden.get("must_ask", [])
    ask_recall = _prf(produced_asm, must_ask)["recall"] if must_ask else 1.0

    # Tier classifier: assumptions the golden case flags as must_confirm should
    # receive confidence_tier="must_confirm". Vacuously 1.0 when not specified.
    expected_must = golden.get("expected_must_confirm", [])
    if expected_must:
        produced_must = [
            a.statement for a in model.assumptions
            if a.confidence_tier == "must_confirm"
        ]
        tier_recall = _prf(produced_must, expected_must)["recall"]
    else:
        tier_recall = 1.0

    return {
        "requirements_f1": reqs["f1"],
        "assumptions_f1": asm["f1"],
        "constraints_f1": con["f1"],
        "must_ask_recall": round(ask_recall, 4),
        "micro_f1": round(f1(tp, fp, fn), 4),
        "n_assumptions_pending": len(produced_asm),
        "tier_recall": round(tier_recall, 4),
    }


# Metrics the regression gate watches for this suite.
METRIC_KEYS = [
    "scores.micro_f1",
    "scores.requirements_f1",
    "scores.assumptions_f1",
    "scores.constraints_f1",
    "scores.must_ask_recall",
    "scores.tier_recall",
]
