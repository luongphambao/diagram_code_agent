"""Wraps a compiled subagent graph so its per-step tool calls surface in the
outer LangGraph stream."""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage
from langchain_core.messages import ToolMessage as LCToolMessage
from langgraph.config import get_stream_writer

from .middleware.usage import _compact_tool_args, _compact_tool_output

logger = logging.getLogger(__name__)


class _StreamingSubAgentRunnable:
    """Wraps a compiled subagent graph so its per-step tool calls surface in the
    outer LangGraph stream.

    deepagents calls ``compiled["runnable"].with_config(...).ainvoke(state, cfg)``
    for every ``task(...)`` call.  We intercept ``ainvoke``, run ``astream``
    internally, and write each tool-call / tool-result event to the outer stream
    via ``get_stream_writer()``.  The server handles these as ``"custom"`` mode
    events and re-emits them as live ACTIVITY SSE events.

    ``get_stream_writer()`` is captured **before** we enter the inner astream
    (LangGraph sets a new context-var value for the inner graph), so we always
    write to the *outer* stream.  If we are not inside a streaming context
    (tests, headless eval) the writer is ``None`` and we fall back silently.
    """

    def __init__(self, runnable, name: str) -> None:
        self._runnable = runnable
        self._name = name

    def with_config(self, config=None, **kwargs):
        return _StreamingSubAgentRunnable(self._runnable.with_config(config or {}, **kwargs), self._name)

    async def ainvoke(self, state, config=None, **kwargs):
        # Capture the outer stream writer once, before entering the inner astream.
        try:
            writer = get_stream_writer()
        except Exception:
            writer = None

        final_values = None
        try:
            async for mode, data in self._runnable.astream(
                state, config, stream_mode=["updates", "values"], **kwargs
            ):
                if mode == "values":
                    final_values = data
                elif mode == "updates" and writer is not None:
                    for _node, upd in (data or {}).items():
                        if not isinstance(upd, dict):
                            continue
                        for msg in upd.get("messages", []) or []:
                            if isinstance(msg, AIMessage):
                                for tc in msg.tool_calls or []:
                                    writer(
                                        {
                                            "subagent": self._name,
                                            "phase": "start",
                                            "tool": tc.get("name", "tool"),
                                            "detail": _compact_tool_args(tc.get("args")),
                                        }
                                    )
                            elif isinstance(msg, LCToolMessage):
                                writer(
                                    {
                                        "subagent": self._name,
                                        "phase": "end",
                                        "tool": getattr(msg, "name", "tool"),
                                        "ok": getattr(msg, "status", None) != "error",
                                        "detail": _compact_tool_output(getattr(msg, "content", "")),
                                    }
                                )
        except Exception:
            # Streaming failed (version mismatch, wrong context, etc.) — fall back
            # to a plain invoke so the task still completes.
            logger.warning(
                "subagent %s streaming failed, falling back to ainvoke",
                self._name,
                exc_info=True,
            )
            return self._flag_call_limit_stop(await self._runnable.ainvoke(state, config, **kwargs) or {})

        return self._flag_call_limit_stop(final_values or {})

    def _flag_call_limit_stop(self, result: dict) -> dict:
        """Make a call-limit stop LOUD instead of silent.

        ModelCallLimitMiddleware(exit_behavior="end") terminates the subagent
        with a bare "Model call limits exceeded: ..." AIMessage; the main agent
        used to read that as an ordinary (confusing) status. Prefix it so main
        knows the work is partial and must be reported to the user — never
        silently re-dispatched.
        """
        msgs = (result or {}).get("messages") or []
        if msgs:
            last = msgs[-1]
            content = getattr(last, "content", "")
            if isinstance(content, str) and content.startswith("Model call limits exceeded"):
                logger.warning("subagent %s stopped at its model-call limit", self._name)
                note = (
                    f"SUBAGENT {self._name} STOPPED AT ITS SAFETY CALL LIMIT — the "
                    "work is PARTIAL; whatever was produced is already on disk in "
                    "the workspace. Tell the user this stage hit its safety limit, "
                    "continue from the existing artifacts, and do NOT re-dispatch "
                    "the same task without changing the approach. "
                )
                try:
                    msgs[-1] = last.model_copy(update={"content": note + content})
                except Exception:  # noqa: BLE001 — never break the task result
                    pass
        return result
