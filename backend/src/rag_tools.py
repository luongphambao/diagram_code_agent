"""RAG retrieval tools for the diagram agent.

Provides ``find_similar_solutions`` — a tool that searches BnK's unified solution-memory
corpus (case-study narrative + real WBS estimate/tech merged — see
``rag/solution_memory.py`` + ``backend/scripts/build_solution_memory.py``) via Qdrant and
returns the most similar past projects to the current requirement, one hit answering both
"what did we solve" (client/problem/solution/outcome) and "what did it cost" (effort MD,
tech stack, pricing model). The agent calls this BEFORE propose_tech_stack / when estimating
effort, to ground recommendations in real BnK delivery history instead of guessing.
"""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from backends import WorkspaceFile, current_workspace

logger = logging.getLogger(__name__)

_SIMILAR_SOLUTIONS_FILE = WorkspaceFile("similar_solutions.json")


@tool(parse_docstring=True)
def find_similar_solutions(query: str, top_k: int = 3) -> str:
    """Search BnK's internal project database to find past solutions similar to the current requirement.

    Use this BEFORE web_research and propose_tech_stack. The results in
    similar_solutions.json should inform tech stack choices and help justify
    recommendations with "BnK has done this before" evidence.

    Args:
        query: Natural language description of the problem domain, solution type,
            and key capabilities (e.g. "insurance underwriting platform with OCR
            and workflow engine, cloud-native on AWS").
        top_k: Number of similar projects to return (default 3, max 5).
    """
    from rag.indexer import get_retriever

    top_k = max(1, min(int(top_k), 5))

    try:
        retriever = get_retriever(top_k=top_k)
        docs = retriever.invoke(query)
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAG retrieval failed: %s", exc)
        result = {
            "status": "ERROR",
            "query": query,
            "error": str(exc)[:300],
            "instruction": (
                "Similarity search unavailable. Proceed without BnK past-project references. "
                "Run `python -m diagram_mcp.rag.indexer` to build the index."
            ),
        }
        _similar_solutions_file().write_text(json.dumps(result, indent=2), encoding="utf-8")
        return json.dumps(result, indent=2)

    projects = []
    for doc in docs:
        meta = doc.metadata
        projects.append(
            {
                "title": meta.get("title") or meta.get("name", ""),
                "client": meta.get("client", ""),
                "business_domain": meta.get("business_domain", ""),
                "solution_type": meta.get("solution_type", ""),
                "total_mandays": meta.get("total_mandays") or None,
                "capex_usd": meta.get("capex_usd") or None,
                "opex_annual_usd": meta.get("opex_annual_usd") or None,
                "timeline_months": meta.get("timeline_months") or None,
                "pricing_model": meta.get("pricing_model") or "",
                "tech_keywords": meta.get("tech_keywords", ""),
                "image_ref": meta.get("image_ref") or None,
                "provenance": meta.get("source") or "",  # "narrative+wbs" | "narrative" | "wbs_only"
                "summary_snippet": doc.page_content[:500],
            }
        )

    result = {
        "status": "OK",
        "query": query,
        "count": len(projects),
        "projects": projects,
        "instruction": (
            "Reference these past BnK projects when proposing the tech stack and effort estimate. "
            "For each tech choice, note if BnK has used it in a similar project. "
            "Use total_mandays / timeline_months as a real-world benchmark for sanity-checking "
            "the current estimate — treat provenance='narrative' (no confirmed WBS number) as "
            "less certain than 'narrative+wbs' or 'wbs_only'. Never present these figures as the "
            "current project's own numbers — they are reference analogs, cite them as such."
        ),
    }

    _similar_solutions_file().write_text(json.dumps(result, indent=2), encoding="utf-8")
    logger.info("find_similar_solutions: found %d projects for query '%s'", len(projects), query[:80])
    return json.dumps(result, indent=2)


def _similar_solutions_file():
    current_workspace().mkdir(parents=True, exist_ok=True)
    return _SIMILAR_SOLUTIONS_FILE


@tool(parse_docstring=True)
def benchmark_solution(domain: str, solution_type: str = "") -> str:
    """Get real effort/tech benchmarks for a business domain from BnK's project history.

    Unlike find_similar_solutions (semantic search for the closest few projects), this
    aggregates ALL past projects tagged with the given domain into min/median/max man-day
    stats and the most common tech choices — use it to sanity-check a total estimate
    ("is 40 MD reasonable for a banking project?") or to see what BnK typically builds
    with in a domain, not just the single closest analog. Deterministic — no embeddings
    call, just a lookup over the offline solution-memory corpus.

    Args:
        domain: a domain tag, e.g. "banking", "insurance", "document-ai", "logistics",
            "manufacturing", "healthcare", "retail", "data-platform", "ai-ml",
            "agriculture" — or a free-text business_domain string (substring-matched).
        solution_type: optional further narrowing, e.g. "Underwriting Platform" — leave
            empty to include all solution types in the domain.
    """
    from rag.benchmarks import domain_rollup

    try:
        result = domain_rollup(domain, solution_type=solution_type or None)
    except Exception as exc:  # noqa: BLE001
        result = {
            "status": "ERROR",
            "error": str(exc)[:300],
            "instruction": (
                "Benchmark lookup failed. Run `python backend/scripts/build_solution_memory.py` "
                "first if backend/data/solution_memory.json doesn't exist yet."
            ),
        }
        return json.dumps(result, indent=2)

    if not result.get("effort_md_sample_size"):
        result["instruction"] = (
            f"No past project in '{domain}' has a recorded effort figure "
            f"({result['matched_count']} matched by domain, 0 with a usable MD number). "
            "Proceed without a benchmark, or widen/change the domain."
        )
    else:
        result["instruction"] = (
            "Use effort_md_median as the benchmark reference point and the min-max range as "
            "the plausible band when sanity-checking an estimate. common_tech reflects what "
            "BnK has actually shipped in this domain — prefer these choices when equally "
            "suitable, and note explicitly when you deviate from them."
        )
    result["status"] = "OK"
    return json.dumps(result, ensure_ascii=False, indent=2)
