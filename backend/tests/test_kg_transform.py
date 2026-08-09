"""Unit tests for the pure corpus→graph transforms in :mod:`kg_transform`.

All fixtures are hand-built minimal dicts shaped like real solution_memory
entries / WBS payloads — no dependency on ``DATA/`` or a database, per
conventions §1.
"""

from __future__ import annotations

import kg_transform as kt


# ════════════════════════════════════════════════════════════════════════════
# Client identity
# ════════════════════════════════════════════════════════════════════════════


def test_client_parenthetical_context_is_split_not_lost() -> None:
    node = kt.client_node("Trần Đức Group (nhà sản xuất nội thất khách sạn cao cấp, Việt Nam)")
    assert node is not None
    assert node["label"] == "Trần Đức Group"
    assert "nội thất" in node["props"]["context"]


def test_same_client_different_parenthetical_is_one_node() -> None:
    a = kt.client_node("Eximbank (ngân hàng TMCP)")
    b = kt.client_node("Eximbank")
    assert a is not None and b is not None
    assert a["id"] == b["id"]


def test_empty_client_mints_no_node() -> None:
    """~44% of decks have no named client — must not become a placeholder node."""
    assert kt.client_node("") is None
    assert kt.client_node("   ") is None


# ════════════════════════════════════════════════════════════════════════════
# Domain axis split
# ════════════════════════════════════════════════════════════════════════════


def test_domain_tags_split_into_industry_and_solution_type_axes() -> None:
    assert kt.domain_node("banking")["props"]["axis"] == "industry"
    assert kt.domain_node("healthcare")["props"]["axis"] == "industry"
    assert kt.domain_node("ai-ml")["props"]["axis"] == "solution_type"
    assert kt.domain_node("document-ai")["props"]["axis"] == "solution_type"


# ════════════════════════════════════════════════════════════════════════════
# Technology recurrence filter
# ════════════════════════════════════════════════════════════════════════════


def test_singleton_technology_is_not_a_node() -> None:
    """810 of 944 raw tech strings occur exactly once — must not become dead nodes."""
    by_source = {"a": ["OnceOnlyTool"], "b": ["PostgreSQL"], "c": ["PostgreSQL"]}
    nodes = kt.technology_nodes(by_source, min_project_count=2)
    ids = set(nodes)
    assert kt.tech_id("PostgreSQL") in ids
    assert kt.tech_id("OnceOnlyTool") not in ids


def test_technology_counted_once_per_source_not_per_mention() -> None:
    """A tech named twice in one project's tech[] must count as one project,
    not inflate recurrence."""
    by_source = {"a": ["Docker", "Docker", "docker"], "b": ["Docker"]}
    counts = kt.count_technologies(by_source)
    assert counts[kt.tech_id("Docker")] == 2


def test_stopword_tech_never_becomes_a_node() -> None:
    by_source = {"a": ["Agile"], "b": ["Agile"], "c": ["Agile"]}
    nodes = kt.technology_nodes(by_source, min_project_count=1)
    assert kt.tech_id("Agile") not in nodes


def test_technology_label_is_majority_spelling() -> None:
    by_source = {"a": ["UiPath"], "b": ["uipath"], "c": ["UIPATH"]}
    nodes = kt.technology_nodes(by_source, min_project_count=2)
    node = nodes[kt.tech_id("UiPath")]
    assert node["label"] in {"UiPath", "uipath", "UIPATH"}
    assert node["props"]["mention_count"] == 3


# ════════════════════════════════════════════════════════════════════════════
# Opportunity + edges
# ════════════════════════════════════════════════════════════════════════════

_ENTRY = {
    "slug": "demo-rpa",
    "folder": "Demo RPA Deck",
    "title": "Demo RPA Deck",
    "client": "Acme Corp (manufacturer)",
    "type": "Proposal",
    "domain": ["manufacturing", "ai-ml"],
    "tech": ["UiPath", "PostgreSQL", "OnceOnlyTool"],
    "problem": "manual invoice processing",
    "solution": "RPA automation",
    "outcome": "80% faster",
    "image_ref": None,
    "estimate": {"effort_md": 42.0, "timeline_months": 3},
    "wbs_match": {"source_file": "Demo RPA - WBS.json", "total_mandays": 45.0},
    "wbs_join_reasoning": "exact title match",
    "source": "narrative+wbs",
}


def test_colliding_slugs_are_merged_not_dropped_or_crashed() -> None:
    """CIMB_Proposal_April_2026 1 / _1 and Protenlindo ...-2 2 / -2_2 hash to the
    identical slug (build_case_library.py's 60-char, non-alnum-folded _slug()).
    Loading both as separate Opportunity nodes crashes the Postgres primary key;
    this must merge them into one node with the drop recorded, not silently
    keep whichever happened to sort last."""
    a = {**_ENTRY, "folder": "CIMB_Proposal_April_2026 1", "slug": "cimb-1", "tech": []}
    b = {**_ENTRY, "folder": "CIMB_Proposal_April_2026_1", "slug": "cimb-1", "tech": ["UiPath"]}
    merged = kt.dedupe_entries([a, b])
    assert len(merged) == 1
    # richer entry (has tech) wins
    assert merged[0]["folder"] == "CIMB_Proposal_April_2026_1"
    assert merged[0]["_merged_from"] == ["CIMB_Proposal_April_2026 1"]


def test_dedupe_is_order_independent() -> None:
    a = {**_ENTRY, "folder": "A", "slug": "same", "tech": ["X"]}
    b = {**_ENTRY, "folder": "B", "slug": "same", "tech": ["X", "Y"]}
    forward = kt.dedupe_entries([a, b])
    backward = kt.dedupe_entries([b, a])
    assert forward[0]["folder"] == backward[0]["folder"] == "B"


def test_opportunity_node_carries_estimate_and_wbs_total() -> None:
    node = kt.opportunity_node(_ENTRY)
    assert node["id"] == "opp:demo-rpa"
    assert node["props"]["effort_md"] == 42.0
    assert node["props"]["wbs_total_mandays"] == 45.0


def test_opportunity_edges_only_include_recurring_tech() -> None:
    tech_ids = {kt.tech_id("UiPath"), kt.tech_id("PostgreSQL")}  # OnceOnlyTool excluded
    edges = kt.opportunity_edges(_ENTRY, tech_ids)
    rels = {(e["rel"], e["dst"]) for e in edges}
    assert ("USES_TECH", kt.tech_id("UiPath")) in rels
    assert ("USES_TECH", kt.tech_id("OnceOnlyTool")) not in rels
    assert ("FOR_CLIENT", kt.client_id("Acme Corp (manufacturer)")) in rels
    assert ("IN_DOMAIN", kt.domain_id("manufacturing")) in rels


def test_opportunity_wbs_edge_uses_the_existing_llm_confirmed_join() -> None:
    edge = kt.opportunity_wbs_edge(_ENTRY)
    assert edge is not None
    assert edge["dst"] == kt.wbs_project_id("Demo RPA - WBS.json")
    assert edge["props"]["reasoning"] == "exact title match"


def test_opportunity_without_wbs_match_yields_no_edge() -> None:
    entry = {**_ENTRY, "wbs_match": None}
    assert kt.opportunity_wbs_edge(entry) is None


# ════════════════════════════════════════════════════════════════════════════
# WBS project transform
# ════════════════════════════════════════════════════════════════════════════

_WBS_PAYLOAD = {
    "project_info": {"name": "Demo RPA", "client": "Acme Corp"},
    "technology_stack": ["UiPath", "PostgreSQL", "Once-Off Tool"],
    "effort_totals": {"total_mandays": 45.0},
    "effort_by_module": [
        {"code": "I", "name": "SET UP & INSTALLATION", "total_md": 10.0},
        {"code": "II", "name": "DEVELOPMENT", "total_md": 25.0},
    ],
    "wbs_items": [
        {
            "code": "I.A",
            "name": "Provision environment",
            "phase": "SET UP & INSTALLATION",
            "be_md": 3.0,
            "pm_md": 1.0,
        },
        {
            "code": "II.A",
            "name": "Build invoice workflow",
            "module": "MODULE B - INVOICE ENGINE",
            "be_md": 8.0,
            "fe_mobile_md": 4.0,
            "oi_md": 20.0,  # partner estimate — must not become a Role assignment
        },
        {
            "code": "II.B",
            "name": "No effort at all",
            "remark": "Just by case",
        },
    ],
}


def test_wbs_project_node_and_task_nodes_are_created() -> None:
    tech_ids = {kt.tech_id("UiPath"), kt.tech_id("PostgreSQL")}
    nodes, edges = kt.transform_wbs_project("Demo RPA - WBS.json", _WBS_PAYLOAD, tech_ids)
    types = {n["type"] for n in nodes}
    assert "WbsProject" in types
    assert "WbsTask" in types
    task_labels = {n["label"] for n in nodes if n["type"] == "WbsTask"}
    assert "Provision environment" in task_labels
    assert "Build invoice workflow" in task_labels
    # the zero-effort task must not appear — nothing to attribute
    assert "No effort at all" not in task_labels


def test_partner_estimate_column_produces_no_role_assignment() -> None:
    """oi_md (20 MD) must not create an ASSIGNED edge to any Role — see
    kg_vocab's estimator-confusion note."""
    tech_ids: set[str] = set()
    _nodes, edges = kt.transform_wbs_project("Demo RPA - WBS.json", _WBS_PAYLOAD, tech_ids)
    assigned = [e for e in edges if e["rel"] == "ASSIGNED"]
    total_role_md = sum(e["props"]["man_days"] for e in assigned)
    # 3(be) + 1(pm) + 8(be) + 2(fe) + 2(mobile) = 16 — the 20 MD of oi_md is excluded
    assert total_role_md == 16.0


def test_task_in_recognised_phase_gets_in_phase_edge() -> None:
    tech_ids: set[str] = set()
    nodes, edges = kt.transform_wbs_project("Demo RPA - WBS.json", _WBS_PAYLOAD, tech_ids)
    task_id = next(n["id"] for n in nodes if n["label"] == "Provision environment")
    phase_edges = [e for e in edges if e["src"] == task_id and e["rel"] == "IN_PHASE"]
    assert phase_edges and phase_edges[0]["dst"] == "phase:SETUP"


def test_task_in_project_local_module_gets_feature_module_not_phase() -> None:
    tech_ids: set[str] = set()
    nodes, edges = kt.transform_wbs_project("Demo RPA - WBS.json", _WBS_PAYLOAD, tech_ids)
    task_id = next(n["id"] for n in nodes if n["label"] == "Build invoice workflow")
    module_edges = [e for e in edges if e["src"] == task_id and e["rel"] == "IN_MODULE"]
    assert module_edges
    fm_node = next(n for n in nodes if n["id"] == module_edges[0]["dst"])
    assert fm_node["type"] == "FeatureModule"
    assert not any(e["src"] == task_id and e["rel"] == "IN_PHASE" for e in edges)


def test_composite_role_column_splits_effort_across_both_roles() -> None:
    tech_ids: set[str] = set()
    nodes, edges = kt.transform_wbs_project("Demo RPA - WBS.json", _WBS_PAYLOAD, tech_ids)
    task_id = next(n["id"] for n in nodes if n["label"] == "Build invoice workflow")
    role_md = {
        e["dst"]: e["props"]["man_days"] for e in edges if e["src"] == task_id and e["rel"] == "ASSIGNED"
    }
    assert role_md["role:FE"] == 2.0
    assert role_md["role:MOBILE"] == 2.0
    assert role_md["role:BE"] == 8.0


def test_wbs_technology_edges_respect_the_recurrence_filter() -> None:
    tech_ids = {kt.tech_id("UiPath")}  # PostgreSQL and Once-Off Tool excluded
    _nodes, edges = kt.transform_wbs_project("Demo RPA - WBS.json", _WBS_PAYLOAD, tech_ids)
    tech_edges = {e["dst"] for e in edges if e["rel"] == "USES_TECH"}
    assert tech_edges == {kt.tech_id("UiPath")}


# ════════════════════════════════════════════════════════════════════════════
# Full graph assembly
# ════════════════════════════════════════════════════════════════════════════


def test_build_graph_end_to_end_small_fixture() -> None:
    nodes, edges = kt.build_graph([_ENTRY], {"Demo RPA - WBS.json": _WBS_PAYLOAD}, min_tech_project_count=1)
    node_ids = {n["id"] for n in nodes}

    assert "opp:demo-rpa" in node_ids
    assert kt.wbs_project_id("Demo RPA - WBS.json") in node_ids
    assert "role:BE" in node_ids and "phase:SETUP" in node_ids

    # the Opportunity↔WbsProject join survives the full pipeline
    join_edges = [e for e in edges if e["rel"] == "HAS_WBS"]
    assert any(e["src"] == "opp:demo-rpa" for e in join_edges)


def test_build_graph_creates_standalone_wbs_project_when_unjoined() -> None:
    """~21 of 52 WBS files have no matching Opportunity — they still surface as
    their own node rather than being silently dropped (conventions §4)."""
    entry_no_match = {**_ENTRY, "wbs_match": None}
    nodes, _edges = kt.build_graph(
        [entry_no_match], {"Orphan - WBS.json": _WBS_PAYLOAD}, min_tech_project_count=1
    )
    assert kt.wbs_project_id("Orphan - WBS.json") in {n["id"] for n in nodes}


def test_build_graph_is_deterministic_across_two_runs() -> None:
    """Node/edge ids must be content-derived, not random — required for the
    idempotent Postgres upsert and for git-diffable jsonl exports."""
    a = kt.build_graph([_ENTRY], {"Demo RPA - WBS.json": _WBS_PAYLOAD}, min_tech_project_count=1)
    b = kt.build_graph([_ENTRY], {"Demo RPA - WBS.json": _WBS_PAYLOAD}, min_tech_project_count=1)
    assert {n["id"] for n in a[0]} == {n["id"] for n in b[0]}
    assert sorted((e["src"], e["rel"], e["dst"]) for e in a[1]) == sorted(
        (e["src"], e["rel"], e["dst"]) for e in b[1]
    )


# ════════════════════════════════════════════════════════════════════════════
# Kpi facet — the adversarial CMC-Telecom-style attribution case
# ════════════════════════════════════════════════════════════════════════════

# Shaped like extract_kpis.py's real output on the BnK - CMC RPA Proposal deck:
# every case-study KPI belongs to a DIFFERENT client than the deck's own
# subject, and the source text says so explicitly.
_CMC_STYLE_EXTRACT = [
    {
        "folder": "Demo RPA Deck",  # same folder as _ENTRY, to exercise the join
        "deck_subject_client": "CMC Telecom",
        "kpis": [
            {
                "metric": "Manual volume automated",
                "value": "95%",
                "attributed_client": "Eximbank",
                "is_commitment_for_subject_client": False,
                "slide_evidence": "32",
            },
            {
                "metric": "Processing time reduction",
                "value": "70%",
                "attributed_client": "BIDV",
                "is_commitment_for_subject_client": False,
                "slide_evidence": "",
            },
            {
                "metric": "Team delivery capacity",
                "value": "40+ engineers",
                "attributed_client": "BnK Solution (internal capability stat)",
                "is_commitment_for_subject_client": False,
                "slide_evidence": "",
            },
            {
                "metric": "Illustrative machine OEE",
                "value": "59.5%",
                "attributed_client": "Không xác định; ví dụ minh họa máy CNC",
                "is_commitment_for_subject_client": False,
                "slide_evidence": "",
            },
        ],
    }
]


def test_case_study_kpi_is_attributed_to_the_real_client_not_the_deck_subject() -> None:
    nodes, edges = kt.transform_kpi_extract(_CMC_STYLE_EXTRACT, {"Demo RPA Deck": "opp:demo-rpa"})
    eximbank_kpi = next(n for n in nodes if n["label"] == "Manual volume automated")
    attributed = [e for e in edges if e["src"] == eximbank_kpi["id"] and e["rel"] == "ATTRIBUTED_TO"]
    assert attributed == [
        {"src": eximbank_kpi["id"], "rel": "ATTRIBUTED_TO", "dst": "client:eximbank", "props": {}}
    ]
    assert eximbank_kpi["props"]["is_commitment_for_subject_client"] is False


def test_bnk_self_reference_is_not_a_client_node() -> None:
    """A KPI 'attributed to BnK Solution' describes BnK's own capability, not a
    client outcome — must not mint a pseudo-Client node."""
    nodes, edges = kt.transform_kpi_extract(_CMC_STYLE_EXTRACT, {"Demo RPA Deck": "opp:demo-rpa"})
    capacity_kpi = next(n for n in nodes if n["label"] == "Team delivery capacity")
    assert not [e for e in edges if e["src"] == capacity_kpi["id"] and e["rel"] == "ATTRIBUTED_TO"]


def test_unidentified_example_gets_no_attribution_edge() -> None:
    nodes, edges = kt.transform_kpi_extract(_CMC_STYLE_EXTRACT, {"Demo RPA Deck": "opp:demo-rpa"})
    illustrative_kpi = next(n for n in nodes if n["label"] == "Illustrative machine OEE")
    assert not [e for e in edges if e["src"] == illustrative_kpi["id"] and e["rel"] == "ATTRIBUTED_TO"]


def test_every_kpi_gets_a_claims_edge_from_its_deck_opportunity() -> None:
    _nodes, edges = kt.transform_kpi_extract(_CMC_STYLE_EXTRACT, {"Demo RPA Deck": "opp:demo-rpa"})
    claims = [e for e in edges if e["rel"] == "CLAIMS_KPI" and e["src"] == "opp:demo-rpa"]
    assert len(claims) == 4  # all four KPIs, regardless of attribution outcome


def test_kpi_from_unmatched_folder_still_creates_a_node_no_claims_edge() -> None:
    """A folder with no surviving Opportunity (capability decks with no single
    client) must not silently lose its extracted KPI facts — conventions §4."""
    nodes, edges = kt.transform_kpi_extract(_CMC_STYLE_EXTRACT, {})  # no folder->opportunity mapping at all
    kpi_nodes = [n for n in nodes if n["type"] == "Kpi"]
    assert len(kpi_nodes) == 4
    assert not [e for e in edges if e["rel"] == "CLAIMS_KPI"]


def test_kpi_facet_flows_through_build_graph_and_survives_dedupe() -> None:
    """KPIs extracted from a folder that gets merged away by dedupe_entries
    (space-vs-underscore duplicate) must still attach to the surviving
    Opportunity — the folder->id map has to include merged-away folders."""
    a = {**_ENTRY, "folder": "Demo RPA Deck 1", "slug": "same-slug", "tech": []}
    b = {**_ENTRY, "folder": "Demo RPA Deck_1", "slug": "same-slug", "tech": ["UiPath"]}
    kpi_extract = [
        {
            "folder": "Demo RPA Deck 1",  # the folder that WON'T survive dedupe (less tech)
            "deck_subject_client": "Acme",
            "kpis": [
                {
                    "metric": "Accuracy",
                    "value": "99%",
                    "attributed_client": "Acme",
                    "is_commitment_for_subject_client": True,
                    "slide_evidence": "",
                }
            ],
        }
    ]
    nodes, edges = kt.build_graph([a, b], {}, min_tech_project_count=1, kpi_extract=kpi_extract)
    survivor_id = "opp:same-slug"
    assert survivor_id in {n["id"] for n in nodes}
    claims = [e for e in edges if e["rel"] == "CLAIMS_KPI"]
    assert claims and claims[0]["src"] == survivor_id


def test_identical_kpi_from_both_duplicate_deck_exports_collapses_to_one_node() -> None:
    """Real corpus case (2026-08-08): 'Protenlindo Proposal_Update-2 2' and
    '..._2_2' are the same deck exported twice — extract_kpis.py produces a
    near-identical KPI list for each, independently, since it processes every
    analysis.md file on its own. Two DIFFERENT raw folder names used to
    collide on kpi_id's old folder-based scheme (both normalize to the same
    key), crashing the Postgres load with a duplicate primary key. The fix:
    content-addressed ids mean identical KPI facts from both folders now
    deliberately produce the SAME node — one Kpi, evidenced twice."""
    a = {**_ENTRY, "folder": "Protenlindo Proposal_Update-2 2", "slug": "same-slug", "tech": []}
    b = {**_ENTRY, "folder": "Protenlindo Proposal_Update-2_2", "slug": "same-slug", "tech": ["UiPath"]}
    same_kpi = {
        "metric": "Image processing time",
        "value": "3s",
        "attributed_client": "Protenlindo",
        "is_commitment_for_subject_client": True,
        "slide_evidence": "",
    }
    kpi_extract = [
        {
            "folder": "Protenlindo Proposal_Update-2 2",
            "deck_subject_client": "Protenlindo",
            "kpis": [same_kpi],
        },
        {
            "folder": "Protenlindo Proposal_Update-2_2",
            "deck_subject_client": "Protenlindo",
            "kpis": [same_kpi],
        },
    ]
    nodes, edges = kt.build_graph([a, b], {}, min_tech_project_count=1, kpi_extract=kpi_extract)
    kpi_nodes = [n for n in nodes if n["type"] == "Kpi"]
    assert len(kpi_nodes) == 1  # collapsed, not a Postgres primary-key collision
    claims = [e for e in edges if e["rel"] == "CLAIMS_KPI"]
    assert len(claims) == 2  # both source folders still evidenced, as two edges to the one node
    assert {c["props"]["evidence"] for c in claims} == {
        "Protenlindo Proposal_Update-2 2",
        "Protenlindo Proposal_Update-2_2",
    }


def test_no_kpi_extract_leaves_graph_unchanged() -> None:
    with_none = kt.build_graph([_ENTRY], {}, min_tech_project_count=1, kpi_extract=None)
    with_empty = kt.build_graph([_ENTRY], {}, min_tech_project_count=1, kpi_extract=[])
    assert {n["id"] for n in with_none[0]} == {n["id"] for n in with_empty[0]}
    assert not any(n["type"] == "Kpi" for n in with_none[0])


def test_kpi_attributed_client_gets_a_real_node_not_a_dangling_edge() -> None:
    """Real bug found loading the full corpus (2026-08-08): kpi_edges used to
    emit an ATTRIBUTED_TO edge to client_id(attributed) without ensuring that
    id had a node. Postgres has no FK constraint on kg_edges.dst, so the load
    "succeeded" with 477 dangling edges; Neo4j's directed MATCH silently
    skipped every one with no node to match, loading only 217 — same edge
    list, two different counts, which is what surfaced this."""
    entry = {**_ENTRY, "wbs_match": None}
    kpi_extract = [
        {
            "folder": "Demo RPA Deck",
            "deck_subject_client": "Acme Corp",
            "kpis": [
                {
                    "metric": "Accuracy",
                    "value": "99%",
                    "attributed_client": "Globex Corp",  # a client mentioned ONLY here, nowhere else
                    "is_commitment_for_subject_client": False,
                    "slide_evidence": "",
                }
            ],
        }
    ]
    nodes, edges = kt.build_graph([entry], {}, min_tech_project_count=1, kpi_extract=kpi_extract)
    node_ids = {n["id"] for n in nodes}
    attributed_edge = next(e for e in edges if e["rel"] == "ATTRIBUTED_TO")
    assert attributed_edge["dst"] in node_ids  # the edge target must actually exist as a node


def test_kpi_attributed_to_an_existing_opportunity_client_does_not_duplicate_it() -> None:
    """The reverse collision: a KPI attributed to a client who is ALSO some
    other deck's own subject client mints the same client:* id from both
    opportunity_client_nodes() and transform_kpi_extract() independently —
    build_graph's final id-dedup pass must collapse it to one node."""
    entry = {**_ENTRY, "client": "Globex Corp", "wbs_match": None}
    kpi_extract = [
        {
            "folder": "Demo RPA Deck",
            "deck_subject_client": "Someone Else",
            "kpis": [
                {
                    "metric": "Accuracy",
                    "value": "99%",
                    "attributed_client": "Globex Corp",  # same client as entry's own `client` field
                    "is_commitment_for_subject_client": False,
                    "slide_evidence": "",
                }
            ],
        }
    ]
    nodes, _edges = kt.build_graph([entry], {}, min_tech_project_count=1, kpi_extract=kpi_extract)
    globex_id = kt.client_id("Globex Corp")
    matching = [n for n in nodes if n["id"] == globex_id]
    assert len(matching) == 1  # not two colliding nodes with the same id
