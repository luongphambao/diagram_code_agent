"""Finding store (docx §4.3, §7.1) — the cross-artifact finding *lifecycle*.

`solution_validator.evaluate_solution` re-derives findings from scratch on every
run, so today a finding is ephemeral: there is no way to say "I already looked at
this dangling-edge defect and waived it" or "this one was fixed". A waived defect
re-blocks the next export; a recurring defect can't be counted.

This module gives a finding a durable identity and a status that survives re-runs:

  * findings are keyed by `finding_id` — a content hash of (dimension, entity_ids,
    title) computed by `SolutionFinding` — so the SAME defect keeps the SAME id;
  * an `upsert_findings` merge REFRESHES the content of still-open findings but
    PRESERVES any `waived`/`resolved` status a human already set (docx §4.3);
  * `set_status` records a waive/resolve with reason/owner/timestamp.

It is deliberately self-contained (no CSM schema change): the human audit trail for
a waive/resolve is written separately as a `DecisionRecord` (see `decisions.py`),
which already projects into the CSM. Timestamps are injected by the caller, matching
the `evidence`/`decisions` convention so the log stays content-stable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Literal, Optional

from pydantic import BaseModel, Field

from solution_validator import SolutionFinding

FINDINGS_LOG_NAME = "findings_log.json"

FindingStatus = Literal["open", "waived", "resolved"]


class StoredFinding(BaseModel):
    """One finding plus its lifecycle — the persisted, status-carrying shape.

    The content fields mirror `SolutionFinding`; the trailing fields are the
    lifecycle the validator itself does not own (it always emits `status="open"`).
    """

    finding_id: str
    dimension: str = ""
    severity: str = "medium"
    confidence: str = "high"
    artifact_type: str = ""
    entity_ids: list[str] = Field(default_factory=list)
    title: str = ""
    detail: str = ""
    recommendation: Optional[str] = None
    repair_strategy: str = "none"
    requires_human_decision: bool = False

    status: FindingStatus = "open"
    resolution_reason: str = ""    # why it was waived, or what fix resolved it
    resolved_by: str = ""          # approver/agent that set the terminal status
    resolved_at: str = ""          # ISO 8601; injected by the caller
    first_seen_revision: int = 0   # CSM revision this defect first appeared at
    last_seen_revision: int = 0    # most recent revision the validator still raised it


# Statuses that take a finding out of the "active blocker" set.
SETTLED_STATUSES: frozenset[str] = frozenset({"waived", "resolved"})

# Content fields refreshed from a fresh validation run (status/audit are preserved).
_CONTENT_FIELDS = (
    "dimension", "severity", "confidence", "artifact_type", "entity_ids",
    "title", "detail", "recommendation", "repair_strategy", "requires_human_decision",
)


def _from_finding(f: SolutionFinding, *, revision: int) -> StoredFinding:
    return StoredFinding(
        finding_id=f.finding_id,
        dimension=f.dimension,
        severity=f.severity,
        confidence=f.confidence,
        artifact_type=f.artifact_type,
        entity_ids=list(f.entity_ids),
        title=f.title,
        detail=f.detail,
        recommendation=f.recommendation,
        repair_strategy=f.repair_strategy,
        requires_human_decision=f.requires_human_decision,
        status="open",
        first_seen_revision=revision,
        last_seen_revision=revision,
    )


# --- store -------------------------------------------------------------------

def _log_path(workspace: Optional[Path]) -> Path:
    if workspace is None:
        from backends import current_workspace
        workspace = current_workspace()
    return Path(workspace) / FINDINGS_LOG_NAME


def read_findings(workspace: Optional[Path] = None) -> list[StoredFinding]:
    """Load the findings log; returns [] when absent or unreadable."""
    path = _log_path(workspace)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    items = raw.get("findings", []) if isinstance(raw, dict) else raw
    out: list[StoredFinding] = []
    for d in items or []:
        try:
            out.append(StoredFinding.model_validate(d))
        except Exception:  # noqa: BLE001 — never let one bad row kill the log
            continue
    return out


def _write_findings(findings: Iterable[StoredFinding], workspace: Optional[Path]) -> None:
    path = _log_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"findings": [f.model_dump() for f in findings]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def upsert_findings(
    findings: list[SolutionFinding],
    *,
    workspace: Optional[Path] = None,
    revision: int = 0,
) -> list[StoredFinding]:
    """Merge a fresh validation run into the persisted log and return ALL stored findings.

    For each fresh finding keyed by `finding_id`:
      * new defect -> stored as `open` (first_seen=last_seen=revision);
      * known defect -> content fields REFRESHED, `last_seen_revision` bumped, but its
        `status` and resolution audit are PRESERVED, so a `waived`/`resolved` defect
        does not silently re-open (docx §4.3: track recurring vs. settled).
    Findings already in the log that the fresh run did not raise are kept untouched
    (their history — including a resolved status — is preserved).
    """
    stored = {f.finding_id: f for f in read_findings(workspace)}
    for f in findings:
        prior = stored.get(f.finding_id)
        if prior is None:
            stored[f.finding_id] = _from_finding(f, revision=revision)
            continue
        # Refresh content but keep the lifecycle the human/agent set.
        fresh = _from_finding(f, revision=revision)
        for field in _CONTENT_FIELDS:
            setattr(prior, field, getattr(fresh, field))
        prior.last_seen_revision = revision
        if not prior.first_seen_revision:
            prior.first_seen_revision = revision
    merged = list(stored.values())
    _write_findings(merged, workspace)
    return merged


def set_status(
    finding_id: str,
    status: FindingStatus,
    *,
    reason: str = "",
    by: str = "",
    at: str = "",
    workspace: Optional[Path] = None,
) -> Optional[StoredFinding]:
    """Set a finding's terminal status (`waived`/`resolved`) and persist it.

    Returns the updated record, or None when `finding_id` is not in the log (so the
    caller can tell the agent "no such finding — re-run validation to see live ids").
    """
    findings = read_findings(workspace)
    target: Optional[StoredFinding] = None
    for f in findings:
        if f.finding_id == finding_id:
            target = f
            break
    if target is None:
        return None
    target.status = status
    target.resolution_reason = reason
    target.resolved_by = by
    target.resolved_at = at
    _write_findings(findings, workspace)
    return target


def status_map(workspace: Optional[Path] = None) -> dict[str, str]:
    """`{finding_id: status}` for the current log — used to filter settled findings."""
    return {f.finding_id: f.status for f in read_findings(workspace)}


def active_findings(
    findings: list[SolutionFinding],
    workspace: Optional[Path] = None,
) -> list[SolutionFinding]:
    """Drop findings whose persisted status is `waived`/`resolved`.

    The gate formats/blocks on the result, so a defect a human already settled cannot
    re-raise a warning or re-block an export until it is detected under a NEW id
    (i.e. the underlying defect actually changed).
    """
    settled = {fid for fid, st in status_map(workspace).items() if st in SETTLED_STATUSES}
    return [f for f in findings if f.finding_id not in settled]
