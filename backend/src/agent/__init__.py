"""The diagram deep agent — a single `create_deep_agent` with tools + memory.

Design: **deep agent + tools + memory**, no shell.
  - backend : per-thread FilesystemBackend (workspace) + a per-thread `/memories/`
              route + a shared `/global-memories/` route  (see backends.py)
  - tools   : render_diagram / export_drawio / search_icons / fetch_logo  (see tools/)
  - memory  : /global-memories/AGENTS.md (durable, cross-thread learnings) +
              /memories/AGENTS.md (this thread's own scratch notes)
  - skills  : diagrams-as-code, pro-style   (on-demand know-how)

The agent writes `diagrams` code, calls `render_diagram` to run it and LOOK at the
PNG, refines, then `export_drawio`. The server (`server.py`) streams this agent and
surfaces the produced out.png / out.drawio / diagram.py to the frontend.

This package used to be a single 1525-line ``agent.py`` module. It is now split
into cohesive submodules:

  agent/constants.py    — models, skill paths, call-limit tunables
  agent/middleware/     — context-editing edits, phase filter, drawer gate, vision
                           fallback, usage logging, and the ``_middleware()`` assembler
  agent/subagents/      — declarative SubagentSpec per role (spec.py) + registry
  agent/streaming.py    — _StreamingSubAgentRunnable (outer-stream relay for task() calls)
  agent/harness.py      — process-global deepagents harness-profile tuning
  agent/persistence.py  — make_persistence() (checkpointer + store)
  agent/builder.py      — build_agent() (assembles everything above)

Every name that used to live directly in ``agent.py`` is re-exported here so
existing ``from agent import X`` / ``import agent as agent_module; agent_module.X``
call sites keep working unmodified.
"""

from __future__ import annotations

from deepagents import create_deep_agent  # noqa: F401 — re-exported for parity

from .builder import build_agent
from .constants import (
    CONTEXT_TRIGGER_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_STYLE,
    DRAWER_SKILL_PATHS,
    MAIN_SKILL_PATHS,
    PPT_GENERATOR_SKILL_PATHS,
    REASONING_EFFORT,
    RECURSION_LIMIT,
    WBS_PLANNER_SKILL_PATHS,
    _CRITIC_CALL_LIMIT,
    _DRAWER_CALL_LIMIT,
    _ICON_CALL_LIMIT,
    _MAIN_TOOL_SELECTOR,
    _MAIN_TOOL_SELECTOR_ALWAYS_INCLUDE,
    _PPT_CALL_LIMIT,
    _RUN_CALL_LIMIT,
    _WARN_CALL_COUNT,
    _WARN_INPUT_TOKENS,
    _WBS_CALL_LIMIT,
)
from .harness import _register_tuned_summarization_profiles, _set_general_purpose_enabled
from .middleware import _middleware
from .middleware.context_edits import (
    InjectVisionAsUserEdit,
    KeepLatestImagesEdit,
    OffloadGateArgsEdit,
    SanitizeToolTextBlocksEdit,
)
from .middleware.drawer_gate import DrawerReviseGateMiddleware
from .middleware.phase_filter import (
    PhasePromptFilterMiddleware,
    PhaseToolFilterMiddleware,
    _ARTIFACT_BACKFILL_TOOLS,
    _PHASE_TOOLS,
    _UTILITY_TOOLS,
    _detect_phase,
    _missing_artifact_tools,
    _pending_gate_tools,
    _strip_phase_spans,
    _tool_name,
)
from .middleware.usage import (
    UsageLoggingMiddleware,
    _compact_tool_args,
    _compact_tool_output,
    _warn_missing_text_blocks,
)
from .middleware.vision import VisionErrorFallbackMiddleware
from .persistence import make_persistence
from .streaming import _StreamingSubAgentRunnable
from .subagents import SubagentSpec, build_subagent_specs
