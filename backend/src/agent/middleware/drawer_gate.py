"""Blocks a premature drawer-revise dispatch until finalize_diagram has been reached."""

from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langchain_core.messages import ToolMessage as LCToolMessage


class DrawerReviseGateMiddleware(AgentMiddleware):
    """Block a premature `task(subagent_type="drawer")` revise dispatch.

    `_blocks.py` step 8 tells the main agent that after critic's automatic
    first-pass review, a `VERDICT: REVISE` should only be noted to the user and
    followed by `finalize_diagram()` — never a second drawer/critic round ("one
    pass only"). That rule was prompt-only and the model didn't reliably follow
    it: a real trace (drawer_call.txt, 2026-07-03) showed the main agent
    dispatching "REVISE round 1" to drawer immediately after critic's first
    automatic REVISE verdict, before `finalize_diagram` (the only HITL gate
    where the user actually sees the diagram) had been reached at all. That
    unauthorized round cost a full extra drawer pass (skill re-reads, multiple
    re-renders, ~25+ model calls).

    This middleware makes the rule code-enforced: a `task(drawer, ...)` call is
    blocked unless a `finalize_diagram` gate has been reached (approved OR
    rejected — the HITL middleware emits a `ToolMessage(name="finalize_diagram")`
    either way, see `langchain.agents.middleware.human_in_the_loop._process_decision`)
    *after* the most recent `task(critic, ...)` call. An approved diagram never
    triggers another drawer call, so any drawer dispatch that clears this check
    is by construction a genuine post-rejection revision round — which is also
    why the `CRITIC_REVISION_HARD_CAP` budget (tools/constants.py) is consumed
    here rather than inside `submit_critique` (tools/analysis/blueprint_tools.py):
    critique itself can't tell an automatic pass from a real rejection round
    apart, but this gate can.
    """

    name = "DrawerReviseGateMiddleware"

    @staticmethod
    def _messages(request) -> list:
        state = request.state
        if isinstance(state, dict):
            return state.get("messages") or []
        return getattr(state, "messages", None) or []

    @staticmethod
    def _last_task_call_index(messages, subagent_type: str) -> int | None:
        idx = None
        for i, m in enumerate(messages):
            if isinstance(m, AIMessage):
                for tc in m.tool_calls or []:
                    if (
                        tc.get("name") == "task"
                        and (tc.get("args") or {}).get("subagent_type") == subagent_type
                    ):
                        idx = i
        return idx

    @staticmethod
    def _last_finalize_index(messages) -> int | None:
        idx = None
        for i, m in enumerate(messages):
            if isinstance(m, LCToolMessage) and getattr(m, "name", None) == "finalize_diagram":
                idx = i
        return idx

    def _decide(self, request) -> LCToolMessage | None:
        """Returns a blocking ToolMessage, or None to let the dispatch proceed."""
        tc = request.tool_call
        if tc.get("name") != "task" or (tc.get("args") or {}).get("subagent_type") != "drawer":
            return None
        messages = self._messages(request)
        last_critic_idx = self._last_task_call_index(messages, "critic")
        if last_critic_idx is None:
            return None  # critic hasn't reviewed anything yet — first pass, not our concern
        last_finalize_idx = self._last_finalize_index(messages)
        if last_finalize_idx is None or last_finalize_idx < last_critic_idx:
            return LCToolMessage(
                content=(
                    "Blocked: critic has already reviewed this render. Do NOT "
                    "dispatch another drawer revision yet. Call finalize_diagram() "
                    "first so the user sees the diagram together with critic's "
                    "findings. Only after the user responds at that gate (approve "
                    "or reject) may drawer be revised — combine critic's findings "
                    "with the user's own feedback into one revise instruction."
                ),
                name="task",
                tool_call_id=tc["id"],
                status="error",
            )
        # finalize_diagram was reached after the last critic call: this drawer
        # dispatch is a genuine post-rejection revision round.
        from tools.constants import CRITIC_REVISION_HARD_CAP, _REVISION_COUNT_FILE
        from tools.stage_markers import _read_json_file, _write_json_file, reset_render_count

        count = int(_read_json_file(_REVISION_COUNT_FILE, {"count": 0}).get("count", 0))
        if count >= CRITIC_REVISION_HARD_CAP:
            return LCToolMessage(
                content=(
                    f"Blocked: {CRITIC_REVISION_HARD_CAP} drawer revision rounds "
                    "already used this session. Call finalize_diagram() noting "
                    "residual findings instead of revising again."
                ),
                name="task",
                tool_call_id=tc["id"],
                status="error",
            )
        _write_json_file(_REVISION_COUNT_FILE, {"count": count + 1})
        reset_render_count()
        return None

    def wrap_tool_call(self, request, handler):
        blocked = self._decide(request)
        return blocked if blocked is not None else handler(request)

    async def awrap_tool_call(self, request, handler):
        blocked = self._decide(request)
        return blocked if blocked is not None else await handler(request)
