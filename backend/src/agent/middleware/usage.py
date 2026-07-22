"""Per-model-call usage logging + missing-text-block diagnostics."""

from __future__ import annotations

import asyncio
import json
import logging
import os

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, AnyMessage

from ..constants import _WARN_CALL_COUNT, _WARN_INPUT_TOKENS

logger = logging.getLogger(__name__)


def _warn_missing_text_blocks(agent_name: str, messages: list[AnyMessage]) -> None:
    """Log any outgoing content block lacking a non-empty "text" key.

    mimo rejects requests containing a content block with no (or empty) "text"
    field (see InjectVisionAsUserEdit) — this is a diagnostic-only check (no
    behavior change) so a recurrence pinpoints the exact offending message
    instead of requiring another from-scratch investigation. Callers gate this
    to mimo-backed agents only.
    """
    for i, msg in enumerate(messages):
        content = getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and not block.get("text"):
                logger.warning(
                    "agent %s: outgoing message block missing non-empty text — "
                    "msg_idx=%d msg_type=%s block_type=%s",
                    agent_name,
                    i,
                    type(msg).__name__,
                    block.get("type"),
                )


class UsageLoggingMiddleware(AgentMiddleware):
    """Append per-model-call token usage to WORKSPACE/usage.json.

    Reads ``usage_metadata`` from the first AIMessage in the response and appends
    a record to usage.json so we can observe token spend per agent over time.

    ``_call_count`` used to be a plain instance counter that never reset: the
    middleware object is built once inside ``_middleware()`` at ``build_agent()``
    time, which itself runs ONCE at server startup and is cached globally
    (``session_state.AGENT``), reused across every conversation and every
    ``task(subagent_type=...)`` delegation for the server process's entire
    lifetime. So the "N model calls (threshold=30)" warning log was cumulative
    since process start, not per-round — a real trace showed "agent drawer: 99
    model calls" spanning at least two separate drawer delegations, making it
    impossible to tell how many calls any single round actually took. Fixed by
    resetting the counter whenever ``request.messages`` has no prior AIMessage
    yet, i.e. this model call is the first one of a fresh subgraph invocation
    (each ``task()`` call starts a brand-new, empty conversation for that
    subagent — see the "stateless subagent" design in drawer_agent.py).
    """

    def __init__(self, agent_name: str, *, check_missing_text: bool = False) -> None:
        self._agent_name = agent_name
        self._call_count = 0
        self._check_missing_text = check_missing_text

    @staticmethod
    def _is_fresh_run(messages) -> bool:
        return not any(isinstance(m, AIMessage) for m in messages or [])

    def _log(self, usage: dict) -> None:
        try:
            from backends import current_workspace  # avoid circular at module load

            path = current_workspace() / "usage.json"
            try:
                records: list = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
            except Exception:
                records = []
            records.append({"agent": self._agent_name, **usage})
            path.write_text(json.dumps(records, indent=2), encoding="utf-8")
        except Exception:
            logger.debug("UsageLoggingMiddleware: failed to write usage.json", exc_info=True)

    def _extract_usage(self, response: ModelResponse) -> dict | None:
        for msg in response.result or []:
            if isinstance(msg, AIMessage) and msg.usage_metadata:
                m = msg.usage_metadata
                return {
                    "input_tokens": m.get("input_tokens", 0),
                    "output_tokens": m.get("output_tokens", 0),
                    "total_tokens": m.get("total_tokens", 0),
                }
        return None

    async def awrap_model_call(self, request: ModelRequest, handler):
        if self._check_missing_text:
            _warn_missing_text_blocks(self._agent_name, request.messages)
        if self._is_fresh_run(request.messages):
            self._call_count = 0
        response: ModelResponse = await handler(request)
        usage = self._extract_usage(response)
        if usage:
            self._call_count += 1
            if self._call_count > _WARN_CALL_COUNT:
                logger.warning(
                    "agent %s: %d model calls (threshold=%d) — potential runaway loop",
                    self._agent_name,
                    self._call_count,
                    _WARN_CALL_COUNT,
                )
            if usage["input_tokens"] > _WARN_INPUT_TOKENS:
                logger.warning(
                    "agent %s: input context=%d tok (threshold=%d) — approaching limit",
                    self._agent_name,
                    usage["input_tokens"],
                    _WARN_INPUT_TOKENS,
                )
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._log, usage)
        return response

    def wrap_model_call(self, request: ModelRequest, handler):
        if self._check_missing_text:
            _warn_missing_text_blocks(self._agent_name, request.messages)
        if self._is_fresh_run(request.messages):
            self._call_count = 0
        response: ModelResponse = handler(request)
        usage = self._extract_usage(response)
        if usage:
            self._call_count += 1
            if self._call_count > _WARN_CALL_COUNT:
                logger.warning(
                    "agent %s: %d model calls (threshold=%d) — potential runaway loop",
                    self._agent_name,
                    self._call_count,
                    _WARN_CALL_COUNT,
                )
            if usage["input_tokens"] > _WARN_INPUT_TOKENS:
                logger.warning(
                    "agent %s: input context=%d tok (threshold=%d) — approaching limit",
                    self._agent_name,
                    usage["input_tokens"],
                    _WARN_INPUT_TOKENS,
                )
            self._log(usage)
        return response


def _compact_tool_args(args: dict | None, *, limit: int = 260) -> str:
    """Human-readable one-line summary of tool args for live UI activity."""
    if not isinstance(args, dict) or not args:
        return ""
    safe = dict(args)
    if "code" in safe:
        code = str(safe["code"])
        safe["code"] = f"{len(code)} chars"
    if "blueprint" in safe:
        bp = safe["blueprint"] or {}
        if isinstance(bp, dict):
            safe["blueprint"] = {
                "pattern": bp.get("pattern"),
                "style": bp.get("presentation_style", "diagram"),
                "nodes": len(bp.get("nodes") or []),
                "clusters": len(bp.get("clusters") or []),
                "edges": len(bp.get("edges") or []),
            }
    if "description" in safe:
        desc = " ".join(str(safe["description"]).split())
        safe["description"] = desc[:180] + ("..." if len(desc) > 180 else "")
    if "icons" in safe and isinstance(safe["icons"], list):
        labels = [str(x.get("label", "")) for x in safe["icons"] if isinstance(x, dict) and x.get("label")]
        safe["icons"] = f"{len(safe['icons'])} icons: {', '.join(labels[:8])}"
    try:
        text = json.dumps(safe, ensure_ascii=False)
    except Exception:
        text = str(safe)
    return text[:limit] + ("..." if len(text) > limit else "")


def _compact_tool_output(content, *, limit: int = 320) -> str:
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                if "text" in p:
                    parts.append(str(p.get("text") or ""))
                elif p.get("type") == "image":
                    parts.append("[image preview]")
        text = " ".join(parts)
    else:
        text = ""
    text = " ".join(text.split())
    return text[:limit] + ("..." if len(text) > limit else "")
