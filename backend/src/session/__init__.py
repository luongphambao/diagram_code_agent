"""Session helper submodules split out of ``session_state.py``: tool labels/
attribution, SSE/activity formatting, follow-up phrase detection, artifact
JSON normalization, and HITL gate/decision mapping.

The ``AGENT`` singleton and the two functions that read it directly
(``_pending_interrupt``, ``_summary_and_logs``) stay in the top-level
``session_state.py`` module — NOT here — because ``server.py`` assigns
``session_state.AGENT = build_agent(...)`` at startup and every reader
(``routers/chat.py``) does ``import session_state as ss; ss.AGENT`` (a live
module-attribute read). Splitting ``AGENT`` into this package would leave
functions defined here reading a permanently-``None`` copy while
``session_state.AGENT`` gets the real graph — the same class of bug as a
duplicated contextvar. See ``session_state.py``'s module docstring.
"""

from __future__ import annotations

from .labels import _display_subagent, _label, _SUBAGENT_DISPLAY_NAMES, _TOOL_LABELS, _TOOL_TO_SUBAGENT
from .sse import (
    _compact_json,
    _looks_like_tool_selection_prefix,
    _sse,
    _text_of,
    _tool_detail,
    _tool_output_detail,
    _tool_selection_detail,
    _tool_selection_tools,
)
from .followups import (
    _is_email_followup,
    _is_pdf_followup,
    _is_ppt_followup,
    _is_wbs_followup,
    _last_tool_msg,
    _last_user_text,
    _matches_whole_phrase,
    _wbs_preserve,
)
from .normalize import (
    _ASSUMPTION_ARRAY_FIELDS,
    _BRIEF_ARRAY_FIELDS,
    _coerce_assumptions,
    _coerce_brief,
    _coerce_list,
    _normalize_blueprint,
    _normalize_tech_stack,
)
from .gate_decisions import (
    HITL_V2_ACTIONS,
    _DEFAULT_TZ,
    _PROCEED_ACTIONS,
    _REVISE_ACTIONS,
    _card_for,
    _decision_from_payload,
    _pending_action_name,
    _revise_message,
    decision_record_from_payload,
)
from .artifacts import _artifacts, _read_json, _run_metrics, _stage_artifacts
