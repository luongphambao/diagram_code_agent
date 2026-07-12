"""PDF report, PPT proposal/deck, and proposal-package export gate tools."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from backends import current_workspace
from csm_adapter import build_solution_model
from deck import (
    DECK_QA_NAME,
    build_deck_plan,
    load_deck_plan,
    score_deck_structure,
    validate_deck,
    write_deck_plan,
)
from deck_visual_qa import (
    VISUAL_AUDIT_NAME,
    audit_pptx_deterministic,
    format_visual_audit,
    patch_pptx_overflow,
    write_visual_audit,
)
from langchain_core.tools import tool
from ppt_reporting import DEFAULT_PPT_SECTIONS, PPTProposalError, generate_ppt_proposal_file
from proposal_package import (
    build_manifest,
    export_proposal_package as _export_proposal_package,
    format_manifest,
)
from reporting import (
    DEFAULT_REPORT_SECTIONS,
    ReportRenderError,
    generate_report,
    record_artifact_inventory,
    record_report_step,
)
from ..stage_markers import _bump_tool_summary, _read_json_file
from .gates import _epistemic_note, _solution_gate_note


class PdfReportConfig(BaseModel):
    title: str = Field("", description="Override PDF cover title; defaults to blueprint.slide_title")
    subtitle: str = Field("", description="Cover subtitle/kicker")
    brand: str = Field("", description="Brand name shown on cover; defaults to blueprint.brand")
    include_sections: list[str] = Field(
        default_factory=lambda: DEFAULT_REPORT_SECTIONS.copy(),
        description=(
            "Ordered list of sections to include. Valid names: cover, executive_summary, "
            "requirements_analysis, traceability, solution, techstack, architecture_analysis, "
            "well_architected, step_results, risks, diagram. "
            "Leave EMPTY to include ALL sections (recommended). "
            "Only pass a subset when the USER explicitly asked to omit specific sections."
        ),
    )
    reason_for_subset: str = Field(
        "",
        description=(
            "REQUIRED when include_sections is a subset of all sections: quote the user's "
            "exact words that requested omitting sections (e.g. 'user said: only blueprint and diagram'). "
            "Leave empty when calling with all sections or with no include_sections argument. "
            "If this field is empty and include_sections is shorter than the full list, "
            "the tool will auto-expand to all sections."
        ),
    )


@tool(args_schema=PdfReportConfig)
def generate_pdf_report(
    title: str = "",
    subtitle: str = "",
    brand: str = "",
    include_sections: list[str] | None = None,
    reason_for_subset: str = "",
) -> str:
    """Generate a client-ready HTML + PDF report from approved artifacts.

    Reads the staged architecture artifacts and report_evidence.json, renders
    out.report.html, then renders out.pdf with Playwright Chromium. Call this
    AFTER finalize_diagram is approved.
    """
    auto_expanded_msg = ""
    if include_sections and len(include_sections) < len(DEFAULT_REPORT_SECTIONS) and not reason_for_subset.strip():
        auto_expanded_msg = (
            f" NOTE: include_sections had only {len(include_sections)} section(s) but no "
            "reason_for_subset was provided — auto-expanded to all sections to avoid a "
            "truncated report. Pass reason_for_subset quoting the user's request if a "
            "subset was intentional."
        )
        include_sections = None

    try:
        html_path, pdf_path, sections, unrecognized = generate_report(
            current_workspace(),
            title=title,
            subtitle=subtitle,
            brand=brand,
            include_sections=include_sections,
        )
    except FileNotFoundError as exc:
        return str(exc)
    except ReportRenderError as exc:
        return f"PDF report generation failed: {exc}"
    _bump_tool_summary("generate_pdf_report", pdf_pages=len(sections))
    msg = f"Wrote {pdf_path} and {html_path} ({len(sections)} sections)."
    if auto_expanded_msg:
        msg += auto_expanded_msg
    if unrecognized:
        msg += (
            f" WARNING: {len(unrecognized)} unrecognized section name(s) were ignored: "
            + ", ".join(f'"{n}"' for n in unrecognized)
            + ". Valid names: cover, executive_summary, requirements_analysis, traceability, "
            "solution, techstack, architecture_analysis, well_architected, step_results, risks, diagram."
        )
    if include_sections:
        missing = [s for s in DEFAULT_REPORT_SECTIONS if s not in sections]
        if missing:
            msg += (
                f" NOTE: {len(missing)} section(s) were omitted from this run: "
                + ", ".join(missing) + "."
            )
    msg += _solution_gate_note("pdf_export", block=True)
    return msg


class PptProposalConfig(BaseModel):
    title: str = Field("", description="Override PPT cover title; defaults to blueprint.slide_title")
    subtitle: str = Field("", description="Cover subtitle/kicker")
    brand: str = Field("", description="Brand name shown on cover; defaults to blueprint.brand")
    include_sections: list[str] = Field(
        default_factory=lambda: DEFAULT_PPT_SECTIONS.copy(),
        description=(
            "Ordered list of PPT proposal sections to include. Valid names: cover, "
            "executive_summary, solution_overview, scope, architecture_diagram, "
            "technical_stack, key_decisions, delivery_plan, risks, appendix. "
            "Leave EMPTY to include ALL sections (recommended). "
            "Only pass a subset when the USER explicitly asked to omit sections."
        ),
    )
    reason_for_subset: str = Field(
        "",
        description=(
            "REQUIRED when include_sections is a subset of all sections: quote the user's "
            "exact words that requested omitting sections. Leave empty when calling with all sections."
        ),
    )


@tool(args_schema=PptProposalConfig)
def generate_ppt_proposal(
    title: str = "",
    subtitle: str = "",
    brand: str = "",
    include_sections: list[str] | None = None,
    reason_for_subset: str = "",
) -> str:
    """Generate an editable BnK PowerPoint proposal from approved artifacts.

    Reads the staged architecture artifacts and rendered diagram, then renders
    out.pptx using the BnK proposal template. Call this AFTER finalize_diagram is approved.
    """
    auto_expanded_msg = ""
    if include_sections and len(include_sections) < len(DEFAULT_PPT_SECTIONS) and not reason_for_subset.strip():
        auto_expanded_msg = (
            f" NOTE: include_sections had only {len(include_sections)} section(s) but no "
            "reason_for_subset was provided - auto-expanded to all sections to avoid a "
            "truncated proposal."
        )
        include_sections = None

    try:
        pptx_path, sections, unrecognized = generate_ppt_proposal_file(
            current_workspace(),
            title=title,
            subtitle=subtitle,
            brand=brand,
            include_sections=include_sections,
        )
    except FileNotFoundError as exc:
        return str(exc)
    except PPTProposalError as exc:
        return f"PPT proposal generation failed: {exc}"
    _bump_tool_summary("generate_ppt_proposal", ppt_sections=len(sections))
    msg = f"Wrote {pptx_path} ({len(sections)} sections)."
    if auto_expanded_msg:
        msg += auto_expanded_msg
    if unrecognized:
        msg += (
            f" WARNING: {len(unrecognized)} unrecognized section name(s) were ignored: "
            + ", ".join(f'"{n}"' for n in unrecognized)
            + ". Valid names: "
            + ", ".join(DEFAULT_PPT_SECTIONS)
            + "."
        )
    if include_sections:
        missing = [s for s in DEFAULT_PPT_SECTIONS if s not in sections]
        if missing:
            msg += f" NOTE: {len(missing)} section(s) were omitted from this run: " + ", ".join(missing) + "."
    msg += _solution_gate_note("ppt_export", block=True)
    msg += _deck_qa_note()
    msg += _visual_audit_note(pptx_path)
    return msg


@tool(parse_docstring=True)
def create_pptx(
    title: str = "",
    subtitle: str = "",
    brand: str = "",
    include_sections: list[str] | None = None,
) -> str:
    """Write out.pptx from the approved workspace artifacts.

    Called by the ppt_generator subagent to produce the slide deck from
    context files already present in the workspace (blueprint.json,
    diagram_brief.json, tech_stack.json, out.png).  Unlike the gate tool
    generate_ppt_proposal, this tool runs silently without pausing for
    human approval — it is invoked only after the user has already agreed
    to the proposed section list.

    Args:
        title: Deck title (falls back to blueprint slide_title if empty).
        subtitle: Subtitle / kicker line.
        brand: Client brand name shown on the cover.
        include_sections: Section keys to render; leave empty for all sections.
    """
    try:
        pptx_path, sections, unrecognized = generate_ppt_proposal_file(
            current_workspace(),
            title=title,
            subtitle=subtitle,
            brand=brand,
            include_sections=include_sections or None,
        )
    except FileNotFoundError as exc:
        return f"ERROR: {exc}"
    except PPTProposalError as exc:
        return f"ERROR: PPT generation failed: {exc}"
    _bump_tool_summary("generate_ppt_proposal", ppt_sections=len(sections))
    msg = f"Wrote {pptx_path} ({len(sections)} slides rendered)."
    if unrecognized:
        msg += f" Ignored unrecognised sections: {', '.join(unrecognized)}."
    return msg


# --- deck quality loop (docx §4.8) -------------------------------------------

def _refresh_deck_plan(title: str = "", subtitle: str = "", brand: str = ""):
    """Build/refresh deck_plan.json from the CSM + artifacts. Returns (model, plan)."""
    model = build_solution_model(current_workspace())
    wbs = _read_json_file(current_workspace() / "wbs.json", {}) or {}
    brief = _read_json_file(current_workspace() / "diagram_brief.json", {}) or {}
    has_diagram = (current_workspace() / "out.body.png").exists() or (current_workspace() / "out.png").exists()
    plan = build_deck_plan(
        model, wbs=wbs, brief=brief, has_diagram=has_diagram,
        title=title, subtitle=subtitle, brand=brand,
    )
    write_deck_plan(plan, current_workspace())
    return model, plan


def _deck_qa_note(model=None) -> str:
    """Run validate_deck + score_deck_structure over the stored plan, write deck_qa_result.json."""
    plan = load_deck_plan(current_workspace())
    if plan is None:
        return ""
    if model is None:
        try:
            model = build_solution_model(current_workspace())
        except Exception:
            return ""
    findings = validate_deck(plan, model)
    struct = score_deck_structure(plan)
    try:
        (current_workspace() / DECK_QA_NAME).write_text(
            json.dumps({
                "deck_revision": plan.revision,
                "findings": findings,
                "structural_score": struct["score"],
                "structural_grade": struct["grade"],
                "structural_issues": struct["issues"],
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass
    grounded = sum(1 for s in plan.slides if s.source_refs)
    trace_total = sum(len(s.source_refs) for s in plan.slides)
    head = (
        f"\n\nDECK QA — storyboard revision {plan.revision}: {len(plan.slides)} slides, "
        f"{grounded} grounded in {trace_total} CSM source ref(s). "
        f"Structural score: {struct['score']}/100 [{struct['grade']}]."
    )
    parts: list[str] = []
    if findings:
        by_sev: dict[str, int] = {}
        for f in findings:
            by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1
        lines = [
            f"  ⚠ [{f['severity']}/{f['dimension']}] slide {f['slide_no']}: {f['evidence']}"
            for f in findings[:8]
        ]
        extra = f"\n  … (+{len(findings) - 8} more)" if len(findings) > 8 else ""
        sev = ", ".join(f"{k}:{v}" for k, v in sorted(by_sev.items()))
        parts.append(f"{len(findings)} traceability finding(s) ({sev}):\n" + "\n".join(lines) + extra)
    else:
        parts.append("No traceability/consistency/evidence issues.")
    if struct["issues"]:
        struct_lines = [f"  ⚠ {iss}" for iss in struct["issues"][:6]]
        extra2 = f"\n  … (+{len(struct['issues']) - 6} more)" if len(struct["issues"]) > 6 else ""
        parts.append(f"Structural issues ({struct['deductions']} pts deducted):\n" + "\n".join(struct_lines) + extra2)
    return head + " " + " | ".join(parts)


def _visual_audit_note(pptx_path: str | None) -> str:
    """Run deterministic visual audit on *pptx_path*, auto-patch HIGH issues,
    write deck_visual_audit.json, and return a human-readable summary string."""
    if not pptx_path:
        return ""
    try:
        from pathlib import Path as _Path
        result = audit_pptx_deterministic(pptx_path)
        if result.high_count > 0:
            high_issues = [i for i in result.issues if i.severity == "high"]
            patched_path = patch_pptx_overflow(pptx_path, high_issues)
            result_after = audit_pptx_deterministic(patched_path)
            write_visual_audit(result_after, current_workspace())
            return (
                format_visual_audit(result_after)
                + f"\n  AUTO-PATCHED {len(high_issues)} HIGH issue(s) → saved as {_Path(patched_path).name}"
            )
        write_visual_audit(result, current_workspace())
        return format_visual_audit(result)
    except Exception as exc:  # noqa: BLE001
        return f"\n  Visual audit skipped: {exc}"


@tool(parse_docstring=True)
def audit_deck_visual() -> str:
    """Run deterministic visual audit on the rendered out.pptx.

    Checks every slide for title length, bullet density, table overflow, tiny fonts,
    and brand font drift. Writes deck_visual_audit.json. HIGH-severity issues are
    automatically patched (title truncation, bullet trimming) and saved as
    out_patched.pptx. No LLM, no rendering — reads the PPTX XML model directly.
    Call this after create_pptx or generate_ppt_proposal to get a layout QA report.
    """
    pptx_path = current_workspace() / "out.pptx"
    if not pptx_path.exists():
        return "ERROR: out.pptx not found. Run create_pptx or generate_ppt_proposal first."
    _bump_tool_summary("audit_deck_visual")
    return _visual_audit_note(str(pptx_path))


@tool(parse_docstring=True)
def export_proposal_package(title: str = "") -> str:
    """Assemble the proposal package — manifest + all artifacts — into an export folder.

    Reads workspace stores (deck_plan.json, solution_model.json, decision_log.json,
    findings_log.json, deck_visual_audit.json) and copies the deliverable files
    (out.pptx, out.png, out.drawio, wbs_output.xlsx) into
    workspace/exports/<timestamp>/ together with a manifest.json.

    The manifest records artifact status, slide trace coverage, structure score,
    visual audit result, open findings, and HITL decision count.

    PAUSES for human review: shows the package summary and warns if HIGH findings
    or unresolved visual issues are present before the user sends to the client.

    Args:
        title: Override the project title shown on the manifest (defaults to
               diagram_brief.slide_title or the existing project title).
    """
    try:
        export_dir, manifest = _export_proposal_package(current_workspace(), title=title)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: could not assemble package: {exc}"

    _bump_tool_summary("export_proposal_package")

    summary = format_manifest(manifest)
    summary += f"\n\nPackage written to: {export_dir}"

    if manifest.open_findings_high:
        summary += (
            "\n\n⛔ BLOCKED: there are HIGH-severity findings open. "
            "Resolve or waive them before sending to the client, "
            "or confirm you accept the risk."
        )
    elif manifest.open_findings:
        summary += (
            f"\n\n⚠ {manifest.open_findings} finding(s) still open — review before sending."
        )
    else:
        summary += "\n\nAll quality gates clear. Ready to send to client."

    return summary


@tool(parse_docstring=True)
def plan_deck(title: str = "", subtitle: str = "", brand: str = "") -> str:
    """Build the traceable BnK proposal storyboard (deck_plan.json) from the CSM.

    Assembles the fixed BnK narrative (Executive Summary -> Proposed Solution ->
    Technical Stack -> Scope -> Project Delivery/Effort/Timeline -> Risks -> Pricing),
    with every slide grounded in CSM entity ids (source_refs). Runs silently (no
    approval). Call this in the ppt_generator subagent BEFORE create_pptx, and BEFORE
    propose_deck_plan presents the storyboard for review.

    Args:
        title: Deck title (falls back to diagram_brief.slide_title).
        subtitle: Subtitle / kicker line.
        brand: Client brand name shown on the cover.
    """
    try:
        _model, plan = _refresh_deck_plan(title, subtitle, brand)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: could not build deck plan: {exc}"
    grounded = sum(1 for s in plan.slides if s.source_refs)
    return (
        f"Wrote deck_plan.json — {len(plan.slides)} slides, {grounded} grounded in the CSM "
        f"(storyboard revision {plan.revision}). Next: propose_deck_plan to approve the narrative."
    )


@tool(parse_docstring=True)
def propose_deck_plan(title: str = "", subtitle: str = "", brand: str = "") -> str:
    """Present the proposal storyboard for the user to approve BEFORE rendering the deck.

    PAUSES for human approval (docx §4.8 / §5.3: approve the narrative & trade-offs
    before the file is built). Builds/refreshes deck_plan.json from the CSM, runs
    validate_deck (traceability / coverage / consistency / evidence — advisory, does
    NOT block), writes deck_qa_result.json, and shows the storyboard outline + findings
    + epistemic summary. After approval, call create_pptx (or generate_ppt_proposal)
    to render the deck from the approved plan.

    Args:
        title: Deck title (falls back to diagram_brief.slide_title).
        subtitle: Subtitle / kicker line.
        brand: Client brand name shown on the cover.
    """
    try:
        model, plan = _refresh_deck_plan(title, subtitle, brand)
    except Exception as exc:  # noqa: BLE001
        return f"Could not build the deck plan: {exc}"

    lines: list[str] = []
    for s in plan.slides:
        refs = ""
        if s.source_refs:
            head = ", ".join(s.source_refs[:6])
            refs = f"  ⟵ {head}" + ("…" if len(s.source_refs) > 6 else "")
        lines.append(f"  {s.slide_no:>2}. [{s.narrative_role}] {s.title or '(cover)'}{refs}")

    record_report_step(
        current_workspace(),
        "propose_deck_plan",
        summary=f"Proposed deck storyboard: {len(plan.slides)} slides (revision {plan.revision}).",
        data={"slides": [s.model_dump() for s in plan.slides]},
    )
    return (
        "DECK STORYBOARD — review the narrative & trade-offs before the file is rendered:\n"
        + "\n".join(lines)
        + _deck_qa_note(model)
        + _epistemic_note(model)
        + "\n\nApprove to render the deck from this plan, or tell me what to change in the storyboard."
    )
