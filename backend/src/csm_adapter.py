"""Projection: build a `SolutionModel` from the existing artifact files.

This is the "wrap, don't rewrite" adapter (docx §13.5). It reads the artifacts the
pipeline already writes (`diagram_brief.json`, `blueprint.json`, `wbs.json`) and
compiles them into one ID'd `SolutionModel`, then writes `solution_model.json`.

Design choices that keep it safe to drop in:
  * **No pipeline change** — it only reads existing files; stages keep writing JSON.
  * **Stable IDs** — components key off the blueprint's snake_case node ids, work
    items off their wbs id/ref_code; requirements/decisions/assumptions are ordinal.
    Re-running over the SAME artifacts yields the SAME ids (and the same content hash).
  * **Same soft-match** as `solution_validator` / `traceability`, imported (not copied)
    so all three agree on what "covered" means.
  * **Stable revision** — if `solution_model.json` already exists and the content hash
    is unchanged, the revision (and created_at) are preserved; a real change bumps it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal, Optional

from csm import (
    Assumption,
    Component,
    Constraint,
    Decision,
    Requirement,
    Risk,
    SolutionModel,
    SourceRef,
    TraceLink,
    WorkItem,
    mint_id,
    slug,
)
from solution_validator import _as_list, _read_json, _soft_match

SOLUTION_MODEL_NAME = "solution_model.json"
SOLUTION_MODEL_PREV_NAME = "solution_model.prev.json"
APPROVED_DIR_NAME = "approved"


def archive_approved_revision(workspace: Optional[Path] = None) -> Optional[Path]:
    """Snapshot the current `solution_model.json` as an immutable approved revision.

    Called when a human approves a gate (§4.10 "immutable approved revisions"). Copies
    the current model to ``approved/REV-<n>.json`` and marks it read-only so the exact
    state a stakeholder signed off on can always be reproduced/audited. Idempotent: if a
    snapshot for the current revision already exists it is left untouched. Never raises —
    archival must not break a HITL resume.
    """
    if workspace is None:
        from backends import WORKSPACE
        workspace = WORKSPACE
    workspace = Path(workspace)
    src = workspace / SOLUTION_MODEL_NAME
    if not src.exists():
        return None
    try:
        raw = _read_json(src, {}) or {}
        revision = int(raw.get("revision") or 1)
        approved_dir = workspace / APPROVED_DIR_NAME
        approved_dir.mkdir(parents=True, exist_ok=True)
        dest = approved_dir / f"REV-{revision}.json"
        if dest.exists():
            return dest  # already archived this revision — keep the original sign-off
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            import stat
            dest.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)  # read-only marker
        except OSError:
            pass  # chmod is best-effort (e.g. restrictive Windows ACLs)
        return dest
    except Exception:  # noqa: BLE001
        return None


def _src(ref: str) -> list[SourceRef]:
    return [SourceRef(kind="document", ref=ref)]


def _requirements(brief: dict[str, Any]) -> list[Requirement]:
    out: list[Requirement] = []
    n = 0
    for kind, key in (("functional", "functional_requirements"),
                      ("nfr", "non_functional_requirements")):
        for item in _as_list(brief.get(key)):
            n += 1
            rid, text = "", item
            if isinstance(item, dict):
                rid = str(item.get("id") or "")
                text = item.get("statement") or item.get("text") or item.get("name") or ""
            text = str(text).strip()
            if not text:
                continue
            out.append(Requirement(
                id=rid or mint_id("requirement", n),
                kind=kind, statement=text, provenance="agent",
                source_refs=_src("diagram_brief.json"),
            ))
    return out


_MUST_CONFIRM_RE = re.compile(
    r"(\$|budget|cost\b|costs\b|pricing|fee\b|fees\b|eur\b|usd\b|sgd\b|myr\b|rm\b)"
    r"|(deadline|go.?live|launch date|due date|by q[1-4]\b|by (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))"
    r"|(hipaa|gdpr|pci.?dss?|soc\s?2|iso\s?27|sox\b|fda\b|compliance|regulatory|legal\s+require|audit)"
    r"|(sla\b|uptime|latency|p99\b|p95\b|response.?time|throughput|availability|99\.\d+%)",
    re.IGNORECASE,
)

_NICE_CONFIRM_RE = re.compile(
    r"\b(best practice|typically|usually|standard approach|conventional|by default|prefer)",
    re.IGNORECASE,
)


def _classify_assumption_tier(
    statement: str,
) -> Literal["must_confirm", "should_confirm", "nice_to_confirm"]:
    """Keyword-based tier: must_confirm (financial/deadline/compliance/SLA),
    nice_to_confirm (generic best-practice), should_confirm (everything else)."""
    if _MUST_CONFIRM_RE.search(statement):
        return "must_confirm"
    if _NICE_CONFIRM_RE.search(statement):
        return "nice_to_confirm"
    return "should_confirm"


def _assumptions(brief: dict[str, Any]) -> list[Assumption]:
    out: list[Assumption] = []
    for i, item in enumerate(_as_list(brief.get("assumptions")), start=1):
        text = str(item).strip()
        if text:
            out.append(Assumption(
                id=mint_id("assumption", i), statement=text, status="pending",
                confidence_tier=_classify_assumption_tier(text),
                provenance="agent", source_refs=_src("diagram_brief.json"),
            ))
    return out


def _components(blueprint: dict[str, Any]) -> list[Component]:
    out: list[Component] = []
    for c in _as_list(blueprint.get("clusters")):
        if not isinstance(c, dict) or not c.get("id"):
            continue
        out.append(Component(
            id=mint_id("cluster", str(c.get("id"))), kind="cluster",
            name=str(c.get("label") or c.get("id")), purpose=str(c.get("tier") or ""),
            provenance="agent", source_refs=_src("blueprint.json"),
        ))
    for n in _as_list(blueprint.get("nodes")):
        if not isinstance(n, dict) or not n.get("id"):
            continue
        ntype = str(n.get("type") or "")
        kind = "integration" if ntype == "external" else "component"
        out.append(Component(
            id=mint_id("component", str(n.get("id"))), kind=kind,
            name=str(n.get("label") or n.get("id")),
            cluster=mint_id("cluster", str(n.get("cluster"))) if n.get("cluster") else "",
            purpose=str(n.get("tech") or ""),
            provenance="agent", source_refs=_src("blueprint.json"),
        ))
    return out


# architecture_analysis.json `constraints` are short tags (architecture_advisor._constraints);
# map them onto the CSM Constraint.kind vocabulary.
_CONSTRAINT_TAG_KIND = {
    "budget_sensitive": "budget",
    "compliance_sensitive": "compliance",
    "governance_required": "compliance",
    "resilience_required": "other",
    "production_focused": "other",
}


def _constraints(brief: dict[str, Any], analysis: dict[str, Any]) -> list[Constraint]:
    """Constraints from the brief's free-text layout constraints + the analysis tags."""
    out: list[Constraint] = []
    n = 0
    for item in _as_list(brief.get("layout_constraints")):
        text = str(item).strip()
        if not text:
            continue
        n += 1
        out.append(Constraint(
            id=mint_id("constraint", n), statement=text, kind="other",
            provenance="agent", source_refs=_src("diagram_brief.json"),
        ))
    for tag in _as_list(analysis.get("constraints")):
        tag = str(tag).strip()
        if not tag:
            continue
        n += 1
        out.append(Constraint(
            id=mint_id("constraint", n), statement=tag.replace("_", " "),
            kind=_CONSTRAINT_TAG_KIND.get(tag, "other"),
            provenance="deterministic", source_refs=_src("architecture_analysis.json"),
        ))
    return out


def _risk_fields(item: Any) -> tuple[str, str]:
    """Pull (statement, mitigation) from a tech/blueprint risk dict or bare string."""
    if isinstance(item, dict):
        return (
            str(item.get("risk") or item.get("statement") or "").strip(),
            str(item.get("mitigation") or "").strip(),
        )
    return str(item).strip(), ""


def _risks(tech_stack: dict[str, Any], blueprint: dict[str, Any]) -> list[Risk]:
    """Risks from per-layer tech_stack risks + any blueprint-level risks (de-duped)."""
    out: list[Risk] = []
    seen: set[str] = set()
    n = 0

    # tech_stack.json stores layers under `layers` (dict keyed by layer name).
    layers = tech_stack.get("layers")
    layer_iter = layers.values() if isinstance(layers, dict) else _as_list(layers)
    for source, items in (
        ("tech_stack.json", (
            r for layer in layer_iter if isinstance(layer, dict)
            for r in _as_list(layer.get("risks"))
        )),
        ("blueprint.json", _as_list(blueprint.get("risks"))),
    ):
        for item in items:
            stmt, mit = _risk_fields(item)
            if not stmt or stmt in seen:
                continue
            seen.add(stmt)
            n += 1
            out.append(Risk(
                id=mint_id("risk", n), statement=stmt, mitigation=mit,
                provenance="agent", source_refs=_src(source),
            ))
    return out


def _decisions(blueprint: dict[str, Any]) -> list[Decision]:
    out: list[Decision] = []
    for i, d in enumerate(_as_list(blueprint.get("key_decisions")), start=1):
        title = str(d).strip()
        if title:
            out.append(Decision(
                id=mint_id("decision", i), title=title, status="proposed",
                provenance="agent", source_refs=_src("blueprint.json"),
            ))
    return out


def _work_items(wbs: dict[str, Any]) -> list[WorkItem]:
    out: list[WorkItem] = []
    for i, it in enumerate(_as_list(wbs.get("items")), start=1):
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or it.get("deliverable") or "").strip()
        if not name:
            continue
        key = str(it.get("id") or it.get("ref_code") or it.get("code") or slug(name)[:24])
        try:
            md = float(it.get("total_md") or it.get("mandays") or 0) or 0.0
        except (TypeError, ValueError):
            md = 0.0
        sprint_raw = it.get("assigned_sprint")
        out.append(WorkItem(
            id=mint_id("work_item", key), name=name, effort_mandays=md,
            parent=str(it.get("module") or it.get("phase") or ""),
            predecessors=[str(p) for p in _as_list(it.get("predecessors"))],
            pert_expected_md=float(it.get("pert_expected_md") or 0),
            owner=str(it.get("owner") or "") or None,
            definition_of_done=list(it.get("acceptance_criteria") or []),
            assigned_sprint=(int(sprint_raw) if sprint_raw is not None else None),
            provenance="agent", source_refs=_src("wbs.json"),
        ))
    return out


def _trace_links(model: SolutionModel) -> list[TraceLink]:
    """Soft-match typed edges over CSM ids:

      REQ  --satisfies--> COMP
      WBS  --implements--> COMP / REQ
      CON  --constrains--> COMP / REQ
      DEC  --assumes--> ASM
      DEC / COMP --mitigates--> RISK
    """
    comp_by_name = {c.name: c.id for c in model.components}
    comp_names = list(comp_by_name.keys())
    req_by_text = {r.statement: r.id for r in model.requirements}
    req_texts = list(req_by_text.keys())
    asm_by_text = {a.statement: a.id for a in model.assumptions}
    asm_texts = list(asm_by_text.keys())
    risk_by_text = {r.statement: r.id for r in model.risks}
    risk_texts = list(risk_by_text.keys())

    links: list[TraceLink] = []
    for r in model.requirements:
        for hit in _soft_match(r.statement, comp_names):
            links.append(TraceLink(from_id=r.id, to_id=comp_by_name[hit], relation="satisfies"))
    for w in model.work_items:
        for hit in _soft_match(w.name, comp_names):
            links.append(TraceLink(from_id=w.id, to_id=comp_by_name[hit], relation="implements"))
        for hit in _soft_match(w.name, req_texts):
            links.append(TraceLink(from_id=w.id, to_id=req_by_text[hit], relation="implements"))
    for c in model.constraints:
        for hit in _soft_match(c.statement, comp_names):
            links.append(TraceLink(from_id=c.id, to_id=comp_by_name[hit], relation="constrains"))
        for hit in _soft_match(c.statement, req_texts):
            links.append(TraceLink(from_id=c.id, to_id=req_by_text[hit], relation="constrains"))
    for d in model.decisions:
        for hit in _soft_match(d.title, asm_texts):
            links.append(TraceLink(from_id=d.id, to_id=asm_by_text[hit], relation="assumes"))
        for hit in _soft_match(d.title, risk_texts):
            links.append(TraceLink(from_id=d.id, to_id=risk_by_text[hit], relation="mitigates"))
    for comp in model.components:
        for hit in _soft_match(comp.name, risk_texts):
            links.append(TraceLink(from_id=comp.id, to_id=risk_by_text[hit], relation="mitigates"))
    return links


def from_artifacts(
    brief: dict[str, Any],
    blueprint: dict[str, Any],
    wbs: dict[str, Any],
    *,
    analysis: Optional[dict[str, Any]] = None,
    tech_stack: Optional[dict[str, Any]] = None,
) -> SolutionModel:
    """Pure projection: artifact dicts -> SolutionModel. No I/O, easy to unit-test.

    `analysis` (architecture_analysis.json) and `tech_stack` (tech_stack.json) are
    optional so the 3-arg call stays back-compatible; they feed Constraint/Risk entities.
    """
    model = SolutionModel(
        requirements=_requirements(brief),
        constraints=_constraints(brief, analysis or {}),
        assumptions=_assumptions(brief),
        decisions=_decisions(blueprint),
        components=_components(blueprint),
        risks=_risks(tech_stack or {}, blueprint),
        work_items=_work_items(wbs),
    )
    model.trace_links = _trace_links(model)
    return model


def build_solution_model(
    workspace: Optional[Path] = None,
    *,
    created_at: Optional[str] = None,
) -> SolutionModel:
    """Read the workspace artifacts, project to CSM, write `solution_model.json`.

    Preserves `revision`/`created_at` when the content hash is unchanged, bumps the
    revision when it changes — so a re-run over identical artifacts is idempotent and
    a real change is visible to a change-impact diff.
    """
    if workspace is None:
        from backends import WORKSPACE
        workspace = WORKSPACE
    workspace = Path(workspace)

    model = from_artifacts(
        _read_json(workspace / "diagram_brief.json", {}) or {},
        _read_json(workspace / "blueprint.json", {}) or {},
        _read_json(workspace / "wbs.json", {}) or {},
        analysis=_read_json(workspace / "architecture_analysis.json", {}) or {},
        tech_stack=_read_json(workspace / "tech_stack.json", {}) or {},
    )

    # Fold any HITL v2 decisions (accepted risks, confirmed assumptions, ...) into
    # the model so the validator / change-impact / epistemic summary see them. A new
    # decision changes the content hash and therefore bumps the revision below.
    from decisions import project_into_csm, read_decisions
    project_into_csm(model, read_decisions(workspace))

    # Fold grounded claims (web research / document evidence) into the model as
    # Evidence entities + `supports` trace links, back-filling Decision.evidence_ids.
    # New evidence changes the content hash and therefore bumps the revision below.
    from evidence import project_into_csm as project_evidence, read_evidence
    project_evidence(model, read_evidence(workspace))

    # Fold the deck storyboard (if planned) into the model as Deliverable entities +
    # `visualizes` / `claims` trace links, so a slide can never claim a component that
    # is not in the CSM. No-op until `deck_plan.json` exists; a new/changed plan bumps
    # the revision below.
    from deck import load_deck_plan, project_into_csm as project_deck
    project_deck(model, load_deck_plan(workspace))

    # Fold the active compliance pack (if one was selected via apply_compliance_pack)
    # into the model as Control entities + implements/mitigates/supports links. No-op
    # until `compliance_pack.json` marks a pack; a new/changed pack bumps the revision.
    from compliance import project_into_csm as project_compliance
    project_compliance(model, workspace)

    prev = _read_json(workspace / SOLUTION_MODEL_NAME, {}) or {}
    new_hash = model.content_hash()
    if prev.get("sha256") == new_hash:
        # Nothing changed — keep the prior revision/timestamp so the model is idempotent.
        model.revision = int(prev.get("revision") or 1)
        model.created_at = prev.get("created_at")
    else:
        # Content changed — snapshot the prior model as the change-impact "before".
        src = workspace / SOLUTION_MODEL_NAME
        if src.exists():
            (workspace / SOLUTION_MODEL_PREV_NAME).write_text(
                src.read_text(encoding="utf-8"), encoding="utf-8")
        model.revision = int(prev.get("revision") or 0) + 1
        model.created_at = created_at if created_at is not None else prev.get("created_at")

    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / SOLUTION_MODEL_NAME).write_text(model.to_json(), encoding="utf-8")
    return model
