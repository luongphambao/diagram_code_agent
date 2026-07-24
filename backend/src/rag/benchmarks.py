"""Deterministic benchmark rollups over the unified solution-memory corpus.

Pure aggregation over ``backend/data/solution_memory.json`` — NO embeddings, NO LLM call.
Grouping is by the ``domain`` tags each entry already carries (computed once, offline, by
``build_solution_memory.py``/``build_case_library.py``'s ``_infer_domains``), and matching
is case-insensitive substring — cheap enough to call inline from the numeric WBS pipeline
(``wbs_tools.compute_wbs_rollup``) without adding any agent-facing tool, token cost, or
latency. This is the same "never trust the LLM for a number code can compute" discipline
already used for CAPEX/effort totals elsewhere in this codebase — it just extends to
"how does this estimate compare to real past projects", not only "what does this WBS sum to".
"""

from __future__ import annotations

import statistics
from typing import Any, Optional

from rag.solution_memory import effective_effort_md, load_solution_memory


def domain_rollup(
    domain: str,
    *,
    solution_type: Optional[str] = None,
    path: str | None = None,
) -> dict[str, Any]:
    """Effort-MD benchmark stats + common tech for one domain tag.

    Args:
        domain: a domain tag to match (case-insensitive substring against each entry's
            `domain` list) — e.g. "banking", "insurance", "document-ai". Also accepts a
            free-text business_domain string (e.g. "Trade Finance / Banking") since the
            substring match is bidirectional-friendly for the common tag vocabulary.
        solution_type: optional further narrowing (substring against each entry's `type`).
        path: override the solution_memory.json path (mainly for tests).

    Returns matched_count / effort_md min-median-max (over entries that actually carry a
    number — narrative-only entries with no confirmed WBS join or stated figure are
    excluded from the stats, not treated as zero) / common_tech / a few example projects.
    """
    domain_l = domain.lower().strip()
    entries = load_solution_memory(path)
    matched = [
        e
        for e in entries
        if any(domain_l in d.lower() or d.lower() in domain_l for d in (e.get("domain") or []))
        and (not solution_type or solution_type.lower() in (e.get("type") or "").lower())
    ]

    mds = [m for e in matched if (m := effective_effort_md(e)) is not None and m > 0]

    tech_counts: dict[str, int] = {}
    for e in matched:
        for t in e.get("tech") or []:
            tech_counts[t] = tech_counts.get(t, 0) + 1
    common_tech = sorted(tech_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]

    examples = sorted(
        (e for e in matched if effective_effort_md(e)),
        key=lambda e: effective_effort_md(e) or 0,
        reverse=True,
    )[:5]

    return {
        "domain": domain,
        "solution_type_filter": solution_type,
        "matched_count": len(matched),
        "effort_md_sample_size": len(mds),
        "effort_md_min": round(min(mds), 1) if mds else None,
        "effort_md_median": round(statistics.median(mds), 1) if mds else None,
        "effort_md_max": round(max(mds), 1) if mds else None,
        "common_tech": [{"name": n, "count": c} for n, c in common_tech],
        "example_projects": [
            {
                "title": e.get("title"),
                "client": e.get("client"),
                "effort_md": effective_effort_md(e),
                "source": e.get("source"),
            }
            for e in examples
        ],
    }
