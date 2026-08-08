"""Neo4j mirror of the knowledge graph for visual / multi-hop exploration.

Postgres (:mod:`kg_store`) is the graph's serving store for the agent's
templated tool queries — see [[kg-project-2026-08-08]] for why storage was
deliberately kept swappable. This module is the second consumer of that same
decision: it loads the *identical* ``nodes``/``edges`` shape produced by
:mod:`kg_transform` into Neo4j, for two things Postgres genuinely isn't good
at — a human browsing the graph visually (Neo4j Browser at
``http://localhost:7474``), and evidence-chain queries that walk an unknown
number of hops (``WbsTask -> WbsProject -> Opportunity -> Client``, or the
reverse "what does this technology touch" fan-out) without hand-writing a
recursive CTE per shape.

Uses the HTTP transactional Cypher endpoint via ``httpx`` (already a project
dependency) rather than the ``neo4j`` Bolt driver, per AGENTS.md's "no new
dependency without asking" rule — adding the driver wasn't asked. Bolt stays
open on 7687 for cypher-shell / Browser, which speak it directly.

Real Neo4j *labels* are used per node type (``:Opportunity``, ``:WbsTask``,
...) rather than one generic ``:Node`` label with a ``type`` property — that's
what makes the Browser's built-in "expand by label" and the label-colored
graph view actually useful; the Postgres side keeps the generic-table version
because SQL doesn't reward that split the same way.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("diagram-agent")

_DEFAULT_URL = "http://localhost:7474"
_DEFAULT_USER = "neo4j"

#: The exact node types kg_transform.py emits. A closed set, checked before
#: use as a Cypher label — labels can't be parameterized in Cypher, and this
#: project's own transform is the only producer, but validating anyway means
#: a future new node type fails loudly here instead of writing an
#: unconstrained label into the graph.
KNOWN_NODE_TYPES = frozenset(
    {
        "Opportunity",
        "Client",
        "Domain",
        "Technology",
        "WbsProject",
        "WbsTask",
        "Role",
        "Phase",
        "FeatureModule",
        "Kpi",
    }
)

#: Same reasoning for relationship types.
KNOWN_EDGE_RELS = frozenset(
    {
        "FOR_CLIENT",
        "IN_DOMAIN",
        "USES_TECH",
        "HAS_WBS",
        "CONTAINS",
        "ASSIGNED",
        "IN_PHASE",
        "IN_MODULE",
        "CLAIMS_KPI",
        "ATTRIBUTED_TO",
    }
)


def _connection(base_url: str | None, user: str | None, password: str | None) -> tuple[str, tuple[str, str]]:
    url = (base_url or os.getenv("NEO4J_HTTP_URL", "") or _DEFAULT_URL).rstrip("/")
    auth_user = user or os.getenv("NEO4J_USER", "") or _DEFAULT_USER
    auth_password = password or os.getenv("NEO4J_PASSWORD", "")
    if not auth_password:
        raise RuntimeError(
            "NEO4J_PASSWORD not set — refusing to guess a credential. Set it to the same "
            "value as docker-compose.yml's NEO4J_AUTH (default 'diagramgraph' in dev)."
        )
    return url, (auth_user, auth_password)


def _run(
    client: httpx.Client,
    base_url: str,
    statements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """POST one or more Cypher statements as a single transaction via the
    classic ``/db/neo4j/tx/commit`` endpoint. Raises on any statement error —
    a half-applied graph load is worse than a loud failure."""
    resp = client.post(f"{base_url}/db/neo4j/tx/commit", json={"statements": statements})
    resp.raise_for_status()
    body = resp.json()
    if body.get("errors"):
        raise RuntimeError(f"Neo4j statement error(s): {body['errors']}")
    return body["results"]


def setup(
    *,
    base_url: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> None:
    """Create a uniqueness constraint on ``id`` for each known node label —
    the Neo4j analogue of kg_nodes' Postgres primary key."""
    url, auth = _connection(base_url, user, password)
    with httpx.Client(auth=auth, timeout=30.0) as client:
        statements = [
            {"statement": (f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")}
            for label in sorted(KNOWN_NODE_TYPES)
        ]
        _run(client, url, statements)
    logger.info("neo4j constraints ready for %d labels", len(KNOWN_NODE_TYPES))


def load_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    base_url: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> dict[str, int]:
    """Full-reload the graph: delete every node this project owns, then
    recreate by label/relation batches via ``UNWIND``.

    Deletes only nodes carrying one of :data:`KNOWN_NODE_TYPES` as a label —
    a shared Neo4j instance with other data (there isn't one today, but the
    scoped delete costs nothing) would survive this reload.
    """
    url, auth = _connection(base_url, user, password)
    setup(base_url=url, user=auth[0], password=auth[1])

    by_type: dict[str, list[dict[str, Any]]] = {}
    for n in nodes:
        if n["type"] not in KNOWN_NODE_TYPES:
            raise ValueError(f"unknown node type {n['type']!r} — add it to KNOWN_NODE_TYPES first")
        by_type.setdefault(n["type"], []).append(n)

    by_rel: dict[str, list[dict[str, Any]]] = {}
    for e in edges:
        if e["rel"] not in KNOWN_EDGE_RELS:
            raise ValueError(f"unknown relation {e['rel']!r} — add it to KNOWN_EDGE_RELS first")
        by_rel.setdefault(e["rel"], []).append(e)

    with httpx.Client(auth=auth, timeout=120.0) as client:
        # scoped wipe: only nodes carrying one of our labels
        wipe = [{"statement": f"MATCH (n:{label}) DETACH DELETE n"} for label in sorted(KNOWN_NODE_TYPES)]
        _run(client, url, wipe)

        for label, rows in by_type.items():
            payload = [{"id": n["id"], "label": n["label"], "props": n.get("props") or {}} for n in rows]
            statement = (
                f"UNWIND $rows AS row "
                f"CREATE (n:{label} {{id: row.id}}) "
                f"SET n += row.props, n.label = row.label"
            )
            _run(client, url, [{"statement": statement, "parameters": {"rows": payload}}])

        for rel, rows in by_rel.items():
            payload = [{"src": e["src"], "dst": e["dst"], "props": e.get("props") or {}} for e in rows]
            statement = (
                "UNWIND $rows AS row "
                "MATCH (a {id: row.src}), (b {id: row.dst}) "
                f"CREATE (a)-[r:{rel}]->(b) "
                "SET r += row.props"
            )
            _run(client, url, [{"statement": statement, "parameters": {"rows": payload}}])

    logger.info("neo4j loaded: %d nodes, %d edges", len(nodes), len(edges))
    return {"nodes": len(nodes), "edges": len(edges)}


def graph_stats(
    *,
    base_url: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    url, auth = _connection(base_url, user, password)
    with httpx.Client(auth=auth, timeout=30.0) as client:
        results = _run(
            client,
            url,
            [
                {"statement": "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n ORDER BY n DESC"},
                {"statement": "MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS n ORDER BY n DESC"},
            ],
        )
    node_counts = {row["row"][0]: row["row"][1] for row in results[0]["data"]}
    edge_counts = {row["row"][0]: row["row"][1] for row in results[1]["data"]}
    return {"nodes_by_type": node_counts, "edges_by_rel": edge_counts}


def evidence_chain(
    task_or_project_id: str,
    *,
    base_url: str | None = None,
    user: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    """Walk from a WbsTask or WbsProject id STRICTLY upward to its
    WbsProject / Opportunity / Client — the multi-hop query Postgres would
    need a hand-written recursive CTE for.

    Direction matters here: CONTAINS points project→task and HAS_WBS points
    opportunity→project, so "up" from a task is against both edges'
    direction. An earlier version used an undirected pattern
    (``-[:CONTAINS*]-``) which is a lesson worth keeping visible: undirected
    multi-hop on CONTAINS fans out to every *sibling* task of the same
    project (33 of them, for the first id tried), which is noise, not
    evidence. Directed traversal + an explicit CASE for "start is already a
    WbsProject" keeps this to exactly the chain a human would draw by hand.
    """
    url, auth = _connection(base_url, user, password)
    statement = """
        MATCH (start {id: $id})
        WITH start, CASE WHEN 'WbsProject' IN labels(start) THEN start END AS asProject
        OPTIONAL MATCH (start)<-[:CONTAINS]-(projFromTask:WbsProject)
        WITH start, coalesce(asProject, projFromTask) AS proj
        OPTIONAL MATCH (proj)<-[:HAS_WBS]-(opp:Opportunity)
        OPTIONAL MATCH (opp)-[:FOR_CLIENT]->(client:Client)
        RETURN start.id AS start_id, start.label AS start_label,
               proj.id AS project_id, proj.label AS project_label,
               opp.id AS opportunity_id, opp.label AS opportunity_label,
               client.id AS client_id, client.label AS client_label
    """
    with httpx.Client(auth=auth, timeout=30.0) as client:
        results = _run(client, url, [{"statement": statement, "parameters": {"id": task_or_project_id}}])
    row = results[0]["data"][0]["row"]
    keys = [
        "start_id",
        "start_label",
        "project_id",
        "project_label",
        "opportunity_id",
        "opportunity_label",
        "client_id",
        "client_label",
    ]
    return dict(zip(keys, row))
