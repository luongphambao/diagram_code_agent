"""Agent-facing tools over the BnK knowledge graph (see ``rag/kg_store.py``,
``rag/kg_neo4j.py``, ``domain/kg/kg_transform.py`` — built 2026-08-08, see
project memory [[kg-project-2026-08-08]]).

Complements, does not replace, the existing vector-search tools in
``rag_tools.py``:

- ``find_similar_solutions`` (vector) answers "what's the single closest past
  project to this free-text description" — good for a fuzzy narrative match.
- ``find_related_projects`` (this module, graph) answers "which past projects
  share THESE specific technologies / this domain tag" — an exact-overlap
  ranking, cheap (indexed joins, no embedding call), and composable with the
  other graph tools below via the ids it returns.
- ``benchmark_solution`` (rag/benchmarks.py) aggregates effort at the WHOLE-
  PROJECT grain from the narrative+WBS corpus.
- ``benchmark_role_effort`` (this module) aggregates at the PER-ROLE grain
  from actual WBS task-level assignments — "how many BE man-days does a
  banking project typically need", not just a project total.

All four query tools here degrade softly (return ``status: "ERROR"`` + an
``instruction``) when Postgres/Neo4j aren't reachable, per conventions §4 —
they never raise into the agent loop.
"""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_DB_UNAVAILABLE_INSTRUCTION = (
    "The knowledge graph is unavailable (Postgres not configured/reachable — see "
    "DATABASE_URL). Proceed without this evidence; do not block on it."
)
_NEO4J_UNAVAILABLE_INSTRUCTION = (
    "The Neo4j graph mirror is unavailable (NEO4J_PASSWORD not configured, or the "
    "service isn't running). Proceed without this evidence; do not block on it."
)


@tool(parse_docstring=True)
def find_related_projects(technologies: str = "", domain: str = "", top_k: int = 5) -> str:
    """Find past BnK projects that share specific technologies or a domain tag.

    Graph-based exact-overlap ranking, distinct from find_similar_solutions'
    free-text vector search — use this when you already know which
    technologies or domain matter and want projects that actually used them,
    not merely a semantically-similar narrative. Chain with
    trace_project_lineage(id) on a result's "id" to walk up to its client.

    Args:
        technologies: Comma-separated technology names to match, e.g.
            "UiPath, Power Automate, OCR". Leave empty to rank by domain alone.
        domain: Optional domain tag to narrow by, e.g. "banking", "insurance",
            "document-ai", "logistics", "manufacturing", "healthcare",
            "retail", "data-platform", "ai-ml", "agriculture".
        top_k: Max results to return (default 5, max 10).
    """
    from rag.kg_store import find_similar_opportunities

    tech_list = [t.strip() for t in technologies.split(",") if t.strip()] or None
    try:
        results = find_similar_opportunities(tech_list, domain or None, limit=max(1, min(int(top_k), 10)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("find_related_projects failed: %s", exc)
        return json.dumps(
            {"status": "ERROR", "error": str(exc)[:300], "instruction": _DB_UNAVAILABLE_INSTRUCTION},
            ensure_ascii=False,
            indent=2,
        )

    result = {
        "status": "OK",
        "count": len(results),
        "projects": results,
        "instruction": (
            "tech_hits/domain_hit show how many of your query terms this project actually "
            "shares — treat this as reuse evidence ('BnK has built this before with these "
            "exact technologies'), not a semantic guess. Pass a result's id to "
            "trace_project_lineage for its client/opportunity chain."
        ),
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool(parse_docstring=True)
def benchmark_role_effort(domain: str = "", role: str = "") -> str:
    """Get real per-role effort (man-days) benchmarks from BnK's WBS task history.

    Unlike benchmark_solution (whole-project MD totals), this aggregates at
    the individual role grain — "how many BE man-days does a typical banking
    project need" — computed directly from task-level ASSIGNED edges in the
    knowledge graph. Excludes any effort recorded under a non-BnK estimator
    (e.g. a delivery partner's own parallel estimate) so the benchmark isn't
    silently inflated by numbers that aren't BnK's own sizing.

    Args:
        domain: Optional domain tag to narrow by, e.g. "banking", "insurance",
            "document-ai" — leave empty to benchmark across all domains.
        role: Optional role code to narrow to one role: PM, BA, BE, FE,
            MOBILE, QC, AI, DATA, RPA, DEVOPS, TL, UX, SE. Leave empty to
            return the breakdown across every role.
    """
    from domain.kg.kg_vocab import ROLE_LABELS, ROLES
    from rag.kg_store import benchmark_effort_by_role

    role_code = role.strip().upper() or None
    if role_code and role_code not in ROLES:
        return json.dumps(
            {
                "status": "ERROR",
                "error": f"unknown role {role!r}",
                "instruction": f"Valid roles: {', '.join(sorted(ROLES))}. Retry with one of these, or omit role.",
            },
            ensure_ascii=False,
            indent=2,
        )

    try:
        rows = benchmark_effort_by_role(domain or None, role_code)
    except Exception as exc:  # noqa: BLE001
        logger.warning("benchmark_role_effort failed: %s", exc)
        return json.dumps(
            {"status": "ERROR", "error": str(exc)[:300], "instruction": _DB_UNAVAILABLE_INSTRUCTION},
            ensure_ascii=False,
            indent=2,
        )

    for row in rows:
        row["role_label"] = ROLE_LABELS.get(row["role"].removeprefix("role:"), row["role"])

    if not rows:
        instruction = (
            f"No task-level effort found for domain={domain or '(any)'} role={role or '(any)'}. "
            "Proceed without this benchmark, or widen the domain."
        )
    else:
        instruction = (
            "Use median_md per role as the benchmark point and min/max as the plausible band "
            "when sizing effort by role. n_assignments is the sample size — treat a role with "
            "under ~5 assignments as a weak signal, not a firm reference."
        )
    return json.dumps(
        {"status": "OK", "domain": domain or None, "roles": rows, "instruction": instruction},
        ensure_ascii=False,
        indent=2,
    )


@tool(parse_docstring=True)
def find_related_technologies(technology: str, top_k: int = 10) -> str:
    """Find technologies BnK has used alongside a given one across past projects.

    A reuse-recommendation lookup — "projects using UiPath also tend to use
    Odoo/Docker/..." — for sanity-checking a proposed tech stack against what
    BnK has actually shipped together before, not just what's individually
    common.

    Args:
        technology: The technology name to look up co-occurrences for, e.g.
            "UiPath", "PostgreSQL", "Power Automate".
        top_k: Max co-occurring technologies to return (default 10, max 20).
    """
    from rag.kg_store import tech_cooccurrence

    try:
        results = tech_cooccurrence(technology, limit=max(1, min(int(top_k), 20)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("find_related_technologies failed: %s", exc)
        return json.dumps(
            {"status": "ERROR", "error": str(exc)[:300], "instruction": _DB_UNAVAILABLE_INSTRUCTION},
            ensure_ascii=False,
            indent=2,
        )

    if not results:
        instruction = (
            f"No recorded co-occurrence for {technology!r} — it may be a one-off mention, or misspelled."
        )
    else:
        instruction = (
            "co_projects is how many distinct BnK deliveries paired these two technologies — "
            "prefer higher co_projects choices when your stack needs a complementary component."
        )
    return json.dumps(
        {"status": "OK", "technology": technology, "related": results, "instruction": instruction},
        ensure_ascii=False,
        indent=2,
    )


@tool(parse_docstring=True)
def find_reusable_modules(keyword: str, top_k: int = 10) -> str:
    """Find feature modules BnK has already built that match a keyword.

    Looks up the FeatureModule facet of the knowledge graph — project-local
    WBS module names like "Booking Engine" or "Camera Registration" — to
    answer "has BnK built something like this before" so a WBS draft can
    reuse a proven module breakdown instead of estimating from scratch.

    Args:
        keyword: A feature/module keyword to search for, e.g. "booking",
            "payment", "OCR", "dashboard". Matched as a case-insensitive
            substring against past module names.
        top_k: Max modules to return (default 10, max 20).
    """
    from rag.kg_store import module_reuse

    try:
        results = module_reuse(keyword, limit=max(1, min(int(top_k), 20)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("find_reusable_modules failed: %s", exc)
        return json.dumps(
            {"status": "ERROR", "error": str(exc)[:300], "instruction": _DB_UNAVAILABLE_INSTRUCTION},
            ensure_ascii=False,
            indent=2,
        )

    instruction = (
        "Use project_label as a reference precedent when sizing a similar module in the current "
        "WBS — it's real prior work, not a guess. No hits means BnK likely hasn't built this "
        "exact module before; size it independently."
    )
    return json.dumps(
        {"status": "OK", "keyword": keyword, "modules": results, "instruction": instruction},
        ensure_ascii=False,
        indent=2,
    )


@tool(parse_docstring=True)
def trace_project_lineage(node_id: str) -> str:
    """Trace a knowledge-graph node up to its project, opportunity, and client.

    Pass an "id" field from a prior find_related_projects / benchmark_role_effort
    / find_reusable_modules result (a WbsTask, WbsProject, or similar id) to
    see which real BnK opportunity and client it belongs to — the evidence
    trail behind a cited benchmark or reused module, not just the number
    itself. Requires the Neo4j mirror (optional infra); degrades softly if
    unavailable.

    Args:
        node_id: A knowledge-graph node id, e.g. "wbsproj:..." or a WbsTask id
            copied from another kg tool's result.
    """
    from rag.kg_neo4j import evidence_chain

    try:
        chain = evidence_chain(node_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("trace_project_lineage failed: %s", exc)
        return json.dumps(
            {"status": "ERROR", "error": str(exc)[:300], "instruction": _NEO4J_UNAVAILABLE_INSTRUCTION},
            ensure_ascii=False,
            indent=2,
        )

    return json.dumps(
        {
            "status": "OK",
            "chain": chain,
            "instruction": (
                "This is the evidence chain for the id you passed — cite project_label/"
                "opportunity_label/client_label together when presenting this as grounded "
                "history, not just a bare number."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )
