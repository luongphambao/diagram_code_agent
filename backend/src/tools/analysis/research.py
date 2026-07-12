"""web_research — budgeted Tavily web search tool."""

from __future__ import annotations

import json
import os

from langchain_core.tools import tool

from ..constants import (
    TAVILY_SEARCH_URL,
    WEB_SEARCH_CATEGORY_CAPS,
    WEB_SEARCH_SESSION_CAP,
    WEB_SEARCH_TAVILY_TOPICS,
)
from ..stage_markers import _bump_tool_summary, _save_web_search_state, _web_search_state


def _web_search_category(topic: str) -> str:
    """Map the caller's `topic` onto a budget category.

    `topic` doubles as both the Tavily recency hint and the budget bucket. Any value
    that isn't a known budget category (e.g. "news", or a stray free-text topic) falls
    into the "general" bucket so it still draws from a real sub-budget.
    """
    t = (topic or "").strip().lower()
    return t if t in WEB_SEARCH_CATEGORY_CAPS else "general"


def _web_search_budget_report(state: dict) -> dict:
    """Per-category used/cap snapshot + total remaining, for tool responses."""
    by_cat = state.get("by_category") or {}
    categories = {
        cat: {"used": int(by_cat.get(cat, 0)), "cap": cap,
              "remaining": max(0, cap - int(by_cat.get(cat, 0)))}
        for cat, cap in WEB_SEARCH_CATEGORY_CAPS.items()
    }
    total_used = int(state.get("calls", 0))
    return {
        "session_cap": WEB_SEARCH_SESSION_CAP,
        "total_used": total_used,
        "total_remaining": max(0, WEB_SEARCH_SESSION_CAP - total_used),
        "by_category": categories,
    }


@tool(parse_docstring=True)
def web_research(query: str, topic: str = "tech_stack") -> str:
    """Run ONE live web search to verify time-sensitive facts via Tavily.

    Returns a synthesized answer plus the top source URLs/snippets as JSON.
    The session has a total budget of WEB_SEARCH_SESSION_CAP searches, split into
    per-stage sub-budgets so research is spread across the pipeline instead of dumped
    into a single step. Pick the `topic` that matches WHY you are searching.

    When to use (batch related questions into ONE rich query each time):
      - "tech_stack"   — managed-service pricing, latest stable versions / EOL dates.
      - "architecture" — reference architectures / patterns for the chosen design.
      - "wbs"          — effort benchmarks / delivery norms for the estimate.
      - "evidence"     — compliance / claim grounding for a client-facing statement.
      - "general"      — anything that doesn't fit the buckets above.
      - "news"         — same as general budget, but biases Tavily toward recency.

    Args:
        query: One focused, fact-seeking question, e.g. "2026 AWS Fargate vCPU and
            RDS Postgres db.t4g.medium monthly pricing us-east-1".
        topic: Budget category AND Tavily recency hint (see list above). Defaults to
            "tech_stack".
    """
    import httpx

    state = _web_search_state()
    state.setdefault("by_category", {})
    calls = int(state.get("calls", 0))
    category = _web_search_category(topic)
    cat_used = int(state["by_category"].get(category, 0))
    cat_cap = WEB_SEARCH_CATEGORY_CAPS[category]

    # Total session budget exhausted.
    if calls >= WEB_SEARCH_SESSION_CAP:
        _bump_tool_summary("web_research_budget_exhausted")
        return json.dumps({
            "status": "BUDGET_EXHAUSTED",
            "query": query,
            "budget": _web_search_budget_report(state),
            "instruction": (
                "No web searches remain this session. Proceed with existing knowledge "
                "and results already gathered; flag any unverified pricing/version as an "
                "assumption in assumptions.confirm_with_customer."
            ),
        }, indent=2)

    # This category's sub-budget is spent, but the session still has room elsewhere.
    if cat_used >= cat_cap:
        report = _web_search_budget_report(state)
        open_cats = [c for c, info in report["by_category"].items() if info["remaining"] > 0]
        _bump_tool_summary("web_research_category_exhausted")
        return json.dumps({
            "status": "CATEGORY_EXHAUSTED",
            "query": query,
            "category": category,
            "budget": report,
            "instruction": (
                f"The '{category}' sub-budget ({cat_cap}) is spent. The session still has "
                f"searches left in: {open_cats or 'none'}. Re-issue with a topic from that "
                "list ONLY if the question genuinely belongs to that stage; otherwise "
                "proceed with existing knowledge."
            ),
        }, indent=2)

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        _bump_tool_summary("web_research_no_key")
        return json.dumps({
            "status": "NO_API_KEY",
            "instruction": "TAVILY_API_KEY not set; skip web research and proceed.",
        }, indent=2)

    # Reserve the call (total + per-category) BEFORE the network request.
    state["calls"] = calls + 1
    state["by_category"][category] = cat_used + 1
    state.setdefault("queries", []).append({"query": query, "category": category})
    _save_web_search_state(state)

    tavily_topic = "news" if (topic or "").strip().lower() == "news" else "general"
    if tavily_topic not in WEB_SEARCH_TAVILY_TOPICS:
        tavily_topic = "general"
    try:
        resp = httpx.post(
            TAVILY_SEARCH_URL,
            json={
                "api_key": api_key,
                "query": query,
                "topic": tavily_topic,
                "search_depth": "advanced",
                "include_answer": "advanced",
                "max_results": 5,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        _bump_tool_summary("web_research_error")
        return json.dumps({
            "status": "ERROR",
            "query": query,
            "error": str(exc)[:300],
            "budget": _web_search_budget_report(state),
            "instruction": "Search failed (still counted). Proceed with existing knowledge.",
        }, indent=2)

    sources = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": (r.get("content", "") or "")[:300],
        }
        for r in (data.get("results") or [])[:5]
    ]
    _bump_tool_summary("web_research", web_search_calls=state["calls"])
    report = _web_search_budget_report(state)
    return json.dumps({
        "status": "OK",
        "query": query,
        "category": category,
        "answer": (data.get("answer", "") or "")[:1600],
        "sources": sources,
        "budget": report,
        "instruction": (
            "Cite specific numbers/versions from answer/sources in the relevant "
            "artifact, AND when the claim is client-facing (pricing/version/"
            "compliance/reference-architecture) commit it with record_evidence "
            "(pass source_url + supports_entity_ids). Remaining — "
            f"total: {report['total_remaining']}, this stage ('{category}'): "
            f"{report['by_category'][category]['remaining']}."
        ),
    }, indent=2)
