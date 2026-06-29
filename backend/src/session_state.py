"""Shared agent state, interrupt helpers, and data-normalization utilities.

All route handlers import from here; this module holds the singleton AGENT
global (set by the lifespan in server.py after the Postgres pool opens).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage
from reporting import DEFAULT_REPORT_SECTIONS
from ppt_reporting import DEFAULT_PPT_SECTIONS

logger = logging.getLogger("diagram-agent")

# Set by server.lifespan after build_agent() completes.
AGENT = None

_DEFAULT_TZ = "Asia/Ho_Chi_Minh"

# ---------------------------------------------------------------------------
# Tool metadata
# ---------------------------------------------------------------------------

_TOOL_LABELS = {
    "analyze_architecture_requirements": "Analyzing architecture requirements",
    "propose_diagram_brief": "Preparing the diagram brief",
    "propose_tech_stack": "Proposing the technology stack",
    "propose_blueprint": "Designing the architecture blueprint",
    "render_diagram": "Rendering the diagram",
    "export_drawio": "Exporting the editable .drawio",
    "list_saved_diagrams": "Listing saved diagram sessions",
    "resolve_icons": "Resolving icon plan",
    "search_diagrams_nodes": "Searching built-in diagram nodes",
    "search_icons": "Searching the icon library",
    "fetch_logo": "Fetching a logo",
    "audit_diagram_code": "Auditing diagram code",
    "inspect_diagram": "Reviewing the rendered diagram",
    "submit_critique": "Recording the diagram review",
    "finalize_diagram": "Finalizing the diagram",
    "generate_pdf_report": "Generating the PDF report",
    "generate_ppt_proposal": "Presenting the PPT proposal for approval",
    "create_pptx": "Generating the PowerPoint deck",
    "send_architecture_report_email": "Sending the architecture report email",
    "write_todos": "Planning the steps",
    "task": "Delegating to subagent",
    "ls": "Listing files",
    "read_file": "Reading a file",
    "write_file": "Writing a file",
    "edit_file": "Editing a file",
    "glob": "Searching for files",
    "grep": "Searching file contents",
}

# Maps tool name → which subagent owns it (for activity attribution).
_TOOL_TO_SUBAGENT: dict[str, str] = {
    "search_diagrams_nodes": "icon_resolver",
    "search_icons": "icon_resolver",
    "resolve_icons": "icon_resolver",
    "fetch_logo": "icon_resolver",
    "audit_diagram_code": "drawer",
    "render_diagram": "drawer",
    "export_drawio": "drawer",
    "inspect_diagram": "critic",
    "submit_critique": "critic",
    "create_pptx": "ppt_generator",
}


def _label(tool: str) -> str:
    return _TOOL_LABELS.get(tool, f"Running {tool}")


# ---------------------------------------------------------------------------
# Text / JSON utilities
# ---------------------------------------------------------------------------

def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for p in content:
            if isinstance(p, str):
                out.append(p)
            elif isinstance(p, dict) and ("text" in p or p.get("type") in ("text", "output_text")):
                out.append(p.get("text", ""))
        return "".join(out)
    return ""


def _compact_json(value, *, limit: int = 260) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False)
    except Exception:
        text = str(value)
    text = " ".join(text.split())
    return text[:limit] + ("..." if len(text) > limit else "")


def _tool_detail(tool: str, args: dict | None, *, limit: int = 260) -> str:
    """Summarize tool input for UI logs without dumping huge code/prompts."""
    if not isinstance(args, dict) or not args:
        return ""
    if tool == "task":
        sa = args.get("subagent_type") or args.get("subagent") or args.get("name") or "unknown"
        desc = " ".join(str(args.get("description") or args.get("instruction") or args.get("prompt") or "").split())
        return f"{sa}: {desc[:180]}{'...' if len(desc) > 180 else ''}"
    if tool == "render_diagram":
        code = str(args.get("code") or "")
        return f"diagram.py code={len(code)} chars"
    if tool == "audit_diagram_code":
        code = str(args.get("code") or "")
        return f"diagram.py code={len(code)} chars"
    if tool == "search_icons":
        provider = args.get("provider")
        return f"query={args.get('query', '')}" + (f", provider={provider}" if provider else "")
    if tool == "search_diagrams_nodes":
        provider = args.get("provider")
        category = args.get("category")
        bits = [f"query={args.get('query', '')}"]
        if provider:
            bits.append(f"provider={provider}")
        if category:
            bits.append(f"category={category}")
        return ", ".join(bits)
    if tool == "analyze_architecture_requirements":
        req = " ".join(str(args.get("requirements", "")).split())
        provider = args.get("provider_preference")
        suffix = f", provider={provider}" if provider else ""
        return f"requirements={req[:160]}{'...' if len(req) > 160 else ''}{suffix}"
    if tool == "resolve_icons":
        icons = args.get("icons") or []
        if isinstance(icons, list):
            labels = [str(x.get("label", "")) for x in icons if isinstance(x, dict)]
            return f"{len(icons)} icons: {', '.join([x for x in labels if x][:8])}"
    if tool == "fetch_logo":
        return f"name={args.get('name', '')}"
    if tool == "propose_blueprint":
        bp = args.get("blueprint") or {}
        if isinstance(bp, dict):
            return (
                f"{bp.get('audience', 'client')}/{bp.get('detail_level', 'architecture')} "
                f"style={bp.get('presentation_style', 'diagram')}, "
                f"pattern={bp.get('pattern', '')}, nodes={len(bp.get('nodes') or [])}, "
                f"clusters={len(bp.get('clusters') or [])}, edges={len(bp.get('edges') or [])}"
            )
    if tool == "propose_diagram_brief":
        brief = args.get("brief") or {}
        if isinstance(brief, dict):
            return (
                f"objective={str(brief.get('objective', ''))[:80]}, "
                f"functional={len(brief.get('functional_requirements') or [])}, "
                f"nonfunctional={len(brief.get('non_functional_requirements') or [])}, "
                f"layout={len(brief.get('layout_constraints') or [])}"
            )
    if tool == "propose_tech_stack":
        stack = args.get("tech_stack") or []
        if isinstance(stack, list):
            layers = [str(x.get("layer", "")) for x in stack if isinstance(x, dict)]
            return f"{len(stack)} layers: {', '.join([x for x in layers if x][:8])}"
    if tool == "generate_pdf_report":
        sections = args.get("include_sections") or DEFAULT_REPORT_SECTIONS
        return f"sections={', '.join(map(str, sections))}"
    if tool == "submit_critique":
        findings = args.get("findings") or []
        if isinstance(findings, list):
            return f"{len(findings)} finding(s)"
    return _compact_json(args, limit=limit)


def _tool_output_detail(content, *, limit: int = 320) -> str:
    text = " ".join(_text_of(content).split())
    return text[:limit] + ("..." if len(text) > limit else "")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


# ---------------------------------------------------------------------------
# Request parsing helpers
# ---------------------------------------------------------------------------

def _last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return _text_of(m.get("content", ""))
    return ""


def _last_tool_msg(messages: list[dict]) -> dict | None:
    """Return the last message only when the client is resolving a HITL gate."""
    if messages and messages[-1].get("role") == "tool":
        return messages[-1]
    return None


def _is_pdf_followup(text: str) -> bool:
    """Detect a follow-up asking to package the current diagram as a PDF report."""
    normalized = " ".join(str(text or "").lower().split())
    return any(
        phrase in normalized
        for phrase in (
            "pdf",
            "report",
            "document",
            "doc",
            "tạo pdf",
            "tao pdf",
            "xuất pdf",
            "xuat pdf",
            "tạo báo cáo",
            "tao bao cao",
        )
    )

def _is_ppt_followup(text: str) -> bool:
    """Detect a follow-up asking to package the current diagram as a PowerPoint proposal."""
    normalized = " ".join(str(text or "").lower().split())
    return any(
        phrase in normalized
        for phrase in (
            "ppt",
            "pptx",
            "powerpoint",
            "slide deck",
            "presentation deck",
            "make a proposal",
            "create a proposal",
            "export proposal",
            "generate proposal",
            "tạo ppt",
            "tao ppt",
            "xuất ppt",
            "xuat ppt",
            "tạo proposal",
            "tao proposal",
            "xuất proposal",
            "xuat proposal",
        )
    )


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Data normalization (array coercion, blueprint/tech-stack shape)
# ---------------------------------------------------------------------------

def _coerce_list(val) -> list:
    """Coerce an array-typed field into a list.

    Some models (e.g. mimo) emit array-typed fields as plain objects with
    numeric string keys ({"0": ..., "1": ...}) instead of JSON arrays.
    """
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return list(val.values())
    return []


_BRIEF_ARRAY_FIELDS = ("analysis_signals", "stakeholders", "functional_requirements",
                       "non_functional_requirements", "layout_constraints", "assumptions")


def _coerce_brief(d) -> dict:
    if not isinstance(d, dict):
        return d
    result = dict(d)
    for field in _BRIEF_ARRAY_FIELDS:
        if field in result:
            result[field] = _coerce_list(result[field])
    return result


_ASSUMPTION_ARRAY_FIELDS = ("confirm_with_customer", "compliance")


def _coerce_assumptions(a):
    if not isinstance(a, dict):
        return a
    result = dict(a)
    for field in _ASSUMPTION_ARRAY_FIELDS:
        if field in result:
            result[field] = _coerce_list(result[field])
    return result


def _normalize_blueprint(bp) -> dict:
    if not isinstance(bp, dict):
        return bp or {}
    result = dict(bp)
    _ARRAY_FIELDS = ("nodes", "clusters", "edges", "key_decisions", "nfr_mapping",
                     "analysis_signals", "stakeholders", "functional_requirements",
                     "non_functional_requirements", "layout_constraints", "assumptions")
    for field in _ARRAY_FIELDS:
        val = result.get(field)
        if isinstance(val, dict):
            result[field] = list(val.values())
        elif val is None:
            result[field] = []
    return result


def _normalize_tech_stack(ts) -> dict:
    """Normalize the model's tech_stack into {layer: {choice, rationale, alternatives, ...}}.

    Tolerates list-of-layer-dicts, flat dict-by-layer, and the wrapped
    {layers: {...}, assumptions: ...} shape stored in the workspace.
    """
    _LAYER_FIELDS = ("choice", "rationale", "cost_tier", "decision_criteria", "alternatives",
                     "estimated_monthly_cost_usd", "capacity_sizing", "performance_target", "risks")
    out: dict = {}
    if isinstance(ts, dict) and "layers" in ts:
        ts = ts["layers"]
    if isinstance(ts, list):
        for item in ts:
            if isinstance(item, dict) and item.get("layer"):
                layer_data = {f: item.get(f) for f in _LAYER_FIELDS}
                layer_data["alternatives"] = _coerce_list(layer_data.get("alternatives"))
                layer_data["risks"] = _coerce_list(layer_data.get("risks"))
                out[item["layer"]] = layer_data
    elif isinstance(ts, dict):
        for layer, info in ts.items():
            if isinstance(info, dict):
                layer_data = {f: info.get(f) for f in _LAYER_FIELDS}
                layer_data["alternatives"] = _coerce_list(layer_data.get("alternatives"))
                layer_data["risks"] = _coerce_list(layer_data.get("risks"))
                out[layer] = layer_data
            else:
                out[layer] = {"choice": str(info), "rationale": "", "cost_tier": None,
                              "decision_criteria": None, "alternatives": [],
                              "estimated_monthly_cost_usd": None, "capacity_sizing": "",
                              "performance_target": "", "risks": []}
    return out


# ---------------------------------------------------------------------------
# Interrupt / gate helpers
# ---------------------------------------------------------------------------

async def _pending_interrupt(config: dict):
    """Return the pending HITLRequest value, or None."""
    try:
        st = await AGENT.aget_state(config)
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_state failed: %s", exc)
        return None
    for task in getattr(st, "tasks", None) or []:
        for intr in getattr(task, "interrupts", None) or []:
            return getattr(intr, "value", intr)
    for intr in getattr(st, "interrupts", None) or []:
        return getattr(intr, "value", intr)
    return None


def _pending_action_name(val) -> str | None:
    if isinstance(val, dict):
        ars = val.get("action_requests") or []
        if ars:
            return ars[0].get("name")
        if val.get("type") == "slot_picker":
            return "propose_meeting_slots"
    return None


def _card_for(val, summary: str):
    """Translate an interrupt value → (card_data, current_step, state_delta)."""
    if isinstance(val, dict) and val.get("type") == "slot_picker":
        return (
            {
                "type": "slot_picker",
                "question": "Pick a time that works for the client meeting:",
                "slots": val.get("slots", []),
                "duration_minutes": val.get("duration_minutes", 60),
                "timezone": val.get("timezone", _DEFAULT_TZ),
                "context": val.get("context", ""),
            },
            "awaiting_slot_selection",
            {},
        )

    ars = (val or {}).get("action_requests") or [{}]
    name = ars[0].get("name")
    args = ars[0].get("args") or {}
    if name == "propose_tech_stack":
        ts = _normalize_tech_stack(args.get("tech_stack"))
        scaling_roadmap = _coerce_list(args.get("scaling_roadmap"))
        assumptions = _coerce_assumptions(args.get("assumptions"))
        card_data = {
            "type": "techstack_approval",
            "tech_stack": ts,
            "question": "Review the recommended tech stack and its sizing assumptions. Approve, or reject with the changes you want.",
            "assumptions": assumptions,
            "scaling_roadmap": scaling_roadmap,
            "estimated_total_monthly_cost_usd": args.get("estimated_total_monthly_cost_usd"),
        }
        state_delta = {
            "tech_stack": ts,
            "tech_assumptions": assumptions,
            "tech_scaling_roadmap": scaling_roadmap,
            "tech_total_cost": args.get("estimated_total_monthly_cost_usd"),
        }
        return (card_data, "awaiting_techstack", state_delta)
    if name == "propose_blueprint":
        bp = _normalize_blueprint(args.get("blueprint", {}))
        return (
            {"type": "blueprint_approval", "blueprint": bp,
             "question": "Review the architecture blueprint. Approve, or request changes."},
            "awaiting_blueprint", {"blueprint": bp},
        )
    if name == "finalize_diagram":
        return (
            {"type": "result_review", "summary": summary,
             "question": "Is the diagram good? Approve to finish, or describe the changes you want."},
            "reviewing", {},
        )
    if name == "generate_pdf_report":
        sections = args.get("include_sections") or DEFAULT_REPORT_SECTIONS
        missing = [s for s in DEFAULT_REPORT_SECTIONS if s not in sections]
        return (
            {
                "type": "pdf_report_approval",
                "question": "Generate the PDF report with these settings?",
                "title": args.get("title", ""),
                "subtitle": args.get("subtitle", ""),
                "brand": args.get("brand", ""),
                "include_sections": sections,
                "missing_sections": missing,
            },
            "awaiting_pdf_report",
            {},
        )
    if name == "generate_ppt_proposal":
        sections = args.get("include_sections") or DEFAULT_PPT_SECTIONS
        missing = [s for s in DEFAULT_PPT_SECTIONS if s not in sections]
        return (
            {
                "type": "ppt_proposal_approval",
                "question": "Generate the BnK PowerPoint proposal with these settings?",
                "title": args.get("title", ""),
                "subtitle": args.get("subtitle", ""),
                "brand": args.get("brand", ""),
                "include_sections": sections,
                "missing_sections": missing,
            },
            "awaiting_ppt_proposal",
            {},
        )
    if name == "send_architecture_report_email":
        return (
            {
                "type": "email_approval",
                "question": f"Send the architecture report PDF to {args.get('recipient_email', '')}?",
                "recipient_email": args.get("recipient_email", ""),
                "subject": args.get("subject", ""),
                "project_name": args.get("project_name", ""),
                "subtitle": args.get("subtitle", ""),
                "recipient_name": args.get("recipient_name", "Team"),
            },
            "awaiting_email_approval",
            {},
        )
    if name == "create_client_meeting":
        start_iso = args.get("start_datetime", "")
        end_iso = args.get("end_datetime", "")
        tz_name = args.get("timezone", "Asia/Ho_Chi_Minh")
        display_start = start_iso
        display_end = end_iso
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            _tz = ZoneInfo(tz_name)
            _s = datetime.fromisoformat(start_iso).astimezone(_tz)
            _e = datetime.fromisoformat(end_iso).astimezone(_tz)
            display_start = _s.strftime("%A, %d %b %Y  %H:%M")
            display_end = _e.strftime("%H:%M")
            duration_min = int((_e - _s).total_seconds() / 60)
        except Exception:
            duration_min = 0
        return (
            {
                "type": "meeting_approval",
                "question": f"Schedule a meeting with {args.get('attendee_email', '')}?",
                "title": args.get("title", ""),
                "start_datetime": start_iso,
                "end_datetime": end_iso,
                "display_start": display_start,
                "display_end": display_end,
                "duration_minutes": duration_min,
                "attendee_email": args.get("attendee_email", ""),
                "attendee_name": args.get("attendee_name", "Client"),
                "description": args.get("description", ""),
                "add_google_meet": args.get("add_google_meet", True),
                "timezone": tz_name,
            },
            "awaiting_meeting_approval",
            {},
        )
    if name == "propose_wbs_skeleton":
        phases = args.get("phases") or []
        if isinstance(phases, dict):
            phases = list(phases.values())
        return (
            {
                "type": "wbs_skeleton_approval",
                "question": args.get("question", "Review the WBS structure and approve or request changes."),
                "project_name": args.get("project_name", ""),
                "project_code": args.get("project_code", ""),
                "phases": phases,
            },
            "awaiting_wbs_skeleton",
            {},
        )
    if name == "propose_wbs":
        effort_by_module = args.get("effort_by_module") or []
        if isinstance(effort_by_module, dict):
            effort_by_module = list(effort_by_module.values())
        return (
            {
                "type": "wbs_approval",
                "question": args.get("question", "Review the WBS plan and effort estimates."),
                "total_mandays": args.get("total_mandays", 0),
                "total_manmonths": args.get("total_manmonths", 0),
                "timeline_weeks": args.get("timeline_weeks", 0),
                "timeline_months": args.get("timeline_months", 0),
                "effort_by_role": args.get("effort_by_role") or {},
                "effort_by_module": effort_by_module,
            },
            "awaiting_wbs_approval",
            {},
        )
    if name == "export_wbs_excel":
        return (
            {
                "type": "wbs_excel_approval",
                "question": args.get("question", "Generate the WBS Excel file?"),
                "total_mandays": args.get("total_mandays", 0),
                "timeline_months": args.get("timeline_months", 0),
            },
            "awaiting_wbs_excel",
            {},
        )
    return None, None, {}


# HITL v2 actions that PROCEED (run the tool) vs. send the agent back to REVISE.
# Everything maps onto the langchain HITL vocabulary (approve/reject); the rich
# intent is persisted separately as a DecisionRecord (decisions.py).
_PROCEED_ACTIONS = {"approve", "approve_with_assumptions", "accept_risk"}
_REVISE_ACTIONS = {"reject", "request_evidence", "request_alternative"}
# Actions worth persisting as a structured decision record + CSM projection.
HITL_V2_ACTIONS = {
    "approve_with_assumptions", "accept_risk", "request_evidence",
    "request_alternative", "edit_entity",
}


def _revise_message(action: str, payload: dict) -> str:
    """Build the guiding message the agent sees when a gate sends it back to revise."""
    if action == "request_evidence":
        claim = payload.get("claim") or payload.get("comment") or "the flagged claim"
        src = payload.get("source_expectation")
        msg = f"User requests evidence for: {claim}. Gather a credible source, then re-propose."
        return msg + (f" Preferred source: {src}." if src else "")
    if action == "request_alternative":
        ask = payload.get("constraint_change") or payload.get("option_comparison") or ""
        base = "User requests an alternative option (e.g. Fast MVP / Balanced / Enterprise)."
        return (base + f" {ask}").strip()
    return payload.get("modifications") or payload.get("comment") or \
        "Please revise based on the user's feedback."


def _decision_from_payload(payload: dict, pending_name: str | None) -> dict:
    """Map a gate payload to the langchain HITL decision dict (approve/reject).

    Back-compatible: a payload without an explicit `action` is interpreted exactly as
    before (finalize_diagram uses `satisfied`; other gates use `approved`). A HITL v2
    `action` (accept_risk, request_evidence, ...) maps onto approve/reject here; the
    structured record is created separately by `decision_record_from_payload`.
    """
    action = payload.get("action")
    if action is None:
        if pending_name == "finalize_diagram":
            ok = bool(payload.get("satisfied", True))
            msg = payload.get("feedback")
        else:
            ok = bool(payload.get("approved", False))
            msg = payload.get("modifications")
        action = "approve" if ok else "reject"
    else:
        msg = payload.get("modifications") or payload.get("comment")

    if action in _PROCEED_ACTIONS:
        decision: dict = {"type": "approve"}
        if "selected_slot" in payload:
            decision["selected_slot"] = payload["selected_slot"]
        return decision
    # Revise path (reject / request_evidence / request_alternative / unknown).
    return {"type": "reject", "message": _revise_message(action, payload) if action in _REVISE_ACTIONS
            else (msg or "Please revise based on the user's feedback.")}


def decision_record_from_payload(
    payload: dict,
    gate: str,
    *,
    seq: int,
    approver: str = "",
    timestamp: str = "",
    revision: int = 0,
):
    """Build a DecisionRecord for a HITL v2 action, or None for plain approve/reject.

    Plain approve/reject are already captured by the gate-outcome log + DB; only the
    richer trade-off actions become structured records projected into the CSM.
    """
    action = payload.get("action")
    if action not in HITL_V2_ACTIONS:
        return None
    from decisions import new_decision_record
    # Carry the action-specific fields through verbatim (minus routing keys).
    body = {k: v for k, v in payload.items()
            if k not in ("action", "approved", "satisfied", "modifications", "feedback")}
    return new_decision_record(
        gate, action, seq=seq, approver=approver, timestamp=timestamp,
        revision=revision, comment=payload.get("comment", ""), payload=body,
    )


# ---------------------------------------------------------------------------
# State queries
# ---------------------------------------------------------------------------

async def _summary_and_logs(config: dict) -> tuple[str, list]:
    summary = ""
    logs: list[dict] = []
    try:
        state = await AGENT.aget_state(config)
        messages = state.values.get("messages", [])
    except Exception:  # noqa: BLE001
        return summary, logs
    turn = 0
    pending: dict[str, dict] = {}
    for m in messages:
        if isinstance(m, AIMessage):
            turn += 1
            logs.append({"t": 0, "type": "llm", "turn": turn})
            for tc in (m.tool_calls or []):
                args = tc.get("args", {})
                name = tc.get("name", "tool")
                entry = {
                    "t": 0,
                    "type": "tool_start",
                    "tool": name,
                    "label": _label(name),
                    "input": _tool_detail(name, args, limit=320),
                }
                logs.append(entry)
                pending[tc.get("id", "")] = entry
            txt = _text_of(m.content).strip()
            if txt:
                summary = txt
        elif isinstance(m, ToolMessage):
            entry = pending.get(getattr(m, "tool_call_id", ""))
            if entry is not None:
                out = _text_of(m.content)
                entry["output"] = _tool_output_detail(out)
                if getattr(m, "status", None) == "error":
                    entry["error"] = entry.get("output", "error")
    return summary, logs


def _artifacts(workspace) -> dict:
    """Read the diagram artifacts currently in the workspace (if any)."""
    import base64
    out: dict = {}
    png = workspace / "out.png"
    if png.exists():
        out["png_base64"] = base64.b64encode(png.read_bytes()).decode("ascii")
    drawio = workspace / "out.drawio"
    if drawio.exists():
        out["drawio"] = drawio.read_text(encoding="utf-8", errors="replace")
    code = workspace / "diagram.py"
    if code.exists():
        out["code"] = code.read_text(encoding="utf-8", errors="replace")
    pdf = workspace / "out.pdf"
    if pdf.exists():
        out["pdf_base64"] = base64.b64encode(pdf.read_bytes()).decode("ascii")
    pptx = workspace / "out.pptx"
    if pptx.exists():
        out["pptx_base64"] = base64.b64encode(pptx.read_bytes()).decode("ascii")
    xlsx = workspace / "wbs_filled.xlsx"
    if xlsx.exists():
        out["wbs_xlsx_base64"] = base64.b64encode(xlsx.read_bytes()).decode("ascii")
    return out


def _stage_artifacts(workspace) -> dict:
    """Read structured planning artifacts currently in the workspace."""
    out: dict = {}
    analysis = _read_json(workspace / "architecture_analysis.json")
    brief = _read_json(workspace / "diagram_brief.json")
    ts = _read_json(workspace / "tech_stack.json")
    bp = _read_json(workspace / "blueprint.json")
    tool_summary = _read_json(workspace / "tool_budget_summary.json")
    wbs = _read_json(workspace / "wbs.json")
    if analysis:
        out["architecture_analysis"] = _coerce_brief(analysis)
    if brief:
        out["diagram_brief"] = _coerce_brief(brief)
    if ts:
        out["tech_stack"] = _normalize_tech_stack(ts)
    if bp:
        out["blueprint"] = _normalize_blueprint(bp)
    if tool_summary:
        out["tool_budget_summary"] = tool_summary
    if wbs:
        totals = wbs.get("effort_totals") or {}
        timeline = wbs.get("timeline") or {}
        out["wbs_summary"] = {
            "total_mandays": totals.get("total_mandays", 0),
            "total_manmonths": totals.get("total_manmonths", 0),
            "effort_by_role": totals.get("effort_by_role", {}),
            "weeks": timeline.get("weeks", 0),
            "months": timeline.get("months", 0),
            "effort_by_module": (wbs.get("effort_by_module") or [])[:12],
        }
    return out


def _run_metrics(workspace, logs: list[dict]) -> dict:
    tool_counts: dict[str, int] = {}
    model_calls = 0
    for item in logs:
        if item.get("type") == "llm":
            model_calls += 1
        elif item.get("type") == "tool_start":
            tool = item.get("tool") or "tool"
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
    out = {"model_calls": model_calls, "tool_counts": tool_counts}
    tool_summary = _read_json(workspace / "tool_budget_summary.json")
    if tool_summary:
        out["tool_budget_summary"] = tool_summary
    return out
