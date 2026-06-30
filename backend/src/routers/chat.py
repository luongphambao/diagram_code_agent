"""AG-UI SSE endpoint — /agui."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

import conversations as conv_db
from agent import RECURSION_LIMIT
from backends import WORKSPACE
from safe_path import safe_workspace_path
from context import SessionContext
from reporting import record_report_step
from tools import GATE_TOOL_NAMES, allowed_decisions_for, clear_stage_markers
import session_state as ss
from session_state import (
    _artifacts,
    _card_for,
    _decision_from_payload,
    _is_pdf_followup,
    _is_ppt_followup,
    _label,
    _last_tool_msg,
    _last_user_text,
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
)

logger = logging.getLogger("diagram-agent")

router = APIRouter()


def _persist_decision_record(payload: dict, gate: str | None, approver: str) -> None:
    """Append a HITL v2 DecisionRecord to the workspace log (no-op for plain
    approve/reject or on any failure — must never break the resume)."""
    if not gate or payload.get("action") not in ss.HITL_V2_ACTIONS:
        return
    try:
        from datetime import datetime, timezone

        from decisions import append_decision, next_seq
        from session_state import decision_record_from_payload

        rec = decision_record_from_payload(
            payload, gate,
            seq=next_seq(WORKSPACE),
            approver=approver,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        if rec is not None:
            append_decision(rec, WORKSPACE)
            logger.info("persisted decision %s (%s) at %s", rec.id, rec.action, gate)
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to persist decision record: %s", exc)

_RESTORABLE_FILES = {
    "architecture_analysis": "architecture_analysis.json",
    "diagram_brief":         "diagram_brief.json",
    "tech_stack":            "tech_stack.json",
    "blueprint":             "blueprint.json",
}


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
async def agui_endpoint(request: Request):
    body = await request.json()
    thread_id = body.get("threadId", "thread-default")
    run_id = body.get("runId", "run-1")
    messages = body.get("messages", [])
    file_ids = body.get("file_ids", [])

    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": RECURSION_LIMIT,
        "run_name": "diagram-agent",
        "tags": ["diagram-agent"],
        "metadata": {"thread_id": thread_id, "run_id": run_id},
    }
    session_ctx = SessionContext(
        user_email=body.get("userEmail", "") or "",
        composio_api_key=body.get("composioApiKey", "") or "",
        gmail_account_id=body.get("gmailAccountId", "") or "",
        calendar_account_id=body.get("calendarAccountId", "") or "",
    )
    last_tool = _last_tool_msg(messages)

    async def stream():
        _upsert_snap: dict = {}
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
                logger.info("resume %s → %s (action=%s)", pending_name, decision["type"],
                            payload.get("action"))
                # HITL v2: persist a structured decision record for trade-off actions
                # (accept_risk, approve_with_assumptions, request_evidence, ...). It is
                # projected into the CSM on the next build_solution_model.
                _persist_decision_record(payload, pending_name, session_ctx.user_email)
                if pending_name in GATE_TOOL_NAMES:
                    note = payload.get("feedback") or payload.get("modifications") or ""
                    record_report_step(
                        WORKSPACE,
                        f"{pending_name}_gate",
                        status=decision["type"],
                        summary=(
                            f"User {'approved' if decision['type'] == 'approve' else 'rejected'} {pending_name}."
                            + (f" Feedback: {note}" if note else "")
                        ),
                        data={"gate": pending_name, "decision": decision["type"], "note": str(note) if note else ""},
                    )
                    await conv_db.record_gate_outcome(
                        request.app.state.pool,
                        thread_id=thread_id,
                        gate=pending_name,
                        decision=decision["type"],
                        note=str(note) if note else "",
                    )
                agen = ss.AGENT.astream(
                    Command(resume={"decisions": [decision]}), config,
                    context=session_ctx,
                    stream_mode=["messages", "updates", "custom"],
                )
            else:
                # Fresh run.
                from routers.upload import _attached_images, _attached_text
                desc = _last_user_text(messages)
                is_pdf_followup = _is_pdf_followup(desc)
                is_ppt_followup = _is_ppt_followup(desc)
                preserve_artifacts = (is_pdf_followup or is_ppt_followup) and (WORKSPACE / "out.png").exists()
                if not preserve_artifacts:
                    clear_stage_markers()
                else:
                    await _restore_workspace_from_db(request.app.state.pool, thread_id, WORKSPACE)
                    artifact_instruction = (
                        "The user is asking for a PPT/proposal/PowerPoint deck. Do NOT "
                        "redesign or re-render the diagram. Call `generate_ppt_proposal({})` "
                        "now so the PPT approval gate is shown, then complete after `out.pptx` "
                        "is created."
                        if is_ppt_followup and not is_pdf_followup else
                        "The user is asking for a PDF/report/document. Do NOT "
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
                attached = _attached_text(file_ids)
                image_blocks = _attached_images(file_ids)
                req_file = WORKSPACE / "requirements.md"
                if attached:
                    WORKSPACE.mkdir(parents=True, exist_ok=True)
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
                    content: list | str = (
                        [{"type": "text", "text": (desc or "") + img_note}]
                        + image_blocks
                    )
                else:
                    content = desc

                logger.info("new run: %r%s%s", (desc or "")[:120],
                            " (+docs→requirements.md)" if attached else "",
                            f" (+{len(image_blocks)} ref-image(s))" if image_blocks else "")
                agen = ss.AGENT.astream(
                    {"messages": [HumanMessage(content=content)]}, config,
                    context=session_ctx,
                    stream_mode=["messages", "updates", "custom"],
                )

            current_id: str | None = None
            seen_starts: set[str] = set()
            seen_ends: set[str] = set()
            _pending_tasks: dict[str, dict] = {}
            _completed_delegations: list[dict] = []
            async for mode, payload in agen:
                if mode == "messages":
                    chunk, _meta = payload
                    if getattr(chunk, "type", "") not in ("ai", "AIMessageChunk"):
                        continue
                    text = _text_of(chunk.content)
                    if not text:
                        continue
                    mid = getattr(chunk, "id", None) or "ai"
                    if mid != current_id:
                        if current_id is not None:
                            yield _sse({"type": "TEXT_MESSAGE_END", "messageId": current_id})
                        current_id = mid
                        yield _sse({"type": "TEXT_MESSAGE_START", "messageId": current_id, "role": "assistant"})
                    yield _sse({"type": "TEXT_MESSAGE_CONTENT", "messageId": current_id, "delta": text})
                elif mode == "updates":
                    for _node, upd in (payload or {}).items():
                        if not isinstance(upd, dict):
                            continue
                        msgs_raw = upd.get("messages", []) or []
                        if not isinstance(msgs_raw, (list, tuple)):
                            msgs_raw = getattr(msgs_raw, "value", None) or []
                        for m in msgs_raw:
                            if isinstance(m, AIMessage):
                                for tc in (m.tool_calls or []):
                                    tcid = tc.get("id") or ""
                                    if tcid in seen_starts:
                                        continue
                                    seen_starts.add(tcid)
                                    name = tc.get("name", "tool")
                                    args = tc.get("args", {})
                                    detail = _tool_detail(name, args)
                                    subagent = _TOOL_TO_SUBAGENT.get(name)
                                    if name == "task":
                                        sa_name = args.get("subagent_type") or args.get("subagent") or args.get("name") or "unknown"
                                        sa_desc = args.get("description") or args.get("instruction") or args.get("prompt") or ""
                                        record = {"id": tcid, "subagent": sa_name, "description": sa_desc,
                                                  "status": "running", "result": None,
                                                  "current_detail": detail}
                                        _pending_tasks[tcid] = record
                                        logger.info("→ delegate to %s: %s", sa_name, sa_desc[:80])
                                        yield _sse({"type": "ACTIVITY", "phase": "start", "tool": name,
                                                    "label": f"Delegating to {sa_name}", "subagent": sa_name,
                                                    "detail": detail})
                                        all_delegations = _completed_delegations + list(_pending_tasks.values())
                                        yield _sse({"type": "STATE_DELTA", "delta": [
                                            {"op": "replace", "path": "/delegations", "value": all_delegations}
                                        ]})
                                    else:
                                        logger.info("→ %s%s", _label(name),
                                                    f" [{subagent}]" if subagent else "")
                                        evt: dict = {"type": "ACTIVITY", "phase": "start",
                                                     "tool": name, "label": _label(name),
                                                     "detail": detail}
                                        if subagent:
                                            evt["subagent"] = subagent
                                        yield _sse(evt)
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
                                    record["result"] = (result_text[:500] + "…") if len(result_text) > 500 else result_text
                                    _completed_delegations.append(record)
                                    logger.info("← delegate %s done (%s)", record["subagent"], record["status"])
                                    all_delegations = _completed_delegations + list(_pending_tasks.values())
                                    yield _sse({"type": "STATE_DELTA", "delta": [
                                        {"op": "replace", "path": "/delegations", "value": all_delegations}
                                    ]})
                                logger.info("← %s %s%s", name, "ok" if ok else "ERROR",
                                            f" [{subagent}]" if subagent else "")
                                evt2: dict = {"type": "ACTIVITY", "phase": "end", "tool": name,
                                              "ok": ok, "detail": _tool_output_detail(m.content)}
                                if subagent:
                                    evt2["subagent"] = subagent
                                yield _sse(evt2)
                                if name in {"generate_pdf_report", "generate_ppt_proposal"} and ok:
                                    artifact_delta = [
                                        {"op": "replace", "path": f"/{k}", "value": v}
                                        for k, v in _artifacts(WORKSPACE).items()
                                    ]
                                    artifact_delta.append({"op": "replace", "path": "/current_step", "value": "done"})
                                    yield _sse({"type": "STATE_DELTA", "delta": artifact_delta})
                                if name == "export_wbs_excel" and ok:
                                    artifact_delta = [
                                        {"op": "replace", "path": f"/{k}", "value": v}
                                        for k, v in _artifacts(WORKSPACE).items()
                                    ]
                                    for k, v in _stage_artifacts(WORKSPACE).items():
                                        artifact_delta.append({"op": "replace", "path": f"/{k}", "value": v})
                                    yield _sse({"type": "STATE_DELTA", "delta": artifact_delta})
                elif mode == "custom":
                    sa_name = payload.get("subagent", "")
                    phase = payload.get("phase", "start")
                    tool = payload.get("tool", "tool")
                    ok = payload.get("ok", True)
                    detail = payload.get("detail", "")
                    label = _label(tool)
                    logger.info("  [%s] %s %s", sa_name, "→" if phase == "start" else "←", label)
                    act_evt: dict = {
                        "type": "ACTIVITY", "phase": phase,
                        "tool": tool, "label": label, "subagent": sa_name,
                        "detail": detail,
                    }
                    if phase == "end":
                        act_evt["ok"] = ok
                    yield _sse(act_evt)
                    if phase == "start":
                        for _tcid, record in _pending_tasks.items():
                            if record.get("subagent") == sa_name:
                                record["current_tool"] = tool
                                record["current_label"] = label
                                record["current_detail"] = detail
                                yield _sse({"type": "STATE_DELTA", "delta": [
                                    {"op": "replace", "path": "/delegations",
                                     "value": _completed_delegations + list(_pending_tasks.values())}
                                ]})
                                break
                    elif phase == "end":
                        for record in _pending_tasks.values():
                            if record.get("subagent") == sa_name:
                                record.pop("current_tool", None)
                                record.pop("current_label", None)
                                record.pop("current_detail", None)
                                break
            if current_id is not None:
                yield _sse({"type": "TEXT_MESSAGE_END", "messageId": current_id})

            summary, logs = await _summary_and_logs(config)
            run_met = _run_metrics(WORKSPACE, logs)

            val = await _pending_interrupt(config)
            if val is not None:
                card, step, delta = _card_for(val, summary)
                if card is not None:
                    # HITL v2: tell the UI which trade-off actions this gate offers.
                    gate_name = _pending_action_name(val)
                    if gate_name:
                        card.setdefault("allowed_decisions", allowed_decisions_for(gate_name))
                    logger.info("PAUSED at gate: %s", card["type"])
                    state_delta = [{"op": "replace", "path": "/current_step", "value": step}]
                    for k, v in _stage_artifacts(WORKSPACE).items():
                        state_delta.append({"op": "replace", "path": f"/{k}", "value": v})
                    state_delta.append({"op": "replace", "path": "/run_metrics", "value": run_met})
                    for k, v in delta.items():
                        state_delta.append({"op": "replace", "path": f"/{k}", "value": v})
                    for k, v in _artifacts(WORKSPACE).items():
                        state_delta.append({"op": "replace", "path": f"/{k}", "value": v})
                    yield _sse({"type": "STATE_DELTA", "delta": state_delta})
                    tc_id = f"tc-{run_id}"
                    yield _sse({"type": "TOOL_CALL_START", "toolCallId": tc_id, "toolCallName": card["type"]})
                    yield _sse({"type": "TOOL_CALL_ARGS", "toolCallId": tc_id, "delta": json.dumps(card)})
                    yield _sse({"type": "TOOL_CALL_END", "toolCallId": tc_id})
                    await conv_db.upsert_run(
                        request.app.state.pool,
                        thread_id=thread_id,
                        messages=messages,
                        state={"current_step": step, **_stage_artifacts(WORKSPACE), **delta,
                               **_artifacts(WORKSPACE), "run_metrics": run_met},
                        last_msg=_last_user_text(messages),
                        auto_name=(_last_user_text(messages) or "Untitled")[:50],
                    )
                    yield _sse({"type": "RUN_FINISHED", "threadId": thread_id, "runId": run_id})
                    return

            all_delegations = _completed_delegations + [
                {**r, "status": "running"} for r in _pending_tasks.values()
            ]

            png = WORKSPACE / "out.png"
            if png.exists():
                logger.info("run finished — diagram ready")
                snapshot = {"current_step": "done", "summary": summary, "logs": logs,
                            "run_metrics": run_met}
                snapshot.update(_stage_artifacts(WORKSPACE))
                snapshot.update(_artifacts(WORKSPACE))
                if all_delegations:
                    snapshot["delegations"] = all_delegations
                _upsert_snap = snapshot
                yield _sse({"type": "STATE_SNAPSHOT", "snapshot": snapshot})
            else:
                snap: dict = {"logs": logs, "run_metrics": run_met}
                snap.update(_stage_artifacts(WORKSPACE))
                if all_delegations:
                    snap["delegations"] = all_delegations
                _upsert_snap = snap
                yield _sse({"type": "STATE_SNAPSHOT", "snapshot": snap})

        except Exception as exc:  # noqa: BLE001
            logger.exception("agent run failed: %s", exc)
            yield _sse({"type": "RUN_ERROR", "message": str(exc), "code": "internal_error"})

        if _upsert_snap:
            await conv_db.upsert_run(
                request.app.state.pool,
                thread_id=thread_id,
                messages=messages,
                state=_upsert_snap,
                last_msg=_last_user_text(messages),
                auto_name=(_last_user_text(messages) or "Untitled")[:50],
            )
        yield _sse({"type": "RUN_FINISHED", "threadId": thread_id, "runId": run_id})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
