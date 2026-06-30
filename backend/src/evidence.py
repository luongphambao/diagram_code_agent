"""Evidence store (docx §4.9) — grounded claims wired into the CSM.

`web_research` (Tavily, budget-capped) returns an answer plus source URLs, but
today that lives only in chat history. When the agent recommends a version,
price or reference architecture, nothing records *which* source backs the claim,
*when* it was fetched, how fresh it is, or *which* CSM entity it supports — so a
proposal cannot show the "why".

This module owns:
  * `EvidenceRecord` — the persisted shape of one grounded claim;
  * an append-only `evidence_log.json` store (`append_evidence` / `read_evidence`);
  * `project_into_csm` — fold the records into a `SolutionModel` as `Evidence`
    entities + `supports` trace links, and back-fill `Decision.evidence_ids`.

It imports ONLY from `csm` (the schema), never from `csm_adapter`, so the adapter
can call `project_into_csm` without an import cycle. Timestamps are injected by the
caller (the recording tool) — this module never calls an argless `datetime.now()`,
matching the adapter/decisions convention so a re-projection stays content-stable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Literal, Optional

from pydantic import BaseModel, Field

from csm import (
    Evidence,
    SolutionModel,
    SourceRef,
    TraceLink,
    mint_id,
)

EVIDENCE_LOG_NAME = "evidence_log.json"

SourceType = Literal["web", "documentation", "vendor", "benchmark", "standard", "other"]
Confidence = Literal["low", "medium", "high"]


class EvidenceRecord(BaseModel):
    """One persisted grounded claim (docx §4.9 appendix).

    `supports_entity_ids` name the CSM entities this evidence backs (a decision,
    component, requirement, ...). Only ids that exist in the model become trace
    links; dangling references are dropped silently on projection.
    """

    id: str
    claim: str
    source_url: str = ""
    source_type: SourceType = "web"
    fetched_at: str = ""              # ISO 8601; injected by the recording tool
    freshness_date: str = ""         # the date the source itself reflects, if known
    quote_or_excerpt: str = ""
    confidence: Confidence = "medium"
    supports_entity_ids: list[str] = Field(default_factory=list)
    supersedes_evidence_id: Optional[str] = None


def new_evidence_record(
    claim: str,
    *,
    seq: int,
    source_url: str = "",
    source_type: SourceType = "web",
    fetched_at: str = "",
    freshness_date: str = "",
    quote_or_excerpt: str = "",
    confidence: Confidence = "medium",
    supports_entity_ids: Optional[list[str]] = None,
    supersedes_evidence_id: Optional[str] = None,
) -> EvidenceRecord:
    """Mint a record with a stable id (`EVD-1`, `EVD-2`, ...) from the log size."""
    return EvidenceRecord(
        id=mint_id("evidence", seq),
        claim=claim,
        source_url=source_url,
        source_type=source_type,
        fetched_at=fetched_at,
        freshness_date=freshness_date,
        quote_or_excerpt=quote_or_excerpt,
        confidence=confidence,
        supports_entity_ids=list(supports_entity_ids or []),
        supersedes_evidence_id=supersedes_evidence_id,
    )


# --- store -------------------------------------------------------------------

def _log_path(workspace: Optional[Path]) -> Path:
    if workspace is None:
        from backends import current_workspace
        workspace = current_workspace()
    return Path(workspace) / EVIDENCE_LOG_NAME


def read_evidence(workspace: Optional[Path] = None) -> list[EvidenceRecord]:
    """Load the append-only evidence log; returns [] when absent or unreadable."""
    path = _log_path(workspace)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    items = raw.get("evidence", []) if isinstance(raw, dict) else raw
    out: list[EvidenceRecord] = []
    for d in items or []:
        try:
            out.append(EvidenceRecord.model_validate(d))
        except Exception:  # noqa: BLE001 — never let one bad row kill the log
            continue
    return out


def append_evidence(
    record: EvidenceRecord,
    workspace: Optional[Path] = None,
) -> EvidenceRecord:
    """Append one record to `evidence_log.json` (creating it if needed)."""
    path = _log_path(workspace)
    existing = read_evidence(workspace)
    existing.append(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"evidence": [r.model_dump() for r in existing]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def next_seq(workspace: Optional[Path] = None) -> int:
    """1-based sequence for the next evidence id, derived from the current log size."""
    return len(read_evidence(workspace)) + 1


# --- projection into the CSM -------------------------------------------------

def project_into_csm(model: SolutionModel, records: Iterable[EvidenceRecord]) -> SolutionModel:
    """Fold evidence records into `model` in place (and return it).

    Each record becomes an `Evidence` entity (`provenance="agent"`) carrying a
    `SourceRef` for the URL. For every `supports_entity_ids` target that exists in
    the model we add a `supports` trace link (EVD -> target); when the target is a
    `Decision`, the evidence id is also appended to its `evidence_ids` (deduped).

    Deterministic: records are processed in id order and ids are stable, so
    re-projecting the same log yields the same model (and the same content hash).
    """
    records = sorted(records, key=lambda r: r.id)
    existing_ids = model.ids()
    decisions_by_id = {d.id: d for d in model.decisions}

    for rec in records:
        if rec.id in existing_ids:
            continue  # already projected (defensive; a fresh build never has these)

        ev = Evidence(
            id=rec.id,
            provenance="agent",
            claim=rec.claim,
            source_url=rec.source_url,
            source_type=rec.source_type,
            fetched_at=rec.fetched_at,
            freshness_date=rec.freshness_date,
            quote_or_excerpt=rec.quote_or_excerpt,
            confidence=rec.confidence,
            supports_entity_ids=list(rec.supports_entity_ids),
            supersedes_evidence_id=rec.supersedes_evidence_id,
            source_refs=[SourceRef(kind="web", ref=rec.source_url, quote=rec.quote_or_excerpt)],
        )
        model.evidence.append(ev)
        existing_ids.add(rec.id)

        for target in rec.supports_entity_ids:
            if target not in existing_ids:
                continue  # dangling reference — skip the link
            model.trace_links.append(
                TraceLink(from_id=rec.id, to_id=target, relation="supports", provenance="agent"))
            dec = decisions_by_id.get(target)
            if dec is not None and rec.id not in dec.evidence_ids:
                dec.evidence_ids.append(rec.id)

    return model
