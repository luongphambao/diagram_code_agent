"""Proposal package assembler (Phase 3 — Proposal Mode UX).

Builds a `ProposalManifest` — a single structured view of every artifact, decision,
and quality dimension for a proposal run — and exports the package as a directory
containing the manifest JSON plus copies of all deliverable files.

No LLM, no rendering.  Reads workspace JSON stores and checks for artifact files.
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from safe_path import safe_workspace_path


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class ArtifactEntry(BaseModel):
    artifact_type: Literal["diagram", "wbs", "deck", "report", "other"]
    filename: str
    generated_at: Optional[str] = None
    approved: bool = False


class ProposalManifest(BaseModel):
    manifest_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_title: str = ""
    created_at: str = ""
    status: Literal["draft", "final"] = "draft"

    # Artifacts present in the workspace
    artifacts: list[ArtifactEntry] = Field(default_factory=list)

    # Deck storyboard summary
    slide_count: int = 0
    trace_coverage_pct: float = 0.0  # slides with source_refs / total slides
    structure_score: Optional[int] = None
    structure_grade: Optional[str] = None

    # Quality signals
    open_findings: int = 0
    open_findings_high: int = 0
    visual_audit_passed: Optional[bool] = None
    visual_audit_score: Optional[int] = None

    # Human decisions
    decisions_total: int = 0

    # Export history (appended by export_proposal_package)
    exports: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

_ARTIFACT_CANDIDATES: list[tuple[str, Literal["diagram", "wbs", "deck", "report", "other"]]] = [
    ("out.pptx", "deck"),
    ("out.body.png", "diagram"),
    ("out.png", "diagram"),
    ("out.drawio", "diagram"),
    ("wbs_output.xlsx", "wbs"),
    ("report.pdf", "report"),
    ("report.docx", "report"),
]


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except Exception:  # noqa: BLE001
        return None


def build_manifest(workspace: Path, title: str = "") -> ProposalManifest:
    """Assemble a ProposalManifest from the workspace stores. No LLM, no side effects."""
    ws = Path(workspace)
    manifest = ProposalManifest(
        project_title=title,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    # --- title fallback from diagram_brief ----------------------------------
    if not manifest.project_title:
        brief = _read_json(ws / "diagram_brief.json")
        if brief:
            manifest.project_title = brief.get("slide_title") or brief.get("title") or title or ""

    # --- artifacts present in workspace ------------------------------------
    seen_types: set[str] = set()
    for filename, atype in _ARTIFACT_CANDIDATES:
        fpath = ws / filename
        if not fpath.exists():
            continue
        if atype == "diagram" and "diagram" in seen_types:
            continue  # prefer first diagram found
        seen_types.add(atype)
        manifest.artifacts.append(
            ArtifactEntry(
                artifact_type=atype,
                filename=filename,
                generated_at=datetime.fromtimestamp(fpath.stat().st_mtime, tz=timezone.utc).isoformat(),
                approved=False,  # approval status is set below via decision_log
            )
        )

    # --- deck storyboard ----------------------------------------------------
    deck_plan_raw = _read_json(ws / "deck_plan.json")
    if deck_plan_raw:
        slides = deck_plan_raw.get("slides", [])
        manifest.slide_count = len(slides)
        grounded = sum(1 for s in slides if s.get("source_refs"))
        manifest.trace_coverage_pct = round(100.0 * grounded / len(slides), 1) if slides else 0.0

    # --- deck QA result -----------------------------------------------------
    deck_qa = _read_json(ws / "deck_qa_result.json")
    if deck_qa:
        manifest.structure_score = deck_qa.get("structural_score")
        manifest.structure_grade = deck_qa.get("structural_grade")
        findings = deck_qa.get("findings", [])
        manifest.open_findings = sum(
            1 for f in findings if isinstance(f, dict) and f.get("status", "open") == "open"
        )
        manifest.open_findings_high = sum(
            1
            for f in findings
            if isinstance(f, dict) and f.get("status", "open") == "open" and f.get("severity") == "high"
        )

    # --- visual audit -------------------------------------------------------
    visual_audit = _read_json(ws / "deck_visual_audit.json")
    if visual_audit:
        manifest.visual_audit_passed = visual_audit.get("passed")
        manifest.visual_audit_score = visual_audit.get("threshold_score")

    # --- decision log — approval status & total ----------------------------
    dec_raw = _read_json(ws / "decision_log.json")
    if dec_raw:
        decisions = dec_raw.get("decisions", []) if isinstance(dec_raw, dict) else dec_raw
        manifest.decisions_total = len(decisions)
        # Mark deck "approved" if any decision on the deck gate was "approve"
        approved_gates = {
            d.get("gate")
            for d in (decisions or [])
            if isinstance(d, dict) and d.get("action") in ("approve", "approve_with_assumptions")
        }
        deck_approved = bool(approved_gates & {"propose_deck_plan", "generate_ppt_proposal", "deck_review"})
        for art in manifest.artifacts:
            if art.artifact_type == "deck":
                art.approved = deck_approved
        # Status: final if deck explicitly approved, else draft
        if deck_approved:
            manifest.status = "final"

    # --- findings log (cross-artifact) -------------------------------------
    findings_raw = _read_json(ws / "findings_log.json")
    if findings_raw and manifest.open_findings == 0:  # don't double-count
        findings = findings_raw.get("findings", []) if isinstance(findings_raw, dict) else findings_raw
        open_findings = [
            f for f in (findings or []) if isinstance(f, dict) and f.get("status", "open") == "open"
        ]
        manifest.open_findings = max(manifest.open_findings, len(open_findings))
        manifest.open_findings_high = max(
            manifest.open_findings_high,
            sum(1 for f in open_findings if f.get("severity") == "high"),
        )

    return manifest


# ---------------------------------------------------------------------------
# Exporter
# ---------------------------------------------------------------------------


def export_proposal_package(
    workspace: Path,
    title: str = "",
    output_dir: Optional[Path] = None,
) -> tuple[str, ProposalManifest]:
    """Copy all artifacts + write manifest.json into a timestamped export directory.

    Returns (export_directory_path, manifest).
    """
    ws = Path(workspace)
    if output_dir is None:
        output_dir = ws / "exports"

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    export_path = Path(output_dir) / ts
    export_path.mkdir(parents=True, exist_ok=True)

    manifest = build_manifest(ws, title=title)

    # Copy artifact files
    copied: list[str] = []
    for art in manifest.artifacts:
        src = ws / art.filename
        if src.exists():
            dest = safe_workspace_path(export_path, art.filename)
            shutil.copy2(src, dest)
            copied.append(art.filename)

    # Bundle the ADR / decision-log pack (docx §8.6) so an enterprise engagement ships
    # the auditable "why" with the proposal. Best-effort: never block an export.
    try:
        from adr_export import write_adr_pack

        adr_path, n_adr = write_adr_pack(ws)
        if n_adr or adr_path.exists():
            shutil.copy2(adr_path, safe_workspace_path(export_path, adr_path.name))
            copied.append(adr_path.name)
    except Exception:  # noqa: BLE001
        pass

    # Record this export in the manifest
    manifest.exports.append(
        {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "export_dir": str(export_path),
            "files": copied,
        }
    )

    # Write manifest.json
    manifest_path = export_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return str(export_path), manifest


# ---------------------------------------------------------------------------
# Human-readable summary
# ---------------------------------------------------------------------------


def format_manifest(manifest: ProposalManifest) -> str:
    status_icon = "✅ FINAL" if manifest.status == "final" else "🔄 DRAFT"
    lines = [
        f"\nPROPOSAL PACKAGE — {manifest.project_title or 'Untitled'} [{status_icon}]",
        f"  Created : {manifest.created_at[:19].replace('T', ' ')}",
        f"  Manifest: {manifest.manifest_id}",
    ]

    if manifest.artifacts:
        lines.append("  Artifacts:")
        for art in manifest.artifacts:
            approved_tag = " ✅ approved" if art.approved else ""
            lines.append(f"    • {art.filename} ({art.artifact_type}){approved_tag}")
    else:
        lines.append("  Artifacts: none found")

    # Deck quality
    if manifest.slide_count:
        lines.append(
            f"  Deck    : {manifest.slide_count} slides, "
            f"{manifest.trace_coverage_pct}% grounded"
            + (
                f", structure {manifest.structure_score}/100 [{manifest.structure_grade}]"
                if manifest.structure_score is not None
                else ""
            )
        )

    # Visual audit
    if manifest.visual_audit_passed is not None:
        vis_icon = "✅" if manifest.visual_audit_passed else "⚠"
        lines.append(f"  Visual  : {vis_icon} score {manifest.visual_audit_score}/100")

    # Findings
    if manifest.open_findings_high:
        lines.append(
            f"  ⛔ {manifest.open_findings_high} HIGH finding(s) open — resolve before sending to client."
        )
    elif manifest.open_findings:
        lines.append(f"  ⚠ {manifest.open_findings} finding(s) still open.")
    else:
        lines.append("  Findings: none open.")

    if manifest.decisions_total:
        lines.append(f"  HITL decisions: {manifest.decisions_total} recorded.")

    return "\n".join(lines)
