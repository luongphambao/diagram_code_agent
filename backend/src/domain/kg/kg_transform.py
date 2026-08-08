"""Pure transforms from the two BnK corpora into a property graph.

Input is already-parsed data — ``backend/data/solution_memory.json`` entries and
raw ``DATA/SOLUTION_WBS/*.json`` payloads — not files. Nothing here touches disk
or a database, so it is testable without a corpus or a running Postgres (see
conventions §1: ``domain/*`` must test without an LLM or HTTP).

Output shape is a minimal property graph, chosen deliberately over a typed
Python model per node type: the storage layer (:mod:`rag.kg_store`) is two
generic tables (``kg_nodes``, ``kg_edges``), and every consumer — the Postgres
loader, the ``nodes.jsonl``/``edges.jsonl`` export, a future Neo4j load — wants
the same shape::

    Node = {"id": str, "type": str, "label": str, "props": dict}
    Edge = {"src": str, "rel": str, "dst": str, "props": dict}

``id`` is a stable, content-derived string (never a random UUID) so re-running
the build twice produces the same graph — required for the loader's upsert to
be idempotent and for git-diffing ``nodes.jsonl`` across a corpus refresh to be
readable.

Facets covered (each a node type + the edges that connect it):
  Opportunity · Client · Domain (industry / solution_type axis) · Technology ·
  WbsProject · WbsTask · Role · Phase · FeatureModule · Kpi

Kpi is the one facet NOT derived from already-parsed data: it comes from
``backend/scripts/extract_kpis.py``, a separate LLM pass over the raw
``analysis.md`` text (see that script's docstring for why — the corpus
repeatedly warns that KPI numbers in a proposal are often *another client's*
case-study figures copied in for illustration, which no regex can
disambiguate). This module only consumes that pass's already-attributed
output (``kpi_extract.json``); it does not call an LLM itself, keeping the
"testable without an LLM" property for everything else in this file.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, TypedDict

import kg_vocab as kv


class Node(TypedDict):
    id: str
    type: str
    label: str
    props: dict[str, Any]


class Edge(TypedDict):
    src: str
    rel: str
    dst: str
    props: dict[str, Any]


def _node(node_id: str, node_type: str, label: str, **props: Any) -> Node:
    return {"id": node_id, "type": node_type, "label": label, "props": props}


def _edge(src: str, rel: str, dst: str, **props: Any) -> Edge:
    return {"src": src, "rel": rel, "dst": dst, "props": props}


# ════════════════════════════════════════════════════════════════════════════
# Client
# ════════════════════════════════════════════════════════════════════════════
# Client names in solution_memory carry parenthetical context in the source
# language — "Trần Đức Group (nhà sản xuất nội thất khách sạn cao cấp, Việt
# Nam)" — which is real information (industry, geography) but not part of the
# identity. Split it off into a prop rather than lose it or let it fragment
# identity (two mentions of the same client with different parentheticals must
# resolve to one node).


def client_id(raw_name: str) -> str | None:
    """Stable id for a client name, or None if the source had no client at all
    (~44% of decks — do not mint a placeholder node for "no client")."""
    name = kv.clean_text(raw_name or "")
    if not name:
        return None
    head = name.split("(", 1)[0].strip()
    key = kv.normalize_key(head)
    return f"client:{key}" if key else None


def client_node(raw_name: str) -> Node | None:
    cid = client_id(raw_name)
    if cid is None:
        return None
    name = kv.clean_text(raw_name)
    head, _, paren = name.partition("(")
    context = paren.rstrip(")").strip() if paren else ""
    return _node(cid, "Client", head.strip(), context=context)


# ════════════════════════════════════════════════════════════════════════════
# Domain — one input field, two axes
# ════════════════════════════════════════════════════════════════════════════
# `solution_memory[*].domain` is a single flat tag list (from
# build_case_library.py's `_DOMAIN_KEYWORDS`) that mixes what industry the
# client is in with what kind of solution BnK built. Mixed, the tag is nearly
# useless for filtering ("ai-ml" fires on 100/116 entries because the keyword
# list includes bare "ai"). Split by a fixed table instead of re-deriving from
# text — the keyword-matching already happened upstream; this only sorts its
# output.

DOMAIN_AXIS: dict[str, str] = {
    "banking": "industry",
    "insurance": "industry",
    "agriculture": "industry",
    "manufacturing": "industry",
    "logistics": "industry",
    "healthcare": "industry",
    "retail": "industry",
    "document-ai": "solution_type",
    "data-platform": "solution_type",
    "ai-ml": "solution_type",
}


def domain_id(tag: str) -> str:
    return f"domain:{kv.normalize_key(tag)}"


def domain_node(tag: str) -> Node:
    axis = DOMAIN_AXIS.get(tag, "unknown")
    return _node(domain_id(tag), "Domain", tag, axis=axis)


# ════════════════════════════════════════════════════════════════════════════
# Technology
# ════════════════════════════════════════════════════════════════════════════
# 944 distinct raw tech strings across the corpus, 810 of them (86%) singletons
# — see [[kg-project-2026-08-08]]. Hand-aliasing that tail is not worth the
# effort (the plan is to resolve against CSO/Wikidata/CPE later); what this
# module does now is refuse to mint a node for anything that never recurs, so
# a one-off OCR artifact or overly-specific phrase doesn't become a permanent
# dead node. `min_project_count` defaults to kv.TECH_MIN_PROJECT_COUNT and is a
# parameter so tests can exercise the filter at a smaller threshold.


def tech_id(raw: str) -> str:
    return f"tech:{kv.normalize_key(raw)}"


def count_technologies(raw_tech_by_source: dict[str, list[str]]) -> Counter[str]:
    """How many distinct sources (opportunities/projects) mention each
    technology. Keyed by :func:`tech_id` so spelling variants that fold to the
    same key are counted once per source, not once per mention."""
    counts: Counter[str] = Counter()
    for _source, techs in raw_tech_by_source.items():
        seen_this_source: set[str] = set()
        for raw in techs:
            if not kv.is_technology(raw):
                continue
            tid = tech_id(raw)
            if tid not in seen_this_source:
                seen_this_source.add(tid)
                counts[tid] += 1
    return counts


def technology_nodes(
    raw_tech_by_source: dict[str, list[str]],
    *,
    min_project_count: int = kv.TECH_MIN_PROJECT_COUNT,
) -> dict[str, Node]:
    """One Technology node per id that clears the recurrence threshold, keyed by
    :func:`tech_id`. The node's ``label`` is the most common raw spelling."""
    counts = count_technologies(raw_tech_by_source)
    label_votes: dict[str, Counter[str]] = {}
    for techs in raw_tech_by_source.values():
        for raw in techs:
            if not kv.is_technology(raw):
                continue
            tid = tech_id(raw)
            if counts[tid] >= min_project_count:
                label_votes.setdefault(tid, Counter())[kv.clean_text(raw)] += 1
    return {
        tid: _node(tid, "Technology", votes.most_common(1)[0][0], mention_count=counts[tid])
        for tid, votes in label_votes.items()
    }


# ════════════════════════════════════════════════════════════════════════════
# Opportunity — the graph's root node
# ════════════════════════════════════════════════════════════════════════════
# One Opportunity per solution_memory.json entry. Deliberately NOT deduplicated
# further here (the VN/EN deck pairs and `_1_` variants identified during
# corpus analysis) — solution_memory.json is already one row per source
# folder/WBS-only project with no exact-name collisions observed; folding
# near-duplicate opportunities (same client + overlapping WBS total) is real
# work that needs evidence review, not a heuristic buried in a transform
# function. Tracked as follow-up, not silently done here.
#
# One exact collision DOES get resolved here, though: `_slug()` in
# build_case_library.py truncates to 60 chars and folds non-alphanumerics to
# `-`, so two folders that differ only in a trailing " 1" vs "_1" (observed:
# "CIMB_Proposal_April_2026 1" / "_2026_1", "Protenlindo Proposal_Update-2 2" /
# "-2_2" — both are the space-vs-underscore export-duplicate pattern flagged
# during corpus analysis) hash to the identical slug. That is not an
# accidental id clash to paper over with a suffix; it IS the confirmed-
# duplicate signal — same content, two file exports — so :func:`dedupe_entries`
# merges them into one Opportunity rather than letting the loader crash on a
# primary-key collision or silently keeping whichever happened to sort last.


def opportunity_id(entry: dict) -> str:
    slug = entry.get("slug") or kv.normalize_key(entry.get("folder") or entry.get("title") or "")
    return f"opp:{slug}"


def _richness(entry: dict) -> tuple:
    """Deterministic ranking key for picking the surviving entry out of a
    colliding group — richer content wins, folder name breaks ties so the
    choice doesn't depend on input order (required for build determinism)."""
    wbs_match = entry.get("wbs_match") or {}
    return (
        1 if wbs_match else 0,
        len(entry.get("tech") or []),
        len(entry.get("problem") or "") + len(entry.get("solution") or ""),
        entry.get("folder") or "",
    )


def dedupe_entries(entries: list[dict]) -> list[dict]:
    """Collapse solution_memory entries that resolve to the same
    :func:`opportunity_id`. The dropped entries' folder names are kept on the
    survivor as ``props.merged_from`` rather than discarded (conventions §4:
    no silent drops)."""
    groups: dict[str, list[dict]] = {}
    for entry in entries:
        groups.setdefault(opportunity_id(entry), []).append(entry)

    out: list[dict] = []
    for oid, group in groups.items():
        if len(group) == 1:
            out.append(group[0])
            continue
        group_sorted = sorted(group, key=_richness, reverse=True)
        primary = dict(group_sorted[0])
        primary["_merged_from"] = [e.get("folder") for e in group_sorted[1:]]
        out.append(primary)
    return out


def opportunity_node(entry: dict) -> Node:
    oid = opportunity_id(entry)
    estimate = entry.get("estimate") or {}
    wbs_match = entry.get("wbs_match") or {}
    return _node(
        oid,
        "Opportunity",
        entry.get("title") or entry.get("folder") or oid,
        folder=entry.get("folder"),
        source=entry.get("source", ""),
        type=kv.clean_text(entry.get("type") or "") or None,
        problem=entry.get("problem") or None,
        solution=entry.get("solution") or None,
        outcome=entry.get("outcome") or None,
        image_ref=entry.get("image_ref"),
        effort_md=estimate.get("effort_md") if isinstance(estimate, dict) else None,
        timeline_months=estimate.get("timeline_months") if isinstance(estimate, dict) else None,
        wbs_total_mandays=wbs_match.get("total_mandays") if isinstance(wbs_match, dict) else None,
        merged_from=entry.get("_merged_from") or None,
    )


def opportunity_edges(entry: dict, tech_ids: set[str]) -> list[Edge]:
    """Client / Domain / Technology edges for one Opportunity. ``tech_ids`` is
    the set of ids that :func:`technology_nodes` decided to keep — an
    Opportunity mentioning a below-threshold technology gets no edge for it
    (the mention still lives in the node's raw text, it's just not a graph
    fact)."""
    oid = opportunity_id(entry)
    edges: list[Edge] = []

    cnode = client_node(entry.get("client") or "")
    if cnode is not None:
        edges.append(_edge(oid, "FOR_CLIENT", cnode["id"], evidence=entry.get("folder")))

    for tag in entry.get("domain") or []:
        edges.append(_edge(oid, "IN_DOMAIN", domain_id(tag), axis=DOMAIN_AXIS.get(tag, "unknown")))

    for raw in entry.get("tech") or []:
        if not kv.is_technology(raw):
            continue
        tid = tech_id(raw)
        if tid in tech_ids:
            edges.append(_edge(oid, "USES_TECH", tid, raw_label=kv.clean_text(raw)))

    return edges


def opportunity_client_nodes(entries: list[dict]) -> dict[str, Node]:
    """Deduplicated Client nodes across every entry — a client mentioned in
    three decks must be one node, not three."""
    nodes: dict[str, Node] = {}
    for entry in entries:
        cnode = client_node(entry.get("client") or "")
        if cnode is not None and cnode["id"] not in nodes:
            nodes[cnode["id"]] = cnode
    return nodes


# ════════════════════════════════════════════════════════════════════════════
# WBS project → tasks → role assignments
# ════════════════════════════════════════════════════════════════════════════
# Walks one raw DATA/SOLUTION_WBS/*.json payload. Every task that carries
# resolvable effort becomes a WbsTask node; every resolvable *_md column on it
# becomes an ASSIGNED edge to a Role, carrying the man-days, the estimator
# (bnk/partner — see kg_vocab's oi_md note) and the scenario (baseline/
# original/updated/... — see the cr_original_md / phase2_client_quote_md
# note) as edge properties rather than flattening them away.


def wbs_project_id(file_name: str) -> str:
    return f"wbsproj:{kv.normalize_key(file_name)}"


def wbs_task_id(project_id: str, task: dict, index: int) -> str:
    """``index`` (the task's position in the file's walk order) is always part
    of the id, not just a fallback for a missing ``code``. At least one source
    file (SSV email-sentiment) embeds three sequential estimate revisions in
    one JSON, each restarting the same Roman-numeral / REQ-01 / UAT-01 code
    scheme — ``code`` alone collides across them. Walk order over
    ``json.loads`` output is stable for a given file (dict insertion order is
    preserved), so this stays deterministic across rebuilds without needing
    code uniqueness as a precondition."""
    code = task.get("code") or task.get("id")
    suffix = kv.normalize_key(str(code)) if code else "task"
    return f"{project_id}:task:{index:04d}:{suffix}"


def _walk_tasks(node: Any, out: list[dict]) -> None:
    if isinstance(node, dict):
        keys = set(node)
        if "name" in keys and any(k.lower().endswith("_md") or k.lower() == "md" for k in keys):
            out.append(node)
        for value in node.values():
            _walk_tasks(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk_tasks(value, out)


def _project_technologies(payload: dict) -> list[str]:
    stack = payload.get("technology_stack")
    if isinstance(stack, list):
        return [t for t in stack if isinstance(t, str)]
    if isinstance(stack, dict):
        out: list[str] = []
        for value in stack.values():
            if isinstance(value, str):
                out.append(value)
            elif isinstance(value, list):
                out.extend(v for v in value if isinstance(v, str))
        return out
    return []


def wbs_project_raw_tech(file_name: str, payload: dict) -> tuple[str, list[str]]:
    """``(source_key, technologies)`` pair for feeding into
    :func:`count_technologies` / :func:`technology_nodes` alongside the
    Opportunity-side tech mentions, so a Technology node is shared identity
    regardless of which corpus it was mentioned in."""
    return f"wbs:{file_name}", _project_technologies(payload)


def transform_wbs_project(file_name: str, payload: dict, tech_ids: set[str]) -> tuple[list[Node], list[Edge]]:
    """Everything under one WBS file: the WbsProject node, its WbsTask
    children, ASSIGNED edges to Role, IN_PHASE/IN_MODULE edges, and USES_TECH
    edges for technologies that cleared the recurrence threshold."""
    nodes: list[Node] = []
    edges: list[Edge] = []

    pid = wbs_project_id(file_name)
    project_info = payload.get("project_info") or {}
    effort_totals = payload.get("effort_totals") or {}
    total_md = None
    if isinstance(effort_totals, dict):
        for key in ("total_mandays", "total_md", "grand_total_md", "total"):
            if isinstance(effort_totals.get(key), (int, float)):
                total_md = float(effort_totals[key])
                break

    nodes.append(
        _node(
            pid,
            "WbsProject",
            (project_info.get("name") if isinstance(project_info, dict) else None) or file_name,
            source_file=file_name,
            client=(project_info.get("client") if isinstance(project_info, dict) else None),
            total_mandays=total_md,
        )
    )

    for raw in _project_technologies(payload):
        if not kv.is_technology(raw):
            continue
        tid = tech_id(raw)
        if tid in tech_ids:
            edges.append(_edge(pid, "USES_TECH", tid, raw_label=kv.clean_text(raw)))

    tasks: list[dict] = []
    _walk_tasks(payload, tasks)

    feature_modules: dict[str, Node] = {}

    for i, task in enumerate(tasks):
        name = kv.clean_text(str(task.get("name") or ""))
        if not name:
            continue
        tid_ = wbs_task_id(pid, task, i)

        # -- role assignments: one edge per resolvable *_md column ----------
        assignments: list[tuple[str, float]] = []  # (role, md) with mixed columns split evenly
        role_effort_present = False
        for key, value in task.items():
            low = key.lower()
            if not (low.endswith("_md") or low == "md") or not isinstance(value, (int, float)):
                continue
            field = kv.classify_md_field(key)
            if field is None or field.kind != "role" or not field.roles:
                continue
            role_effort_present = True
            share = float(value) / len(field.roles)
            for role in field.roles:
                assignments.append((role, share))

        if not assignments:
            continue  # a task with no attributable effort isn't worth a node
        nodes.append(_node(tid_, "WbsTask", name, code=task.get("code") or task.get("id")))
        edges.append(_edge(pid, "CONTAINS", tid_))
        for role, md in assignments:
            edges.append(_edge(tid_, "ASSIGNED", f"role:{role}", man_days=round(md, 2), estimator="bnk"))

        # -- phase / feature-module placement --------------------------------
        module_label = task.get("module") or task.get("phase") or task.get("section")
        if isinstance(module_label, str) and module_label.strip():
            phases = kv.resolve_phase(module_label)
            if phases:
                for phase in phases:
                    edges.append(_edge(tid_, "IN_PHASE", f"phase:{phase}"))
            elif not kv.is_structural_module_code(module_label):
                fmid = f"{pid}:module:{kv.normalize_key(module_label)}"
                if fmid not in feature_modules:
                    feature_modules[fmid] = _node(fmid, "FeatureModule", kv.clean_text(module_label))
                edges.append(_edge(tid_, "IN_MODULE", fmid))

        del role_effort_present  # documents intent; unallocated-effort tasks are a follow-up

    nodes.extend(feature_modules.values())
    return nodes, edges


# ════════════════════════════════════════════════════════════════════════════
# Static reference nodes — Role and Phase
# ════════════════════════════════════════════════════════════════════════════


def role_nodes() -> list[Node]:
    return [_node(f"role:{role}", "Role", kv.ROLE_LABELS[role]) for role in kv.ROLES]


def phase_nodes() -> list[Node]:
    return [_node(f"phase:{phase}", "Phase", phase.title()) for phase in kv.PHASES]


# ════════════════════════════════════════════════════════════════════════════
# Kpi — consumes extract_kpis.py's already-attributed output
# ════════════════════════════════════════════════════════════════════════════
# Validated on the corpus's own adversarial case (2026-08-08): the BnK - CMC RPA
# Proposal deck's own text says its KPI table's numbers "không phải cam kết
# KPI riêng cho CMC Telecom" (not a commitment for CMC Telecom) — every row
# belongs to Eximbank/BIDV/Sacombank instead. extract_kpis.py's LLM pass
# reproduced that distinction with 0 misattributions across 36 KPIs on that
# case. This module trusts that pass's ``attributed_client`` field rather than
# re-deriving attribution — same "don't redo strong upstream work" reasoning
# as :func:`opportunity_wbs_edge` trusting solution_memory's WBS join.

#: Phrases the extraction model uses when a KPI genuinely has no identifiable
#: real-world client (a generic/illustrative example, an unlabeled figure) —
#: matched as a substring so free-form LLM phrasing doesn't need an exact list.
_NON_ATTRIBUTION_MARKERS: tuple[str, ...] = (
    "khong xac dinh",
    "khong ro",
    "unidentified",
    "unknown",
    "not stated",
    "vi du minh hoa",
    "illustrative",
    "hypothetical",
    "n/a",
)

#: BnK's own name in various spellings — a KPI "attributed to BnK Solution"
#: describes BnK's capability, not a client's outcome, and must not become a
#: pseudo-Client node (that would let a self-reference silently pass as
#: attributed evidence in a similar-projects query).
_SELF_REFERENCE_KEYS: frozenset[str] = frozenset({"bnk", "bnksolution", "brilliantandkool"})


def is_attributable_client(raw: str) -> bool:
    """False for empty/self-referential/non-identified attribution strings —
    the cases where minting a Client node would be worse than no edge."""
    text = kv.strip_accents(kv.clean_text(raw or "")).lower()
    if not text or any(marker in text for marker in _NON_ATTRIBUTION_MARKERS):
        return False
    cid = client_id(raw)
    if cid is None:
        return False
    return cid.removeprefix("client:") not in _SELF_REFERENCE_KEYS


def kpi_id(folder: str, index: int, metric: str) -> str:
    return f"kpi:{kv.normalize_key(folder)}:{index:03d}:{kv.normalize_key(metric)[:24]}"


def kpi_node(folder: str, index: int, kpi: dict) -> Node:
    metric = kv.clean_text(str(kpi.get("metric") or ""))
    return _node(
        kpi_id(folder, index, metric),
        "Kpi",
        metric or f"KPI {index}",
        value=kpi.get("value"),
        attributed_client_raw=kpi.get("attributed_client"),
        is_commitment_for_subject_client=bool(kpi.get("is_commitment_for_subject_client")),
        slide_evidence=kpi.get("slide_evidence") or None,
        source_folder=folder,
    )


def kpi_edges(folder: str, opportunity_id_: str | None, index: int, kpi: dict) -> list[Edge]:
    """``CLAIMS_KPI`` from the Opportunity this deck belongs to (if any — a
    handful of analysis.md folders don't survive into solution_memory.json's
    Opportunity set, e.g. capability decks with no single client; the Kpi node
    still gets created, just without that edge, per conventions §4 — no
    silent drop of the extracted fact itself, only of the missing link).
    ``ATTRIBUTED_TO`` the real client the number is about, when identifiable.
    """
    metric = kv.clean_text(str(kpi.get("metric") or ""))
    kid = kpi_id(folder, index, metric)
    edges: list[Edge] = []
    if opportunity_id_ is not None:
        edges.append(_edge(opportunity_id_, "CLAIMS_KPI", kid, evidence=folder))
    attributed = kpi.get("attributed_client") or ""
    if is_attributable_client(attributed):
        cid = client_id(attributed)
        if cid is not None:
            edges.append(_edge(kid, "ATTRIBUTED_TO", cid))
    return edges


def transform_kpi_extract(
    kpi_extract: list[dict],
    opportunity_id_by_folder: dict[str, str],
) -> tuple[list[Node], list[Edge]]:
    """Everything from ``extract_kpis.py``'s output: one Kpi node + edges per
    extracted fact, across every deck in the extraction file."""
    nodes: list[Node] = []
    edges: list[Edge] = []
    for entry in kpi_extract:
        folder = entry.get("folder") or ""
        opp_id = opportunity_id_by_folder.get(folder)
        for i, kpi in enumerate(entry.get("kpis") or []):
            nodes.append(kpi_node(folder, i, kpi))
            edges.extend(kpi_edges(folder, opp_id, i, kpi))
    return nodes, edges


# ════════════════════════════════════════════════════════════════════════════
# Opportunity ↔ WbsProject join
# ════════════════════════════════════════════════════════════════════════════
# solution_memory.json already carries a confirmed join for every entry with
# source in {"wbs_only", "narrative+wbs"}: `wbs_match.source_file`. That join
# was made with an LLM read of the actual narrative text against WBS
# candidates (build_solution_memory.py), which is stronger evidence than
# re-deriving it from filenames here — so this function only *uses* the
# existing join, it does not attempt a new one.


def opportunity_wbs_edge(entry: dict) -> Edge | None:
    wbs_match = entry.get("wbs_match")
    if not isinstance(wbs_match, dict):
        return None
    source_file = wbs_match.get("source_file")
    if not source_file:
        return None
    return _edge(
        opportunity_id(entry),
        "HAS_WBS",
        wbs_project_id(source_file),
        reasoning=entry.get("wbs_join_reasoning"),
    )


# ════════════════════════════════════════════════════════════════════════════
# Top-level orchestration
# ════════════════════════════════════════════════════════════════════════════


def build_graph(
    solution_memory: list[dict],
    wbs_payloads: dict[str, dict],
    *,
    min_tech_project_count: int = kv.TECH_MIN_PROJECT_COUNT,
    kpi_extract: list[dict] | None = None,
) -> tuple[list[Node], list[Edge]]:
    """Assemble the full graph from already-loaded corpus data.

    ``wbs_payloads`` is ``{file_name: parsed_json}`` for every file under
    ``DATA/SOLUTION_WBS`` — including ones with no Opportunity match, which
    still become standalone WbsProject nodes rather than being dropped.

    ``kpi_extract`` is ``extract_kpis.py``'s output (one entry per
    analysis.md, already carrying per-KPI client attribution) — optional
    because that LLM pass is a separate, explicitly-opted-into step; omitting
    it builds every other facet unchanged.
    """
    solution_memory = dedupe_entries(solution_memory)

    nodes: list[Node] = [*role_nodes(), *phase_nodes()]
    edges: list[Edge] = []

    # -- technology recurrence must be computed across BOTH corpora first, so
    #    a tech mentioned twice split across a deck and a WBS file still
    #    clears the threshold as one identity. ---------------------------------
    raw_tech_by_source: dict[str, list[str]] = {}
    for entry in solution_memory:
        raw_tech_by_source[f"opp:{entry.get('slug', '')}"] = entry.get("tech") or []
    for file_name, payload in wbs_payloads.items():
        source_key, techs = wbs_project_raw_tech(file_name, payload)
        raw_tech_by_source[source_key] = techs
    tech_nodes = technology_nodes(raw_tech_by_source, min_project_count=min_tech_project_count)
    tech_ids = set(tech_nodes)
    nodes.extend(tech_nodes.values())

    # -- Opportunity + Client + Domain ---------------------------------------
    client_nodes = opportunity_client_nodes(solution_memory)
    nodes.extend(client_nodes.values())

    domain_tags: set[str] = set()
    for entry in solution_memory:
        nodes.append(opportunity_node(entry))
        edges.extend(opportunity_edges(entry, tech_ids))
        domain_tags.update(entry.get("domain") or [])
        wbs_edge = opportunity_wbs_edge(entry)
        if wbs_edge is not None:
            edges.append(wbs_edge)
    nodes.extend(domain_node(tag) for tag in sorted(domain_tags))

    # -- every WBS file becomes a project, joined or not ----------------------
    for file_name, payload in wbs_payloads.items():
        wbs_nodes, wbs_edges = transform_wbs_project(file_name, payload, tech_ids)
        nodes.extend(wbs_nodes)
        edges.extend(wbs_edges)

    # -- Kpi facet, if an extraction pass was supplied -------------------------
    if kpi_extract:
        opp_id_by_folder: dict[str, str] = {}
        for entry in solution_memory:
            oid = opportunity_id(entry)
            opp_id_by_folder[entry.get("folder") or ""] = oid
            for merged_folder in entry.get("_merged_from") or []:
                opp_id_by_folder[merged_folder] = oid
        kpi_nodes, kpi_edges_ = transform_kpi_extract(kpi_extract, opp_id_by_folder)
        nodes.extend(kpi_nodes)
        edges.extend(kpi_edges_)

    return nodes, edges
