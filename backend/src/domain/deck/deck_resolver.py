"""Resolve CSM / WBS / business-narrative -> the params each BnK slide contract needs.

``deck_sections.SECTION_CONTENT_CONTRACTS`` declares WHAT each slide needs (``params`` +
``required_inputs``); this module RESOLVES those from the real sources of truth in a
workspace: the CSM (``solution_model.json``), ``wbs.json``, ``out.slide.json``
(title/brand), and the NEW ``business_narrative.json``. It replaces the legacy path that
read ``blueprint.json`` / ``diagram_brief.json`` / ``tech_stack.json`` directly — the files
that no longer exist in CSM-era workspaces and whose absence is the concrete cause of empty
decks (see ``backend/docs/bnk_deck_sections.md`` §8).

Two entry points:
  * :func:`available_inputs` -> ``set[str]`` of resolvable required-input keys (feeds
    ``deck_sections.plannable_contracts`` / ``resolve_missing`` so a section with no data is
    skipped-and-warned, never rendered empty).
  * :func:`csm_to_slide_params` -> ``dict`` of params for ONE contract, pulled from CSM/WBS.

Plus the case-study helper :func:`pick_case_study` (matches the current CSM to a past project
from the offline ``case_library.json`` built by ``backend/scripts/build_case_library.py``).

Imports only ``csm`` + ``deck_sections`` (both cycle-free), same discipline as ``deck.py``.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from csm import SolutionModel
from domain.deck.deck_sections import SECTION_CONTENT_CONTRACTS, SectionContract
from domain.wbs.wbs_effort import cost_by_role as _cost_by_role


def _clip(text: Any, limit: int = 200) -> str:
    v = " ".join(str(text or "").split())
    return v[:limit].rstrip() + ("…" if len(v) > limit else "")


def _reqs(model: SolutionModel, kind: str) -> list[str]:
    return [r.statement for r in model.requirements if r.kind == kind]


def _components_by_cluster(model: SolutionModel) -> list[tuple[str, str, list[str]]]:
    """``[(cluster_name, cluster_purpose, [component_name, ...]), ...]`` in model order."""
    clusters = {c.id: c for c in model.components if c.kind == "cluster"}
    grouped: dict[str, list[str]] = {}
    for c in model.components:
        if c.kind == "component":
            grouped.setdefault(c.cluster, []).append(c.name)
    out: list[tuple[str, str, list[str]]] = []
    for cid, names in grouped.items():
        cl = clusters.get(cid)
        out.append((cl.name if cl else (cid or "Other"), cl.purpose if cl else "", names))
    return out


_REGULATORY_KEYWORDS = [
    "GDPR", "PCI-DSS", "PCI DSS", "UCP 600", "AML", "KYC", "HIPAA", "SOX", "SOC2", "SOC 2",
    "ISO 27001", "ISO27001", "CCPA", "PDPA", "FATCA", "Basel",
]
_GEOGRAPHY_KEYWORDS = [
    "Singapore", "Vietnam", "Ap-southeast", "ap-southeast", "Europe", "EU ", "US ", "USA",
    "APAC", "EMEA", "Japan", "Korea", "Indonesia", "Thailand", "Philippines",
]


def _find_sentences(statements: list[str], keywords: list[str]) -> list[str]:
    """Statements that mention any keyword, de-duplicated, in original order."""
    out, seen = [], set()
    for s in statements:
        low = s.lower()
        if any(kw.lower() in low for kw in keywords) and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _find_keywords_present(statements: list[str], keywords: list[str]) -> list[str]:
    """Which keywords (canonical form) appear anywhere across the statements."""
    hay = " ".join(statements).lower()
    return [kw for kw in keywords if kw.lower() in hay]


def _infer_client_info(model: SolutionModel, wbs: dict) -> dict[str, Any]:
    """Derive client/platform/geography/regulatory straight from the CSM + WBS project_info.

    No business_narrative needed for the common case — these facts are usually already
    stated as constraints/assumptions/NFRs during requirements gathering, just never
    surfaced on their own slide.
    """
    pinfo = (wbs or {}).get("project_info") or {}
    all_statements = (
        [c.statement for c in model.constraints]
        + [a.statement for a in model.assumptions]
        + [r.statement for r in model.requirements if r.kind == "nfr"]
    )

    geography = _find_sentences(
        [c.statement for c in model.constraints] + [a.statement for a in model.assumptions],
        _GEOGRAPHY_KEYWORDS,
    )
    regulatory = _find_keywords_present(all_statements, _REGULATORY_KEYWORDS)
    platform = [
        s for s in [a.statement for a in model.assumptions]
        if re.search(r"\bexisting\b.*\b(infrastructure|platform|system)\b", s, re.IGNORECASE)
    ]

    return {
        "client": pinfo.get("client") or "",
        "platform": "; ".join(_clip(p, 100) for p in platform[:2]),
        "geography": "; ".join(_clip(g, 90) for g in geography[:2]),
        "regulatory": ", ".join(regulatory) if regulatory else "",
        "business_domain": pinfo.get("business_domain") or "",
    }


def _wbs_totals(wbs: dict) -> dict[str, Any]:
    totals = (wbs or {}).get("effort_totals") or {}
    timeline = (wbs or {}).get("timeline") or {}
    return {
        "total_md": totals.get("total_mandays") or 0,
        "total_mm": totals.get("total_manmonths") or 0,
        "by_role": totals.get("effort_by_role") or {},
        "weeks": timeline.get("weeks") or 0,
        "months": timeline.get("months") or 0,
        "sprints": timeline.get("sprints") or 0,
    }


# --- default boilerplate (BnK-standard, used when nothing project-specific exists) -------

_SDLC_DEFAULT = [
    ("Analysis", "Requirement gathering & wireframing", ""),
    ("Design", "System architecture & UX design", ""),
    ("Development", "Implementation of the solution", ""),
    ("Testing", "Manual QA + SIT + UAT support", "Load/Security test per client"),
    ("Deployment", "DEV + UAT + PROD; deployment guide handover", ""),
    ("Maintenance", "Post-go-live support (1 month, defect fixes)", ""),
]
_METHODOLOGY_DEFAULT = (
    "Agile/Scrum delivery in 2-week sprints; PM acts as Scrum Master; demo & retro each sprint."
)
_POST_LAUNCH_DEFAULT = [
    "Raise ticket", "Analyze", "Propose", "Confirm", "Execute", "Deploy", "Test", "Close",
]
_CHANGE_REQUEST_DEFAULT = (
    "Changes outside the agreed scope are logged, estimated, and approved as a Change Request "
    "before implementation; effort/price adjusted accordingly."
)
_CLIENT_TEAM_DEFAULT = ["Technical Lead", "Business Analyst", "Project Manager"]
_MILESTONES_DEFAULT = ["30% kickoff", "30% dev complete", "30% UAT", "10% go-live"]
_INVOICE_TERMS_DEFAULT = "BnK issues an invoice per milestone; CUSTOMER pays within 30 days."


# --- per-contract param builders --------------------------------------------------------
# Each builder: (model, wbs, narrative, meta, library) -> params dict (or {} to skip).

def _b_cover(model, wbs, nar, meta, lib):
    return {
        "project_title": meta.get("title") or meta.get("diagram_title") or "",
        "date": meta.get("date") or "",
        "client_brand": meta.get("brand") or (nar.get("client_info") or {}).get("client") or "",
    }


def _b_exec_overview(model, wbs, nar, meta, lib):
    biz = [r.statement for r in model.requirements if r.kind == "business"]
    intro = _clip(meta.get("kicker") or (biz[0] if biz else ""), 220)
    objectives = [_clip(s) for s in (_reqs(model, "functional")[:5] or biz[:5])]
    return {"intro_paragraph": intro, "key_objectives": objectives}


def _b_goals_value(model, wbs, nar, meta, lib):
    vps = nar.get("value_props") or []
    return {"value_props": [
        {"title": _clip(v.get("title"), 60), "points": [_clip(p, 120) for p in v.get("points", [])]}
        for v in vps
    ]}


def _b_success_story(model, wbs, nar, meta, lib):
    cs = nar.get("case_study") or (pick_case_study(model, lib) if lib else None)
    if not cs:
        return {}
    return {
        "case_title": _clip(cs.get("title"), 60),
        "context_paragraph": _clip(cs.get("problem") or cs.get("context"), 300),
        "outcome": _clip(cs.get("outcome") or cs.get("solution"), 240),
        "image_ref": cs.get("image_ref"),
    }


def _b_solution_name(model, wbs, nar, meta, lib):
    return {
        "solution_name": meta.get("title") or meta.get("diagram_title") or "",
        "subtitle": "Proposed Solution | Scope of Work | Project Delivery",
    }


def _b_solution_overview(model, wbs, nar, meta, lib):
    return {
        "functionality": [_clip(s) for s in _reqs(model, "functional")],
        "non_functionality": [_clip(s) for s in _reqs(model, "nfr")],
    }


def _b_feature_list(model, wbs, nar, meta, lib):
    feats = []
    for s in _reqs(model, "functional")[:6]:
        head, _, _tail = s.partition(" (")
        feats.append({"name": _clip(head, 42), "description": _clip(s, 120)})
    return {"features": feats}


def _b_tech_stack(model, wbs, nar, meta, lib):
    rows = [
        {"layer": name, "technology": ", ".join(names[:8]), "description": _clip(purpose, 80)}
        for name, purpose, names in _components_by_cluster(model)
    ]
    return {"tech_rows": rows}


def _b_architecture(model, wbs, nar, meta, lib):
    return {"diagram_image": meta.get("png") or "out.png"}


def _b_sdlc(model, wbs, nar, meta, lib):
    return {"sdlc_phases": [{"phase": p, "in_scope": s, "out_scope": o} for p, s, o in _SDLC_DEFAULT]}


def _b_change_request(model, wbs, nar, meta, lib):
    return {"change_request_process": _CHANGE_REQUEST_DEFAULT}


def _b_delivery_effort(model, wbs, nar, meta, lib):
    t = _wbs_totals(wbs)
    rows = [
        {"module": f"{m.get('code', '')} {m.get('name', '')}".strip(), "md": m.get("total_md", 0)}
        for m in (wbs.get("effort_by_module") or [])
    ]
    return {
        "total_md": f"Total Effort: {t['total_md']} MD (~{t['total_mm']} man-months)",
        "effort_rows": rows,
    }


def _b_master_plan(model, wbs, nar, meta, lib):
    """The real Master Plan Gantt — same schedule model as the WBS Excel's
    "3. Delivery Plan" sheet (wbs_excel._module_schedule + wbs_effort.delivery_grid), so the
    deck's timeline slide and the client-facing Excel never drift apart.
    """
    from wbs_effort import delivery_grid
    from wbs_excel import _module_schedule

    t = _wbs_totals(wbs)
    weeks = int(t["weeks"] or (wbs.get("timeline") or {}).get("weeks") or 16)
    grid = delivery_grid(weeks)

    if wbs.get("phases"):
        gantt_rows = [
            {"code": m["code"], "name": m["name"],
             "start_week": m["start_week"], "end_week": m["end_week"]}
            for m in _module_schedule(wbs, grid["weeks"])
        ]
    else:
        gantt_rows = []

    return {
        "weeks": grid["weeks"], "months": grid["months"], "sprints": grid["sprints"],
        "gantt_rows": gantt_rows,
    }


def _b_risk(model, wbs, nar, meta, lib):
    return {"risks": [
        {"risk": _clip(r.statement, 90), "mitigation": _clip(r.mitigation, 90)}
        for r in model.risks
    ]}


def _b_methodology(model, wbs, nar, meta, lib):
    return {"methodology": _METHODOLOGY_DEFAULT}


def _b_post_launch(model, wbs, nar, meta, lib):
    return {"sla_process": list(_POST_LAUNCH_DEFAULT)}


def _b_team(model, wbs, nar, meta, lib):
    bnk = []
    for m in (wbs.get("team_composition") or []):
        md, hc = m.get("total_md"), m.get("est_headcount")
        if md:
            bnk.append(f"{m.get('role', 'Role')}: {md} MD" + (f" (~{hc} HC)" if hc else ""))
    return {"client_team": list(_CLIENT_TEAM_DEFAULT), "bnk_team": bnk}


def _b_capex(model, wbs, nar, meta, lib):
    from wbs_effort import DEFAULT_RATE_CARD_USD_PER_MONTH, rate_per_manday

    totals = wbs.get("effort_totals") or {}
    rate = meta.get("rate_card") or totals.get("rate_card_usd_per_month") \
        or DEFAULT_RATE_CARD_USD_PER_MONTH
    # cost_by_role_usd is written by wbs_effort.rollup() for any WBS rolled up after this
    # feature landed; older wbs.json files (rolled up before) fall back to computing it here
    # from effort_by_role + the (possibly project-overridden) rate card — CAPEX is always
    # derivable from the WBS alone, never blocked on a business-narrative input. Rate-card
    # months use a 20-workday convention (not the 22 used for total_manmonths elsewhere) —
    # see wbs_effort.RATE_CARD_WORKDAYS_PER_MONTH / rate_per_manday.
    cost_role = totals.get("cost_by_role_usd") or _cost_by_role(totals.get("effort_by_role") or {}, rate)
    total = totals.get("total_cost_usd")
    if total is None:
        total = round(sum(cost_role.values()), 2)

    rows = []
    for m in (wbs.get("effort_by_module") or []):
        md = float(m.get("total_md") or 0)
        cost = sum(
            float(b or 0) * rate_per_manday(rate.get(role, 0))
            for role, b in (m.get("breakdown") or {}).items()
        )
        rows.append({
            "module": f"{m.get('code', '')} {m.get('name', '')}".strip(),
            "md": md, "cost": round(cost),
        })
    total_cost = f"Total Cost: {round(total):,} USD (NET)"
    return {"total_cost": total_cost, "cost_rows": rows,
            "net_note": "This quotation is the NET amount; tax not included."}


def _b_opex(model, wbs, nar, meta, lib):
    return {"opex_rows": nar.get("opex") or []}     # optional; needs cost estimate upstream


def _b_milestones(model, wbs, nar, meta, lib):
    ms = [m.get("name") for m in (wbs.get("milestones") or []) if m.get("name")]
    return {"milestones": ms or list(_MILESTONES_DEFAULT), "invoice_terms": _INVOICE_TERMS_DEFAULT}


def _b_reference(model, wbs, nar, meta, lib):
    return {"screens": meta.get("screens") or []}


def _b_kpis(model, wbs, nar, meta, lib):
    return {"kpis": nar.get("kpis") or [], "business_goals": nar.get("business_goals") or []}


def _b_client_info(model, wbs, nar, meta, lib):
    inferred = _infer_client_info(model, wbs)
    override = nar.get("client_info") or {}
    merged = {**inferred, **{k: v for k, v in override.items() if v}}
    return {"client_info": merged}


def _b_advice(model, wbs, nar, meta, lib):
    ap = nar.get("advice_phase") or {}
    if not ap:
        return {}
    return {"advice_scope": ap.get("scope") or [], "advice_deliverable": ap.get("deliverable") or ""}


def _b_agenda(model, wbs, nar, meta, lib):
    sections = [
        re.sub(r"^\{roman\}\.\s*", "", c.title).strip()
        for c in SECTION_CONTENT_CONTRACTS if c.kind == "divider"
    ]
    # de-dup while preserving order (optional dividers may repeat a section name)
    seen, out = set(), []
    for s in sections:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return {"section_list": out}


_BUILDERS = {
    "cover": _b_cover, "agenda": _b_agenda,
    "exec_summary_overview": _b_exec_overview, "exec_summary_goals_value": _b_goals_value,
    "success_story": _b_success_story,
    "solution_name": _b_solution_name, "solution_overview": _b_solution_overview,
    "solution_feature_list": _b_feature_list, "solution_tech_stack": _b_tech_stack,
    "solution_architecture": _b_architecture,
    "scope_sdlc": _b_sdlc, "scope_change_request": _b_change_request,
    "delivery_effort": _b_delivery_effort, "delivery_master_plan": _b_master_plan,
    "delivery_risk": _b_risk, "delivery_methodology": _b_methodology,
    "delivery_post_launch": _b_post_launch, "delivery_team": _b_team,
    "pricing_capex": _b_capex, "pricing_opex": _b_opex, "pricing_milestones": _b_milestones,
    "reference_screens": _b_reference,
    "kpis": _b_kpis, "client_info": _b_client_info, "advice_phase": _b_advice,
}


def csm_to_slide_params(
    model: SolutionModel,
    wbs: Optional[dict],
    contract: SectionContract,
    *,
    narrative: Optional[dict] = None,
    meta: Optional[dict] = None,
    library: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """Params for ONE contract, resolved from CSM/WBS/narrative. ``{}`` => skip (no data)."""
    fn = _BUILDERS.get(contract.key)
    if fn is None:
        return {}
    return fn(model, wbs or {}, narrative or {}, meta or {}, library or [])


def available_inputs(
    model: SolutionModel,
    wbs: Optional[dict],
    *,
    narrative: Optional[dict] = None,
    meta: Optional[dict] = None,
    has_diagram: bool = False,
) -> set[str]:
    """Resolvable required-input keys for this workspace (feeds ``plannable_contracts``)."""
    wbs, nar, meta = wbs or {}, narrative or {}, meta or {}
    a: set[str] = set()
    if meta.get("title") or any(r.kind == "business" for r in model.requirements):
        a |= {"brief.objective", "blueprint.slide_title"}
    if any(r.kind == "functional" for r in model.requirements):
        a.add("brief.functional_requirements")
    if any(c.kind == "component" for c in model.components):
        a.add("tech_stack.layers")
    if wbs.get("effort_totals"):
        a.add("wbs.effort_totals")
    if wbs.get("timeline"):
        a.add("wbs.timeline")
    if wbs.get("phases"):
        a.add("wbs.phases")
    if wbs.get("effort_by_module"):
        a.add("wbs.effort_by_module")
    if model.risks:
        a.add("csm.risks")
    if has_diagram or meta.get("png"):
        a.add("out.png")
    for key in ("value_props", "case_study", "kpis", "client_info", "advice_phase"):
        if nar.get(key):
            a.add(f"business_narrative.{key}")
    # Library fallback: success_story is satisfiable even without a narrative case_study,
    # because pick_case_study() can source one from the past-project library. success_story
    # stays optional and skips cleanly if the pick returns None at render time.
    if nar.get("case_study") is None:
        a.add("business_narrative.case_study")
    # client_info is mostly CSM-derivable (client/domain from wbs.project_info, geography
    # from constraints/assumptions, regulatory from NFRs) — no business_narrative needed
    # for the common case; see _infer_client_info.
    if (wbs.get("project_info") or {}).get("client") or model.constraints or model.assumptions:
        a.add("business_narrative.client_info")
    if wbs.get("effort_by_module"):
        a |= {"tech_stack.opex", "tech_stack.cost"}  # OPEX derivable from module cost
    # pricing (CAPEX) is always derivable from wbs.effort_totals + the default rate card —
    # never blocked on a business-narrative rate_card override.
    return a


# --- case-study library (built offline from DATA/SLIDE_IMAGES/*/analysis.md) ------------

def pick_case_study(model: SolutionModel, library: list[dict]) -> Optional[dict]:
    """Top-1 past project by domain/tech overlap with the current CSM (None if no overlap)."""
    if not library:
        return None
    hay = " ".join(
        [c.name for c in model.components] + [d.title for d in model.decisions]
        + [r.statement for r in model.requirements]
    ).lower()
    best, best_score = None, 0
    for entry in library:
        score = sum(1 for t in entry.get("tech", []) if t.lower() in hay)
        score += sum(2 for d in entry.get("domain", []) if d.lower() in hay)
        if score > best_score:
            best, best_score = entry, score
    return best if best_score > 0 else None
