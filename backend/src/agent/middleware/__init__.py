"""Assembles the per-agent middleware stack.

ORDERING CONTRACT (enforced by tests/test_middleware_order.py — do not reorder
without updating that test):
  ContextEditing -> UsageLogging -> ModelCallLimit -> ToolArgCoercion (must
  precede DrawerReviseGate — gate decisions assume well-formed task args) ->
  VisionErrorFallback -> ToolCallLimit(task) -> DrawerReviseGate ->
  PhaseToolFilter + PhasePromptFilter -> LLMToolSelector -> [ModelFallback].

``exit_behavior``: ModelCallLimitMiddleware uses "end"; the `task`
ToolCallLimitMiddleware uses "continue" ("end" raises NotImplementedError with
pending parallel calls) — keep these exact.
"""

from __future__ import annotations

import logging
import os

from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    LLMToolSelectorMiddleware,
    ModelCallLimitMiddleware,
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
from .drawer_gate import DrawerReviseGateMiddleware
from .phase_filter import PhasePromptFilterMiddleware, PhaseToolFilterMiddleware
from .usage import UsageLoggingMiddleware
from .vision import VisionErrorFallbackMiddleware

logger = logging.getLogger(__name__)


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
            clear_at_least=8_000,
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
    if use_phase_filter:
        layers.append(PhaseToolFilterMiddleware())
        layers.append(PhasePromptFilterMiddleware())
    if use_tool_selector and _MAIN_TOOL_SELECTOR:
        layers.append(LLMToolSelectorMiddleware(
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
