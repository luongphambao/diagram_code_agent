"""Tests for the per-stage web_research budget (total cap + category sub-caps).

Network-free: every assertion exercises a branch that returns BEFORE the Tavily
call (budget/category exhaustion, helper math), and the budget state is driven via
an in-memory dict so no workspace files or API key are needed.
"""

import json

from tools import analysis_tools as at
from tools.analysis import research as _research
from tools.constants import WEB_SEARCH_CATEGORY_CAPS, WEB_SEARCH_SESSION_CAP


def test_category_caps_sum_to_session_cap():
    # The per-stage sub-budgets must add up to the total so the docs/prompts stay honest.
    assert sum(WEB_SEARCH_CATEGORY_CAPS.values()) == WEB_SEARCH_SESSION_CAP


def test_category_mapping_falls_back_to_general():
    assert at._web_search_category("tech_stack") == "tech_stack"
    assert at._web_search_category("ARCHITECTURE") == "architecture"
    assert at._web_search_category("news") == "general"      # valid Tavily topic, not a bucket
    assert at._web_search_category("whatever") == "general"
    assert at._web_search_category("") == "general"


def test_budget_report_math():
    state = {"calls": 5, "by_category": {"tech_stack": 4, "wbs": 1}}
    report = at._web_search_budget_report(state)
    assert report["total_used"] == 5
    assert report["total_remaining"] == WEB_SEARCH_SESSION_CAP - 5
    assert report["by_category"]["tech_stack"] == {
        "used": 4, "cap": WEB_SEARCH_CATEGORY_CAPS["tech_stack"], "remaining": 0
    }
    assert report["by_category"]["evidence"]["used"] == 0


def _patch_state(monkeypatch, state: dict) -> dict:
    """Drive web_research's budget off an in-memory dict (no files, no network).

    web_research's body resolves these names via tools.analysis.research's own
    module globals (that's where it now lives), so the patch target must be that
    module — not the tools.analysis_tools re-export shim (`at`), whose copy of
    the name is a separate binding that the function body never reads.
    """
    saved = {}
    monkeypatch.setattr(_research, "_web_search_state", lambda: state)
    monkeypatch.setattr(_research, "_save_web_search_state", lambda s: saved.update(s))
    monkeypatch.setattr(_research, "_bump_tool_summary", lambda *a, **k: None)
    return saved


def test_session_budget_exhausted_blocks_all(monkeypatch):
    _patch_state(monkeypatch, {"calls": WEB_SEARCH_SESSION_CAP, "by_category": {}})
    out = json.loads(at.web_research.func("anything", topic="architecture"))
    assert out["status"] == "BUDGET_EXHAUSTED"


def test_category_exhausted_but_session_has_room(monkeypatch):
    # wbs sub-budget is 1; spend it, with plenty of total budget left.
    cap = WEB_SEARCH_CATEGORY_CAPS["wbs"]
    _patch_state(monkeypatch, {"calls": cap, "by_category": {"wbs": cap}})
    out = json.loads(at.web_research.func("effort benchmark for OCR", topic="wbs"))
    assert out["status"] == "CATEGORY_EXHAUSTED"
    assert out["category"] == "wbs"
    # The response should point the agent at stages that still have quota.
    open_cats = [c for c, info in out["budget"]["by_category"].items() if info["remaining"] > 0]
    assert "tech_stack" in open_cats


def test_no_api_key_after_budget_passes(monkeypatch):
    # Budget is fine but no key configured -> NO_API_KEY (still no network).
    _patch_state(monkeypatch, {"calls": 0, "by_category": {}})
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    out = json.loads(at.web_research.func("2026 Fargate pricing", topic="tech_stack"))
    assert out["status"] == "NO_API_KEY"
