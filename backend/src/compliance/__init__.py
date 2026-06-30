"""Compliance packs (docx §4 P2, §10.3, §13.2) — reusable control/evidence mapping.

A *pack* declares the controls a standard requires (encryption, audit logging, …).
`apply_pack` projects those controls into the `SolutionModel` as `Control` entities,
wiring `implements` links to the work/components that satisfy them and `mitigates`
links to the risks they address — all deterministic and keyword-driven so re-running
over the same model yields the same ids and hash. `evidence_gaps` / `compliance_findings`
then surface required controls that are unimplemented or ungrounded, so a client-facing
claim like "SOC 2 ready" can be blocked until it is backed by evidence (§4.4).

This package imports ONLY from `csm` and `solution_validator` (never `csm_adapter`) to
stay free of import cycles, mirroring `evidence.py` / `decisions.py`.

The *active* pack for a workspace is recorded in ``compliance_pack.json`` (a single
marker, set by the `apply_compliance_pack` tool); `build_solution_model` reads it and
folds the controls in after evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from csm import Control, SolutionModel, TraceLink, mint_id

PACKS_DIR = Path(__file__).parent / "packs"
COMPLIANCE_PACK_MARKER = "compliance_pack.json"


# --- pack loading ------------------------------------------------------------

def list_packs() -> list[str]:
    """Names of the packs bundled under packs/ (without the .json suffix)."""
    if not PACKS_DIR.exists():
        return []
    return sorted(p.stem for p in PACKS_DIR.glob("*.json"))


def load_pack(name: str) -> Optional[dict[str, Any]]:
    """Read a pack definition by name; None if it does not exist or is malformed."""
    from safe_path import safe_filename
    path = PACKS_DIR / f"{safe_filename(name)}.json"
    if not path.suffix == ".json":
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# --- active-pack marker (per workspace) --------------------------------------

def _marker_path(workspace: Optional[Path]) -> Path:
    if workspace is None:
        from backends import WORKSPACE
        workspace = WORKSPACE
    return Path(workspace) / COMPLIANCE_PACK_MARKER


def set_active_pack(pack_name: str, workspace: Optional[Path] = None) -> None:
    path = _marker_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pack": pack_name}, indent=2), encoding="utf-8")


def get_active_pack(workspace: Optional[Path] = None) -> Optional[str]:
    path = _marker_path(workspace)
    if not path.exists():
        return None
    try:
        return (json.loads(path.read_text(encoding="utf-8")) or {}).get("pack")
    except (OSError, json.JSONDecodeError):
        return None


# --- matching helpers --------------------------------------------------------

def _entity_text(*parts: Any) -> str:
    out: list[str] = []
    for p in parts:
        if isinstance(p, (list, tuple)):
            out.extend(str(x) for x in p)
        elif p:
            out.append(str(p))
    return " ".join(out).lower()


def _matches(text: str, keywords: list[str]) -> bool:
    return any(kw.lower() in text for kw in keywords or [])


# --- projection --------------------------------------------------------------

def apply_pack(model: SolutionModel, pack_name: str) -> SolutionModel:
    """Mint the pack's controls into ``model`` (idempotent). Returns the same model.

    For each declared control: a stable ``CTRL-<pack>_<key>`` entity is added (skipped
    if already present), implemented_by/evidence are inferred by keyword match against
    the model's work items, components and evidence, and `implements`/`mitigates`/
    `supports` trace links are appended. Deterministic: no clocks, stable ids.
    """
    pack = load_pack(pack_name)
    if not pack:
        return model
    existing_ids = model.ids()
    existing_links = {(t.from_id, t.to_id, t.relation) for t in model.trace_links}

    # Build searchable corpora once.
    work_corpus = [
        (w.id, _entity_text(w.name, w.definition_of_done)) for w in model.work_items
    ]
    comp_corpus = [
        (c.id, _entity_text(c.name, c.purpose)) for c in model.components
    ]
    evid_corpus = [
        (e.id, _entity_text(e.claim, e.quote_or_excerpt)) for e in model.evidence
    ]
    risk_corpus = [
        (r.id, _entity_text(r.statement, r.mitigation)) for r in model.risks
    ]

    def _add_link(from_id: str, to_id: str, relation: str) -> None:
        key = (from_id, to_id, relation)
        if key in existing_links:
            return
        existing_links.add(key)
        model.trace_links.append(
            TraceLink(from_id=from_id, to_id=to_id, relation=relation, provenance="deterministic")
        )

    for spec in pack.get("controls", []):
        key = spec.get("key")
        if not key:
            continue
        cid = mint_id("control", f"{pack['name']}_{key}")
        keywords = spec.get("keywords", [])

        implemented_by = [eid for eid, txt in (work_corpus + comp_corpus) if _matches(txt, keywords)]
        evidence_ids = [eid for eid, txt in evid_corpus if _matches(txt, keywords)]

        if cid not in existing_ids:
            model.controls.append(
                Control(
                    id=cid,
                    provenance="deterministic",
                    statement=spec.get("statement", ""),
                    kind=spec.get("kind", "other"),
                    standard_ref=spec.get("standard_ref", ""),
                    status="implemented" if implemented_by else "required",
                    implemented_by_ids=implemented_by,
                    evidence_ids=evidence_ids,
                )
            )
            existing_ids.add(cid)
        else:
            # Refresh inferred coverage on a control that already exists.
            ctrl = model.by_id(cid)
            if isinstance(ctrl, Control):
                ctrl.implemented_by_ids = implemented_by
                ctrl.evidence_ids = evidence_ids
                if ctrl.status != "waived":
                    ctrl.status = "implemented" if implemented_by else "required"

        for impl_id in implemented_by:
            _add_link(impl_id, cid, "implements")
        for evd_id in evidence_ids:
            _add_link(evd_id, cid, "supports")
        for rid, txt in risk_corpus:
            if _matches(txt, keywords):
                _add_link(cid, rid, "mitigates")

    return model


def project_into_csm(model: SolutionModel, workspace: Optional[Path] = None) -> SolutionModel:
    """Fold the workspace's active compliance pack (if any) into ``model``."""
    pack_name = get_active_pack(workspace)
    if pack_name:
        apply_pack(model, pack_name)
    return model


# --- gaps + findings ---------------------------------------------------------

def evidence_gaps(model: SolutionModel) -> list[Control]:
    """Required controls that are unimplemented and/or ungrounded (no evidence)."""
    gaps: list[Control] = []
    for c in model.controls:
        if c.status == "waived":
            continue
        if not c.evidence_ids or not c.implemented_by_ids:
            gaps.append(c)
    return gaps


def compliance_findings(model: SolutionModel) -> list:
    """SolutionFindings for the active compliance posture (dimension='compliance').

    * No implementation AND no evidence → high / human_decision (missing control).
    * Implemented but no evidence       → medium / request_evidence (unproven control).
    """
    from solution_validator import SolutionFinding

    findings: list = []
    for c in model.controls:
        if c.status == "waived":
            continue
        grounded = bool(c.evidence_ids)
        implemented = bool(c.implemented_by_ids)
        if grounded:
            continue
        if not implemented:
            findings.append(
                SolutionFinding(
                    severity="high",
                    dimension="compliance",
                    artifact_type="requirement",
                    entity_ids=[c.id],
                    title=f"Required control missing: {c.kind}",
                    detail=(
                        f"{c.id} ({c.statement!r}, {c.standard_ref}) has no implementing "
                        f"component/work item and no evidence."
                    ),
                    recommendation="Add work to implement the control or waive it with rationale.",
                    repair_strategy="human_decision",
                    requires_human_decision=True,
                )
            )
        else:
            findings.append(
                SolutionFinding(
                    severity="medium",
                    dimension="compliance",
                    artifact_type="requirement",
                    entity_ids=[c.id],
                    title=f"Control lacks evidence: {c.kind}",
                    detail=(
                        f"{c.id} ({c.standard_ref}) is implemented by "
                        f"{', '.join(c.implemented_by_ids)} but has no evidence record."
                    ),
                    recommendation="Attach an evidence record (record_evidence) proving the control.",
                    repair_strategy="request_evidence",
                )
            )
    return findings
