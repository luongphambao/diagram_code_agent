"""Tests for the agent-facing knowledge-graph tools in ``kg_tools.py``.

Mocks the underlying ``rag.kg_store`` / ``rag.kg_neo4j`` functions rather than
hitting a live Postgres/Neo4j — these tools' own job is argument translation
(natural-case tech names -> normalized ids, role validation, JSON shaping,
soft-degrade on failure), which is exactly what's worth pinning here. The
underlying query correctness is covered separately by ``test_kg_transform.py``
(the id-construction logic) and manual verification against the real corpus.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import kg_tools


def test_find_related_projects_passes_through_and_shapes_result() -> None:
    with patch("rag.kg_store.find_similar_opportunities") as mock_fn:
        mock_fn.return_value = [
            {"id": "opp:x", "label": "X", "props": {}, "tech_hits": 2, "domain_hit": True}
        ]
        raw = kg_tools.find_related_projects.func(
            technologies="UiPath, Power Automate", domain="banking", top_k=3
        )
    data = json.loads(raw)
    assert data["status"] == "OK"
    assert data["count"] == 1
    mock_fn.assert_called_once_with(["UiPath", "Power Automate"], "banking", limit=3)


def test_find_related_projects_empty_technologies_becomes_none() -> None:
    with patch("rag.kg_store.find_similar_opportunities") as mock_fn:
        mock_fn.return_value = []
        kg_tools.find_related_projects.func(technologies="", domain="banking", top_k=5)
    mock_fn.assert_called_once_with(None, "banking", limit=5)


def test_find_related_projects_caps_top_k_at_ten() -> None:
    with patch("rag.kg_store.find_similar_opportunities") as mock_fn:
        mock_fn.return_value = []
        kg_tools.find_related_projects.func(technologies="X", top_k=999)
    assert mock_fn.call_args.kwargs["limit"] == 10


def test_find_related_projects_degrades_softly_on_db_error() -> None:
    with patch("rag.kg_store.find_similar_opportunities", side_effect=RuntimeError("DATABASE_URL not set")):
        raw = kg_tools.find_related_projects.func(technologies="UiPath")
    data = json.loads(raw)
    assert data["status"] == "ERROR"
    assert "instruction" in data


def test_benchmark_role_effort_normalizes_lowercase_role() -> None:
    with patch("rag.kg_store.benchmark_effort_by_role") as mock_fn:
        mock_fn.return_value = [
            {
                "role": "role:BE",
                "n_assignments": 5,
                "total_md": 10.0,
                "min_md": 1.0,
                "median_md": 2.0,
                "max_md": 5.0,
            }
        ]
        raw = kg_tools.benchmark_role_effort.func(domain="banking", role="be")
    data = json.loads(raw)
    assert data["status"] == "OK"
    mock_fn.assert_called_once_with("banking", "BE")
    assert data["roles"][0]["role_label"] == "Backend Engineering"


def test_benchmark_role_effort_rejects_unknown_role_without_calling_db() -> None:
    with patch("rag.kg_store.benchmark_effort_by_role") as mock_fn:
        raw = kg_tools.benchmark_role_effort.func(role="CEO")
    data = json.loads(raw)
    assert data["status"] == "ERROR"
    assert "BE" in data["instruction"]  # lists valid roles
    mock_fn.assert_not_called()


def test_benchmark_role_effort_empty_role_means_no_filter() -> None:
    with patch("rag.kg_store.benchmark_effort_by_role") as mock_fn:
        mock_fn.return_value = []
        kg_tools.benchmark_role_effort.func(domain="banking", role="")
    mock_fn.assert_called_once_with("banking", None)


def test_find_related_technologies_shapes_result() -> None:
    with patch("rag.kg_store.tech_cooccurrence") as mock_fn:
        mock_fn.return_value = [{"technology_id": "tech:odoo", "label": "Odoo", "co_projects": 2}]
        raw = kg_tools.find_related_technologies.func(technology="UiPath", top_k=5)
    data = json.loads(raw)
    assert data["status"] == "OK"
    assert data["related"][0]["label"] == "Odoo"
    mock_fn.assert_called_once_with("UiPath", limit=5)


def test_find_reusable_modules_shapes_result() -> None:
    with patch("rag.kg_store.module_reuse") as mock_fn:
        mock_fn.return_value = [
            {"module_id": "m1", "label": "Booking Engine", "project_id": "p1", "project_label": "LTC"}
        ]
        raw = kg_tools.find_reusable_modules.func(keyword="booking", top_k=5)
    data = json.loads(raw)
    assert data["status"] == "OK"
    assert data["modules"][0]["project_label"] == "LTC"


def test_find_reusable_modules_degrades_softly_on_error() -> None:
    with patch("rag.kg_store.module_reuse", side_effect=RuntimeError("boom")):
        raw = kg_tools.find_reusable_modules.func(keyword="booking")
    data = json.loads(raw)
    assert data["status"] == "ERROR"


def test_trace_project_lineage_shapes_result() -> None:
    with patch("rag.kg_neo4j.evidence_chain") as mock_fn:
        mock_fn.return_value = {"start_id": "t1", "opportunity_label": "X", "client_label": "Acme"}
        raw = kg_tools.trace_project_lineage.func(node_id="t1")
    data = json.loads(raw)
    assert data["status"] == "OK"
    assert data["chain"]["client_label"] == "Acme"


def test_trace_project_lineage_degrades_softly_when_neo4j_unavailable() -> None:
    with patch("rag.kg_neo4j.evidence_chain", side_effect=RuntimeError("NEO4J_PASSWORD not set")):
        raw = kg_tools.trace_project_lineage.func(node_id="t1")
    data = json.loads(raw)
    assert data["status"] == "ERROR"
    assert "Neo4j" in data["instruction"]
