"""HITL v2 decision records (docx §5.3, §1.1 decision #3).

Today a human gate is binary: the user approves or rejects and the choice lives
only in the chat history. The product plan wants each gate to be a *decision
workspace* — the user can also accept a risk, approve with assumptions, request
evidence or ask for an alternative — and every such action must become a durable,
structured record that is wired back into the Canonical Solution Model.

This module owns:
  * `DecisionRecord` — the persisted shape of one human decision;
  * an append-only `decision_log.json` store (`append_decision` / `read_decisions`);
  * `project_into_csm` — fold the decisions into a `SolutionModel` so the validator,
    `query_change_impact` and the epistemic summary all see them.

It imports ONLY from `csm` (the schema), never from `csm_adapter`, so the adapter
can call `project_into_csm` without an import cycle. Timestamps are injected by the
caller (the router) — this module never calls an argless `datetime.now()`, matching
the adapter's convention so a re-projection stays content-stable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Literal, Optional

from pydantic import BaseModel, Field

from csm import (
    Assumption,
    Decision,
    Risk,
    SolutionModel,
    TraceLink,
    mint_id,
)

DECISION_LOG_NAME = "decision_log.json"

# The trade-off actions a human can take at a gate (docx §5.3). `approve`/`reject`
# keep the old binary behaviour; the rest are new in HITL v2.
DecisionAction = Literal[
    "approve",
    "reject",
    "approve_with_assumptions",
    "accept_risk",
    "request_evidence",
    "request_alternative",
    "edit_entity",
    "waive_finding",     # accept a cross-artifact finding as a known trade-off
    "resolve_finding",   # record that a finding was fixed
]


class DecisionRecord(BaseModel):
    """One persisted human decision at a gate.

    `payload` holds the action-specific fields so the schema does not sprawl:
      * approve_with_assumptions -> {"assumption_ids": [...], "due": ?, "owner": ?}
      * accept_risk             -> {"risk_id"?, "statement"?, "owner", "mitigation",
                                    "residual"?, "probability"?, "impact"?}
      * request_evidence        -> {"claim", "source_expectation"?}
      * request_alternative     -> {"constraint_change"?, "option_comparison"?}
      * edit_entity             -> {"entity_id", "patch": {...}}
    """

    id: str
    gate: str = ""                 # gate tool name, e.g. "propose_blueprint"
    action: DecisionAction
    approver: str = ""
    approver_role: str = ""        # role the approver acted in (architect/pm/reviewer/...) §8.6
    timestamp: str = ""            # ISO 8601; injected by the caller
    revision: int = 0              # CSM revision the decision was made against
    comment: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


def new_decision_record(
    gate: str,
    action: DecisionAction,
    *,
    seq: int,
    approver: str = "",
    approver_role: str = "",
    timestamp: str = "",
    revision: int = 0,
    comment: str = "",
    payload: Optional[dict[str, Any]] = None,
) -> DecisionRecord:
    """Mint a record with a stable, human-distinct id (`DEC-h1`, `DEC-h2`, ...).

    The `h` prefix keeps human-decision ids from colliding with the ordinal
    `DEC-1`/`DEC-2` ids the adapter mints from `blueprint.key_decisions`.
    """
    return DecisionRecord(
        id=mint_id("decision", f"h{seq}"),
        gate=gate,
        action=action,
        approver=approver,
        approver_role=approver_role,
        timestamp=timestamp,
        revision=revision,
        comment=comment,
        payload=payload or {},
    )


# --- store -------------------------------------------------------------------

def _log_path(workspace: Optional[Path]) -> Path:
    if workspace is None:
        from backends import current_workspace
        workspace = current_workspace()
    return Path(workspace) / DECISION_LOG_NAME


def read_decisions(workspace: Optional[Path] = None) -> list[DecisionRecord]:
    """Load the append-only decision log; returns [] when absent or unreadable."""
    path = _log_path(workspace)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    items = raw.get("decisions", []) if isinstance(raw, dict) else raw
    out: list[DecisionRecord] = []
    for d in items or []:
        try:
            out.append(DecisionRecord.model_validate(d))
        except Exception:  # noqa: BLE001 — never let one bad row kill the log
            continue
    return out


def append_decision(
    record: DecisionRecord,
    workspace: Optional[Path] = None,
) -> DecisionRecord:
    """Append one record to `decision_log.json` (creating it if needed)."""
    path = _log_path(workspace)
    existing = read_decisions(workspace)
    existing.append(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"decisions": [r.model_dump() for r in existing]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def next_seq(workspace: Optional[Path] = None) -> int:
    """1-based sequence for the next decision id, derived from the current log size."""
    return len(read_decisions(workspace)) + 1


# --- projection into the CSM -------------------------------------------------

def _decision_title(rec: DecisionRecord) -> str:
    pretty = rec.action.replace("_", " ")
    return f"{pretty} @ {rec.gate}" if rec.gate else pretty


def project_into_csm(model: SolutionModel, records: Iterable[DecisionRecord]) -> SolutionModel:
    """Fold human decisions into `model` in place (and return it).

    Each record becomes a `Decision` entity (`provenance="human"`) so the trace
    graph has a real endpoint, plus the action's side effect:
      * accept_risk             -> add/refresh a `Risk` + `accepts` link;
      * approve_with_assumptions-> mark referenced `Assumption`s confirmed + `accepts`;
      * request_evidence        -> a pending `Assumption` capturing the request;
      * request_alternative     -> a deferred `Decision` carrying the ask.

    Deterministic: records are processed in id order and ids are stable, so
    re-projecting the same log yields the same model (and the same content hash).
    """
    records = sorted(records, key=lambda r: r.id)
    existing_ids = model.ids()
    assumptions_by_id = {a.id: a for a in model.assumptions}

    for rec in records:
        if rec.id in existing_ids:
            continue  # already projected (defensive; a fresh build never has these)

        status = "approved" if rec.action in (
            "approve", "approve_with_assumptions", "accept_risk",
            "waive_finding", "resolve_finding",
        ) else "deferred"
        dec = Decision(
            id=rec.id,
            provenance="human",
            title=_decision_title(rec),
            rationale=rec.comment,
            status=status,
            approver=rec.approver or None,
        )

        if rec.action == "accept_risk":
            rid = rec.payload.get("risk_id") or mint_id("risk", f"h{rec.id}")
            risk = next((r for r in model.risks if r.id == rid), None)
            if risk is None:
                risk = Risk(id=rid, provenance="human",
                            statement=rec.payload.get("statement") or rec.comment or "Accepted risk")
                model.risks.append(risk)
                existing_ids.add(rid)
            risk.owner = rec.payload.get("owner", risk.owner) or rec.approver
            risk.mitigation = rec.payload.get("mitigation", risk.mitigation)
            if rec.payload.get("probability"):
                risk.probability = rec.payload["probability"]
            if rec.payload.get("impact"):
                risk.impact = rec.payload["impact"]
            dec.risk_ids = [rid]
            model.trace_links.append(
                TraceLink(from_id=rec.id, to_id=rid, relation="accepts", provenance="human"))

        elif rec.action == "approve_with_assumptions":
            confirmed: list[str] = []
            for aid in rec.payload.get("assumption_ids", []):
                a = assumptions_by_id.get(aid)
                if a is not None:
                    a.status = "confirmed"
                    a.provenance = "human"
                    if rec.approver and not a.owner:
                        a.owner = rec.approver
                    confirmed.append(aid)
                    model.trace_links.append(
                        TraceLink(from_id=rec.id, to_id=aid, relation="accepts", provenance="human"))
            dec.assumption_ids = confirmed

        elif rec.action == "request_evidence":
            claim = rec.payload.get("claim") or rec.comment or "Evidence requested"
            aid = mint_id("assumption", f"evd_{rec.id}")
            if aid not in existing_ids:
                model.assumptions.append(Assumption(
                    id=aid, provenance="human", status="pending",
                    statement=f"Evidence requested: {claim}", owner=rec.approver))
                existing_ids.add(aid)
            dec.assumption_ids = [aid]

        elif rec.action == "request_alternative":
            extra = rec.payload.get("constraint_change") or rec.payload.get("option_comparison") or ""
            if extra:
                dec.rationale = (dec.rationale + " | " + extra).strip(" |")

        elif rec.action in ("waive_finding", "resolve_finding"):
            # Anchor the human decision to the finding it settles (finding ids live in
            # findings_log.json, outside the CSM, so we carry it in the rationale).
            fid = rec.payload.get("finding_id") or ""
            if fid:
                dec.rationale = (f"{fid}: " + (dec.rationale or "")).strip()

        model.decisions.append(dec)
        existing_ids.add(rec.id)

    return model
