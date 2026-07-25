"""Deck plan store (docx §4.8) — a traceable PPT storyboard wired into the CSM.

Today the PPT pipeline generates a slide outline *inline* (`ppt_reporting.
_generate_slide_outline`), renders it and throws it away. Nothing is persisted, so
the storyboard cannot be reviewed before the file is built, no slide claim is tied
to a CSM entity, and a deck can silently "claim" a component that does not exist
(the failure docx §4.4 calls out).

This module makes the deck a first-class, traceable artifact — a *projection* of the
CSM, never a source of truth:

  * `SlideSpec` / `DeckPlan` — the persisted storyboard. `SlideSpec` is a SUPERSET of
    the outline dict `ppt_reporting._render_slide` already understands (title / layout
    / block / bullets / asset_ref), plus `source_refs` (the CSM entity ids the slide
    is grounded in) and `narrative_role` — so the existing renderer consumes it as-is.
  * `build_deck_plan` — assemble the FIXED BnK storyboard (Exec Summary -> Proposed
    Solution -> Tech Stack -> Scope -> Delivery/Effort/Timeline -> Risk -> Pricing,
    matching the 66 reference decks in DATA/SLIDE) from the CSM. Each slide's bullets
    and `source_refs` are derived from the entities themselves, so a claim is grounded
    *by construction*. Deterministic — no LLM, no I/O.
  * `validate_deck` — structured findings (docx §4.3 taxonomy): a `source_ref` that
    does not resolve, missing narrative coverage, an effort number that disagrees with
    the WBS, or a client-facing pricing/version claim with no Evidence behind it.
  * `project_into_csm` — fold the plan into a `SolutionModel` as `Deliverable`
    entities + `visualizes` / `claims` trace links (docx §6.2).

Like `evidence.py` / `decisions.py`, it imports ONLY from `csm` (never `csm_adapter`
or `ppt_reporting`), so the adapter can call `project_into_csm` and the renderer can
read the plan without an import cycle.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable, Literal, Optional

from pydantic import BaseModel, Field

from csm import Deliverable, SolutionModel, SourceRef, TraceLink, mint_id
from domain.deck.deck_resolver import available_inputs, csm_to_slide_params
from domain.deck.deck_sections import (
    IMPLEMENTED_BLOCKS,
    SECTION_CONTENT_CONTRACTS,
    SectionContract,
    plannable_contracts,
)

logger = logging.getLogger(__name__)

DECK_PLAN_NAME = "deck_plan.json"
DECK_QA_NAME = "deck_qa_result.json"

# Layout / block names MUST match ppt_reporting.VALID_LAYOUTS / VALID_BLOCKS. Kept as
# literal strings here (not imported) so deck.py stays free of a ppt_reporting cycle.
# The last 4 (case_study/kpis/client_info/advice) are the deck_sections.Role superset —
# not rendered by the registry-driven builder until WS2/WS3 add their block renderer, but
# declared here now so a future SlideSpec carrying one of them validates cleanly.
NarrativeRole = Literal[
    "context",
    "objective",
    "solution",
    "architecture",
    "scope",
    "effort",
    "timeline",
    "risk",
    "pricing",
    "case_study",
    "kpis",
    "client_info",
    "advice",
]

# Roles the storyboard MUST cover for a complete proposal (docx §7.1 deck gate).
REQUIRED_ROLES: tuple[str, ...] = ("objective", "solution", "scope", "effort", "timeline")


class SlideSpec(BaseModel):
    """One storyboard slide. A superset of the render outline dict + traceability."""

    slide_no: int
    section: str = ""
    title: str = ""
    layout: str = "Detail-01"
    block: str = "bullets"
    bullets: list[str] = Field(default_factory=list)
    asset_ref: Optional[str] = None
    narrative_role: NarrativeRole = "solution"
    source_refs: list[str] = Field(default_factory=list)  # CSM entity ids this slide is grounded in
    client_facing: bool = False  # external-facing claim => must be evidence-backed
    # Full params dict resolved by deck_resolver.csm_to_slide_params for this contract —
    # today's renderers (ppt_reporting._render_block) still derive their own data from
    # `report`/`workspace` and ignore this field (harmless extra key on model_dump()); it
    # exists so a NEW block renderer (case_study, methodology, ...) has a clean single
    # source to read from instead of re-deriving CSM/WBS data itself.
    params: dict[str, Any] = Field(default_factory=dict)


class DeckPlan(BaseModel):
    """The persisted storyboard — a projection of the CSM, reviewed before rendering."""

    revision: int = 1
    created_at: Optional[str] = None  # injected; excluded from the content hash
    title: str = ""
    subtitle: str = ""
    brand: str = ""
    audience: str = "client"
    slides: list[SlideSpec] = Field(default_factory=list)

    def content_hash(self) -> str:
        payload = self.model_dump(exclude={"created_at", "revision"})
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_json(self) -> str:
        data = self.model_dump()
        data["sha256"] = self.content_hash()
        return json.dumps(data, indent=2, ensure_ascii=False)

    def roles(self) -> set[str]:
        return {s.narrative_role for s in self.slides}


# --- building the storyboard from the CSM ------------------------------------


def _clip(text: Any, limit: int = 200) -> str:
    value = " ".join(str(text or "").split())
    return value[:limit].rstrip() + ("..." if len(value) > limit else "")


def _wbs_totals(wbs: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Pull the headline delivery numbers from wbs.json (effort_totals + P50/P80)."""
    wbs = wbs or {}
    totals = wbs.get("effort_totals") or {}
    items = wbs.get("items") or []
    p50 = sum(float(it.get("pert_p50_md") or 0) for it in items if isinstance(it, dict))
    p80 = sum(float(it.get("pert_p80_md") or 0) for it in items if isinstance(it, dict))
    timeline = wbs.get("timeline") or {}
    return {
        "total_mandays": totals.get("total_mandays") or 0,
        "total_manmonths": totals.get("total_manmonths") or 0,
        "p50_md": round(p50, 1),
        "p80_md": round(p80, 1),
        "weeks": timeline.get("weeks") or 0,
        "months": timeline.get("months") or 0,
        "sprints": timeline.get("sprints") or 0,
    }


# --- registry-driven storyboard (deck_sections.SECTION_CONTENT_CONTRACTS) -----

_ROMAN_NUMERALS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]


def _roman(n: int) -> str:
    return _ROMAN_NUMERALS[n - 1] if 1 <= n <= len(_ROMAN_NUMERALS) else str(n)


# Contracts whose slide is client-facing (cites pricing/versions) and therefore wants an
# Evidence source_ref behind it — mirrors _build_deck_plan_legacy's own client_facing=True
# slides exactly (technical_stack / pricing CAPEX).
_CLIENT_FACING_KEYS = frozenset({"solution_tech_stack", "pricing_capex"})


def _has_real_content(params: dict[str, Any]) -> bool:
    """True when at least one resolved param actually carries data. An empty dict, or a
    dict whose every value is itself empty/falsy (e.g. ``{"screens": []}``), means the
    builder found nothing usable — the contract is skipped rather than rendered with a
    blank body / an unreplaced ``{placeholder}`` in the title."""
    return any(v for v in params.values())


def _contract_title(contract: SectionContract, params: dict[str, Any]) -> str:
    """Most contracts show their fixed template title; a couple resolve the REAL title
    from params (e.g. solution_name's big Overview-01 heading is the project's actual
    name, not the literal string "Solution Proposal")."""
    if contract.key == "solution_name" and params.get("solution_name"):
        return str(params["solution_name"])
    return contract.title


def _contract_bullets(key: str, params: dict[str, Any]) -> list[str]:
    """Shape a builder's params dict into the plain bullet list some consumers read.

    The renderer for most structured blocks (func_nfr/sdlc/gantt/pricing/team/...) ignores
    SlideSpec.bullets entirely — it re-derives its data straight from wbs.json/report at
    render time. But `validate_deck`'s consistency check greps the delivery_effort slide's
    *bullets* text for the stated WBS total (it has no other way to know what the slide
    will say), so that one block's params ARE mirrored into bullets even though the
    renderer itself won't read them — keeps the QA layer meaningful for the registry path.
    """
    if key == "exec_summary_overview":
        bullets = [params["intro_paragraph"]] if params.get("intro_paragraph") else []
        return bullets + list(params.get("key_objectives") or [])
    if key == "solution_name":
        return [params["subtitle"]] if params.get("subtitle") else []
    if key == "delivery_effort":
        return [params["total_md"]] if params.get("total_md") else []
    return []


def _contract_source_refs(
    contract: SectionContract,
    *,
    comp_ids: list[str],
    dec_ids: list[str],
    evd_ids: list[str],
    wbs_ids: list[str],
    req_ids_by_kind: dict[str, list[str]],
) -> list[str]:
    """Grounding ids for validate_deck's traceability/evidence checks — mirrors what
    _build_deck_plan_legacy attached to the equivalent slide, so switching builders does
    not regress the QA layer for the contracts both paths share."""
    key = contract.key
    if key == "exec_summary_overview":
        return req_ids_by_kind["business"] or req_ids_by_kind["functional"]
    if key == "solution_overview":  # the func_nfr slide
        return req_ids_by_kind["functional"] + req_ids_by_kind["nfr"]
    if key == "solution_architecture":
        return comp_ids
    if key == "solution_tech_stack":
        return dec_ids + evd_ids
    if key in ("delivery_effort", "delivery_master_plan"):
        return wbs_ids
    if key == "pricing_capex":
        return wbs_ids + evd_ids
    return []


def _is_plan_healthy(plan: "DeckPlan") -> bool:
    """A sanity floor for the registry-driven plan — same bar validate_deck/
    score_deck_structure already enforce, checked BEFORE writing so a broken registry
    walk falls back to the legacy sequence instead of shipping a thin deck."""
    return len(plan.slides) >= 5 and set(REQUIRED_ROLES) <= plan.roles()


def _build_deck_plan_registry(
    model: SolutionModel,
    *,
    wbs: dict[str, Any],
    narrative: dict[str, Any],
    meta: dict[str, Any],
    library: list[dict[str, Any]],
    has_diagram: bool,
    title: str,
    subtitle: str,
    brand: str,
) -> DeckPlan:
    """Assemble the storyboard by walking ``deck_sections.SECTION_CONTENT_CONTRACTS``
    instead of a hand-written sequence. Each content contract's params are resolved via
    ``deck_resolver.csm_to_slide_params``; a contract with unmet ``required_inputs`` is
    skipped (never rendered thin — the fix for the "no content" bug the registry exists
    for). Only contracts whose ``block`` is already in ``deck_sections.IMPLEMENTED_BLOCKS``
    are emitted — the rest (methodology, risk_table, case_study, opex, ...) are picked up
    automatically the moment a later workstream adds their ppt_reporting renderer and adds
    the block name to IMPLEMENTED_BLOCKS; nothing here needs to change when that happens.

    A section divider is buffered and only actually emitted once at least one content
    contract in the same section survives (missing-input skip / unimplemented-block skip
    would otherwise leave an orphaned "II. Success Story" header with nothing behind it) —
    and roman numerals are assigned at emit time, so a fully-skipped section doesn't burn
    a numeral and leave a visible I/II/IV gap.
    """
    avail = available_inputs(model, wbs, narrative=narrative, meta=meta, has_diagram=has_diagram)

    comp_ids = [c.id for c in model.components]
    dec_ids = [d.id for d in model.decisions]
    evd_ids = [e.id for e in model.evidence]
    wbs_ids = [w.id for w in model.work_items]
    req_ids_by_kind = {
        "business": [r.id for r in model.requirements if r.kind == "business"],
        "functional": [r.id for r in model.requirements if r.kind == "functional"],
        "nfr": [r.id for r in model.requirements if r.kind == "nfr"],
    }

    slides: list[SlideSpec] = []
    roman_counter = 0
    pending_divider: Optional[dict[str, Any]] = None

    def flush_pending_divider() -> None:
        nonlocal pending_divider, roman_counter
        if pending_divider is None:
            return
        roman_counter += 1
        slides.append(
            SlideSpec(
                slide_no=len(slides) + 1,
                section=pending_divider["section"],
                title=pending_divider["title"].replace("{roman}", _roman(roman_counter)),
                layout=pending_divider["layout"],
                block="bullets",
                narrative_role=pending_divider["role"],
            )
        )
        pending_divider = None

    for contract, missing in plannable_contracts(avail, include_optional=True):
        if contract.kind == "closing":
            continue  # _append_thank_you handles this unconditionally, always
        if contract.kind == "divider":
            pending_divider = {
                "title": contract.title,
                "section": contract.section,
                "role": contract.role,
                "layout": contract.layout,
            }
            continue
        if contract.kind == "content" and missing:
            continue  # required input unmet — skip cleanly, never render thin
        if contract.block not in IMPLEMENTED_BLOCKS:
            continue  # no renderer yet for this block — auto-included once one lands

        if contract.kind == "cover":
            slides.append(
                SlideSpec(
                    slide_no=len(slides) + 1,
                    section=contract.section,
                    title="",
                    layout=contract.layout,
                    block="bullets",
                    narrative_role=contract.role,
                )
            )
            continue

        params = csm_to_slide_params(model, wbs, contract, narrative=narrative, meta=meta, library=library)
        if not _has_real_content(params):
            continue  # the builder found nothing usable — skip, never render blank/{placeholder}

        block, asset_ref = contract.block, None
        if block == "diagram":
            # Drive through the EXISTING asset_ref-based dispatch in ppt_reporting._render_slide
            # (Empty layout + asset_ref=="architecture_diagram") — zero ppt_reporting changes
            # needed for the registry path to reach the same diagram-embed code legacy uses.
            block, asset_ref = "bullets", "architecture_diagram"

        flush_pending_divider()

        slides.append(
            SlideSpec(
                slide_no=len(slides) + 1,
                section=contract.section,
                title=_contract_title(contract, params),
                layout=contract.layout,
                block=block,
                bullets=_contract_bullets(contract.key, params),
                asset_ref=asset_ref,
                narrative_role=contract.role,
                source_refs=_contract_source_refs(
                    contract,
                    comp_ids=comp_ids,
                    dec_ids=dec_ids,
                    evd_ids=evd_ids,
                    wbs_ids=wbs_ids,
                    req_ids_by_kind=req_ids_by_kind,
                ),
                client_facing=contract.key in _CLIENT_FACING_KEYS,
                params=params,
            )
        )

    return DeckPlan(
        title=title or str(meta.get("title") or meta.get("diagram_title") or ""),
        subtitle=subtitle or str(meta.get("kicker") or ""),
        brand=brand or str(meta.get("brand") or ""),
        slides=slides,
    )


def build_deck_plan(
    model: SolutionModel,
    *,
    wbs: Optional[dict[str, Any]] = None,
    brief: Optional[dict[str, Any]] = None,
    meta: Optional[dict[str, Any]] = None,
    narrative: Optional[dict[str, Any]] = None,
    library: Optional[list[dict[str, Any]]] = None,
    has_diagram: bool = False,
    title: str = "",
    subtitle: str = "",
    brand: str = "",
) -> DeckPlan:
    """Assemble the BnK storyboard from the CSM (deterministic, no LLM, no I/O).

    Drives ``deck_sections.SECTION_CONTENT_CONTRACTS`` (the canonical registry) via
    :func:`_build_deck_plan_registry` — content whose required inputs are unmet is
    skipped, never rendered thin. Falls back to :func:`_build_deck_plan_legacy` (the
    original hand-written sequence) if the registry path errors or produces an unhealthy
    plan (too few slides / missing a required narrative role) — a defensive net while the
    registry's renderer coverage is still growing (see ``deck_sections.IMPLEMENTED_BLOCKS``).

    New optional inputs beyond the legacy signature:
      * ``meta`` — ``out.slide.json`` (title/kicker/brand/diagram png ref); the legacy
        function actually reads these off ``brief`` even though real workspaces write
        them to ``out.slide.json``, not ``diagram_brief.json`` — this param is the fix.
      * ``narrative`` — ``business_narrative.json`` (case_study/value_props/kpis/...),
        absent in most workspaces today; every builder degrades gracefully without it.
      * ``library`` — the legacy case_library.json keyword-fallback corpus for
        ``pick_case_study``; optional because the primary semantic-retrieval path
        (``rag.solution_memory``) needs no library at all.
    """
    wbs = wbs or {}
    brief = brief or {}
    meta = meta or {}
    narrative = narrative or {}
    library = library or []

    plan: Optional[DeckPlan] = None
    try:
        plan = _build_deck_plan_registry(
            model,
            wbs=wbs,
            narrative=narrative,
            meta=meta,
            library=library,
            has_diagram=has_diagram,
            title=title,
            subtitle=subtitle,
            brand=brand,
        )
    except Exception:  # noqa: BLE001 — a registry regression must never block deck generation
        logger.exception("Registry-driven deck plan build failed — falling back to the legacy sequence.")
        plan = None

    if plan is not None:
        if _is_plan_healthy(plan):
            return plan
        logger.warning(
            "Registry-driven deck plan looked unhealthy (%d slides, roles=%s) — "
            "falling back to the legacy sequence.",
            len(plan.slides),
            sorted(plan.roles()),
        )

    return _build_deck_plan_legacy(
        model,
        wbs=wbs,
        brief=brief,
        has_diagram=has_diagram,
        title=title,
        subtitle=subtitle,
        brand=brand,
    )


def _build_deck_plan_legacy(
    model: SolutionModel,
    *,
    wbs: Optional[dict[str, Any]] = None,
    brief: Optional[dict[str, Any]] = None,
    has_diagram: bool = False,
    title: str = "",
    subtitle: str = "",
    brand: str = "",
) -> DeckPlan:
    """The original hand-written storyboard sequence (deterministic, no LLM, no I/O).

    Bullets and `source_refs` are derived from the CSM entities a slide presents, so a
    claim is grounded by construction; `validate_deck` then enforces that grounding.

    Kept as the defensive fallback for :func:`build_deck_plan` — see that function's
    docstring. Prefer extending ``deck_sections.SECTION_CONTENT_CONTRACTS`` +
    ``deck_resolver`` over this function; it exists only so a registry regression never
    takes deck generation down with it.
    """
    brief = brief or {}
    totals = _wbs_totals(wbs)

    req_business = [r for r in model.requirements if r.kind == "business"]
    req_func = [r for r in model.requirements if r.kind == "functional"]
    req_nfr = [r for r in model.requirements if r.kind == "nfr"]
    comp_ids = [c.id for c in model.components]
    dec_ids = [d.id for d in model.decisions]
    evd_ids = [e.id for e in model.evidence]
    con_ids = [c.id for c in model.constraints]
    asm_ids = [a.id for a in model.assumptions]
    wbs_ids = [w.id for w in model.work_items]
    risk_entities = list(model.risks)

    objective = _clip(brief.get("objective") or "", 280)
    exec_bullets = ([objective] if objective else []) + [
        _clip(r.statement) for r in (req_business or model.requirements)[:5]
    ]

    slides: list[SlideSpec] = []

    def add(role: NarrativeRole, **kw: Any) -> None:
        slides.append(SlideSpec(slide_no=len(slides) + 1, narrative_role=role, **kw))

    # 1 — Cover
    add("context", section="cover", title="", layout="Cover-01", block="bullets")
    # 2-3 — Executive Summary
    add(
        "context",
        section="executive_summary",
        title="I. Executive Summary",
        layout="Head Page",
        block="bullets",
    )
    add(
        "objective",
        section="executive_summary",
        title="EXECUTIVE SUMMARY | Overview",
        layout="Detail-01",
        block="bullets",
        bullets=exec_bullets or ["(objective TBD)"],
        source_refs=[r.id for r in (req_business or model.requirements)[:5]],
    )
    # 4-6 — Proposed Solution
    add(
        "solution",
        section="solution_overview",
        title="II. Proposed Solution",
        layout="Head Page",
        block="bullets",
    )
    add(
        "solution",
        section="solution_overview",
        title="PROPOSED SOLUTION | Overview",
        layout="Overview-01",
        block="bullets",
        bullets=[_clip(objective or "A centralized platform delivering the scope below.", 200)],
        source_refs=comp_ids,
    )
    add(
        "objective",
        section="solution_overview",
        title="PROPOSED SOLUTION | Requirements",
        layout="Detail-01",
        block="func_nfr",
        source_refs=[r.id for r in (req_func + req_nfr)],
    )
    # 7-8 — Architecture (only when a rendered diagram exists)
    if has_diagram:
        add(
            "architecture",
            section="architecture_diagram",
            title="Architecture Overview",
            layout="Head-01",
            block="bullets",
        )
        add(
            "architecture",
            section="architecture_diagram",
            title="",
            layout="Empty",
            block="bullets",
            asset_ref="architecture_diagram",
            source_refs=comp_ids,
        )
    # 9 — Technical Stack (cites versions => client-facing, wants evidence)
    add(
        "solution",
        section="technical_stack",
        title="PROPOSED SOLUTION | Technical Stack",
        layout="Detail-01",
        block="tech_stack_table",
        source_refs=dec_ids + evd_ids,
        client_facing=True,
    )
    # 10-12 — Scope of Work
    add("scope", section="scope", title="IV. Scope of Work", layout="Head Page", block="bullets")
    add("scope", section="scope", title="SCOPE OF WORK | SDLC Phases", layout="Detail-01", block="sdlc")
    add(
        "scope",
        section="scope",
        title="SCOPE OF WORK | Assumptions & Constraints",
        layout="Detail-01",
        block="bullets",
        bullets=[_clip(c.statement) for c in model.constraints]
        + [_clip(a.statement) for a in model.assumptions],
        source_refs=con_ids + asm_ids,
    )
    # 13-16 — Project Delivery
    add("effort", section="delivery_plan", title="V. Project Delivery", layout="Head Page", block="bullets")
    add(
        "effort",
        section="delivery_plan",
        title="PROJECT DELIVERY | Estimated Effort",
        layout="Detail-01",
        block="delivery_effort",
        bullets=[
            f"Total Effort: {totals['total_mandays']} MD (~{totals['total_manmonths']} man-months)",
            f"P50 estimate: {totals['p50_md']} MD",
            f"P80 estimate: {totals['p80_md']} MD",
        ],
        source_refs=wbs_ids,
    )
    add(
        "timeline",
        section="delivery_plan",
        title="PROJECT DELIVERY | Master Plan & Milestones",
        layout="Detail-01",
        block="gantt",
        bullets=[
            f"Timeline: {totals['weeks']} weeks (~{totals['months']} months)",
            f"Delivery in {totals['sprints']} two-week sprints",
        ],
        source_refs=wbs_ids,
    )
    add(
        "effort",
        section="delivery_plan",
        title="PROJECT DELIVERY | Team Structure",
        layout="Detail-01",
        block="team",
    )
    # 17 — Risks
    add(
        "risk",
        section="risks",
        title="PROJECT DELIVERY | Risks & Mitigations",
        layout="Detail-01",
        block="bullets",
        bullets=[
            _clip(f"{r.statement}" + (f" -> {r.mitigation}" if r.mitigation else "")) for r in risk_entities
        ]
        or ["No material delivery risks identified."],
        source_refs=[r.id for r in risk_entities],
    )
    # 18-20 — Pricing (CAPEX cites pricing => client-facing, wants evidence)
    add("pricing", section="pricing", title="VI. Pricing", layout="Head Page", block="bullets")
    add(
        "pricing",
        section="pricing",
        title="PRICING | CAPEX",
        layout="Detail-01",
        block="pricing",
        source_refs=wbs_ids + evd_ids,
        client_facing=True,
    )
    add(
        "pricing",
        section="pricing",
        title="PRICING | Payment Milestones",
        layout="Detail-01",
        block="milestones",
    )

    return DeckPlan(
        title=title or str(brief.get("slide_title") or ""),
        subtitle=subtitle or str(brief.get("slide_kicker") or ""),
        brand=brand or str(brief.get("brand") or ""),
        slides=slides,
    )


# --- validation (docx §4.3 / §4.4 / §7.1 deck gate) --------------------------


def validate_deck(plan: DeckPlan, model: SolutionModel) -> list[dict[str, Any]]:
    """Deterministic structured findings over the storyboard. Empty list == clean.

    Each finding mirrors the §4.3 taxonomy:
    `{finding_id, severity, dimension, artifact_type, slide_no, entity_ids,
      evidence, recommendation, status}`.
    """
    findings: list[dict[str, Any]] = []
    model_ids = model.ids()
    evidence_ids = {e.id for e in model.evidence}
    n = 0

    def finding(
        severity: str,
        dimension: str,
        slide_no: int,
        entity_ids: list[str],
        evidence: str,
        recommendation: str,
    ) -> None:
        nonlocal n
        n += 1
        findings.append(
            {
                "finding_id": f"DECK-{n:03d}",
                "severity": severity,
                "dimension": dimension,
                "artifact_type": "deck_plan",
                "slide_no": slide_no,
                "entity_ids": entity_ids,
                "evidence": evidence,
                "recommendation": recommendation,
                "status": "open",
            }
        )

    # 1. Traceability — every source_ref must resolve to a CSM entity (docx §4.4).
    for s in plan.slides:
        dangling = [ref for ref in s.source_refs if ref not in model_ids]
        if dangling:
            finding(
                "high",
                "traceability",
                s.slide_no,
                dangling,
                f"Slide {s.slide_no} '{s.title}' claims entities not in the solution model: "
                + ", ".join(dangling),
                "Remove the slide claim or add the entity to the CSM before rendering.",
            )

    # 2. Completeness — required narrative roles must each have a slide (docx §7.1).
    present = plan.roles()
    missing_roles = [r for r in REQUIRED_ROLES if r not in present]
    if missing_roles:
        finding(
            "medium",
            "completeness",
            0,
            [],
            "Storyboard is missing required narrative roles: " + ", ".join(missing_roles),
            "Add slides covering: " + ", ".join(missing_roles) + ".",
        )

    # 3. Consistency — the effort slide must agree with the WBS total in the CSM.
    wbs_total = round(sum(w.effort_mandays for w in model.work_items), 1)
    if wbs_total > 0:
        for s in plan.slides:
            if s.block != "delivery_effort":
                continue
            joined = " ".join(s.bullets)
            if not _mentions_number(joined, wbs_total):
                finding(
                    "high",
                    "consistency",
                    s.slide_no,
                    [w.id for w in model.work_items],
                    f"Effort slide does not state the WBS total of {wbs_total} MD (bullets: {joined!r}).",
                    f"Restate total effort as {wbs_total} MD to match the WBS roll-up.",
                )

    # 4. Evidence — a client-facing pricing/version claim needs an Evidence source_ref
    #    (docx §5.4: customer-facing deck only uses grounded claims).
    for s in plan.slides:
        if not s.client_facing:
            continue
        if not any(ref in evidence_ids for ref in s.source_refs):
            finding(
                "medium",
                "evidence",
                s.slide_no,
                list(s.source_refs),
                f"Client-facing slide '{s.title}' cites pricing/versions with no grounded "
                "Evidence (EVD-*) behind it.",
                "Record an Evidence claim (record_evidence) and reference it, or mark the "
                "slide internal-only.",
            )

    return findings


_NUMBER_RE = re.compile(r"(?<![A-Za-z\d.])\d+(?:\.\d+)?(?![\d.])")


def _mentions_number(text: str, value: float) -> bool:
    """True when `text` states `value` as a standalone number (e.g. 82 or 82.0).

    Numbers glued to a letter (the "50" inside the label "P50") are NOT a match — only
    free-standing figures count, so the WBS total must actually be quoted on the slide.
    """
    found = {float(m) for m in _NUMBER_RE.findall(text)}
    return any(abs(f - value) < 0.05 for f in found)


# --- store -------------------------------------------------------------------


def _plan_path(workspace: Optional[Path]) -> Path:
    if workspace is None:
        from backends import current_workspace

        workspace = current_workspace()
    return Path(workspace) / DECK_PLAN_NAME


def write_deck_plan(plan: DeckPlan, workspace: Optional[Path] = None) -> Path:
    """Write the storyboard to `deck_plan.json`, preserving revision when unchanged."""
    path = _plan_path(workspace)
    prev = load_deck_plan(workspace)
    if prev is not None:
        if prev.content_hash() == plan.content_hash():
            plan.revision = prev.revision
            plan.created_at = prev.created_at
        else:
            plan.revision = prev.revision + 1
            plan.created_at = plan.created_at or prev.created_at
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.to_json(), encoding="utf-8")
    return path


def load_deck_plan(workspace: Optional[Path] = None) -> Optional[DeckPlan]:
    """Load `deck_plan.json`; returns None when absent or unreadable."""
    path = _plan_path(workspace)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    try:
        return DeckPlan.model_validate(raw)
    except Exception:  # noqa: BLE001 — a malformed plan should not crash a build
        return None


# --- structural quality scorer -----------------------------------------------

# Thresholds for per-slide rules.
_MAX_BULLETS = 8  # more → "wall of text"
_MAX_TITLE_LEN = 80  # characters
_MIN_BULLETS_CONTENT = 1  # section covers + cover may have 0 bullets legitimately


def score_deck_structure(plan: DeckPlan) -> dict:
    """Rule-based structural quality score (0-100).

    Scores the deck plan without visual rendering or an LLM.  Every rule is a
    deterministic check on the storyboard shape (slide count, title length,
    bullet density, source coverage).

    Returns a dict with keys:
      * ``score``          — float [0, 100]
      * ``grade``          — letter A/B/C/D/F
      * ``issues``         — list[str] of human-readable violation messages
      * ``slide_scores``   — list[dict] with per-slide breakdown
    """
    issues: list[str] = []
    slide_scores: list[dict] = []
    deduct: float = 0.0

    # Layout names that are decoration / section dividers (allow 0 bullets).
    _section_layouts = {"Cover-01", "Head Page", "cover", "section"}

    for s in plan.slides:
        slide_issues: list[str] = []
        is_section = s.layout in _section_layouts or s.block == "section"

        # Title length
        if len(s.title) > _MAX_TITLE_LEN:
            msg = f"slide {s.slide_no}: title too long ({len(s.title)} chars > {_MAX_TITLE_LEN})"
            issues.append(msg)
            slide_issues.append(msg)
            deduct += 2.0

        # Bullet density
        n_bullets = len(s.bullets)
        if n_bullets > _MAX_BULLETS:
            msg = f"slide {s.slide_no}: too many bullets ({n_bullets} > {_MAX_BULLETS})"
            issues.append(msg)
            slide_issues.append(msg)
            deduct += 2.0

        # Empty content slides
        if not is_section and n_bullets < _MIN_BULLETS_CONTENT and not s.asset_ref:
            msg = f"slide {s.slide_no}: content slide has no bullets and no asset_ref"
            issues.append(msg)
            slide_issues.append(msg)
            deduct += 1.0

        # Ungrounded client-facing slide
        if s.client_facing and not s.source_refs:
            msg = f"slide {s.slide_no}: client-facing slide has no source_refs (ungrounded)"
            issues.append(msg)
            slide_issues.append(msg)
            deduct += 5.0

        # Non-section slide without any source_refs
        elif not is_section and not s.source_refs:
            msg = f"slide {s.slide_no}: content slide has no source_refs"
            issues.append(msg)
            slide_issues.append(msg)
            deduct += 2.0

        slide_scores.append(
            {
                "slide_no": s.slide_no,
                "title": s.title,
                "issues": slide_issues,
            }
        )

    # Overall deck rules
    n_slides = len(plan.slides)
    if n_slides < 5:
        msg = f"deck has too few slides ({n_slides} < 5)"
        issues.append(msg)
        deduct += 10.0
    elif n_slides > 30:
        msg = f"deck is very long ({n_slides} slides > 30)"
        issues.append(msg)
        deduct += 5.0

    missing_roles = [r for r in REQUIRED_ROLES if r not in plan.roles()]
    if missing_roles:
        for role in missing_roles:
            msg = f"missing required narrative role: {role}"
            issues.append(msg)
            deduct += 8.0

    score = max(0.0, min(100.0, 100.0 - deduct))
    grade = (
        "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D" if score >= 45 else "F"
    )

    return {
        "score": round(score, 1),
        "grade": grade,
        "issues": issues,
        "slide_scores": slide_scores,
        "deductions": round(deduct, 1),
    }


# --- projection into the CSM -------------------------------------------------


def project_into_csm(model: SolutionModel, plan: Optional[DeckPlan]) -> SolutionModel:
    """Fold the deck plan into `model` in place (and return it).

    The deck becomes one `Deliverable` (kind="pptx", id "ART-deck"); every slide with
    a resolvable `source_ref` becomes a `Deliverable` (kind="slide", id "SLIDE-<n>")
    plus trace links: `visualizes` to architecture entities (COMP/FLOW) and `claims`
    to proposal entities (DEC/REQ/EVD). Only existing targets are linked.

    Deterministic: slides processed in order, ids stable, re-projection is a no-op
    (so the content hash is unchanged on a rebuild).
    """
    if plan is None:
        return model

    deck_id = mint_id("deliverable", "deck")
    if deck_id in model.ids():
        return model  # already projected (defensive)

    comp_ids = {c.id for c in model.components}
    claim_ids = (
        {d.id for d in model.decisions} | {r.id for r in model.requirements} | {e.id for e in model.evidence}
    )
    existing = model.ids()
    deck_sources: list[str] = []

    for s in sorted(plan.slides, key=lambda x: x.slide_no):
        resolved = [ref for ref in s.source_refs if ref in existing]
        if not resolved:
            continue
        slide_id = mint_id("slide", s.slide_no)
        model.deliverables.append(
            Deliverable(
                id=slide_id,
                kind="slide",
                title=s.title or f"Slide {s.slide_no}",
                solution_revision=model.revision,
                source_entity_ids=list(resolved),
                provenance="agent",
                source_refs=[SourceRef(kind="derived", ref=DECK_PLAN_NAME)],
            )
        )
        for target in resolved:
            relation = "visualizes" if target in comp_ids else ("claims" if target in claim_ids else None)
            if relation is None:
                continue
            model.trace_links.append(
                TraceLink(from_id=slide_id, to_id=target, relation=relation, provenance="agent")
            )
        for ref in resolved:
            if ref not in deck_sources:
                deck_sources.append(ref)

    model.deliverables.append(
        Deliverable(
            id=deck_id,
            kind="pptx",
            title=plan.title or "Proposal deck",
            solution_revision=model.revision,
            source_entity_ids=deck_sources,
            provenance="agent",
            source_refs=[SourceRef(kind="derived", ref=DECK_PLAN_NAME)],
        )
    )
    return model
