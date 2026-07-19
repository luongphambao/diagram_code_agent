"""Assembles the per-agent middleware stack.

ORDERING CONTRACT (enforced by tests/test_middleware_order.py — do not reorder
without updating that test):
  ContextEditing -> UsageLogging -> ModelCallLimit -> ToolArgCoercion (must
  precede DrawerReviseGate — gate decisions assume well-formed task args) ->
  VisionErrorFallback -> ToolCallLimit(task) -> DrawerReviseGate ->
  DrawerContextInject (must follow DrawerReviseGate — only augment dispatches
  that weren't blocked) -> PhaseToolFilter + PhasePromptFilter ->
  LLMToolSelector -> [ModelFallback].

``exit_behavior``: ModelCallLimitMiddleware uses "end"; the `task`
ToolCallLimitMiddleware uses "continue" ("end" raises NotImplementedError with
pending parallel calls) — keep these exact.
"""

from __future__ import annotations

import logging
import os

from langchain.agents.middleware import (
    AgentMiddleware,
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    LLMToolSelectorMiddleware,
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelFallbackMiddleware,
    ToolCallLimitMiddleware,
)

from tools import GATE_TOOL_NAMES

from ..constants import (
    CONTEXT_TRIGGER_TOKENS,
    _MAIN_TOOL_SELECTOR,
    _MAIN_TOOL_SELECTOR_ALWAYS_INCLUDE,
    _RUN_CALL_LIMIT,
)
from .context_edits import (
    InjectVisionAsUserEdit,
    KeepLatestImagesEdit,
    OffloadGateArgsEdit,
    SanitizeToolTextBlocksEdit,
)
from .drawer_context_inject import DrawerContextInjectMiddleware
from .drawer_gate import DrawerReviseGateMiddleware
from .phase_filter import PhasePromptFilterMiddleware, PhaseToolFilterMiddleware
from .usage import UsageLoggingMiddleware
from .vision import VisionErrorFallbackMiddleware

logger = logging.getLogger(__name__)

class SafeLLMToolSelectorMiddleware(AgentMiddleware):
    """LLM tool selector that intersects always_include with current tools.

    PhaseToolFilterMiddleware intentionally removes tools that are invalid in the
    current workflow phase. LangChain's selector validates ``always_include``
    against that filtered request, so static entries like ``finalize_diagram``
    can raise before the model call. Build an inner selector per request with
    only the names still present.
    """

    def __init__(self, *, max_tools: int | None = None,
                 always_include: list[str] | None = None):
        super().__init__()
        self.max_tools = max_tools
        self.always_include = always_include or []

    @staticmethod
    def _tool_name(tool) -> str:
        if isinstance(tool, dict):
            return tool.get("name", "")
        return getattr(tool, "name", "")

    def _selector(self, request: ModelRequest) -> LLMToolSelectorMiddleware:
        available = {self._tool_name(tool) for tool in request.tools or []}
        always_include = [name for name in self.always_include if name in available]
        return LLMToolSelectorMiddleware(
            max_tools=self.max_tools,
            always_include=always_include,
        )

    async def awrap_model_call(self, request: ModelRequest, handler):
        return await self._selector(request).awrap_model_call(request, handler)

    def wrap_model_call(self, request: ModelRequest, handler):
        return self._selector(request).wrap_model_call(request, handler)


def _middleware(run_limit: int = _RUN_CALL_LIMIT, *, agent_name: str = "agent",
                model: str | None = None,
                use_vision_relay: bool = False,
                use_tool_selector: bool = False,
                use_phase_filter: bool = False,
                use_drawer_revise_gate: bool = False,
                task_call_limit: int | None = None):
    from config import resolve_provider as _resolve_provider
    exclude = GATE_TOOL_NAMES
    # KeepLatestImagesEdit MUST run before InjectVisionAsUserEdit: it reduces
    # the ToolMessage history down to a single live image before the relay
    # edit scans for images to relay. See InjectVisionAsUserEdit's docstring.
    edits: list = [KeepLatestImagesEdit()]
    if use_vision_relay:
        edits.append(InjectVisionAsUserEdit())
    edits += [
        SanitizeToolTextBlocksEdit(),
        OffloadGateArgsEdit(),
        ClearToolUsesEdit(
            trigger=CONTEXT_TRIGGER_TOKENS,
            # ClearToolUsesEdit.apply() breaks out of its clearing loop as soon as
            # `clear_at_least` tokens have been reclaimed, even if older clearable
            # ToolMessages remain (langchain/agents/middleware/context_editing.py).
            # Edits are ephemeral (recomputed from the full persisted checkpoint on
            # every model call, never written back), so a small clear_at_least only
            # ever trims a flat slice off the front — on a long-lived thread (many
            # accumulated user turns) the untouched remainder dominates and the
            # per-call floor keeps climbing indefinitely instead of settling near
            # `trigger`. Set far above any real context size so the loop always
            # clears every candidate outside `keep` instead of stopping early.
            clear_at_least=1_000_000,
            keep=4,
            clear_tool_inputs=True,
            exclude_tools=exclude,
        ),
    ]
    from tool_coercion import ToolArgCoercionMiddleware
    layers = [
        ContextEditingMiddleware(
            edits=edits,
            token_count_method="approximate",
        ),
        UsageLoggingMiddleware(
            agent_name,
            check_missing_text=bool(model) and _resolve_provider(model)[0] == "mimo",
        ),
        ModelCallLimitMiddleware(run_limit=run_limit, exit_behavior="end"),
        # Every agent: repair mimo's stringified list/dict args before Pydantic
        # validation and compact the kwargs-echoing invocation-error messages.
        # Must be listed before DrawerReviseGateMiddleware (gate decisions assume
        # well-formed task args).
        ToolArgCoercionMiddleware(),
    ]
    if use_vision_relay:
        # Vision 400s ("Multimodal data is corrupted") retry once text-only
        # instead of letting the model retry-storm the same payload.
        layers.append(VisionErrorFallbackMiddleware())
    if task_call_limit is not None:
        # Defense-in-depth against subagent-dispatch storms: caps `task` calls
        # per run. exit_behavior="continue" (not "end") — "end" raises
        # NotImplementedError when parallel tool calls are pending.
        layers.append(ToolCallLimitMiddleware(
            tool_name="task", run_limit=task_call_limit, exit_behavior="continue",
        ))
    if use_drawer_revise_gate:
        layers.append(DrawerReviseGateMiddleware())
        # Must follow DrawerReviseGateMiddleware: only augment task(drawer, ...)
        # dispatches that weren't blocked by the gate above.
        layers.append(DrawerContextInjectMiddleware())
    if use_phase_filter:
        layers.append(PhaseToolFilterMiddleware())
        layers.append(PhasePromptFilterMiddleware())
    if use_tool_selector and _MAIN_TOOL_SELECTOR:
        layers.append(SafeLLMToolSelectorMiddleware(
            max_tools=20,
            always_include=_MAIN_TOOL_SELECTOR_ALWAYS_INCLUDE,
        ))
    # Optional model fallback: set FALLBACK_MODEL env var to activate.
    # Format: "provider:model-name" e.g. "anthropic:claude-sonnet-4-5-20250929"
    fallback = os.getenv("FALLBACK_MODEL", "").strip()
    if fallback:
        layers.append(ModelFallbackMiddleware(fallback))
        logger.info("ModelFallbackMiddleware active  fallback=%s", fallback)
    return layers
