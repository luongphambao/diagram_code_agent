"""Icon search, node search, logo fetch, and drawio shape search tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from backends import LOCAL_ICONS, LOCAL_MANIFEST, LOCAL_NODE_CATALOG, WORKSPACE
from .constants import (
    ICON_SEARCH_DEFAULT_TOTAL_CAP,
    ICON_SEARCH_PER_QUERY_CAP,
    NODE_SINGLE_SEARCH_HARD_CAP,
    NODE_SINGLE_SEARCH_WARN,
    _ICON_PLAN_FILE,
)
from .stage_markers import (
    _bump_tool_summary,
    _icon_search_state,
    _node_search_state,
    _save_icon_search_state,
    _save_node_search_state,
)


def _icon_search_total_cap(state: dict) -> int:
    planned = state.get("planned_icons")
    if isinstance(planned, int) and planned > 0:
        return planned * ICON_SEARCH_PER_QUERY_CAP
    return ICON_SEARCH_DEFAULT_TOTAL_CAP


def _icon_rel(path: str) -> str:
    try:
        return str(Path(path).relative_to(Path(LOCAL_ICONS))).replace("\\", "/")
    except Exception:
        return path


def _icon_key(query: str, provider: Optional[str]) -> str:
    prov = (provider or "").strip().lower()
    q = " ".join((query or "").lower().replace("-", " ").replace("_", " ").split())
    return f"{prov}:{q}"


def _search_icon_hits(query: str, provider: Optional[str] = None, *, limit: int = 30) -> list[str]:
    try:
        manifest = json.loads(Path(LOCAL_MANIFEST).read_text(encoding="utf-8"))
    except Exception:
        return []

    terms = [t for t in query.lower().replace("-", " ").replace("_", " ").split() if t]
    root = Path(LOCAL_ICONS)
    hits: list[str] = []
    for prov, cats in manifest.get("providers", {}).items():
        if provider and prov.lower() != provider.lower():
            continue
        for cat, names in cats.items():
            for name in names:
                hay = f"{prov} {cat} {name}".lower()
                if all(t in hay for t in terms):
                    sub = name if cat == "_root" else f"{cat}/{name}"
                    hits.append(str(root / prov / f"{sub}.png"))
                    if len(hits) >= limit:
                        return hits
    return hits


def _tokens(text: str) -> list[str]:
    return [t for t in text.lower().replace("-", " ").replace("_", " ").split() if t]


def _node_search_hits(query: str, provider: str = "", category: str = "", *, limit: int = 10) -> list[dict]:
    try:
        catalog = json.loads(Path(LOCAL_NODE_CATALOG).read_text(encoding="utf-8"))
    except Exception:
        return []
    terms = _tokens(query)
    if not terms:
        return []
    provider_filter = provider.strip().lower()
    category_filter = category.strip().lower()
    scored: list[dict] = []
    for prov, cats in catalog.items():
        if provider_filter and provider_filter != str(prov).lower():
            continue
        if not isinstance(cats, dict):
            continue
        for cat, classes in cats.items():
            if category_filter and category_filter != str(cat).lower():
                continue
            for class_name in classes or []:
                hay = f"{prov} {cat} {class_name}".lower()
                class_lower = str(class_name).lower()
                if not all(term in hay for term in terms):
                    continue
                score = 0
                query_flat = "".join(terms)
                class_flat = class_lower.replace("_", "").replace("-", "")
                if class_lower == query.lower():
                    score += 100
                elif class_flat == query_flat:
                    score += 90
                elif class_lower.startswith(query.lower()):
                    score += 55
                score += sum(10 for term in terms if term in class_lower)
                if provider_filter and provider_filter == str(prov).lower():
                    score += 8
                if category_filter and category_filter == str(cat).lower():
                    score += 5
                scored.append({
                    "provider": prov,
                    "category": cat,
                    "class_name": class_name,
                    "import_path": f"diagrams.{prov}.{cat}.{class_name}",
                    "score": score,
                })
    scored.sort(key=lambda item: (-item["score"], item["provider"], item["category"], item["class_name"]))
    return scored[: max(1, min(limit, 50))]


try:
    from langchain_core.tools import tool

    @tool(parse_docstring=True)
    def search_icons(query: str, provider: Optional[str] = None) -> str:
        """Search the bundled icon pack for matching icon paths.

        Returns absolute `.png` paths to use in `Custom(label, "<path>")` when no
        built-in `diagrams` node fits.

        When to use: only AFTER `search_diagrams_nodes` finds no built-in node for a
        component. Try one keyword; on NOT_FOUND try at most one broader term, then
        fall back to `fetch_logo` (brands) or omit the icon. Searches are budget-capped,
        so do not call repeatedly for the same icon.

        Args:
            query: Short filename-style keyword for the icon, e.g. "redis", "lambda".
            provider: Optional provider subtree to restrict the search; one of
                "aws", "azure", "gcp", "onprem", "k8s", "programming", "saas".
        """
        state = _icon_search_state()
        key = _icon_key(query, provider)
        cache = state.setdefault("cache", {})
        if key in cache:
            cached = cache[key]
            _bump_tool_summary("search_icons", icon_search_cache_hits=1)
            return json.dumps({**cached, "cached": True}, indent=2)

        total_cap = _icon_search_total_cap(state)
        total_calls = int(state.get("total_calls", 0))
        counts = state.setdefault("counts", {})
        key_count = int(counts.get(key, 0))
        if total_calls >= total_cap or key_count >= ICON_SEARCH_PER_QUERY_CAP:
            result = {
                "status": "BUDGET_EXHAUSTED",
                "query": query,
                "provider": provider,
                "total_calls": total_calls,
                "total_cap": total_cap,
                "query_calls": key_count,
                "query_cap": ICON_SEARCH_PER_QUERY_CAP,
                "instruction": (
                    "Stop searching this icon. Use an existing icon_plan.json path, "
                    "omit icon=, or use one generic fallback."
                ),
            }
            _bump_tool_summary("search_icons_budget_exhausted")
            return json.dumps(result, indent=2)

        counts[key] = key_count + 1
        state["total_calls"] = total_calls + 1
        hits = _search_icon_hits(query, provider, limit=5)
        result = {
            "status": "FOUND" if hits else "NOT_FOUND",
            "query": query,
            "provider": provider,
            "hits": [{"path": p, "icon": _icon_rel(p)} for p in hits[:5]],
            "instruction": (
                "Use one returned icon path. If NOT_FOUND, try at most one broader "
                "different keyword, then omit icon= or fetch_logo for a brand."
                if hits
                else "Try at most one broader different keyword, then omit icon= "
                     "or fetch_logo for a brand."
            ),
        }
        cache[key] = result
        _save_icon_search_state(state)
        _bump_tool_summary("search_icons", icon_search_total_calls=state["total_calls"])
        return json.dumps(result, indent=2)

    @tool(parse_docstring=True)
    def search_diagrams_nodes(query: str = "", provider: str = "", category: str = "",
                              limit: int = 10, queries: Optional[list[str]] = None) -> str:
        """Search built-in `diagrams` node classes using the local node catalog.

        Returns verified import paths from `resources/node_catalog.json`. Use
        `resolve_icons` / `search_icons` only when no built-in node fits.

        When to use: before writing any raw `from diagrams.<provider>.<category> import X`
        import. ALWAYS prefer the batch form `queries=[...]` to resolve every planned
        import in one call — one-by-one single searches are budget-capped and warned.

        Args:
            query: A single node search term (only when not batching). Prefer `queries`.
            provider: Optional provider subtree filter, e.g. "aws", "azure", "gcp", "onprem".
            category: Optional category filter within a provider (e.g. "database", "compute").
            limit: Max hits returned per query (default 10).
            queries: Batch list of terms, e.g. ["redis", "cloud run", "pubsub"]; returns
                a mapping of each query to its hits. Use this for the whole blueprint
                in ONE call.
        """
        state = _node_search_state()
        if queries:
            state["batch_calls"] = int(state.get("batch_calls", 0)) + 1
            _save_node_search_state(state)
            _bump_tool_summary("search_diagrams_nodes_batch")
            return json.dumps(
                {q: _node_search_hits(q, provider, category, limit=limit) for q in queries},
                indent=2)
        single_calls = int(state.get("single_calls", 0)) + 1
        state["single_calls"] = single_calls
        _save_node_search_state(state)
        _bump_tool_summary("search_diagrams_nodes_single", node_single_searches=single_calls)
        if single_calls > NODE_SINGLE_SEARCH_HARD_CAP:
            return json.dumps({
                "status": "BUDGET_EXHAUSTED",
                "query": query,
                "instruction": (
                    "Stop one-by-one node searches. Batch remaining terms with "
                    "queries=[...] or use already returned imports."
                ),
                "single_calls": single_calls,
                "single_call_cap": NODE_SINGLE_SEARCH_HARD_CAP,
            }, indent=2)
        hits = _node_search_hits(query, provider, category, limit=limit)
        payload: dict = {"status": "OK", "query": query, "hits": hits}
        if single_calls > NODE_SINGLE_SEARCH_WARN:
            payload["warning"] = (
                "Too many single node searches. Batch remaining terms with queries=[...]."
            )
        return json.dumps(payload, indent=2)

    class IconRequest(BaseModel):
        """One planned icon lookup for batch resolution."""
        label: str = Field(description="visible node/component label")
        provider: str = Field("", description="provider subtree, e.g. aws|azure|gcp|onprem|programming|saas")
        icon_keyword: str = Field(description="short filename-style search term, e.g. redis|run|sql|pubsub")

    @tool(parse_docstring=True)
    def resolve_icons(icons: list[IconRequest]) -> str:
        """Resolve a planned batch of icon lookups in one tool call.

        Returns JSON entries with a best matching absolute `path` and prettygraph
        relative `icon`. Also writes `icon_plan.json` in the workspace so revision
        tasks can reuse prior choices instead of searching again.

        When to use: once per round, after planning all icons. Pass every needed icon
        in a single call rather than calling repeatedly; the result is cached for the
        round and re-resolving is rejected.

        Args:
            icons: Full list of planned icon lookups (each an IconRequest with label,
                provider, and icon_keyword) to resolve together in one batch.
        """
        state = _icon_search_state()
        if state.get("resolved_this_round") and _ICON_PLAN_FILE.exists():
            from .stage_markers import _read_json_file
            cached = _read_json_file(_ICON_PLAN_FILE, [])
            _bump_tool_summary("resolve_icons_cached")
            return json.dumps({
                "status": "ALREADY_RESOLVED_THIS_ROUND",
                "instruction": (
                    "Reuse icon_plan.json. Use search_icons only for new NOT_FOUND "
                    "items with a different keyword."
                ),
                "icons": cached,
            }, indent=2)

        root = Path(LOCAL_ICONS)
        resolved: list[dict] = []
        for item in icons:
            hits = _search_icon_hits(item.icon_keyword, item.provider or None, limit=5)
            best = hits[0] if hits else ""
            rel = ""
            if best:
                try:
                    rel = str(Path(best).relative_to(root)).replace("\\", "/")
                except Exception:
                    rel = best
            resolved.append({
                "label": item.label,
                "provider": item.provider,
                "icon_keyword": item.icon_keyword,
                "status": "FOUND" if best else "NOT_FOUND",
                "path": best or None,
                "icon": rel or None,
                "alternatives": hits[1:5],
                "tried_keywords": [item.icon_keyword],
            })
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        _ICON_PLAN_FILE.write_text(json.dumps(resolved, indent=2), encoding="utf-8")
        state.update({
            "resolved_this_round": True,
            "planned_icons": len({(i.provider.lower(), i.icon_keyword.lower()) for i in icons}),
            "total_calls": 0,
            "counts": {},
            "cache": {},
        })
        _save_icon_search_state(state)
        _bump_tool_summary("resolve_icons", planned_icons=state["planned_icons"])
        return json.dumps(resolved, indent=2)

    @tool(parse_docstring=True)
    def fetch_logo(name: str) -> str:
        """Resolve a brand/product logo — lobe-icons (321 AI/LLM brands + data stores) first,
        then local pack, then Iconify, then favicon; downloads & validates.

        For AI/LLM brands (Claude, OpenAI, Gemini, Mistral, LangChain, HuggingFace, Ollama,
        Qdrant, Redis, MongoDB, Kafka, etc.) returns a cached PNG path from lobe-icons CDN.
        Falls back to web scraping for other brands. Returns an absolute PNG/SVG path to
        use in box(icon=...), or NOT_FOUND.

        When to use: for a named third-party brand/product when neither a built-in
        `diagrams` node nor `search_icons` produced a usable icon.

        Args:
            name: The brand or product name to resolve, e.g. "OpenAI", "Snowflake", "Stripe".
        """
        try:
            from aiicons import lookup_ai_logo
            path = lookup_ai_logo(name, str(LOCAL_ICONS))
            if path:
                return path
        except Exception:  # noqa: BLE001
            pass
        try:
            from logo_fetch import get_logo
            path = get_logo(name, str(LOCAL_ICONS), str(WORKSPACE))
        except Exception as exc:  # noqa: BLE001
            return f"NOT_FOUND: fetch_logo error: {exc}"
        return path or f"NOT_FOUND: no verified logo for '{name}'. Use a built-in node or search_icons()."

    @tool(parse_docstring=True)
    def search_drawio_shapes(query: str, limit: int = 5) -> str:
        """Search 10,446 official draw.io shapes for their exact style strings.

        Returns the exact `style=` strings that render correctly — never guess
        mxgraph.* style names.

        When to use: when you need a specific vendor shape (AWS Lambda, Azure VM, k8s
        Pod, UML actor, BPMN task, etc.) in the exported .drawio file.

        Args:
            query: Shape search keywords, e.g. "aws lambda", "azure vm", "k8s pod",
                "uml actor", "dynamodb", "kafka".
            limit: Max number of matching shapes to return (default 5).
        """
        try:
            from shapesearch import search_shapes
            results = search_shapes(query, limit)
            if not results:
                return json.dumps({"status": "NOT_FOUND", "query": query,
                                   "hint": "Try broader keywords or check spelling."}, indent=2)
            return json.dumps({"status": "OK", "query": query, "results": results}, indent=2)
        except Exception as exc:  # noqa: BLE001
            return f"search_drawio_shapes error: {exc}"

except ImportError:
    # Allow importing this module even without langchain (e.g., for testing constants)
    pass
