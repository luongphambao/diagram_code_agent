"""HITL gate → UI card mapping, and payload → langchain approve/reject decision.

Named ``gate_decisions`` (not ``decisions``) to avoid colliding with the
top-level ``decisions`` module (the HITL v2 DecisionRecord store, now at
``memory/stores/decisions.py``) that :func:`decision_record_from_payload`
imports from below.
"""

from __future__ import annotations

from domain.reporting.ppt_reporting import DEFAULT_PPT_SECTIONS
from domain.reporting.reporting import DEFAULT_REPORT_SECTIONS

from .normalize import _coerce_assumptions, _coerce_list, _normalize_blueprint, _normalize_tech_stack

_DEFAULT_TZ = "Asia/Ho_Chi_Minh"


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
    if name == "send_email":
        attachments = args.get("attachments") or []
        what = ", ".join(attachments) if attachments else "the generated deliverables"
        return (
            {
                "type": "email_approval",
                "question": f"Send {what} to {args.get('recipient_email', '')}?",
                "recipient_email": args.get("recipient_email", ""),
                "subject": args.get("subject", ""),
                "project_name": args.get("project_name", ""),
                "subtitle": args.get("subtitle", ""),
                "recipient_name": args.get("recipient_name", "Team"),
                "attachments": attachments,
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
    if name == "export_to_delivery":
        sys_l = str(args.get("system", "")).strip().lower()
        dry_run = bool(args.get("dry_run", True))
        return (
            {
                "type": "delivery_export_approval",
                "question": (
                    f"Push the WBS work items to {sys_l or 'the delivery tracker'}"
                    + (" (preview / dry-run)?" if dry_run else " — live sync?")
                ),
                "system": sys_l,
                "dry_run": dry_run,
            },
            "awaiting_delivery_export",
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
    from memory.stores.decisions import new_decision_record
    # Carry the action-specific fields through verbatim (minus routing keys).
    body = {k: v for k, v in payload.items()
            if k not in ("action", "approved", "satisfied", "modifications", "feedback")}
    return new_decision_record(
        gate, action, seq=seq, approver=approver, timestamp=timestamp,
        revision=revision, comment=payload.get("comment", ""), payload=body,
    )
