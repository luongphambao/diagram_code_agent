"""Shared agent state, interrupt helpers, and data-normalization utilities.

All route handlers import from here; this module holds the singleton AGENT
global (set by the lifespan in server.py after the Postgres pool opens).

Most of the former 842-line module now lives in the ``session/`` package
(labels, sse, followups, normalize, gate_decisions, artifacts — all
AGENT-independent, re-exported below). ``AGENT`` itself and the two functions
that read it directly (``_pending_interrupt``, ``_summary_and_logs``) stay
HERE, in this top-level module, because ``server.py`` assigns
``session_state.AGENT = build_agent(...)`` at startup and every reader
(``routers/chat.py`` does ``import session_state as ss; ss.AGENT``) resolves
it as a live module-attribute read. Moving ``AGENT`` into ``session/`` would
mean functions defined there see a permanently-``None`` copy while this
module's copy gets the real graph — the same class of bug as a duplicated
contextvar (see ``backends.py``'s module docstring for the sibling case).
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, ToolMessage

from session import (  # noqa: F401 — re-exported for backward compatibility
    HITL_V2_ACTIONS,
    _ASSUMPTION_ARRAY_FIELDS,
    _BRIEF_ARRAY_FIELDS,
    _DEFAULT_TZ,
    _PROCEED_ACTIONS,
    _REVISE_ACTIONS,
    _SUBAGENT_DISPLAY_NAMES,
    _TOOL_LABELS,
    _TOOL_TO_SUBAGENT,
    _artifacts,
    _card_for,
    _coerce_assumptions,
    _coerce_brief,
    _coerce_list,
    _business_case_preserve,
    _compact_json,
    _decision_from_payload,
    _display_subagent,
    _is_business_case_followup,
    _is_email_followup,
    _is_pdf_followup,
    _is_ppt_followup,
    _is_wbs_followup,
    _is_wbs_reestimate_followup,
    _label,
    _last_tool_msg,
    _last_user_text,
    _looks_like_tool_selection_prefix,
    _wbs_preserve,
    _matches_whole_phrase,
    _normalize_blueprint,
    _normalize_tech_stack,
    _pending_action_name,
    _read_json,
    _revise_message,
    _run_metrics,
    _sse,
    _stage_artifacts,
    _text_of,
    _tool_detail,
    _tool_output_detail,
    _tool_selection_detail,
    _tool_selection_tools,
    decision_record_from_payload,
)

logger = logging.getLogger("diagram-agent")

# Set by server.lifespan after build_agent() completes.
AGENT = None


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
            for tc in m.tool_calls or []:
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
            if txt and _tool_selection_tools(txt) is None:
                summary = txt
        elif isinstance(m, ToolMessage):
            entry = pending.get(getattr(m, "tool_call_id", ""))
            if entry is not None:
                out = _text_of(m.content)
                entry["output"] = _tool_output_detail(out)
                if getattr(m, "status", None) == "error":
                    entry["error"] = entry.get("output", "error")
    # ModelCallLimitMiddleware(exit_behavior="end") ends the run with a bare
    # "Model call limits exceeded: run limit (N/N)" — translate it so the user
    # sees an explanation instead of a cryptic internal counter.
    if summary.startswith("Model call limits exceeded"):
        detail = summary[len("Model call limits exceeded:") :].strip()
        summary = (
            "This run stopped at its safety call limit before finishing "
            f"({detail}). Partial artifacts are saved in the workspace — send a "
            "follow-up message to continue from where it stopped."
        )
    return summary, logs
