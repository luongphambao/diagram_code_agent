"""Constants and stage file paths for the diagram tools package."""

from __future__ import annotations

from pathlib import Path

from backends import WORKSPACE
from reporting import REPORT_EVIDENCE_NAME

# Stage markers written under WORKSPACE so the staged tools can enforce order.
_ARCH_ANALYSIS_FILE = WORKSPACE / "architecture_analysis.json"
_BRIEF_FILE = WORKSPACE / "diagram_brief.json"
_TECHSTACK_FILE = WORKSPACE / "tech_stack.json"
_BLUEPRINT_FILE = WORKSPACE / "blueprint.json"
_CRITIQUE_FILE = WORKSPACE / "critique.json"

_RENDER_SPEC_FILE = WORKSPACE / "render_spec.json"
_RENDER_COUNT_FILE = WORKSPACE / "render_count.json"
_ICON_SEARCH_BUDGET_FILE = WORKSPACE / "icon_search_budget.json"
_NODE_SEARCH_BUDGET_FILE = WORKSPACE / "node_search_budget.json"
_REVISION_COUNT_FILE = WORKSPACE / "revision_count.json"
_TOOL_SUMMARY_FILE = WORKSPACE / "tool_budget_summary.json"
_ICON_PLAN_FILE = WORKSPACE / "icon_plan.json"

# Files copied into each session archive folder under OUTPUTS_DIR.
_SESSION_ARTIFACTS = ("out.png", "out.body.png", "out.drawio", "diagram.py", "out.nodes.json", "out.dot")

# Per-round render budget: soft nudge at 3 (finalize with what you have), hard
# refusal at 6 (the #1 cause of "run limit 80/80" was an endless fix->render
# loop chasing audit warnings that cannot be fully resolved).
RENDER_SOFT_CAP = 3
RENDER_HARD_CAP = 6
ICON_SEARCH_PER_QUERY_CAP = 3
ICON_SEARCH_DEFAULT_TOTAL_CAP = 12
NODE_SINGLE_SEARCH_WARN = 3
NODE_SINGLE_SEARCH_HARD_CAP = 6
CRITIC_REVISION_HARD_CAP = 2

# Tavily web search is metered per session. The total cap is split into per-stage
# sub-budgets (the `topic`/category argument to web_research) so a single stage
# can't drain the whole quota: research is spread across tech-stack, architecture,
# WBS and evidence/compliance instead of being dumped into one step.
#
# Sum of WEB_SEARCH_CATEGORY_CAPS == WEB_SEARCH_SESSION_CAP. Keep them in sync.
WEB_SEARCH_SESSION_CAP = 10
WEB_SEARCH_CATEGORY_CAPS: dict[str, int] = {
    "tech_stack": 4,    # managed-service pricing, latest stable versions / EOL (heaviest)
    "architecture": 2,  # reference architectures / patterns for the chosen design
    "wbs": 1,           # effort benchmarks / delivery norms
    "evidence": 2,      # compliance / claim grounding (feeds the evidence store)
    "general": 1,       # fallback bucket for anything that doesn't fit above
}
# Tavily's own `topic` hint only accepts these; category is mapped onto one of them.
WEB_SEARCH_TAVILY_TOPICS: frozenset[str] = frozenset({"general", "news"})
_WEB_SEARCH_BUDGET_FILE = WORKSPACE / "web_search_budget.json"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"

RENDER_TIMEOUT_S = 180
# Max width of the image handed BACK to the model to inspect. The full-resolution
# out.png is kept on disk for the user — this only shrinks the copy that goes into
# the conversation (it is re-sent every turn, so a smaller copy saves context).
INSPECT_MAX_WIDTH = 800

# out.* artifacts produced by a render, cleaned before each run.
_OUT_NAMES = (
    "out.png", "out.body.png", "out.dot", "out.drawio", "out.nodes.json",
    "out.slide.json",
)

# prettygraph package must be importable by the generated diagram.py (pretty style does
# `from prettygraph import Pretty`). Stage the package directory into the workspace.
_PRETTYGRAPH_PKG_DIR = Path(__file__).parent.parent / "prettygraph"
