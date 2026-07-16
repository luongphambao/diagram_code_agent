"""Diagram brief, tech stack, blueprint, inspect/critique tools — the core HITL
gate sequence that runs before rendering."""

from __future__ import annotations

import json
import os
from typing import Annotated, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool

from backends import current_workspace
from domain.diagram.findings import DiagramFinding, format_critique, prune, verdict_for
from domain.reporting.reporting import record_report_step
from ..constants import (
    CRITIC_REVISION_HARD_CAP,
    _ARCH_ANALYSIS_FILE,
    _BLUEPRINT_FILE,
    _BRIEF_FILE,
    _CRITIQUE_FILE,
    _ICON_PLAN_FILE,
    _RENDER_SPEC_FILE,
    _REVISION_COUNT_FILE,
    _TECHSTACK_FILE,
)
from ..icon_tools import _icon_rel, _search_icon_hits
from ..stage_markers import (
    _bump_tool_summary,
    _inspection_image_b64,
    _layout_audit,
    _read_json_file,
    _reset_revision_count,
    reset_render_count,
)
from ..schemas.brief import DiagramBrief
from ..schemas.blueprint import Blueprint
from ..schemas.tech_stack import (
    CostRange,
    ProposeTechStackArgs,
    ScalingPhase,
    SolutionAssumptions,
    TechAlternative,
    TechChoice,
    TechRisk,
)
from .gates import _solution_gate_note


@tool(parse_docstring=True)
def propose_diagram_brief(brief: DiagramBrief) -> str:
    """Record the diagram requirements brief before recommending a tech stack.

    Captures objective, stakeholders, requirements, constraints, and assumptions so
    later blueprint and rendering decisions stay grounded and simplification choices
    are explicit. This is NOT a human-approval gate.

    When to use: after reading the user's prompt and any attached documents, before
    propose_tech_stack.

    Args:
        brief: The structured diagram brief (objective, stakeholders, functional and
            non-functional requirements, constraints, and assumptions).
    """
    current_workspace().mkdir(parents=True, exist_ok=True)
    _BRIEF_FILE.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
    record_report_step(
        current_workspace(),
        "propose_diagram_brief",
        summary=(
            f"Recorded diagram brief with {len(brief.functional_requirements)} functional "
            f"and {len(brief.non_functional_requirements)} non-functional requirements."
        ),
        data=brief.model_dump(),
    )
    return (
        "Diagram brief recorded. Next: propose the technology stack with "
        "propose_tech_stack."
    )


@tool(args_schema=ProposeTechStackArgs)
def propose_tech_stack(
    tech_stack: list[TechChoice],
    assumptions: Optional[SolutionAssumptions] = None,
    scaling_roadmap: Optional[list[ScalingPhase]] = None,
    estimated_total_monthly_cost_usd: Optional[CostRange] = None,
) -> str:
    """Propose the technology stack for the user to review and approve.

    `tech_stack` is a LIST of layers, each an object with layer, choice, rationale,
    cost_tier, decision_criteria, alternatives, estimated_monthly_cost_usd,
    capacity_sizing, performance_target, risks.

    Core layers (always consider): frontend, backend, database, auth, infra,
    monitoring, networking, security.
    Conditional layers (add when requirements call for it): cache, queue, cdn,
    search, storage, ci_cd, analytics, ai_ml, integration.

    `assumptions` captures the sizing basis (budget, user scale, data, team,
    availability, compliance) BEFORE listing tech choices — state assumptions
    explicitly, put unconfirmed ones in confirm_with_customer.

    `scaling_roadmap` is a 2-3 phase roadmap with measurable triggers.
    `estimated_total_monthly_cost_usd` is the sum across all layers.

    This PAUSES for human approval — only call it once you have analysed the
    requirements. If rejected you get the user's note — revise and propose again.
    """
    if not _BRIEF_FILE.exists():
        return "Create the diagram brief first by calling propose_diagram_brief."
    current_workspace().mkdir(parents=True, exist_ok=True)

    layers_dict = {
        t.layer: {
            "choice": t.choice,
            "rationale": t.rationale,
            "cost_tier": t.cost_tier,
            "decision_criteria": t.decision_criteria.model_dump() if t.decision_criteria else None,
            "alternatives": [
                a.model_dump() if isinstance(a, TechAlternative) else {"name": str(a), "why_rejected": ""}
                for a in t.alternatives
            ],
            "estimated_monthly_cost_usd": t.estimated_monthly_cost_usd.model_dump() if t.estimated_monthly_cost_usd else None,
            "capacity_sizing": t.capacity_sizing,
            "performance_target": t.performance_target,
            "risks": [r.model_dump() if isinstance(r, TechRisk) else r for r in t.risks],
        }
        for t in tech_stack
    }

    as_dict: dict = {
        "assumptions": assumptions.model_dump() if assumptions else None,
        "layers": layers_dict,
        "scaling_roadmap": [p.model_dump() if isinstance(p, ScalingPhase) else p for p in (scaling_roadmap or [])],
        "estimated_total_monthly_cost_usd": estimated_total_monthly_cost_usd.model_dump() if estimated_total_monthly_cost_usd else None,
    }

    warnings: list[str] = []

    if not assumptions:
        warnings.append(
            "No sizing assumptions recorded — a senior proposal states budget, user scale, and concurrency explicitly."
        )
    elif not assumptions.confirm_with_customer:
        warnings.append(
            "confirm_with_customer is empty — list every assumption that has NOT been validated by the customer."
        )

    layers_without_cost = [t.layer for t in tech_stack if not t.estimated_monthly_cost_usd]
    if layers_without_cost:
        warnings.append(f"Layers missing cost estimate: {', '.join(layers_without_cost)}.")

    if estimated_total_monthly_cost_usd and assumptions and assumptions.monthly_budget_range_usd:
        budget_max = assumptions.monthly_budget_range_usd.max_usd
        if estimated_total_monthly_cost_usd.max_usd > budget_max:
            warnings.append(
                f"Total cost ceiling ${estimated_total_monthly_cost_usd.max_usd}/mo exceeds budget "
                f"${budget_max}/mo — adjust design or re-scope."
            )

    if estimated_total_monthly_cost_usd:
        layer_min_sum = sum(
            t.estimated_monthly_cost_usd.min_usd for t in tech_stack if t.estimated_monthly_cost_usd
        )
        if layer_min_sum > estimated_total_monthly_cost_usd.max_usd:
            warnings.append(
                f"Sum of layer minimums (${layer_min_sum}/mo) exceeds stated total maximum "
                f"(${estimated_total_monthly_cost_usd.max_usd}/mo) — cost estimates are inconsistent."
            )

    analysis_file = current_workspace() / "architecture_analysis.json"
    if analysis_file.exists():
        try:
            import json as _json
            analysis = _json.loads(analysis_file.read_text(encoding="utf-8"))
            sec_level = (analysis.get("security_level") or "").lower()
            layer_names = {t.layer for t in tech_stack}
            if sec_level in ("high", "critical"):
                for required in ("security", "networking"):
                    if required not in layer_names:
                        warnings.append(
                            f"security_level is '{sec_level}' but layer '{required}' is missing — "
                            "add it or document why it's omitted."
                        )
        except Exception:
            pass

    _TECHSTACK_FILE.write_text(json.dumps(as_dict, indent=2), encoding="utf-8")
    record_report_step(
        current_workspace(),
        "propose_tech_stack",
        summary=f"Approved technology stack covering {len(layers_dict)} layer(s).",
        data=as_dict,
    )

    result = (
        "Tech stack APPROVED. Next: design the architecture and call "
        "propose_blueprint with the components, clusters and connections."
    )
    if warnings:
        result += "\n\nSoft warnings (informational — does not block):\n" + "\n".join(f"• {w}" for w in warnings)
    return result


def _req_soft_match(requirement: str, candidates: list[str]) -> bool:
    """Return True if any candidate substring-matches the requirement text."""
    req_norm = requirement.lower().replace("-", " ").replace("_", " ")
    for c in candidates:
        c_norm = c.lower().replace("-", " ").replace("_", " ")
        terms = [t for t in c_norm.split() if len(t) > 3]
        if terms and any(t in req_norm for t in terms):
            return True
    return False


def _validate_pillar_coverage(blueprint: Blueprint) -> list[str]:
    """Return warning strings for pillars with no addressed_by AND no gaps declared."""
    if blueprint.pillar_coverage is None:
        return ["pillar_coverage not provided — add Well-Architected pillar coverage to the blueprint."]
    warnings: list[str] = []
    coverage = blueprint.pillar_coverage
    for pillar_name in ("operational_excellence", "security", "reliability",
                        "performance_efficiency", "cost_optimization", "sustainability"):
        pillar = getattr(coverage, pillar_name)
        if not pillar.addressed_by and not pillar.gaps:
            warnings.append(
                f"Pillar '{pillar_name}': no addressed_by nodes and no declared gaps — "
                "populate addressed_by with node IDs / decisions, or add a gap with explanation."
            )
    return warnings


def _validate_nfr_mapping(blueprint: Blueprint) -> list[str]:
    """Return unmapped NFRs: NFRs in the brief that have no entry in blueprint.nfr_mapping."""
    if not _BRIEF_FILE.exists():
        return []
    try:
        brief_data = json.loads(_BRIEF_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    brief_nfrs: list[str] = brief_data.get("non_functional_requirements", [])
    if not brief_nfrs:
        return []
    mapped_nfrs = [m.nfr for m in blueprint.nfr_mapping]
    unmapped = [
        nfr for nfr in brief_nfrs
        if not _req_soft_match(nfr, mapped_nfrs)
    ]
    return unmapped


def _validate_req_coverage(blueprint: Blueprint) -> tuple[int, int, list[str]]:
    """Return (covered_count, total_count, list_of_uncovered) for functional requirements."""
    if not _BRIEF_FILE.exists():
        return 0, 0, []
    try:
        brief_data = json.loads(_BRIEF_FILE.read_text(encoding="utf-8"))
    except Exception:
        return 0, 0, []
    func_reqs: list[str] = brief_data.get("functional_requirements", [])
    if not func_reqs:
        return 0, 0, []
    candidates: list[str] = []
    for node in blueprint.nodes:
        if node.label:
            candidates.append(node.label)
        if node.id:
            candidates.append(node.id)
    for cluster in blueprint.clusters:
        if cluster.label:
            candidates.append(cluster.label)
    candidates.extend(blueprint.key_decisions)
    covered = [req for req in func_reqs if _req_soft_match(req, candidates)]
    uncovered = [req for req in func_reqs if not _req_soft_match(req, candidates)]
    return len(covered), len(func_reqs), uncovered


def _detect_provider() -> str:
    """Read provider from architecture_analysis.json, fall back to empty string."""
    try:
        analysis = json.loads(_ARCH_ANALYSIS_FILE.read_text(encoding="utf-8"))
        return (analysis.get("provider_preference") or "").strip().lower()
    except Exception:
        return ""


def _build_render_spec(blueprint: Blueprint, provider: str) -> dict:
    """Build a compact render spec dict from an approved blueprint."""
    legend = [{"label": le.label, "flow": le.flow} for le in blueprint.legend]
    if not legend:
        _flow_labels = {
            "data": "Data Flow", "control": "Control Flow", "serving": "Serving / Inference",
            "registry": "Registry & Storage", "monitoring": "Monitoring", "security": "Security",
        }
        seen: list[str] = []
        for e in blueprint.edges:
            if e.flow and e.flow not in seen:
                seen.append(e.flow)
        legend = [{"label": _flow_labels.get(f, f.title()), "flow": f} for f in seen]
    return {
        "provider": provider,
        "pattern": blueprint.pattern,
        "density": blueprint.density,
        "presentation_style": blueprint.presentation_style,
        "layout_intent": blueprint.layout_intent,
        "slide_title": blueprint.slide_title,
        "slide_kicker": blueprint.slide_kicker,
        "brand": blueprint.brand,
        "diagram_title": blueprint.diagram_title,
        "legend": legend,
        "nodes": [
            {"id": n.id, "label": n.label, "tech": n.tech, "cluster": n.cluster, "type": n.type}
            for n in blueprint.nodes
        ],
        "clusters": [
            {"id": c.id, "label": c.label, "tier": c.tier,
             "parent": c.parent, "accent": c.accent, "number": c.number,
             "zone": c.zone}
            for c in blueprint.clusters
        ],
        "edges": [
            {"from": e.from_, "to": e.to, "label": e.label, "protocol": e.protocol,
             "flow": e.flow, "style": e.style}
            for e in blueprint.edges
        ],
    }


def _preseed_icon_plan(blueprint: Blueprint, provider: str) -> None:
    """Run deterministic icon lookups for every node label and write icon_plan.json."""
    plan: dict[str, list[str]] = {}
    for node in blueprint.nodes:
        query = node.label or node.id
        hits = _search_icon_hits(query, provider or None, limit=5)
        plan[node.id] = [_icon_rel(h) for h in hits]
    try:
        _ICON_PLAN_FILE.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    except Exception:
        pass


@tool(parse_docstring=True)
def propose_blueprint(blueprint: Blueprint) -> str:
    """Propose the architecture blueprint for the user to review and approve.

    PAUSES for human approval. Runs deterministic validators for Well-Architected
    pillar coverage, NFR mapping, and functional requirements coverage — warnings
    are surfaced but do NOT block approval.

    When to use: AFTER the tech stack is approved, to lock the component/cluster/edge
    design before icon resolution and rendering.

    Args:
        blueprint: The full architecture blueprint (nodes, clusters, edges, pattern,
            and density) to present for approval.
    """
    if not _TECHSTACK_FILE.exists():
        return "Get the tech stack approved first by calling propose_tech_stack."
    current_workspace().mkdir(parents=True, exist_ok=True)
    _BLUEPRINT_FILE.write_text(
        blueprint.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
    )

    # Write compact render_spec.json so the drawer reads from disk.
    provider = _detect_provider()
    render_spec = _build_render_spec(blueprint, provider)
    _RENDER_SPEC_FILE.write_text(json.dumps(render_spec, indent=2), encoding="utf-8")

    # Pre-compute style_plan.json + label_fits.json code-side (pure functions of
    # the spec) so the drawer reads them instead of spending 2 model calls.
    try:
        from ..rendering_tools import write_style_and_fit_plans
        write_style_and_fit_plans(render_spec)
    except Exception:
        pass  # advisory files; the drawer can still re-plan via its prompt rules

    # Pre-seed icon_plan.json so the drawer skips redundant search_icons calls.
    _preseed_icon_plan(blueprint, provider)

    # Deterministic NATIVE pre-render: build out.drawio (+ out.png / out.slide.json)
    # from the spec NOW, so a canonical architecture ALWAYS gets the native engine
    # (deterministic layout + ground-truth stencils + obstacle-avoiding router)
    # regardless of the drawer LLM's later choice. Non-fatal — but a failure MUST
    # be surfaced: a silent miss here is what strands runs on the Graphviz path.
    native_prerender_err: str | None = None
    try:
        from ..rendering_tools import _render_native_from_spec
        _render_native_from_spec(render_spec, current_workspace())
    except Exception as exc:  # noqa: BLE001 — advisory; never block approval
        native_prerender_err = f"{type(exc).__name__}: {exc}"

    # --- deterministic validators (warnings only, do not block) ---
    warnings: list[str] = []
    if native_prerender_err:
        warnings.append(
            f"native pre-render FAILED ({native_prerender_err}) — out.drawio was not "
            "produced; the drawer must call export_drawio_native() itself and report "
            "the error if it recurs (do NOT silently fall back to render_diagram).")

    pillar_warns = _validate_pillar_coverage(blueprint)
    if pillar_warns:
        warnings.extend(pillar_warns)

    unmapped_nfrs = _validate_nfr_mapping(blueprint)
    if unmapped_nfrs:
        warnings.append(
            f"NFR mapping: {len(unmapped_nfrs)} NFR(s) from the brief have no nfr_mapping entry: "
            + ", ".join(f'"{n}"' for n in unmapped_nfrs[:5])
        )

    covered, total, uncovered_reqs = _validate_req_coverage(blueprint)
    coverage_line = ""
    if total > 0:
        coverage_pct = round(100 * covered / total)
        coverage_line = f"Coverage: {covered}/{total} functional requirements ({coverage_pct}%)"
        if uncovered_reqs:
            coverage_line += " — missing: " + "; ".join(f'"{r}"' for r in uncovered_reqs[:5])

    # --- density mismatch detection ---
    n = len(blueprint.nodes)
    d = blueprint.density
    if n < 10 and d == "poster":
        warnings.append(
            f"density mismatch: blueprint has only {n} nodes but density='poster'. "
            "Poster mode with <10 nodes produces a sparse wall-grid — consider "
            "density='standard' for small systems, or density='detailed' (flow-driven) "
            "if you want the default house style."
        )
    elif n >= 13 and d == "standard":
        warnings.append(
            f"density mismatch: blueprint has {n} nodes but density='standard'. "
            "Standard is for genuinely small systems (<10 components). Switch to "
            "density='detailed' (flow-driven, the house default) so the diagram "
            "shows the full architecture."
        )

    # --- report quality ---
    if len(blueprint.key_decisions) < 3:
        warnings.append(
            f"report quality: blueprint has only {len(blueprint.key_decisions)} key_decision(s) "
            "(target ≥ 3). This field feeds the executive summary, traceability, and risks sections "
            "of the PDF report — add concrete design decisions and trade-offs before approving."
        )
    if not blueprint.pillar_coverage:
        warnings.append(
            "report quality: pillar_coverage is empty. "
            "This field feeds the Well-Architected Review section of the PDF report — "
            "populate at least the 4 core pillars (security, reliability, performance_efficiency, "
            "cost_optimization) before approving."
        )

    record_report_step(
        current_workspace(),
        "propose_blueprint",
        summary=(
            f"Approved {blueprint.pattern} blueprint with {n} nodes (density={d}), "
            f"{len(blueprint.clusters)} clusters, and {len(blueprint.edges)} edges."
            + (f" {coverage_line}." if coverage_line else "")
        ),
        data=blueprint.model_dump(by_alias=True),
    )
    reset_render_count()
    _reset_revision_count()

    result_parts = [
        f"Blueprint APPROVED (density={d}, {n} nodes). "
        "Next: write the diagram code, call render_diagram, "
        "look at the PNG and refine, call export_drawio, then finalize_diagram.",
    ]
    if coverage_line:
        result_parts.append(coverage_line)
    if warnings:
        result_parts.append(
            "Architect warnings (address before finalizing if possible):\n"
            + "\n".join(f"  ⚠ {w}" for w in warnings)
        )
    # Per-stage cross-artifact gate (advisory): now that the blueprint exists, surface
    # drift (unmapped requirement, dangling edge, missing decisions) early instead of
    # only at export. 3-outcome verdict; settled findings are filtered.
    return "\n\n".join(result_parts) + _solution_gate_note("blueprint")


@tool
def inspect_diagram(tool_call_id: Annotated[str, InjectedToolCallId]) -> ToolMessage:
    """Load the LAST rendered diagram (out.png) plus its layout audit to review it.

    Read-only — this does NOT render. Returns the rendered PNG so you can LOOK at
    it and the objective layout audit (page aspect ratio + label-bearing edges
    that strand). Call this once, then judge the diagram against the blueprint.
    """
    png = current_workspace() / "out.png"
    if not png.exists():
        return ToolMessage(
            content="No rendered diagram (out.png) to inspect yet.",
            name="inspect_diagram",
            tool_call_id=tool_call_id,
            status="error",
        )
    audit = _layout_audit()
    text = "Here is the rendered diagram to review."
    if audit:
        text += "\n\nObjective layout audit (read this FIRST):\n" + audit
    include_image = os.getenv("RENDER_INCLUDES_IMAGE", "1").lower() not in ("0", "false", "no")
    if include_image:
        b64, mime = _inspection_image_b64(png)
        return ToolMessage(
            content_blocks=[
                {"type": "text", "text": text},
                {"type": "image", "base64": b64, "mime_type": mime},
            ],
            name="inspect_diagram",
            tool_call_id=tool_call_id,
            status="success",
        )
    return ToolMessage(
        content=text + "\n\nImage is at out.png in the workspace.",
        name="inspect_diagram",
        tool_call_id=tool_call_id,
        status="success",
    )


@tool(parse_docstring=True)
def submit_critique(findings: list[DiagramFinding]) -> str:
    """Record your diagram review as a list of concrete findings and get the verdict.

    Findings are ranked and capped; the returned text starts with `VERDICT: PASS`
    or `VERDICT: REVISE`. Return that verdict text verbatim as your final answer so
    the architect can act on it.

    When to use: once, after inspecting the rendered diagram against the blueprint.

    Args:
        findings: The list of concrete review findings; each is
            {severity, confidence, category, title, detail, fix_suggestion?,
            in_blueprint?}. Pass an empty list if the diagram is clean.
    """
    kept = prune(findings)
    current_workspace().mkdir(parents=True, exist_ok=True)
    _CRITIQUE_FILE.write_text(
        json.dumps([f.model_dump() for f in kept], indent=2), encoding="utf-8"
    )
    critique_data = [f.model_dump() for f in kept]
    if verdict_for(kept) == "revise":
        # The revision-round counter is owned by DrawerReviseGateMiddleware
        # (agent.py) — it increments _REVISION_COUNT_FILE and resets the render
        # budget only when it actually lets a post-finalize_diagram drawer
        # revise dispatch through, since only that middleware can tell an
        # automatic first-pass critique apart from a genuine post-rejection
        # round. Here we only READ the count, to stop suggesting a revision
        # once the budget is already used up (avoids drafting a revise the
        # gate would just block).
        count = int(_read_json_file(_REVISION_COUNT_FILE, {"count": 0}).get("count", 0))
        _bump_tool_summary("submit_critique", critic_revisions=count)
        if count >= CRITIC_REVISION_HARD_CAP:
            base = format_critique(kept)
            return (
                f"VERDICT: PASS (revision limit reached: {CRITIC_REVISION_HARD_CAP} "
                "drawer revision rounds already used — proceed to finalize and "
                "mention residual findings)\n"
                + "\n".join(base.splitlines()[1:])
            )
    else:
        _bump_tool_summary("submit_critique")
    verdict_text = format_critique(kept)
    record_report_step(
        current_workspace(),
        "submit_critique",
        status="revise" if verdict_for(kept) == "revise" else "passed",
        summary=verdict_text.splitlines()[0] if verdict_text else "Critic review completed.",
        data={"findings": critique_data},
    )
    return verdict_text
