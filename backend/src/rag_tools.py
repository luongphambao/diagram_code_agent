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
                "name": meta.get("name", ""),
                "client": meta.get("client", ""),
                "business_domain": meta.get("business_domain", ""),
                "solution_type": meta.get("solution_type", ""),
                "total_mandays": meta.get("total_mandays") or None,
                "tech_keywords": meta.get("tech_keywords", ""),
                "summary_snippet": doc.page_content[:400],
            }
        )

    result = {
        "status": "OK",
        "query": query,
        "count": len(projects),
        "projects": projects,
        "instruction": (
            "Reference these past BnK projects when proposing the tech stack. "
            "For each tech choice, note if BnK has used it in a similar project. "
            "Use total_mandays as a rough effort benchmark for sanity-checking."
        ),
    }

    _similar_solutions_file().write_text(json.dumps(result, indent=2), encoding="utf-8")
    logger.info("find_similar_solutions: found %d projects for query '%s'", len(projects), query[:80])
    return json.dumps(result, indent=2)


def _similar_solutions_file():
    current_workspace().mkdir(parents=True, exist_ok=True)
    return _SIMILAR_SOLUTIONS_FILE
