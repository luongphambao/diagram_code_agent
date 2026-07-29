"""BRD eval judge (docs/plans/2026-07-29-brd-agent.md §D, S4).

Deterministic scorer over domain.brd.brd_docx / domain.brd.brd_validate — no
LLM, no vision, no renderer. Each case exercises ONE invariant from the
module's design: id stability across a positional heading insert, the
optimistic-lock checksum guard, rename/cascade-delete id churn NOT falsely
triggering apply_brd_ops's revert-on-semantic-loss, and validate_brd's
structural lint catalog. Scores are boolean-recall based rather than fuzzy —
these are invariants the code either upholds or doesn't, there is no partial
credit that means anything.
"""

from __future__ import annotations


def _recall(checks: list[bool]) -> float:
    return round(sum(1 for c in checks if c) / len(checks), 4) if checks else 1.0


def score_brd(result: dict, case: dict) -> dict:
    kind = case["kind"]

    if kind == "id_stability":
        after_ids = result["after_ids"]
        stable = case.get("expect_stable_ids", [])
        new = case.get("expect_new_ids", [])
        checks = [sid in after_ids for sid in stable] + [sid in after_ids for sid in new]
        recall = _recall(checks)
        return {"recall": recall, "ok": 1.0 if recall == 1.0 else 0.0}

    if kind == "checksum_guard":
        checks = [result["rejected_stale"], result["unchanged_on_reject"], result["accepted_when_correct"]]
        recall = _recall(checks)
        return {"recall": recall, "ok": 1.0 if recall == 1.0 else 0.0}

    if kind == "semantic_preservation":
        after_ids = result["after_ids"]
        descendants = case.get("expect_descendant_ids_present", [])
        checks = [
            bool(result["ok"]),
            not result["reverted"],
            case.get("expect_old_id_gone", "") not in after_ids,
            case.get("expect_new_id_present", "") in after_ids,
        ] + [sid in after_ids for sid in descendants]
        recall = _recall(checks)
        return {"recall": recall, "ok": 1.0 if recall == 1.0 else 0.0}

    if kind == "validate":
        got_codes = {e["code"] for e in result["errors"]}
        expected = case.get("expect_error_codes", [])
        checks = [code in got_codes for code in expected]
        recall = _recall(checks)
        return {"recall": recall, "ok": 1.0 if recall == 1.0 else 0.0}

    raise ValueError(f"unknown BRD eval case kind: {kind!r}")


METRIC_KEYS = ["scores.ok", "scores.recall"]
