"""Tunables for the diagram deep agent: models, skill paths, call-limits,
context-management thresholds. All env-overridable; see each comment for why
the current default was chosen.
"""

from __future__ import annotations

import os

from backends import SKILLS_DIR

DEFAULT_MODEL = "mimo-v2.5"
DEFAULT_STYLE = "pretty"  # "pretty" (prettygraph) or "plain" (raw diagrams)
RECURSION_LIMIT = 450  # max agent steps per run (used by the server)
# Shared across main + every delegated subagent (task-tool invocations propagate
# the same config, so their steps count against this same budget) - ~2 graph
# steps per model call. Raised from 160 after a real run (main 46 calls +
# icon_resolver 34 calls = ~160 steps alone, before drawer even started)
# hit GraphRecursionError with no graceful degradation. 450 gives ~2.8x headroom
# over that failing case; per-agent ModelCallLimitMiddleware run_limits (main 120,
# icon/critic/drawer 40 each, wbs 120, ppt 60) still cap any single runaway agent
# gracefully well before this shared ceiling is reached in a normal request.
REASONING_EFFORT = "medium"  # used as fallback when no config.yaml present

MAIN_SKILL_PATHS = [
    (SKILLS_DIR / "diagrams-as-code").as_posix(),
    (SKILLS_DIR / "pro-style").as_posix(),
]
# Drawer and main now share a single canonical copy of these skills. The former
# `skills/drawer/*` duplicates had silently drifted (the top-level copies went
# stale); they were consolidated into the top-level dirs to remove the drift.
DRAWER_SKILL_PATHS = list(MAIN_SKILL_PATHS)
WBS_PLANNER_SKILL_PATHS = [
    (SKILLS_DIR / "wbs-planning").as_posix(),
]
PPT_GENERATOR_SKILL_PATHS = [
    (SKILLS_DIR / "ppt-generator").as_posix(),
]

# Context-management: the conversation is re-sent every turn, so stale tool
# outputs (read_file of skill docs, repeated search_icons, old render images)
# dominate cost. ClearToolUsesEdit replaces old tool results with "[cleared]"
# once a turn's (approximate) tokens exceed the trigger, keeping the most recent
# few intact. It runs locally (no LLM) and preserves tool_call/result pairs, so
# HITL gates and resume are unaffected. We clear aggressively (clear_at_least is
# huge → drop every clearable old result, keep only the recent ones) because the
# agent re-reads anything it still needs from disk. (deepagents already bundles a
# SummarizationMiddleware as the long-run safety net.)
CONTEXT_TRIGGER_TOKENS = 30_000  # main context is lean (no images/icons), can be higher

# Per-run model-call caps: after this many model calls in one run the agent
# exits cleanly ("Model call limits exceeded") instead of looping forever.
# Each agent (main / drawer / critic) is a SEPARATE run with its own budget.
# A clean drawer pass needs ~8-14 calls (prompt budget: "≤12 model calls" now
# that style/fit are pre-computed and the audit runs inside render_diagram).
# The render per-tool budget (tools.RENDER_HARD_CAP) doesn't cover export_drawio,
# so the model-call ceiling is the real backstop for a stuck drawer — keep it
# comfortably above the intended budget, not 8x looser.
# Override via env for experiments.
# Lowered 120→80 (main) after the retry-storm fixes (arg coercion, pre-flight
# audit, code-driven WBS tail): the happy path needs far fewer calls now, and a
# lower ceiling stops a residual runaway ~1.2M input tokens sooner.
_RUN_CALL_LIMIT = int(os.getenv("RUN_CALL_LIMIT", "80"))  # main only
_CRITIC_CALL_LIMIT = int(os.getenv("CRITIC_CALL_LIMIT", "40"))  # inspect+critique only

# Per-stage (per-subagent) model-call budgets (§4.10 "per-stage budget"). Each
# subagent is a separate run with its own ceiling so a single stage can't burn
# the whole session; tune independently via env without touching the others.
# Token/cost per stage is recorded separately by UsageLoggingMiddleware → usage.json
# (keyed by agent_name), which the quality dashboard reads for spend-to-quality.
# icon_resolver's own prompt budgets "under 6 tool calls" for the happy path
# (one resolve_icons batch + a few NOT_FOUND retries). It was briefly lowered to
# 15 after a defecting run (manually read/edit/grep-ing icon_plan.json instead of
# using resolve_icons/update_icon_plan_entry) burned ~40 calls / ~1M tokens. That
# specific manual-edit runaway is now blocked independently at the permission
# layer (_ICON_PLAN_WRITE_DENY in subagents/icon_resolver.py) and resolve_icons/
# resolve_missing_icons self-reject repeat calls, so the call ceiling is now a
# backstop rather than the primary defense. Restored to 40 for generous headroom
# on legitimate NOT_FOUND / brand-logo retries (stubborn off-catalog labels)
# without reopening the blowout path. Env-overridable.
_ICON_CALL_LIMIT = int(os.getenv("ICON_CALL_LIMIT", "40"))
_DRAWER_CALL_LIMIT = int(os.getenv("DRAWER_CALL_LIMIT", "40"))  # ~2.5x the ≤15-call budget
# wbs_planner: 60 is ample now that the deterministic tail is one finalize_wbs
# call (Pass 2 ≈ N add_wbs_items + 1).
_WBS_CALL_LIMIT = int(os.getenv("WBS_CALL_LIMIT", "60"))
_PPT_CALL_LIMIT = int(os.getenv("PPT_CALL_LIMIT", "60"))

# Early-warning thresholds: log at WARNING level so runaway traces surface in
# logs before they show up in LangSmith. Both are env-tunable.
_WARN_CALL_COUNT = int(os.getenv("WARN_CALL_COUNT", "30"))
_WARN_INPUT_TOKENS = int(os.getenv("WARN_INPUT_TOKENS", "80000"))

# Main agent has ~42 tool schemas every call (34 MAIN_TOOLS + 6 filesystem
# built-ins + write_todos + task). LLMToolSelectorMiddleware trims that down via
# one small extra selection call — only worth it for the main agent; subagents
# already have narrow (2-9 tool) tool sets where the selector call would cost
# more than it saves. Env-gated so it can be turned off without a code change if
# usage.json shows it isn't paying for itself, or the selector excludes a tool
# the model actually needed.
_MAIN_TOOL_SELECTOR = os.getenv("MAIN_TOOL_SELECTOR", "1").strip().lower() not in ("0", "false", "no")
_MAIN_TOOL_SELECTOR_ALWAYS_INCLUDE = [
    "read_file",
    "ls",
    "glob",
    "grep",
    "task",
    "write_todos",
    # Stage and approval gates are control-flow tools. If the selector drops one,
    # the model can get stuck saying the required gate is unavailable.
    "analyze_architecture_requirements",
    "propose_diagram_brief",
    "propose_tech_stack",
    "propose_blueprint",
    "finalize_diagram",
    "generate_pdf_report",
    "propose_deck_plan",
    "generate_ppt_proposal",
    "send_email",
    "create_client_meeting",
    "propose_wbs_skeleton",
    "propose_wbs",
    "export_wbs_excel",
    "export_to_delivery",
    "propose_business_case",
]
