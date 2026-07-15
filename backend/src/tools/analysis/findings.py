"""Evidence, comments, findings lifecycle, compliance, delivery/ADR export, and
edit_entity / quality_summary CSM tools."""

from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import tool

from backends import current_workspace
from memory.stores.csm_adapter import build_solution_model
from domain.reporting.quality_dashboard import (
    SNAPSHOT_NAME as QUALITY_SNAPSHOT_NAME,
    build_quality_snapshot,
    format_snapshot,
    write_snapshot,
)
from ..stage_markers import _bump_tool_summary, _read_json_file


@tool(parse_docstring=True)
def record_evidence(
    claim: str,
    source_url: str = "",
    source_type: str = "web",
    quote_or_excerpt: str = "",
    confidence: str = "medium",
    supports_entity_ids: Optional[list[str]] = None,
    freshness_date: str = "",
    supersedes_evidence_id: Optional[str] = None,
) -> str:
    """Persist a grounded claim as a durable evidence record (docx §4.9).

    Use AFTER web_research (or reading a document) to ground a client-facing claim
    — a price, a version/EOL date, a compliance statement, a reference architecture
    — so the proposal can show *why* and an auditor can trace the source. The record
    is appended to `evidence_log.json` and folded into the solution model as an
    Evidence entity with `supports` trace links back to the entities it backs.

    When to use: right after the search/source that established the fact, while the
    URL and excerpt are at hand. Link it to the CSM entities it supports via
    `supports_entity_ids` (e.g. the decision it justifies or the component it sizes).

    Args:
        claim: The single factual statement being grounded, e.g. "AWS Fargate is
            $0.04048/vCPU-hour in us-east-1 (2026)".
        source_url: The URL (or document locator) the claim came from.
        source_type: One of web, documentation, vendor, benchmark, standard, other.
        quote_or_excerpt: A short verbatim span from the source supporting the claim.
        confidence: low, medium, or high — how strongly the source supports the claim.
        supports_entity_ids: CSM entity ids this evidence backs (DEC-/COMP-/REQ-...).
            When an id names a decision, the evidence is added to its evidence_ids.
        freshness_date: The date the source itself reflects (e.g. pricing as-of), if
            known; distinct from when it was fetched.
        supersedes_evidence_id: An older EVD-### this record refreshes/replaces.
    """
    from datetime import datetime, timezone
    from memory.stores.evidence import append_evidence, new_evidence_record, next_seq

    valid_types = {"web", "documentation", "vendor", "benchmark", "standard", "other"}
    stype = (source_type or "web").strip().lower()
    if stype not in valid_types:
        stype = "other"
    conf = (confidence or "medium").strip().lower()
    if conf not in {"low", "medium", "high"}:
        conf = "medium"

    record = new_evidence_record(
        claim=claim,
        seq=next_seq(current_workspace()),
        source_url=source_url or "",
        source_type=stype,  # type: ignore[arg-type]
        fetched_at=datetime.now(timezone.utc).isoformat(),
        freshness_date=freshness_date or "",
        quote_or_excerpt=quote_or_excerpt or "",
        confidence=conf,  # type: ignore[arg-type]
        supports_entity_ids=list(supports_entity_ids or []),
        supersedes_evidence_id=supersedes_evidence_id,
    )
    append_evidence(record, current_workspace())
    total = next_seq(current_workspace()) - 1
    _bump_tool_summary("record_evidence", evidence_count=total)
    linked = ", ".join(record.supports_entity_ids) or "(no entity link)"
    return (
        f"Recorded {record.id} (confidence={record.confidence}) supporting {linked}. "
        f"{total} evidence record(s) on file; folded into the solution model on next "
        f"build_solution_model."
    )


def _settle_finding(finding_id: str, status: str, note: str, *, action: str) -> str:
    """Set a finding's terminal status + record the human DecisionRecord (docx §4.3)."""
    from datetime import datetime, timezone

    from memory.stores.decisions import append_decision, new_decision_record, next_seq
    from memory.stores.finding_store import set_status

    fid = (finding_id or "").strip()
    if not fid:
        return "Pass the finding_id (SF-xxxx) shown in the CROSS-ARTIFACT CHECK output."
    now = datetime.now(timezone.utc).isoformat()
    updated = set_status(fid, status, reason=note or "", by="agent", at=now, workspace=current_workspace())
    if updated is None:
        return (f"No finding {fid} in findings_log.json — re-run the stage or export gate to "
                "refresh the cross-artifact check, then use a live SF-id.")
    # Audit trail: a human DecisionRecord, folded into the CSM on next build_solution_model.
    try:
        rec = new_decision_record(
            "cross_artifact_check",
            action,  # type: ignore[arg-type]
            seq=next_seq(current_workspace()),
            approver="agent",
            timestamp=now,
            comment=note or "",
            payload={"finding_id": fid},
        )
        append_decision(rec, current_workspace())
    except Exception:
        pass
    _bump_tool_summary(action)
    verb = "waived" if status == "waived" else "resolved"
    return (f"Finding {fid} marked {verb}: {note or '(no note)'}. It no longer blocks an export; "
            "re-run the export gate to confirm the verdict clears.")


@tool(parse_docstring=True)
def waive_finding(finding_id: str, reason: str) -> str:
    """Accept a cross-artifact validation finding as a known trade-off (docx §4.3).

    Use when a finding from the CROSS-ARTIFACT CHECK is an intentional, accepted
    decision (a requirement is deliberately deferred, internal-only WBS work is
    expected) rather than a defect to fix. The finding's status becomes `waived` in
    findings_log.json so it stops blocking an export, and a human decision record is
    persisted for the audit trail. Prefer resolve_finding when you actually fixed the
    underlying artifact.

    Args:
        finding_id: The SF-xxxx id shown in the CROSS-ARTIFACT CHECK output.
        reason: Why this finding is accepted as-is — the trade-off being accepted.
    """
    return _settle_finding(finding_id, "waived", reason, action="waive_finding")


@tool(parse_docstring=True)
def resolve_finding(finding_id: str, fix_applied: str) -> str:
    """Mark a cross-artifact validation finding as fixed (docx §4.3).

    Use AFTER you corrected the underlying artifact (added the missing node, mapped
    the requirement, ran the rollup). The finding's status becomes `resolved` so it no
    longer blocks an export, and a human decision record is persisted. If the defect
    genuinely persists it re-appears under a NEW id on the next check.

    Args:
        finding_id: The SF-xxxx id shown in the CROSS-ARTIFACT CHECK output.
        fix_applied: What you changed to fix it.
    """
    return _settle_finding(finding_id, "resolved", fix_applied, action="resolve_finding")


@tool(parse_docstring=True)
def apply_compliance_pack(pack_name: str) -> str:
    """Activate a reusable compliance control pack for this proposal (docx §4 P2, §13.2).

    Maps a standard's controls (encryption, audit logging, access review, …) onto the
    solution: each control becomes a CSM entity linked to the work/components that
    implement it and the risks it mitigates. Required controls that have no
    implementation or no evidence then surface as `compliance` findings in the
    CROSS-ARTIFACT CHECK, so a client claim like "SOC 2 ready" is blocked until it is
    backed by evidence. Call this once the architecture and WBS exist. Available packs:
    generic_security.

    Args:
        pack_name: Name of the pack to activate (e.g. "generic_security").
    """
    from compliance import evidence_gaps, list_packs, load_pack, set_active_pack
    available = list_packs()
    if not load_pack(pack_name):
        return (f"Unknown compliance pack {pack_name!r}. "
                f"Available: {', '.join(available) or '(none)'}.")
    set_active_pack(pack_name, current_workspace())
    try:
        model = build_solution_model(current_workspace())  # rebuild so controls + findings appear now
        gaps = evidence_gaps(model)
        n_controls = len(model.controls)
    except Exception:
        n_controls, gaps = 0, []
    _bump_tool_summary("apply_compliance_pack")
    gap_note = (f" {len(gaps)} control(s) still need implementation/evidence."
                if gaps else " all controls covered.")
    return (f"Compliance pack '{pack_name}' active: {n_controls} control(s) mapped into the "
            f"solution model.{gap_note} Re-run the export gate to see compliance findings; "
            "attach proof with record_evidence or waive with rationale.")


@tool(parse_docstring=True)
def add_comment(body: str, anchor_entity_id: str = "", role: str = "reviewer") -> str:
    """Attach a review comment to a CSM entity for the audit trail (docx §8.6).

    Anchors a note to a stable entity id (REQ-/COMP-/WBS-/SLIDE-/DEC-…) instead of a
    chat message, so the review thread survives a rename and ships with the proposal
    package. Use to flag an open question, a decision rationale, or a reviewer concern
    against a specific part of the solution.

    Args:
        body: The comment text.
        anchor_entity_id: The CSM entity id the comment is about ("" for a general note).
        role: The commenter's role (architect / pm / reviewer / client).
    """
    from datetime import datetime, timezone
    from memory.stores.comments import append_comment, new_comment_record, next_seq

    rec = new_comment_record(
        body=body,
        seq=next_seq(current_workspace()),
        anchor_entity_id=(anchor_entity_id or "").strip(),
        author="agent",
        role=(role or "reviewer").strip(),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    append_comment(rec, current_workspace())
    _bump_tool_summary("add_comment")
    anchor = f" on {rec.anchor_entity_id}" if rec.anchor_entity_id else ""
    return f"Comment {rec.id} added{anchor} (comment_log.json). Resolve it with resolve_comment({rec.id})."


@tool(parse_docstring=True)
def resolve_comment(comment_id: str) -> str:
    """Mark a review comment as resolved (docx §8.6).

    Args:
        comment_id: The CMT-xxx id of the comment to close.
    """
    from datetime import datetime, timezone
    from memory.stores.comments import resolve_comment as _resolve

    rec = _resolve(comment_id, resolved_by="agent",
                   resolved_at=datetime.now(timezone.utc).isoformat(), workspace=current_workspace())
    if rec is None:
        return f"No comment {comment_id!r} found in comment_log.json."
    _bump_tool_summary("resolve_comment")
    return f"Comment {comment_id} marked resolved."


@tool(parse_docstring=True)
def export_to_delivery(system: str, dry_run: bool = True) -> str:
    """Export the WBS work items to a delivery tracker (Jira/Linear/Confluence) (docx §8.6).

    Syncs each CSM work item to one external issue, keyed by its stable id, so a re-run
    creates new items, updates changed ones and skips unchanged ones (idempotent — never
    duplicates). PAUSES for human approval before running (explicit send gate, §12.3).
    Default `dry_run=True` writes a reviewable preview and pushes nothing; set
    `dry_run=False` to actually sync. With no tracker credentials configured a real sync
    is simulated with deterministic ids so the flow is testable.

    Args:
        system: One of jira, linear, confluence.
        dry_run: True (default) = preview only; False = perform the sync.
    """
    sys_l = (system or "").strip().lower()
    if sys_l not in ("jira", "linear", "confluence"):
        return f"Unknown delivery system {system!r}. Use jira, linear, or confluence."
    try:
        model = build_solution_model(current_workspace())
    except Exception as exc:  # noqa: BLE001
        return f"Could not build solution model: {exc}"
    if not model.work_items:
        return "No WBS work items to export — run the WBS pipeline first."
    from domain.reporting.delivery_export import sync_work_items
    res = sync_work_items(model, sys_l, dry_run=dry_run, workspace=current_workspace())  # type: ignore[arg-type]
    _bump_tool_summary("export_to_delivery")
    c = res["counts"]
    if res["dry_run"]:
        mode = "PREVIEW (dry-run)"
    elif res.get("pushed"):
        mode = "SYNCED (live)"
    else:
        mode = "SYNCED (simulated — no credentials)"
    tail = (" Preview written to delivery_export_preview.json — set dry_run=false to push."
            if res["dry_run"] else " Mapping saved to delivery_sync_log.json.")
    return (f"Delivery export to {sys_l} [{mode}]: {c['create']} create, {c['update']} update, "
            f"{c['skip']} skip (of {len(model.work_items)} work item(s)).{tail}")


@tool(parse_docstring=True)
def reality_sync(source_path: str) -> str:
    """Compare the design to a real codebase/infra and report drift (docx §5.2).

    "Reality Sync Mode": ingests a source folder (a repo, Terraform, k8s/compose YAML, or
    an OpenAPI spec) into a current-state model and diffs it against the approved design,
    so you can answer "does the proposal match what is actually built?". Writes
    current_state_model.json + drift_report.json and returns a summary: components
    designed-but-not-built, built-but-not-designed (drift), and matched. Read-only — it
    never changes the solution model.

    Args:
        source_path: Path to the repo/infra folder to ingest.
    """
    from pathlib import Path as _Path
    from domain.reporting.reality_sync import format_drift, run_reality_sync

    src = _Path(source_path)
    if not src.exists():
        return f"Source path not found: {source_path!r}."
    try:
        report = run_reality_sync(src, current_workspace())
    except Exception as exc:  # noqa: BLE001
        return f"Reality sync failed: {exc}"
    _bump_tool_summary("reality_sync")
    return format_drift(report)


@tool(parse_docstring=True)
def export_adr_pack() -> str:
    """Export the decision log as a Markdown ADR pack for the proposal (docx §8.6).

    Renders every recorded decision (options, choice, rationale, approver, evidence,
    review trigger) into `adr_pack.md` so an enterprise engagement ships with an
    auditable Architecture Decision Record set. Call near finalization.
    """
    try:
        from domain.reporting.adr_export import write_adr_pack
        path, n = write_adr_pack(current_workspace())
    except Exception as exc:  # noqa: BLE001
        return f"ADR export failed: {exc}"
    _bump_tool_summary("export_adr_pack")
    if n == 0:
        return "ADR pack: no decisions recorded yet — nothing to export."
    return f"ADR pack written ({n} decision record(s)) → adr_pack.md."


# ---------------------------------------------------------------------------
# edit_entity — in-place CSM entity patch (docx §5.3 HITL v2)
# ---------------------------------------------------------------------------

_PATCHABLE_FIELDS = frozenset({
    "title", "description", "source", "provenance_note", "status",
    "risk_level", "severity", "mitigation", "rationale", "owner",
    "definition_of_done", "kind", "confidence",
})

_CSM_COLLECTIONS = [
    "requirements", "constraints", "assumptions", "decisions",
    "components", "risks", "work_items", "evidence", "deliverables",
]


@tool(parse_docstring=True)
def edit_entity(entity_id: str, field: str, new_value: str) -> str:
    """Patch a single field on a CSM entity in solution_model.json.

    Reads the current solution model, locates the entity by its stable id,
    applies the field update, copies the old model to solution_model.prev.json
    (enabling query_change_impact), bumps the revision, and writes back.
    Call query_change_impact() immediately after to surface the blast radius.

    Args:
        entity_id: Stable CSM id of the entity to update
            (e.g. REQ-1, COMP-3, WBS-7, DEC-2, ASM-1).
        field: Field name to update. Patchable string fields: title, description,
            source, provenance_note, status, risk_level, severity, mitigation,
            rationale, owner, definition_of_done, kind, confidence.
        new_value: New string value for the field.
    """
    import json as _json
    from memory.stores.csm import SolutionModel
    from memory.stores.csm_adapter import SOLUTION_MODEL_NAME, SOLUTION_MODEL_PREV_NAME

    if field not in _PATCHABLE_FIELDS:
        return (
            f"EDIT_ENTITY: ERROR — field '{field}' is not patchable. "
            f"Allowed: {sorted(_PATCHABLE_FIELDS)}."
        )

    cur_path = current_workspace() / SOLUTION_MODEL_NAME
    cur_raw = _read_json_file(cur_path, None)
    if cur_raw is None:
        return "EDIT_ENTITY: ERROR — no solution_model.json yet (run the pipeline first)."

    # Find and patch the entity in the raw dict
    old_val = None
    found = False
    for coll in _CSM_COLLECTIONS:
        for item in cur_raw.get(coll, []):
            if item.get("id") == entity_id:
                old_val = item.get(field)
                item[field] = new_value
                found = True
                break
        if found:
            break

    if not found:
        return (
            f"EDIT_ENTITY: ERROR — entity '{entity_id}' not found in solution model. "
            f"Searched collections: {_CSM_COLLECTIONS}."
        )

    # Validate the patched model before writing
    try:
        SolutionModel.model_validate(cur_raw)
    except Exception as exc:  # noqa: BLE001
        return f"EDIT_ENTITY: ERROR — validation failed after patch: {exc}"

    # Snapshot the current file as .prev (enables query_change_impact)
    prev_path = current_workspace() / SOLUTION_MODEL_PREV_NAME
    prev_path.write_text(cur_path.read_text(encoding="utf-8"), encoding="utf-8")

    # Bump revision and write back
    cur_raw["revision"] = cur_raw.get("revision", 0) + 1
    cur_path.write_text(
        _json.dumps(cur_raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return (
        f"EDIT_ENTITY: {entity_id}.{field} updated "
        f"({repr(old_val)!s} → {repr(new_value)!s}), "
        f"revision bumped to {cur_raw['revision']}. "
        "Call query_change_impact() to see the blast radius."
    )


@tool
def quality_summary() -> str:
    """Compute and return the quality dashboard for the current workspace.

    Reads findings_log.json, decision_log.json, evidence_log.json, and
    solution_model.json, then computes a QualitySnapshot: open/waived/resolved
    findings by dimension and severity, HITL decision counts, evidence coverage
    (% of requirements grounded in at least one evidence record), assumption
    confirmation rate by confidence tier, risk mitigation rate, and a 0-100
    quality score (grade A-F).

    The snapshot is written to quality_snapshot.json in the workspace. Call this
    after any gate to see the current quality health of the solution proposal.
    """
    try:
        snap = build_quality_snapshot(current_workspace())
        write_snapshot(snap, current_workspace())
        return format_snapshot(snap)
    except Exception as exc:
        return f"QUALITY_SUMMARY: ERROR — {exc}"
