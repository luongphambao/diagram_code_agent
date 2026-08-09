"""Postgres-backed storage and query layer for the BnK knowledge graph.

Two generic tables — ``kg_nodes`` / ``kg_edges`` — hold every facet produced by
:mod:`kg_transform` (Opportunity, Client, Domain, Technology, WbsProject,
WbsTask, Role, Phase, FeatureModule). A generic property-graph schema was
chosen over one table per node type deliberately: see
[[kg-project-2026-08-08]] — the storage engine is the cheap, reversible part of
this project and the design explicitly defers committing to a graph database
(Neo4j et al.) until the ontology has proven itself against real queries. The
same ``nodes``/``edges`` shape loads unchanged into Neo4j later if that becomes
worth doing; only this module's SQL would be replaced by Cypher.

Follows the idempotent-DDL convention from ``conversations.py`` (see
docs/database.md §3) rather than a migration framework — this project uses
none. Connections are synchronous (``psycopg``, not ``psycopg_pool``/asyncio):
the graph is rebuilt offline by a script and queried from short-lived agent
tool calls, neither of which is on the async request hot path that
``agent/persistence.py`` serves.

Query functions are written as plain parameterized SQL, not Text2Cypher /
Text2SQL — per the 2026 evidence gathered for this project, LLM-generated
graph queries sit at ~44-50% execution accuracy even from frontier models
(worse on enterprise schemas), while templated queries score ~95%. These
functions ARE the templates; an agent tool wraps each one with a stable
signature.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import psycopg

from domain.kg.kg_transform import domain_id as _domain_id
from domain.kg.kg_transform import tech_id as _tech_id

logger = logging.getLogger("diagram-agent")

_DDL_NODES = """
CREATE TABLE IF NOT EXISTS kg_nodes (
    id         TEXT PRIMARY KEY,
    type       TEXT NOT NULL,
    label      TEXT NOT NULL,
    props      JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_DDL_EDGES = """
CREATE TABLE IF NOT EXISTS kg_edges (
    id         BIGSERIAL PRIMARY KEY,
    src        TEXT NOT NULL,
    rel        TEXT NOT NULL,
    dst        TEXT NOT NULL,
    props      JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

# No UNIQUE(src, rel, dst): a task can legitimately carry two ASSIGNED edges to
# the same role from two different source columns (e.g. be_md and
# be_coding_md both present) — collapsing those would silently drop effort.
# Full-reload (TRUNCATE + reinsert, see load_graph) makes idempotency a
# property of the *loader*, not of a constraint.
_DDL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS kg_nodes_type_idx ON kg_nodes (type);",
    "CREATE INDEX IF NOT EXISTS kg_edges_src_rel_idx ON kg_edges (src, rel);",
    "CREATE INDEX IF NOT EXISTS kg_edges_dst_rel_idx ON kg_edges (dst, rel);",
]


def _database_url(database_url: str | None) -> str:
    url = database_url or os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set — the knowledge graph has no durable store without "
            "Postgres (see docs/database.md). Not falling back to memory: unlike the "
            "LangGraph checkpointer, a silently-empty graph looks identical to a "
            "correctly-empty one, which is worse than failing loudly here."
        )
    return url


def setup(database_url: str | None = None) -> None:
    """Create the kg_nodes/kg_edges tables (+ indexes) if absent."""
    url = _database_url(database_url)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(_DDL_NODES)
        conn.execute(_DDL_EDGES)
        for stmt in _DDL_INDEXES:
            conn.execute(stmt)
    logger.info("kg_nodes/kg_edges ready")


def load_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    database_url: str | None = None,
) -> dict[str, int]:
    """Full-reload the graph: TRUNCATE both tables, then bulk-insert.

    A full reload rather than an incremental upsert-and-diff, because the
    source corpora (`solution_memory.json`, `DATA/SOLUTION_WBS/`) are small
    (order 10^3 nodes) and rebuilt as a whole by
    ``backend/scripts/build_knowledge_graph.py`` — there is no partial-refresh
    requirement yet. Runs inside one transaction: a failed load leaves the
    previous graph intact rather than a half-written one.
    """
    url = _database_url(database_url)
    setup(url)
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE kg_nodes, kg_edges;")
            cur.executemany(
                "INSERT INTO kg_nodes (id, type, label, props) VALUES (%s, %s, %s, %s)",
                [(n["id"], n["type"], n["label"], json.dumps(n.get("props") or {})) for n in nodes],
            )
            cur.executemany(
                "INSERT INTO kg_edges (src, rel, dst, props) VALUES (%s, %s, %s, %s)",
                [(e["src"], e["rel"], e["dst"], json.dumps(e.get("props") or {})) for e in edges],
            )
        conn.commit()
    logger.info("kg loaded: %d nodes, %d edges", len(nodes), len(edges))
    return {"nodes": len(nodes), "edges": len(edges)}


def graph_stats(*, database_url: str | None = None) -> dict[str, Any]:
    """Node-type and edge-relation counts — the sanity-check view after a load."""
    url = _database_url(database_url)
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT type, count(*) FROM kg_nodes GROUP BY type ORDER BY 2 DESC;")
            node_counts = dict(cur.fetchall())
            cur.execute("SELECT rel, count(*) FROM kg_edges GROUP BY rel ORDER BY 2 DESC;")
            edge_counts = dict(cur.fetchall())
    return {"nodes_by_type": node_counts, "edges_by_rel": edge_counts}


# ════════════════════════════════════════════════════════════════════════════
# Query templates — the agent-facing tool layer wraps these 1:1
# ════════════════════════════════════════════════════════════════════════════


def find_similar_opportunities(
    technologies: list[str] | None = None,
    domain: str | None = None,
    *,
    limit: int = 5,
    database_url: str | None = None,
) -> list[dict[str, Any]]:
    """Opportunities ranked by how many of the given technologies (and,
    optionally, a domain tag) they share — a graph analogue of tag-overlap
    search, cheap because it's two indexed joins, not a vector search."""
    url = _database_url(database_url)
    # Node ids are built with kg_transform's normalize_key (accent-folded,
    # lowercased, alnum-only) — matching that exactly here, not re-deriving a
    # slightly different id, is what makes "UiPath" (natural caller spelling)
    # actually hit the "tech:uipath" node instead of silently returning zero
    # rows. Same reasoning for domain_id below.
    tech_ids = [_tech_id(t) for t in technologies] if technologies else None
    domain_id = _domain_id(domain) if domain else None
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT n.id, n.label, n.props,
                       count(*) FILTER (WHERE e.rel = 'USES_TECH' AND e.dst = ANY(%(tech_ids)s)) AS tech_hits,
                       count(*) FILTER (WHERE e.rel = 'IN_DOMAIN' AND e.dst = %(domain_id)s::text) AS domain_hit
                FROM kg_nodes n
                JOIN kg_edges e ON e.src = n.id
                WHERE n.type = 'Opportunity'
                  AND (
                      (%(tech_ids)s IS NOT NULL AND e.rel = 'USES_TECH' AND e.dst = ANY(%(tech_ids)s))
                      OR (%(domain_id)s::text IS NOT NULL AND e.rel = 'IN_DOMAIN' AND e.dst = %(domain_id)s::text)
                  )
                GROUP BY n.id, n.label, n.props
                ORDER BY tech_hits DESC, domain_hit DESC
                LIMIT %(limit)s;
                """,
                {"tech_ids": tech_ids, "domain_id": domain_id, "limit": limit},
            )
            rows = cur.fetchall()
    return [
        {"id": r[0], "label": r[1], "props": r[2], "tech_hits": r[3], "domain_hit": bool(r[4])} for r in rows
    ]


def benchmark_effort_by_role(
    domain: str | None = None,
    role: str | None = None,
    *,
    database_url: str | None = None,
) -> list[dict[str, Any]]:
    """Man-day distribution per role, optionally narrowed to Opportunities
    tagged with *domain*. Deliberately excludes anything with
    ``props->>'estimator' = 'partner'`` — mixing BnK's own effort with a
    partner's parallel estimate (the ``oi_md`` case) would silently bias the
    benchmark, see kg_vocab's estimator-confusion note."""
    url = _database_url(database_url)
    role_filter = f"role:{role}" if role else None
    domain_id = _domain_id(domain) if domain else None
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH scoped_tasks AS (
                    SELECT DISTINCT t.id AS task_id
                    FROM kg_nodes t
                    JOIN kg_edges proj_contains ON proj_contains.dst = t.id AND proj_contains.rel = 'CONTAINS'
                    LEFT JOIN kg_edges has_wbs ON has_wbs.dst = proj_contains.src AND has_wbs.rel = 'HAS_WBS'
                    LEFT JOIN kg_edges in_domain
                        ON in_domain.src = has_wbs.src AND in_domain.rel = 'IN_DOMAIN'
                        AND in_domain.dst = %(domain_id)s::text
                    WHERE t.type = 'WbsTask'
                      AND (%(domain_id)s::text IS NULL OR in_domain.dst IS NOT NULL)
                )
                SELECT e.dst AS role,
                       count(*)                                             AS n_assignments,
                       sum((e.props->>'man_days')::numeric)                 AS total_md,
                       min((e.props->>'man_days')::numeric)                 AS min_md,
                       percentile_cont(0.5) WITHIN GROUP (
                           ORDER BY (e.props->>'man_days')::numeric)        AS median_md,
                       max((e.props->>'man_days')::numeric)                 AS max_md
                FROM kg_edges e
                JOIN scoped_tasks st ON st.task_id = e.src
                WHERE e.rel = 'ASSIGNED'
                  AND COALESCE(e.props->>'estimator', 'bnk') = 'bnk'
                  AND (%(role_filter)s::text IS NULL OR e.dst = %(role_filter)s::text)
                GROUP BY e.dst
                ORDER BY total_md DESC;
                """,
                {"domain_id": domain_id, "role_filter": role_filter},
            )
            rows = cur.fetchall()
    return [
        {
            "role": r[0],
            "n_assignments": r[1],
            "total_md": float(r[2]) if r[2] is not None else None,
            "min_md": float(r[3]) if r[3] is not None else None,
            "median_md": float(r[4]) if r[4] is not None else None,
            "max_md": float(r[5]) if r[5] is not None else None,
        }
        for r in rows
    ]


def tech_cooccurrence(
    technology: str,
    *,
    limit: int = 10,
    database_url: str | None = None,
) -> list[dict[str, Any]]:
    """Technologies most often used alongside *technology*, across both
    Opportunity and WbsProject USES_TECH edges — a reuse-recommendation
    primitive ("projects using UiPath also tend to use...")."""
    url = _database_url(database_url)
    tech_id_ = _tech_id(technology)
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT other.dst AS other_tech, n.label, count(DISTINCT other.src) AS co_projects
                FROM kg_edges seed
                JOIN kg_edges other ON other.src = seed.src AND other.rel = 'USES_TECH' AND other.dst != seed.dst
                JOIN kg_nodes n ON n.id = other.dst
                WHERE seed.rel = 'USES_TECH' AND seed.dst = %(tech_id)s
                GROUP BY other.dst, n.label
                ORDER BY co_projects DESC
                LIMIT %(limit)s;
                """,
                {"tech_id": tech_id_, "limit": limit},
            )
            rows = cur.fetchall()
    return [{"technology_id": r[0], "label": r[1], "co_projects": r[2]} for r in rows]


def module_reuse(
    keyword: str,
    *,
    limit: int = 10,
    database_url: str | None = None,
) -> list[dict[str, Any]]:
    """FeatureModule nodes whose label matches *keyword* (case-insensitive
    substring), with which WbsProject each came from — "has anyone built a
    booking engine before" as a lookup rather than free-text search."""
    url = _database_url(database_url)
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT fm.id, fm.label, proj.id AS project_id, proj.label AS project_label
                FROM kg_nodes fm
                JOIN kg_edges contains ON contains.dst =
                    (SELECT t.id FROM kg_nodes t
                     JOIN kg_edges im ON im.src = t.id AND im.rel = 'IN_MODULE' AND im.dst = fm.id
                     LIMIT 1)
                JOIN kg_nodes proj ON proj.id = contains.src AND proj.type = 'WbsProject'
                WHERE fm.type = 'FeatureModule' AND fm.label ILIKE %(pattern)s
                LIMIT %(limit)s;
                """,
                {"pattern": f"%{keyword}%", "limit": limit},
            )
            rows = cur.fetchall()
    return [{"module_id": r[0], "label": r[1], "project_id": r[2], "project_label": r[3]} for r in rows]
