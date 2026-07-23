"""AG-UI SSE endpoint — /agui."""

from __future__ import annotations

import json
import logging

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

import conversations as conv_db
from agent import RECURSION_LIMIT
from backends import (
    resolve_workspace,
    reset_current_workspace,
    set_current_workspace,
)
from runtime.safe_path import safe_workspace_path
from context import SessionContext
from domain.reporting.reporting import record_report_step
from observability import new_id, reset_context, set_context
from security.auth import Identity, require_identity
from security.ownership import ensure_owner
from tools import GATE_TOOL_NAMES, allowed_decisions_for, clear_stage_markers
import session_state as ss
from session_state import (
    _artifacts,
    _card_for,
    _decision_from_payload,
    _display_subagent,
    _is_email_followup,
    _is_pdf_followup,
    _is_ppt_followup,
    _is_wbs_followup,
    _wbs_preserve,
    _label,
    _last_tool_msg,
    _last_user_text,
    _looks_like_tool_selection_prefix,
    _pending_action_name,
    _pending_interrupt,
    _run_metrics,
    _sse,
    _stage_artifacts,
    _summary_and_logs,
    _text_of,
    _TOOL_TO_SUBAGENT,
    _tool_detail,
    _tool_output_detail,
    _tool_selection_detail,
    _tool_selection_tools,
)

logger = logging.getLogger("diagram-agent")

router = APIRouter()


def _activity_event(
    phase: str,
    tool: str,
    label: str = "",
    detail: str = "",
    subagent: str | None = None,
    ok: bool | None = None,
) -> dict:
    """Build a tool/subagent progress event as an AG-UI CUSTOM envelope.

    AG-UI's EventType enum has no bare "ACTIVITY" type (only ACTIVITY_SNAPSHOT /
    ACTIVITY_DELTA, which model a different shape) — CUSTOM is the spec's generic
    passthrough for app-specific events, letting an @ag-ui/client consumer parse
    this stream without dropping/rejecting it.
    """
    value: dict = {"phase": phase, "tool": tool, "label": label, "detail": detail}
    if subagent:
        value["subagent"] = subagent
    if ok is not None:
        value["ok"] = ok
    return {"type": "CUSTOM", "name": "activity", "value": value}


def _persist_decision_record(payload: dict, gate: str | None, approver: str, approver_role: str = "") -> None:
    """Append a HITL v2 DecisionRecord to the workspace log (no-op for plain
    approve/reject or on any failure — must never break the resume).

    Records the approver's role (§8.6) and, when a role is supplied, checks it against
    the gate's role policy (can_approve): a disallowed role is logged as a warning but
    still recorded for the audit trail (advisory enforcement — the streaming resume must
    not hard-fail until the frontend reliably supplies roles)."""
    if not gate or payload.get("action") not in ss.HITL_V2_ACTIONS:
        return
    try:
        from datetime import datetime, timezone

        from memory.stores.decisions import append_decision, next_seq
        from session_state import decision_record_from_payload
        from tools import can_approve

        if approver_role and not can_approve(approver_role, gate):
            logger.warning(
                "role %r is not permitted to approve gate %s (recorded anyway)", approver_role, gate
            )
        from backends import current_workspace

        rec = decision_record_from_payload(
            payload,
            gate,
            seq=next_seq(current_workspace()),
            approver=approver,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        if rec is not None:
            rec.approver_role = approver_role
            append_decision(rec, current_workspace())
            logger.info(
                "persisted decision %s (%s) at %s by role=%s", rec.id, rec.action, gate, approver_role or "-"
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to persist decision record: %s", exc)


_RESTORABLE_FILES = {
    "architecture_analysis": "architecture_analysis.json",
    "diagram_brief": "diagram_brief.json",
    "tech_stack": "tech_stack.json",
    "blueprint": "blueprint.json",
}


def _wbs_plan_ready(workspace) -> bool:
    try:
        wbs = json.loads((workspace / "wbs.json").read_text(encoding="utf-8"))
    except Exception:
        return False
    items = wbs.get("items") or []
    totals = wbs.get("effort_totals") or {}
    try:
        total_mandays = float(totals.get("total_mandays") or 0)
    except (TypeError, ValueError):
        total_mandays = 0
    return bool(items) and total_mandays > 0


def _wbs_solution_context_exists(workspace) -> bool:
    """Return True when there is enough upstream context to plan a WBS."""
    return any(
        (workspace / filename).exists()
        for filename in (
            "blueprint.json",
            "tech_stack.json",
            "diagram_brief.json",
            "requirements.md",
            "layout_plan.json",
            "out.drawio",
            "out.png",
        )
    )


async def _restore_workspace_from_db(pool, thread_id: str, workspace) -> None:
    """Write stage JSON files back to disk if they are missing but present in DB state.

    This guards against the shared-workspace race: any fresh run calls
    clear_stage_markers() which deletes JSON files for all threads.  When a
    PPT/PDF followup comes in for a thread whose files were wiped by another
    thread, we recover them from the snapshot saved in conversations.state_json.
    """
    from pathlib import Path

    ws = Path(workspace)
    missing = [k for k, f in _RESTORABLE_FILES.items() if not (ws / f).exists()]
    if not missing:
        return
    history = await conv_db.get_history(pool, thread_id)
    if not history:
        return
    state = history.get("state") or {}
    ws.mkdir(parents=True, exist_ok=True)
    for key in missing:
        filename = _RESTORABLE_FILES[key]
        value = state.get(key)
        if value:
            safe_workspace_path(ws, filename).write_text(
                json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info("restored %s from DB state for thread %s", filename, thread_id)


@router.post("/agui")
async def agui_endpoint(request: Request, identity: Identity = Depends(require_identity)):
    body = await request.json()
    thread_id = body.get("threadId", "thread-default")
    run_id = body.get("runId", "run-1")
    messages = body.get("messages", [])
    file_ids = body.get("file_ids", [])

    # §0.6: threadId is client-supplied and was previously unauthenticated — any
    # caller who knew/guessed a thread_id could resume/approve it. The first
    # authenticated caller to touch a thread_id claims it; a later caller with a
    # different identity gets 404 rather than silently attaching to it.
    await ensure_owner(request.app.state.pool, thread_id, identity.email)

    # §4.10 per-thread isolation: every JSON store / stage marker / render artifact —
    # including the agent's own built-in FilesystemBackend, requirements.md, and the
    # per-thread /memories/ route — is resolved against this thread's own workspace
    # dir. Only /global-memories/ stays shared across threads — see backends.py.
    ws = resolve_workspace(thread_id)

    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": RECURSION_LIMIT,
        "run_name": "diagram-agent",
        "tags": ["diagram-agent"],
        "metadata": {"thread_id": thread_id, "run_id": run_id},
    }
    session_ctx = SessionContext(
        # §0.6: user_email now comes from the server-verified identity, not the
        # client-supplied body — a self-asserted userEmail could previously be
        # used as the HITL approver-of-record for any gate.
        user_email=identity.email,
        composio_api_key=body.get("composioApiKey", "") or "",
        gmail_account_id=body.get("gmailAccountId", "") or "",
        calendar_account_id=body.get("calendarAccountId", "") or "",
    )
    last_tool = _last_tool_msg(messages)

    async def stream():
        _ws_token = set_current_workspace(ws)
        # §1.4: bind correlation ids for every log line this run emits, reset
        # in the same finally: as the workspace token below (same lifetime —
        # both scoped to this one streamed /agui run).
        _ctx_token = set_context(request_id=new_id(), thread_id=thread_id, run_id=run_id)
        _upsert_snap: dict = {}
        run_errored = False
        yield _sse({"type": "RUN_STARTED", "threadId": thread_id, "runId": run_id})
        try:
            if last_tool is not None:
                # Resume from a HITL gate with the user's approve/reject decision.
                try:
                    payload = json.loads(last_tool.get("content", "{}"))
                except Exception:  # noqa: BLE001
                    payload = {}
                pending_name = _pending_action_name(await _pending_interrupt(config))
                decision = _decision_from_payload(payload, pending_name)
                logger.info(
                    "resume %s → %s (action=%s)", pending_name, decision["type"], payload.get("action")
                )
                # HITL v2: persist a structured decision record for trade-off actions
                # (accept_risk, approve_with_assumptions, request_evidence, ...). It is
                # projected into the CSM on the next build_solution_model.
                _persist_decision_record(
                    payload, pending_name, session_ctx.user_email, approver_role=identity.role
                )
                # §4.10: on a gate approval, snapshot the signed-off solution model as an
                # immutable approved revision (approved/REV-<n>.json) for audit/repro.
                if decision.get("type") == "approve" and pending_name in GATE_TOOL_NAMES:
                    try:
                        from memory.stores.csm_adapter import archive_approved_revision

                        archive_approved_revision(ws)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("approved-revision archive skipped: %s", exc)
                if pending_name in GATE_TOOL_NAMES:
                    note = payload.get("feedback") or payload.get("modifications") or ""
                    record_report_step(
                        ws,
                        f"{pending_name}_gate",
                        status=decision["type"],
                        summary=(
                            f"User {'approved' if decision['type'] == 'approve' else 'rejected'} {pending_name}."
                            + (f" Feedback: {note}" if note else "")
                        ),
                        data={
                            "gate": pending_name,
                            "decision": decision["type"],
                            "note": str(note) if note else "",
                        },
                    )
                    await conv_db.record_gate_outcome(
                        request.app.state.pool,
                        thread_id=thread_id,
                        gate=pending_name,
                        decision=decision["type"],
                        note=str(note) if note else "",
                    )
                agen = ss.AGENT.astream(
                    Command(resume={"decisions": [decision]}),
                    config,
                    context=session_ctx,
                    stream_mode=["messages", "updates", "custom"],
                )
            else:
                # Fresh run.
                from routers.upload import _attached_images, _attached_text

                desc = _last_user_text(messages)
                attached = _attached_text(file_ids)
                image_blocks = _attached_images(file_ids)
                is_pdf_followup = _is_pdf_followup(desc)
                is_ppt_followup = _is_ppt_followup(desc)
                is_wbs_followup = _is_wbs_followup(desc)
                is_email_followup = _is_email_followup(desc)
                if (
                    is_pdf_followup or is_ppt_followup or is_wbs_followup or is_email_followup
                ) and not attached:
                    # Restore before deciding whether a downstream follow-up can
                    # preserve artifacts. A previous run may have wiped the
                    # per-thread JSON files while the conversation snapshot still
                    # has them; checking disk first would falsely classify the
                    # request as fresh and clear the files WBS/PPT/PDF/email need.
                    await _restore_workspace_from_db(request.app.state.pool, thread_id, ws)
                # A newly attached document is fresh intake for a (possibly new) project,
                # not a request to re-export the existing diagram/WBS — never preserve
                # stale artifacts over it, no matter what followup phrase matched.
                preserve_diagram_artifacts = (
                    (is_pdf_followup or is_ppt_followup) and (ws / "out.png").exists() and not attached
                )
                # A WBS request is ALWAYS a downstream step from an approved solution, never a
                # fresh project — so preserve whenever the upstream solution exists on disk,
                # NOT only when wbs.json already exists. Requiring wbs.json here meant the very
                # FIRST WBS request (wbs.json not yet written) fell through to clear_stage_markers()
                # and deleted the brief/tech_stack/blueprint that load_solution_context reads,
                # so the planner reported "No upstream artifacts found" and never started.
                solution_exists = _wbs_solution_context_exists(ws)
                wbs_exists_flag = _wbs_plan_ready(ws)
                preserve_wbs_artifacts, wbs_already_planned = _wbs_preserve(
                    desc,
                    solution_exists=solution_exists,
                    wbs_exists=wbs_exists_flag,
                    attached=bool(attached),
                )
                # preserve_wbs_artifacts=True + wbs_already_planned=False + wbs.json already
                # on disk is the one combination _wbs_preserve() can't be plain re-export
                # (that's wbs_already_planned=True) nor first-time planning (no wbs.json
                # yet) — it's a re-estimate request (see _is_wbs_reestimate_followup).
                wbs_reestimate_requested = (
                    preserve_wbs_artifacts and not wbs_already_planned and wbs_exists_flag
                )
                # A request to EMAIL a deliverable is never a regenerate/re-export request,
                # even when the phrasing also matches "wbs"/"report" (e.g. "gửi file WBS qua
                # email"). Preserve everything on disk unconditionally and never let the
                # pdf/ppt/wbs branches below inject a "regenerate now" instruction — see the
                # `preserve_email_artifacts` check ordered first in the if/elif chain.
                preserve_email_artifacts = is_email_followup and not attached
                preserve_artifacts = (
                    preserve_diagram_artifacts or preserve_wbs_artifacts or preserve_email_artifacts
                )
                if not preserve_artifacts:
                    clear_stage_markers(preserve_wbs=(not attached and _wbs_plan_ready(ws)))
                else:
                    if preserve_email_artifacts:
                        desc = (
                            (desc + "\n\n" if desc else "")
                            + "IMPORTANT: The user wants to SEND an already-generated "
                            "deliverable via email. Do NOT regenerate/re-render/re-export "
                            "anything and do NOT re-run the WBS/PDF/PPT pipeline — the "
                            "files (out.pdf, out.pptx, wbs_filled.xlsx, out.drawio, "
                            "out.png) already exist in the workspace. Call `send_email(...)` "
                            "directly; leave `attachments` empty to attach whatever "
                            "deliverables already exist, or name a specific subset. Only "
                            "generate a deliverable first if the one requested genuinely "
                            "does not exist yet."
                        )
                    elif wbs_already_planned:
                        desc = (
                            (desc + "\n\n" if desc else "")
                            + "IMPORTANT: The user is asking to (re-)export/send the WBS "
                            "deliverable. A WBS plan already exists and was approved "
                            "(wbs.json). Do NOT re-delegate to wbs_planner or redo the "
                            "skeleton/estimate gates — just call `export_wbs_excel()` "
                            "directly to regenerate the file."
                        )
                    elif wbs_reestimate_requested:
                        # An approved wbs.json already exists AND the user wants to CHANGE
                        # it (drop/scale/filter items), not just re-export the stale numbers
                        # or redraft the skeleton from scratch. Point the agent at the
                        # code-interpreter path built for exactly this (improvement plan §C):
                        # transform the existing wbs.json with run_python, then commit +
                        # recompute via apply_wbs_reestimate — never retype numbers by hand.
                        desc = (
                            (desc + "\n\n" if desc else "")
                            + "IMPORTANT: An approved `wbs.json` already exists. The user "
                            "wants to MODIFY/RE-ESTIMATE it (e.g. drop items/modules, remove "
                            "columns like fe/mobile, scale effort) — this is NOT a plain "
                            "re-export and NOT a from-scratch replan. Delegate to "
                            "`wbs_planner` and instruct it to: read the current `wbs.json`, "
                            "use `run_python` to write a NEW file with the requested "
                            "transform applied (never overwrite `wbs.json` directly, never "
                            "hand-retype `qc`/`pm`/`total` — those get re-derived "
                            "automatically), then call "
                            "`apply_wbs_reestimate(source_file=...)` to validate + commit + "
                            "recompute the rollup/timeline/team/milestones. Do NOT call "
                            "`draft_wbs_skeleton`/`propose_wbs_skeleton` again — the skeleton "
                            "is unchanged. Only call `export_wbs_excel()` after the "
                            "re-estimate is committed, if the user also wants the file "
                            "regenerated."
                        )
                    elif preserve_wbs_artifacts:
                        # First-time WBS on an existing solution: artifacts are preserved
                        # (brief/tech_stack/blueprint kept on disk) so load_solution_context
                        # has its inputs. Do NOT inject the re-export shortcut — let the normal
                        # wbs_planner delegation (skeleton → estimate gates) run.
                        desc = (
                            (desc + "\n\n" if desc else "")
                            + "IMPORTANT: The approved solution artifacts (diagram_brief.json, "
                            "tech_stack.json, blueprint.json) already exist in the workspace — "
                            "build the WBS from them. Delegate to `wbs_planner` as usual; do NOT "
                            "re-run intake or redesign the diagram."
                        )
                        desc += (
                            "\n\nIMPORTANT WBS ORDER: This is a FIRST-TIME WBS request. "
                            "Do NOT call `export_wbs_excel()` yet if no approved `wbs.json` "
                            "exists. Delegate to `wbs_planner` first: run "
                            "`load_solution_context`, draft `wbs_skeleton.json`, call "
                            "`propose_wbs_skeleton()`, then create/finalize `wbs.json`, "
                            "call `propose_wbs()`, and only after that call "
                            "`export_wbs_excel()`. Do NOT report this as blocked merely "
                            "because `wbs.json` is missing before planning."
                        )
                    else:
                        artifact_instruction = (
                            "The user is asking for a PPT/proposal/PowerPoint deck. Do NOT "
                            "redesign or re-render the diagram. Call `generate_ppt_proposal({})` "
                            "now so the PPT approval gate is shown, then complete after `out.pptx` "
                            "is created."
                            if is_ppt_followup and not is_pdf_followup
                            else "The user is asking for a PDF/report/document. Do NOT "
                            "redesign or re-render the diagram. Call `generate_pdf_report({})` "
                            "now so the PDF approval gate is shown, then complete after `out.pdf` "
                            "is created."
                        )
                        desc = (
                            (desc + "\n\n" if desc else "")
                            + "IMPORTANT: A rendered diagram already exists in the workspace "
                            "(`out.png`, `out.drawio`, `diagram.py`) with approved planning "
                            f"artifacts. {artifact_instruction}"
                        )
                req_file = ws / "requirements.md"
                if attached:
                    ws.mkdir(parents=True, exist_ok=True)
                    req_file.write_text(
                        f"<untrusted_document>\n{attached}\n</untrusted_document>",
                        encoding="utf-8",
                    )
                    desc = (
                        (desc + "\n\n" if desc else "")
                        + "IMPORTANT: the detailed requirement documents are saved to "
                        "`requirements.md` in your working directory — read that file "
                        "first for the full requirements."
                    )
                elif req_file.exists() and not preserve_artifacts:
                    req_file.unlink()

                if image_blocks:
                    img_note = (
                        "\n\nReference image(s) are attached above. Use the topology "
                        "and layout shown as a guide when proposing the blueprint; "
                        "the critic may compare the final render against them."
                    )
                    content: list | str = [{"type": "text", "text": (desc or "") + img_note}] + image_blocks
                else:
                    content = desc

                logger.info(
                    "new run: %r%s%s",
                    (desc or "")[:120],
                    " (+docs→requirements.md)" if attached else "",
                    f" (+{len(image_blocks)} ref-image(s))" if image_blocks else "",
                )
                agen = ss.AGENT.astream(
                    {"messages": [HumanMessage(content=content)]},
                    config,
                    context=session_ctx,
                    stream_mode=["messages", "updates", "custom"],
                )

            current_id: str | None = None
            selector_candidate_id: str | None = None
            selector_buffer = ""
            suppressed_text_ids: set[str] = set()
            seen_starts: set[str] = set()
            seen_ends: set[str] = set()
            _pending_tasks: dict[str, dict] = {}
            _completed_delegations: list[dict] = []

            def _text_events(message_id: str, delta: str) -> list[dict]:
                nonlocal current_id
                events: list[dict] = []
                if message_id != current_id:
                    if current_id is not None:
                        events.append({"type": "TEXT_MESSAGE_END", "messageId": current_id})
                    current_id = message_id
                    events.append(
                        {
                            "type": "TEXT_MESSAGE_START",
                            "messageId": current_id,
                            "role": "assistant",
                        }
                    )
                events.append(
                    {
                        "type": "TEXT_MESSAGE_CONTENT",
                        "messageId": current_id,
                        "delta": delta,
                    }
                )
                return events

            def _selector_events(message_id: str, tools: list[str]) -> list[dict]:
                nonlocal current_id
                events: list[dict] = []
                if current_id is not None and current_id != message_id:
                    events.append({"type": "TEXT_MESSAGE_END", "messageId": current_id})
                    current_id = None
                detail = _tool_selection_detail(tools)
                events.append(
                    _activity_event("start", "tool_selector", label="Selecting tools", detail=detail)
                )
                events.append(
                    _activity_event("end", "tool_selector", label="Selecting tools", detail=detail, ok=True)
                )
                return events

            async for mode, payload in agen:
                if mode == "messages":
                    chunk, _meta = payload
                    if getattr(chunk, "type", "") not in ("ai", "AIMessageChunk"):
                        continue
                    text = _text_of(chunk.content)
                    if not text:
                        continue
                    mid = getattr(chunk, "id", None) or "ai"
                    if mid in suppressed_text_ids:
                        continue

                    if selector_candidate_id is not None and mid != selector_candidate_id:
                        if selector_buffer:
                            for event in _text_events(selector_candidate_id, selector_buffer):
                                yield _sse(event)
                        selector_candidate_id = None
                        selector_buffer = ""

                    if selector_candidate_id == mid:
                        selector_buffer += text
                        tools = _tool_selection_tools(selector_buffer)
                        if tools is not None:
                            suppressed_text_ids.add(mid)
                            selector_candidate_id = None
                            selector_buffer = ""
                            logger.info("tool selector chose: %s", ", ".join(tools))
                            for event in _selector_events(mid, tools):
                                yield _sse(event)
                            continue
                        if (
                            _looks_like_tool_selection_prefix(selector_buffer)
                            and len(selector_buffer) <= 4096
                        ):
                            continue
                        text = selector_buffer
                        selector_candidate_id = None
                        selector_buffer = ""
                    elif _looks_like_tool_selection_prefix(text):
                        selector_candidate_id = mid
                        selector_buffer = text
                        tools = _tool_selection_tools(selector_buffer)
                        if tools is not None:
                            suppressed_text_ids.add(mid)
                            selector_candidate_id = None
                            selector_buffer = ""
                            logger.info("tool selector chose: %s", ", ".join(tools))
                            for event in _selector_events(mid, tools):
                                yield _sse(event)
                        continue

                    for event in _text_events(mid, text):
                        yield _sse(event)
                elif mode == "updates":
                    for _node, upd in (payload or {}).items():
                        if not isinstance(upd, dict):
                            continue
                        msgs_raw = upd.get("messages", []) or []
                        if not isinstance(msgs_raw, (list, tuple)):
                            msgs_raw = getattr(msgs_raw, "value", None) or []
                        for m in msgs_raw:
                            if isinstance(m, AIMessage):
                                for tc in m.tool_calls or []:
                                    tcid = tc.get("id") or ""
                                    if tcid in seen_starts:
                                        continue
                                    seen_starts.add(tcid)
                                    name = tc.get("name", "tool")
                                    args = tc.get("args", {})
                                    detail = _tool_detail(name, args)
                                    subagent = _TOOL_TO_SUBAGENT.get(name)
                                    if name == "task":
                                        sa_name = (
                                            args.get("subagent_type")
                                            or args.get("subagent")
                                            or args.get("name")
                                            or "unknown"
                                        )
                                        sa_desc = (
                                            args.get("description")
                                            or args.get("instruction")
                                            or args.get("prompt")
                                            or ""
                                        )
                                        record = {
                                            "id": tcid,
                                            "subagent": sa_name,
                                            "description": sa_desc,
                                            "status": "running",
                                            "result": None,
                                            "current_detail": detail,
                                        }
                                        _pending_tasks[tcid] = record
                                        logger.info("→ delegate to %s: %s", sa_name, sa_desc[:80])
                                        yield _sse(
                                            _activity_event(
                                                "start",
                                                name,
                                                label=f"Delegating to {_display_subagent(sa_name)}",
                                                subagent=sa_name,
                                                detail=detail,
                                            )
                                        )
                                        all_delegations = _completed_delegations + list(
                                            _pending_tasks.values()
                                        )
                                        yield _sse(
                                            {
                                                "type": "STATE_DELTA",
                                                "delta": [
                                                    {
                                                        "op": "add",
                                                        "path": "/delegations",
                                                        "value": all_delegations,
                                                    }
                                                ],
                                            }
                                        )
                                    else:
                                        logger.info(
                                            "→ %s%s%s",
                                            _label(name),
                                            f" [{subagent}]" if subagent else "",
                                            f" — {detail}" if detail else "",
                                        )
                                        yield _sse(
                                            _activity_event(
                                                "start",
                                                name,
                                                label=_label(name),
                                                detail=detail,
                                                subagent=subagent,
                                            )
                                        )
                            elif isinstance(m, ToolMessage):
                                tcid = getattr(m, "tool_call_id", "") or ""
                                if tcid in seen_ends:
                                    continue
                                seen_ends.add(tcid)
                                name = getattr(m, "name", "tool")
                                ok = getattr(m, "status", None) != "error"
                                subagent = _TOOL_TO_SUBAGENT.get(name)
                                if tcid in _pending_tasks:
                                    result_text = _text_of(m.content)
                                    record = _pending_tasks.pop(tcid)
                                    record["status"] = "completed" if ok else "error"
                                    record["result"] = (
                                        (result_text[:500] + "…") if len(result_text) > 500 else result_text
                                    )
                                    _completed_delegations.append(record)
                                    logger.info(
                                        "← delegate %s done (%s)", record["subagent"], record["status"]
                                    )
                                    all_delegations = _completed_delegations + list(_pending_tasks.values())
                                    yield _sse(
                                        {
                                            "type": "STATE_DELTA",
                                            "delta": [
                                                {
                                                    "op": "add",
                                                    "path": "/delegations",
                                                    "value": all_delegations,
                                                }
                                            ],
                                        }
                                    )
                                output_detail = _tool_output_detail(m.content)
                                if ok:
                                    logger.info("← %s ok%s", name, f" [{subagent}]" if subagent else "")
                                else:
                                    logger.info(
                                        "← %s ERROR%s — %s",
                                        name,
                                        f" [{subagent}]" if subagent else "",
                                        output_detail,
                                    )
                                yield _sse(
                                    _activity_event(
                                        "end", name, ok=ok, detail=output_detail, subagent=subagent
                                    )
                                )
                                if name in {"generate_pdf_report", "generate_ppt_proposal"} and ok:
                                    artifact_delta = [
                                        {"op": "add", "path": f"/{k}", "value": v}
                                        for k, v in _artifacts(ws).items()
                                    ]
                                    artifact_delta.append(
                                        {"op": "add", "path": "/current_step", "value": "done"}
                                    )
                                    yield _sse({"type": "STATE_DELTA", "delta": artifact_delta})
                                if name == "export_wbs_excel" and ok:
                                    artifact_delta = [
                                        {"op": "add", "path": f"/{k}", "value": v}
                                        for k, v in _artifacts(ws).items()
                                    ]
                                    for k, v in _stage_artifacts(ws).items():
                                        artifact_delta.append({"op": "add", "path": f"/{k}", "value": v})
                                    yield _sse({"type": "STATE_DELTA", "delta": artifact_delta})
                elif mode == "custom":
                    sa_name = payload.get("subagent", "")
                    phase = payload.get("phase", "start")
                    tool = payload.get("tool", "tool")
                    ok = payload.get("ok", True)
                    detail = payload.get("detail", "")
                    label = _label(tool)
                    logger.info(
                        "  [%s] %s %s%s",
                        sa_name,
                        "→" if phase == "start" else "←",
                        label,
                        f" — {detail}" if detail else "",
                    )
                    yield _sse(
                        _activity_event(
                            phase,
                            tool,
                            label=label,
                            detail=detail,
                            subagent=sa_name,
                            ok=(ok if phase == "end" else None),
                        )
                    )
                    if phase == "start":
                        for _tcid, record in _pending_tasks.items():
                            if record.get("subagent") == sa_name:
                                record["current_tool"] = tool
                                record["current_label"] = label
                                record["current_detail"] = detail
                                yield _sse(
                                    {
                                        "type": "STATE_DELTA",
                                        "delta": [
                                            {
                                                "op": "add",
                                                "path": "/delegations",
                                                "value": _completed_delegations
                                                + list(_pending_tasks.values()),
                                            }
                                        ],
                                    }
                                )
                                break
                    elif phase == "end":
                        for record in _pending_tasks.values():
                            if record.get("subagent") == sa_name:
                                record.pop("current_tool", None)
                                record.pop("current_label", None)
                                record.pop("current_detail", None)
                                break
            if selector_candidate_id is not None and selector_buffer:
                for event in _text_events(selector_candidate_id, selector_buffer):
                    yield _sse(event)
            if current_id is not None:
                yield _sse({"type": "TEXT_MESSAGE_END", "messageId": current_id})

            summary, logs = await _summary_and_logs(config)
            run_met = _run_metrics(ws, logs)

            val = await _pending_interrupt(config)
            if val is not None:
                card, step, delta = _card_for(val, summary)
                if card is not None:
                    # HITL v2: tell the UI which trade-off actions this gate offers.
                    gate_name = _pending_action_name(val)
                    if gate_name:
                        card.setdefault("allowed_decisions", allowed_decisions_for(gate_name))
                    logger.info("PAUSED at gate: %s", card["type"])
                    state_delta = [{"op": "add", "path": "/current_step", "value": step}]
                    for k, v in _stage_artifacts(ws).items():
                        state_delta.append({"op": "add", "path": f"/{k}", "value": v})
                    state_delta.append({"op": "add", "path": "/run_metrics", "value": run_met})
                    for k, v in delta.items():
                        state_delta.append({"op": "add", "path": f"/{k}", "value": v})
                    for k, v in _artifacts(ws).items():
                        state_delta.append({"op": "add", "path": f"/{k}", "value": v})
                    yield _sse({"type": "STATE_DELTA", "delta": state_delta})
                    tc_id = f"tc-{run_id}"
                    yield _sse({"type": "TOOL_CALL_START", "toolCallId": tc_id, "toolCallName": card["type"]})
                    yield _sse({"type": "TOOL_CALL_ARGS", "toolCallId": tc_id, "delta": json.dumps(card)})
                    yield _sse({"type": "TOOL_CALL_END", "toolCallId": tc_id})
                    await conv_db.upsert_run(
                        request.app.state.pool,
                        thread_id=thread_id,
                        messages=messages,
                        state={
                            "current_step": step,
                            **_stage_artifacts(ws),
                            **delta,
                            **_artifacts(ws),
                            "run_metrics": run_met,
                        },
                        last_msg=_last_user_text(messages),
                        auto_name=(_last_user_text(messages) or "Untitled")[:50],
                        owner_email=identity.email,
                    )
                    yield _sse({"type": "RUN_FINISHED", "threadId": thread_id, "runId": run_id})
                    return

            all_delegations = _completed_delegations + [
                {**r, "status": "running"} for r in _pending_tasks.values()
            ]

            png = ws / "out.png"
            if png.exists():
                logger.info("run finished — diagram ready")
                snapshot = {"current_step": "done", "summary": summary, "logs": logs, "run_metrics": run_met}
                snapshot.update(_stage_artifacts(ws))
                snapshot.update(_artifacts(ws))
                if all_delegations:
                    snapshot["delegations"] = all_delegations
                _upsert_snap = snapshot
                yield _sse({"type": "STATE_SNAPSHOT", "snapshot": snapshot})
            else:
                snap: dict = {"logs": logs, "run_metrics": run_met}
                snap.update(_stage_artifacts(ws))
                if all_delegations:
                    snap["delegations"] = all_delegations
                _upsert_snap = snap
                yield _sse({"type": "STATE_SNAPSHOT", "snapshot": snap})

        except GraphRecursionError as exc:
            logger.exception("agent run hit the graph recursion limit: %s", exc)
            run_errored = True
            yield _sse(
                {
                    "type": "RUN_ERROR",
                    "message": (
                        "The run hit its overall step safety limit "
                        f"(recursion_limit={RECURSION_LIMIT}) and was stopped. Partial "
                        "artifacts are saved in the workspace — send a follow-up "
                        "message to continue from where it stopped."
                    ),
                    "code": "recursion_limit",
                }
            )
        except (httpx.TimeoutException, TimeoutError) as exc:
            # Covers the raw transport read timeout (httpx.ReadTimeout) and the
            # vendored langchain_openai StreamChunkTimeoutError (subclass of
            # TimeoutError) — the model connection went quiet mid-stream.
            logger.warning("agent run timed out mid-stream: %r", exc)
            run_errored = True
            yield _sse(
                {
                    "type": "RUN_ERROR",
                    "message": (
                        "The model connection timed out while generating a response "
                        "(the endpoint went quiet). Partial artifacts, if any, are saved "
                        "in the workspace — please resend your message to continue."
                    ),
                    "code": "model_timeout",
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("agent run failed: %s", exc)
            run_errored = True
            yield _sse({"type": "RUN_ERROR", "message": str(exc), "code": "internal_error"})
        finally:
            reset_current_workspace(_ws_token)
            reset_context(_ctx_token)

        if _upsert_snap:
            await conv_db.upsert_run(
                request.app.state.pool,
                thread_id=thread_id,
                messages=messages,
                state=_upsert_snap,
                last_msg=_last_user_text(messages),
                auto_name=(_last_user_text(messages) or "Untitled")[:50],
                owner_email=identity.email,
            )
        if not run_errored:
            # AG-UI treats RUN_ERROR as terminal; don't also emit RUN_FINISHED.
            yield _sse({"type": "RUN_FINISHED", "threadId": thread_id, "runId": run_id})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
