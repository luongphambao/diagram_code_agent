"""Constants and stage file paths for the diagram tools package."""

from __future__ import annotations

import os
from pathlib import Path

from backends import WORKSPACE, WorkspaceFile
from domain.reporting.reporting import REPORT_EVIDENCE_NAME

# Stage markers written under the current-thread workspace so the staged tools can
# enforce order. Resolved lazily per request via WorkspaceFile (per-thread isolation,
# §4.10) — importers can keep ``from .constants import _BRIEF_FILE`` unchanged.
_ARCH_ANALYSIS_FILE = WorkspaceFile("architecture_analysis.json")
_BRIEF_FILE = WorkspaceFile("diagram_brief.json")
_TECHSTACK_FILE = WorkspaceFile("tech_stack.json")
_BLUEPRINT_FILE = WorkspaceFile("blueprint.json")
_CRITIQUE_FILE = WorkspaceFile("critique.json")

# Typed-diagram foundation (MVP-3): each new diagram kind's canonical spec file,
# analogous to _BLUEPRINT_FILE for architecture. All kinds still share
# _RENDER_SPEC_FILE below as the flattened dict the native renderer consumes.
_SEQUENCE_SPEC_FILE = WorkspaceFile("sequence_spec.json")

# Typed-diagram foundation: an explicit frontend diagram-type selection (sent
# as `diagramKind` on /agui, see routers/chat.py::agui_endpoint) is persisted
# here so it outranks both the LLM's own DiagramBrief.diagram_kind and the
# deterministic keyword suggestion in architecture_analysis.json — "Auto
# detect" (no override written) leaves this file absent.
_DIAGRAM_KIND_OVERRIDE_FILE = WorkspaceFile("diagram_kind_override.json")

_RENDER_SPEC_FILE = WorkspaceFile("render_spec.json")
_RENDER_COUNT_FILE = WorkspaceFile("render_count.json")
_ICON_SEARCH_BUDGET_FILE = WorkspaceFile("icon_search_budget.json")
_NODE_SEARCH_BUDGET_FILE = WorkspaceFile("node_search_budget.json")
_REVISION_COUNT_FILE = WorkspaceFile("revision_count.json")
_TOOL_SUMMARY_FILE = WorkspaceFile("tool_budget_summary.json")
_ICON_PLAN_FILE = WorkspaceFile("icon_plan.json")
_TECH_ICONS_FILE = WorkspaceFile("tech_icons.json")
# Append-only history of scorecard totals across a diagram's export/edit/inspect
# steps (§ engineer loop) — lets edit_drawio/inspect_render_quality show a delta
# instead of just the current score, since KeepLatestImagesEdit means the model
# can never visually compare before/after.
_QUALITY_HISTORY_FILE = WorkspaceFile("quality_history.json")

# Files copied into each session archive folder under OUTPUTS_DIR.
_SESSION_ARTIFACTS = (
    "out.png",
    "out.body.png",
    "out.drawio",
    "diagram.py",
    "out.nodes.json",
    "out.dot",
    # Native-engine artifacts (§ engineer loop) — carried into the archive so
    # a saved session is self-describing for the native path too, not just
    # the legacy Graphviz one these six were originally written for.
    "render_spec.json",
    "layout_plan.json",
    "engineer_report.json",
    "out.native_stats.json",
)

# Per-round render budget: soft nudge at 3 (finalize with what you have), hard
# refusal at 6 (the #1 cause of "run limit 80/80" was an endless fix->render
# loop chasing audit warnings that cannot be fully resolved).
RENDER_SOFT_CAP = 3
RENDER_HARD_CAP = 6
# search_diagrams_nodes/search_icons are icon_resolver-EXCLUSIVE tools (not bound
# to drawer/main — see tools/__init__.py ICON_RESOLVER_TOOLS), so these caps only
# ever affect icon_resolver. A real trace (drawer_call.txt, 2026-07-03) showed
# icon_resolver ignoring its own tool docstrings ("ALWAYS prefer the batch form")
# and firing ~13 one-by-one search_diagrams_nodes calls, then ~13 one-by-one
# search_icons calls repeatedly hitting BUDGET_EXHAUSTED, before ever calling the
# batch resolve_icons — each a full wasted model call. Caps tightened so a
# non-batched attempt fails fast (was 6/3, warn at 3) instead of burning ~13 calls
# before the model gives up and switches to batching.
ICON_SEARCH_PER_QUERY_CAP = 3  # one keyword + one broader term + one tech-derived retry
ICON_SEARCH_DEFAULT_TOTAL_CAP = 20
NODE_SINGLE_SEARCH_WARN = 1
NODE_SINGLE_SEARCH_HARD_CAP = 2
CRITIC_REVISION_HARD_CAP = 2

# Native-drawio engineer loop (edit_drawio / inspect_render_quality /
# export_drawio_native / upgrade_drawio) — see tools/stage_markers.py for the
# counter files and reset points, and agent/middleware/drawer_gate.py for the
# one place that grants a fresh round of all three.
_DRAWIO_EDIT_CAP = 2  # edit_drawio batches per exported diagram
# A batch is reverted (not counted against the edit budget) if the production
# score drops by MORE than this many points, or if the semantic-loss guard
# fires (any node/edge count drop is always reverted, regardless of score —
# that's corruption, not noise). The tolerance absorbs the sub-point score
# jitter a legitimate small nudge (e.g. moving one card 10px) can cause via the
# aspect-ratio/composition metric, so normal edits aren't falsely reverted.
_EDIT_REGRESSION_TOLERANCE = 1.0
# Engineer loop tiers 1-2 (LLM rounds): hard cap on inspect_render_quality calls
# per export — each call ships a (downscaled) image to the model, so the budget
# is code-enforced like the edit cap, not prompt-enforced.
_ENGINEER_INSPECT_CAP = 2
# Code-enforces "never re-export hoping for a different geometry"
# (prompts/drawer_agent.py) — without this, export_drawio_native/upgrade_drawio
# silently refilled the two caps above on every call (they reset the edit/
# inspect counters as a side effect of a fresh export), so a drawer hitting
# EDIT/ENGINEER BUDGET EXHAUSTED could just re-export to get a new budget.
_NATIVE_EXPORT_CAP = int(os.getenv("NATIVE_EXPORT_CAP", "2"))

# Tavily web search is metered per session. The total cap is split into per-stage
# sub-budgets (the `topic`/category argument to web_research) so a single stage
# can't drain the whole quota: research is spread across tech-stack, architecture,
# WBS and evidence/compliance instead of being dumped into one step.
#
# Sum of WEB_SEARCH_CATEGORY_CAPS == WEB_SEARCH_SESSION_CAP. Keep them in sync.
WEB_SEARCH_SESSION_CAP = 10
WEB_SEARCH_CATEGORY_CAPS: dict[str, int] = {
    "tech_stack": 4,  # managed-service pricing, latest stable versions / EOL (heaviest)
    "architecture": 2,  # reference architectures / patterns for the chosen design
    "wbs": 1,  # effort benchmarks / delivery norms
    "evidence": 2,  # compliance / claim grounding (feeds the evidence store)
    "general": 1,  # fallback bucket for anything that doesn't fit above
}
# Tavily's own `topic` hint only accepts these; category is mapped onto one of them.
WEB_SEARCH_TAVILY_TOPICS: frozenset[str] = frozenset({"general", "news"})
_WEB_SEARCH_BUDGET_FILE = WorkspaceFile("web_search_budget.json")
TAVILY_SEARCH_URL = "https://api.tavily.com/search"

RENDER_TIMEOUT_S = 180
# Max width of the image handed BACK to the model to inspect. The full-resolution
# out.png is kept on disk for the user — this only shrinks the copy that goes into
# the conversation (it is re-sent every turn, so a smaller copy saves context).
INSPECT_MAX_WIDTH = 800

# out.* artifacts produced by a render, cleaned before each run.
_OUT_NAMES = (
    "out.png",
    "out.body.png",
    "out.dot",
    "out.drawio",
    "out.nodes.json",
    "out.slide.json",
)

# prettygraph package must be importable by the generated diagram.py (pretty style does
# `from prettygraph import Pretty`). Stage the package directory into the workspace.
_PRETTYGRAPH_PKG_DIR = Path(__file__).parent.parent / "prettygraph"

# Code-interpreter tool (improvement plan §C) — same sandbox as render_diagram,
# but a data transform is typically pure Python over an already-in-memory-sized
# JSON/CSV file, so it should finish in seconds; the timeout is well under
# render's 180s. Hard cap mirrors RENDER_HARD_CAP's rationale (§C's flagship
# use case, WBS re-estimation, is a single call-then-commit — this only
# guards against a retry loop, not normal usage).
INTERPRETER_TIMEOUT_S = 60
INTERPRETER_CALL_HARD_CAP = 6
_INTERPRETER_COUNT_FILE = WorkspaceFile("interpreter_count.json")
