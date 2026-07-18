"""Auto-topology builder — turns a declarative render_spec into a native tree.

This is the NET-NEW component the kit lacks: the kit makes the LLM hand-author
the group/frame tree, whereas we already produce ``render_spec.json`` (nodes +
nested clusters + edges + pattern) from ``propose_blueprint``. Here we infer the
group/frame/icon tree from that spec, then hand it to the layout engine.

Input schema (subset of render_spec.json):
  nodes:    {id, label, tech, cluster, type}
  clusters: {id, label, tier, parent, accent, number}
  edges:    {from, to, label, protocol, flow, style}
  top-level: provider, pattern, layout_intent, slide_title, diagram_title
"""

from __future__ import annotations

import re

from .layout_engine import (group, frame, grid, icon, box, card, phantom,
                            zone_frame, render_tree, pool)
from .builder import Diagram
from .theme import THEME, stage_fill, stage_stroke
from . import bpmn as _bpmn

try:
    from ..drawio_catalog import (load_catalog as _load_catalog,
                                  search_icon as _search_icon, get_icon as _get_icon,
                                  expand_tokens as _expand_tokens)
    from ..graph_builder import _aws_group_for_label
    from ..constants import PRO_ACCENTS, FLOW_COLORS
except (ImportError, ValueError):  # pragma: no cover - import fallback
    from domain.diagram.drawio_catalog import (load_catalog as _load_catalog,  # type: ignore
                                search_icon as _search_icon, get_icon as _get_icon,
                                expand_tokens as _expand_tokens)
    from prettygraph.graph_builder import _aws_group_for_label  # type: ignore
    from prettygraph.constants import PRO_ACCENTS, FLOW_COLORS  # type: ignore

_NEUTRAL_STROKE = "#8593A3"
# Card width bands per density class (V2 §5.3): (min_w, max_w).
_SIZE_CLASSES = {"compact": (150, 210), "medium": (176, 272), "wide": (240, 420)}
# Reserved routing lane between stacked layer bands (V2 §7.6): whitespace the
# router uses as connector infrastructure rather than incidental spacing.
_LAYER_LANE_GAP = 46
# A 2-column grid of bands is available ONLY via explicit layout_intent="grid" —
# NOT auto-applied by band count. Tried auto-triggering above a band-count
# threshold; the router (built for a single top-to-bottom channel) routes
# cross-band edges far messier once bands sit in a 2-D grid instead of one
# column (real regression seen on a 7-band spec: long diagonal edges crossing
# unrelated bands). Auto mode also stretches every band to the tallest cell in
# its row/column (grid()'s uniform-cell model), wasting space on small bands.
# Until the router is grid-aware, only an explicit, deliberate request should
# opt into this.
_ICON_SCORE_MIN = 50  # top-hit score to accept a stencil for a node (else a plain card)
# The bare "AWS icon + label below" convention doesn't wrap its label (no
# whiteSpace=wrap in the catalog style, see drawio_catalog.style_for_icon) and
# layout_engine._m_icon only reserves up to 200px of spacing for it — a longer
# single line renders past that reserved gap and overlaps the neighboring node.
# Past this length (per line, after any \n split), fall back to card() instead,
# whose wrapping/sizing is already correct.
_ICON_LABEL_MAX = 24
# Vendor-pack (gcp_*/azure_*) hits score lower than they deserve: their names
# embed the provider prefix, which the query never contains. Accept them at a
# lower score — but only when every significant query token appears in the name.
_ICON_SCORE_VENDOR = 28
# Vendor / filler words that dilute a stencil search ("AWS Lambda" -> "lambda").
_VENDOR_WORDS = {"aws", "amazon", "azure", "gcp", "google", "microsoft", "cloud",
                 "apache", "the", "a", "for", "service", "services", "managed"}
# Role words too generic to identify a product on their own: a hit that matches
# ONLY these is a wrong-icon risk ("Fund Management Service" must not resolve to
# key_management_service on management+service alone).
_GENERIC_TOKENS = {"service", "services", "management", "server", "data",
                   "application", "system", "platform", "engine", "store",
                   "manager", "gateway", "simple"}

# name prefix per provider in the merged catalog (gcp.json / azure.json packs).
_PROVIDER_PREFIX = {"gcp": "gcp_", "google": "gcp_",
                    "azure": "azure_", "microsoft": "azure_"}
# aws4 stencils that are provider-NEUTRAL (safe inside a GCP/Azure diagram);
# every other mxgraph.aws4 icon is AWS-branded and must not leak cross-vendor.
_GENERIC_AWS_OK = re.compile(
    r"^(generic_|traditional_server$|corporate_data_center$|users?$|client$"
    r"|mobile_client$|internet(_alt[12])?$|office_building$|servers?$|globe$)")

# Top-level clusters matching this are CROSS-CUTTING concerns: rendered as the
# neutral grey sidebar column (the "Management, Security & CI/CD" lane) instead
# of a tinted pipeline layer band.
_CROSS_CUT = re.compile(
    r"security|secret|iam\b|identity|ci\s*/?\s*cd|cicd|management|observab"
    r"|monitor|logging|governance|devops|compliance|audit", re.IGNORECASE)

# Corner-logo for NON-AWS container frames (the "AWS look" — a framed group with a
# logo in the corner — but the logo is swappable per provider/on-prem). Keyword in
# the cluster label/tier → a ground-truth catalog icon name (all verified to exist).
# Most specific first. A cluster may override via an explicit `icon` field.
_CONTAINER_LOGO: tuple[tuple[str, str], ...] = (
    ("corporate data center", "corporate_data_center"),
    ("data center", "corporate_data_center"),
    ("datacenter", "corporate_data_center"),
    ("on-prem", "corporate_data_center"),
    ("on prem", "corporate_data_center"),
    ("onprem", "corporate_data_center"),
    ("kubernetes", "kubernetes"),
    ("k8s", "kubernetes"),
    ("container", "kubernetes"),
    ("firewall", "generic_firewall"),
    ("security", "generic_firewall"),
    ("network", "generic_firewall"),
    ("database", "generic_database"),
    ("data store", "generic_database"),
    ("storage", "generic_database"),
    ("data", "generic_database"),
    ("gpu", "traditional_server"),
    ("compute", "traditional_server"),
    ("infra", "traditional_server"),
    ("server", "traditional_server"),
)


def _container_logo(cat, cluster: dict) -> str | None:
    """Pick a corner-logo icon name for a non-AWS container frame (or None).

    Priority: an explicit `cluster["icon"]` → keyword match on label/tier. Only
    returns a name that actually exists in the catalog (so corner_icon never fails).
    """
    candidate = cluster.get("icon")
    if not candidate:
        text = f" {(cluster.get('label') or '').lower()} {(cluster.get('tier') or '').lower()} "
        for kw, logo in _CONTAINER_LOGO:
            if kw in text:
                candidate = logo
                break
    if candidate and cat and _get_icon and _get_icon(cat, candidate):
        return candidate
    return None


def _accent_stroke(accent: str | None) -> str:
    if accent and accent in PRO_ACCENTS:
        return PRO_ACCENTS[accent][1]
    return _NEUTRAL_STROKE


def _flow_color(flow: str | None) -> str | None:
    if flow and flow in FLOW_COLORS:
        return FLOW_COLORS[flow][0]
    return None


def _clean_query(q: str, provider: str = "aws") -> str:
    """Drop vendor/filler words so "AWS Lambda" -> "lambda", "Amazon RDS" -> "rds".

    For GCP, "cloud" is part of the product identity ("Cloud Run", "Cloud Tasks")
    — stripping it would leave queries too generic to hit the gcp_* pack."""
    drop = set(_VENDOR_WORDS)
    if _PROVIDER_PREFIX.get(provider) == "gcp_":
        drop.discard("cloud")
    toks = [t for t in re.split(r"[^a-z0-9]+", (q or "").lower())
            if t and t not in drop]
    return " ".join(toks)


def _node_provider(node: dict, default: str) -> str:
    """Per-node provider: the node's own text wins over the diagram default
    (a migration diagram may mix e.g. one Amazon S3 node into a GCP target)."""
    text = f" {node.get('tech') or ''} {node.get('label') or ''} ".lower()
    if re.search(r"\b(aws|amazon)\b", text):
        return "aws"
    if re.search(r"\b(azure|microsoft)\b", text):
        return "azure"
    if re.search(r"\b(gcp|google)\b", text):
        return "gcp"
    return default


def _sig_tokens(query: str) -> tuple[list[str], list[str]]:
    """(significant, significant-and-non-generic) query tokens, abbreviation-
    expanded so "AWS KMS" carries key/management/service like the catalog names."""
    sig = [t for t in re.split(r"[^a-z0-9]+", query.lower())
           if t and t not in _VENDOR_WORDS]
    sig = _expand_tokens(sig)
    return sig, [t for t in sig if t not in _GENERIC_TOKENS]


def _pick_hit(hits: list[dict], prefix: str | None, query: str) -> str | None:
    """Choose the best catalog hit while keeping vendor identity honest:
    provider-prefixed packs first, then provider-neutral icons — never another
    vendor's branded icon. A hit must share at least one NON-GENERIC significant
    token with the query (when the query has any): ranked-score alone lets
    filler words carry a wrong icon, e.g. "Fund Management Service" scoring
    into key_management_service purely on management+service."""
    sig, sig_ng = _sig_tokens(query)
    if prefix:  # gcp/azure diagram node
        for h in hits:
            if not h["name"].startswith(prefix):
                continue
            if h.get("score", 0) < _ICON_SCORE_VENDOR:
                break  # hits are ranked — nothing better follows
            compact = h["name"].replace("_", "")
            hit = lambda t, _c=compact: t in _c or (len(t) >= 5 and t[:5] in _c)
            if h.get("score", 0) >= _ICON_SCORE_MIN:
                # strong hit — trust the ranker, but demand at least one
                # significant token (non-generic when the query has one) so
                # filler words alone can't match.
                check = sig_ng or sig
                if not check or any(hit(t) for t in check):
                    return h["name"]
                continue
            # weak hit: EVERY significant token must appear (5-char stems allow
            # morphology like balancer/balancing).
            if sig and all(hit(t) for t in sig):
                return h["name"]
        for h in hits:
            if h.get("score", 0) < _ICON_SCORE_MIN:
                break
            if h["name"].startswith(("gcp_", "azure_")):
                continue  # the other vendor's pack (own-prefix handled above)
            if ("mxgraph.aws4" in (h.get("style") or "")
                    and not _GENERIC_AWS_OK.match(h["name"])):
                continue  # AWS-branded stencil in a non-AWS diagram
            compact = h["name"].replace("_", "")
            hit = lambda t, _c=compact: t in _c or (len(t) >= 5 and t[:5] in _c)
            if sig_ng and not any(hit(t) for t in sig_ng):
                continue
            return h["name"]
        return None
    for h in hits:  # aws / on-prem: skip the gcp_/azure_ image packs
        if h.get("score", 0) < _ICON_SCORE_MIN:
            break
        if h["name"].startswith(("gcp_", "azure_")):
            continue
        compact = h["name"].replace("_", "")
        hit = lambda t, _c=compact: t in _c or (len(t) >= 5 and t[:5] in _c)
        if sig_ng and not any(hit(t) for t in sig_ng):
            continue  # ranked high on generic words only — wrong-icon risk
        return h["name"]
    return None


def _resolve_node_icon(cat, node: dict, provider: str = "aws") -> str | None:
    """Best ground-truth stencil name for a node (by tech, then label), or None."""
    if not (cat and _search_icon):
        return None
    prov = _node_provider(node, provider)
    prefix = _PROVIDER_PREFIX.get(prov)
    for raw in (node.get("tech"), node.get("label")):
        if not raw:
            continue
        cleaned = _clean_query(raw, prov)
        # last resort: the first two significant words ("Pub/Sub Commands" ->
        # "pub sub") so role qualifiers don't hide the product name.
        head = " ".join(cleaned.split(" ")[:2])
        # abbreviation rescue LAST: "aws kms" carries no catalog words, so the
        # expanded form ("kms key management service") is tried only after the
        # literal queries miss — expanding up front dilutes exact short names
        # ("waf") under verbose partial matches.
        expanded = " ".join(_expand_tokens(cleaned.split(" "))) if cleaned else ""
        queries = dict.fromkeys((cleaned, raw, head,
                                 expanded if expanded != cleaned else ""))
        for query in queries:  # de-duped, in order
            if not query:
                continue
            hits = _search_icon(cat, query, limit=8, kind="icon")
            name = _pick_hit(hits, prefix, query)
            if name:
                return name
    return None


def _node_label(node: dict) -> str:
    tech = (node.get("tech") or "").strip()
    label = (node.get("label") or node.get("id") or "").strip()
    if not tech:
        return label
    if not label:
        return tech
    # avoid redundant "CloudFront\nAmazon CloudFront" when one contains the other
    if label.lower() in tech.lower():
        return tech
    if tech.lower() in label.lower():
        return label
    return f"{label}\n{tech}"


def _card_texts(node: dict) -> tuple[str, str]:
    """(title, sub) for a card node — sub only when tech adds information."""
    label = (node.get("label") or node.get("id") or "").strip()
    tech = (node.get("tech") or "").strip()
    if not label:
        return tech, ""
    if not tech or tech.lower() == label.lower():
        return label, ""
    if label.lower() in tech.lower():
        return tech, ""
    if tech.lower() in label.lower():
        return label, ""
    return label, tech


def _band_tint(c: dict, i: int) -> tuple[str, str]:
    """(fill, stroke) for a top-level layer band: cross-cutting -> neutral grey,
    an explicit accent -> its pale tint, else the cycling stage palette."""
    text = f"{c.get('label') or ''} {c.get('tier') or ''}"
    if _CROSS_CUT.search(text):
        return THEME.band, THEME.band_stroke
    accent = c.get("accent")
    if accent in PRO_ACCENTS:
        return PRO_ACCENTS[accent][0], PRO_ACCENTS[accent][1]
    return stage_fill(i), stage_stroke(i)


# step.kind -> prettygraph.native.bpmn creator. Kinds taking a "type" subtype
# (start/intermediate/end/gateway) pass it through; typed tasks/plain
# task/sub_process ignore "type" (their creators take no type kwarg).
_BPMN_CREATORS = {
    "start": lambda s: _bpmn.start(s["id"], type=s.get("type") or "none",
                                   lane=s.get("lane", 0), col=s.get("col", 0),
                                   label=s.get("label", "")),
    "intermediate": lambda s: _bpmn.intermediate(s["id"], type=s.get("type") or "message",
                                                 lane=s.get("lane", 0), col=s.get("col", 0),
                                                 label=s.get("label", "")),
    "end": lambda s: _bpmn.end(s["id"], type=s.get("type") or "none",
                               lane=s.get("lane", 0), col=s.get("col", 0),
                               label=s.get("label", "")),
    "gateway": lambda s: _bpmn.gateway(s["id"], type=s.get("type") or "exclusive",
                                       lane=s.get("lane", 0), col=s.get("col", 0),
                                       label=s.get("label", "")),
    "task": lambda s: _bpmn.task(s["id"], lane=s.get("lane", 0), col=s.get("col", 0),
                                 label=s.get("label", "")),
    "user_task": lambda s: _bpmn.user_task(s["id"], lane=s.get("lane", 0), col=s.get("col", 0),
                                           label=s.get("label", "")),
    "service_task": lambda s: _bpmn.service_task(s["id"], lane=s.get("lane", 0), col=s.get("col", 0),
                                                 label=s.get("label", "")),
    "manual_task": lambda s: _bpmn.manual_task(s["id"], lane=s.get("lane", 0), col=s.get("col", 0),
                                               label=s.get("label", "")),
    "script_task": lambda s: _bpmn.script_task(s["id"], lane=s.get("lane", 0), col=s.get("col", 0),
                                               label=s.get("label", "")),
    "business_rule_task": lambda s: _bpmn.business_rule_task(
        s["id"], lane=s.get("lane", 0), col=s.get("col", 0), label=s.get("label", "")),
    "sub_process": lambda s: _bpmn.sub_process(s["id"], lane=s.get("lane", 0), col=s.get("col", 0),
                                               label=s.get("label", "")),
}


def _build_bpmn_tree(spec: dict, flat: bool = False):
    """Build a native BPMN swimlane pool from spec["process"] (ProcessBlueprint).

    Never composes with the architecture cluster-nesting logic or the refined
    preset — the pool primitive IS the presentation for a process diagram.
    """
    process = spec.get("process") or {}
    steps = [s for s in (process.get("steps") or []) if s.get("id")]
    children = []
    for s in steps:
        make = _BPMN_CREATORS.get(s.get("kind"))
        if make is None:
            continue
        children.append(make(s))
    tree = pool("pool", process.get("label") or "", {
        "lanes": process.get("lanes") or [],
        "phases": process.get("phases") or [],
    }, children)
    d = Diagram("bpmn", contract="bake", flat=flat)
    render_tree(d, tree)
    step_ids = {s["id"] for s in steps}
    for f in process.get("flows") or []:
        src, tgt = f.get("from"), f.get("to")
        if src not in step_ids or tgt not in step_ids:
            continue
        opts = {"dash": True} if f.get("kind") == "message" else {}
        d.link(src, tgt, f.get("label") or "", **opts)
    return d, tree


def _build_node_element(n: dict, cat, provider: str,
                        accent: str | None = None, size_class: str | None = None):
    """Card/icon/box element for one render_spec node — the same choice logic
    build_tree's build_cluster() uses, factored out so the exotic diagram-type
    builders (hub_spoke/hierarchy/mesh — diagram_types.py) can build nodes
    without going through the cluster/band tree at all."""
    # Upgrade path (V2 §8): a node carrying an embedded icon reuses it directly
    # — no catalog lookup, preserving the source diagram's exact icon.
    img = n.get("icon_data_uri")
    if img:
        title, sub = _card_texts(n)
        mn, mx = _SIZE_CLASSES.get(size_class or "medium", _SIZE_CLASSES["medium"])
        return card(n["id"], None, title, sub, accent=accent,
                    min_w=mn, max_w=mx, image_data_uri=img)
    name = _resolve_node_icon(cat, n, provider)
    label = _node_label(n)
    longest_line = max((len(ln) for ln in label.split("\n")), default=0)
    if (provider == "aws" and name
            and "mxgraph.aws4" in ((_get_icon(cat, name) or {}).get("style") or "")
            and longest_line <= _ICON_LABEL_MAX):
        # AWS convention: native resourceIcon with the label below (short
        # labels only — see _ICON_LABEL_MAX; a longer label falls through
        # to the card() branch below, which wraps safely).
        return icon(n["id"], name, label)
    title, sub = _card_texts(n)
    mn, mx = _SIZE_CLASSES.get(size_class or "medium", _SIZE_CLASSES["medium"])
    if name or sub:
        return card(n["id"], name, title, sub, accent=accent, min_w=mn, max_w=mx)
    if name is None and provider == "aws":
        return box(n["id"], _node_label(n), fill=THEME.base,
                   stroke=_accent_stroke(None), fs=11)
    return card(n["id"], name, title, sub, accent=accent, min_w=mn, max_w=mx)


# layout_intent values that bypass the cluster/band tree entirely — a hub-and-
# spoke fan, a BFS org tree, and a peer grid are node-level topologies, not
# tiered layer bands. Always force style_preset="icon": these geometries have
# no representation in the refined preset's numbered-zones page template.
_EXOTIC_INTENTS = frozenset({"hub_spoke", "hierarchy", "mesh"})


def _build_exotic_tree(spec: dict, flat: bool, intent: str):
    """hub_spoke (3-column phantom: spokes | hub | spokes), hierarchy (BFS
    level columns, TB, sharp tree edges), mesh (peer grid) — diagram_types.py
    presets that operate directly on nodes/edges, ignoring cluster nesting."""
    from .diagram_types import edge_rounded

    cat = _load_catalog() if _load_catalog else None
    provider = str(spec.get("provider") or "aws").lower()
    nodes = [n for n in spec.get("nodes", []) if n.get("id")]
    edges = [e for e in spec.get("edges", []) if e.get("from") and e.get("to")]
    node_ids = {n["id"] for n in nodes}
    by_id = {n["id"]: n for n in nodes}

    def elem(n):
        return _build_node_element(n, cat, provider)

    if intent == "hub_spoke":
        hub_id = spec.get("hub")
        if hub_id not in node_ids:
            # No explicit hub: the max-degree node (ties broken by declaration order).
            degree = {n["id"]: 0 for n in nodes}
            for e in edges:
                if e["from"] in degree:
                    degree[e["from"]] += 1
                if e["to"] in degree:
                    degree[e["to"]] += 1
            hub_id = max(degree, key=lambda k: degree[k]) if degree else None
        spokes = [n for n in nodes if n["id"] != hub_id]
        left, right = spokes[: len(spokes) // 2 + len(spokes) % 2], spokes[len(spokes) // 2 + len(spokes) % 2:]
        left_col = phantom("__hub_left", "", {"dir": "col", "gap": 30}, [elem(n) for n in left])
        right_col = phantom("__hub_right", "", {"dir": "col", "gap": 30}, [elem(n) for n in right])
        hub_elem = elem(by_id[hub_id]) if hub_id in by_id else box("__hub", "(hub)")
        cols = [c for c in (left_col if left else None, hub_elem,
                            right_col if right else None) if c is not None]
        root = phantom("__hub_row", "", {"dir": "row", "gap": 70}, cols)
    elif intent == "hierarchy":
        incoming = {e["to"] for e in edges}
        roots = [n for n in nodes if n["id"] not in incoming] or nodes[:1]
        level_of: dict[str, int] = {}
        frontier = [n["id"] for n in roots]
        for nid in frontier:
            level_of[nid] = 0
        depth, guard = 0, 0
        adj: dict[str, list[str]] = {}
        for e in edges:
            adj.setdefault(e["from"], []).append(e["to"])
        while frontier and guard < len(nodes) + 1:
            guard += 1
            nxt = []
            for nid in frontier:
                for tgt in adj.get(nid, []):
                    if tgt not in level_of:
                        level_of[tgt] = level_of[nid] + 1
                        nxt.append(tgt)
            frontier = nxt
        # Any node the BFS never reached (disconnected) joins the last level.
        max_lvl = max(level_of.values(), default=0)
        for n in nodes:
            level_of.setdefault(n["id"], max_lvl + 1)
        levels: dict[int, list] = {}
        for n in nodes:
            levels.setdefault(level_of[n["id"]], []).append(n)
        cols = [phantom(f"__lvl{lvl}", "", {"dir": "row", "gap": 40},
                        [elem(n) for n in levels[lvl]])
               for lvl in sorted(levels)]
        root = phantom("__hierarchy", "", {"dir": "col", "gap": 60}, cols)
    else:  # mesh
        clusters = [c for c in spec.get("clusters", []) if c.get("id")]
        peer_items = ([box(c["id"], c.get("label") or c["id"], fill=THEME.base,
                           stroke=_accent_stroke(c.get("accent")))
                       for c in clusters] if clusters else [elem(n) for n in nodes])
        n_items = max(1, len(peer_items))
        cols = 2 if n_items <= 4 else 3
        root = grid("__mesh", None, "", {"cols": cols, "gap": 50, "stroke": "none"}, peer_items)

    d = Diagram(intent, contract="bake", flat=flat)
    render_tree(d, root)
    title = spec.get("slide_title") or spec.get("diagram_title")
    if title and not flat:
        d.title(title)
    role = "tree" if intent == "hierarchy" else ""
    rounded = edge_rounded(intent, role)
    for e in edges:
        s, t = e["from"], e["to"]
        if s in d.R and t in d.R:
            dash = str(e.get("style") or "").lower() == "dashed"
            d.link(s, t, e.get("label") or "", dash=dash, rounded=rounded,
                  stroke=_flow_color(e.get("flow")))
    return d, root


def build_tree(spec: dict, flat: bool = False, plan: dict | None = None):
    """Build a native layout tree (+ Diagram, edges) from a render_spec dict.

    Returns (diagram, root_tree) with the tree already rendered into the diagram.
    flat=True emits absolute geometry at parent="1" (for slide embedding).
    plan: optional layout_plan from layout_plan.analyze_layout — edge-aware band
    order, per-band grid columns and hub edge bundling. Every plan key is
    optional; plan=None is byte-identical to the unplanned build.
    """
    if spec.get("process"):
        # BPMN swimlane process — a distinct diagram family (pool/lane/phase),
        # never routed through the architecture cluster-nesting logic below or
        # through the refined preset (the pool IS the presentation).
        return _build_bpmn_tree(spec, flat=flat)
    intent = str(spec.get("layout_intent", "")).lower()
    if intent in _EXOTIC_INTENTS:
        # hub_spoke/hierarchy/mesh are node-level topologies with no
        # representation in the refined preset's numbered-zones page
        # template — always force icon preset (log the downgrade so the
        # caller — and build_drawio_from_spec's stats, which reads this same
        # field — see style_preset was overridden).
        if str(spec.get("style_preset") or "").lower() == "refined":
            spec["_downgrade_note"] = (
                f'layout_intent="{intent}" has no refined-preset layout — '
                'rendered with style_preset="icon" instead.')
        spec["style_preset"] = "icon"
        return _build_exotic_tree(spec, flat, intent)
    if str(spec.get("style_preset") or "").lower() == "refined":
        # Refined typographic preset (playbook look): its own page-template
        # composition — handles zones, edges and legend itself, same
        # (diagram, root) contract. flat is implied (always parent="1").
        from .refined import build_refined
        return build_refined(spec, plan=plan)
    cat = _load_catalog() if _load_catalog else None
    provider = str(spec.get("provider") or "aws").lower()
    clusters = {c["id"]: c for c in spec.get("clusters", []) if c.get("id")}
    nodes = [n for n in spec.get("nodes", []) if n.get("id")]

    nodes_by_cluster: dict[str, list] = {}
    loose: list[dict] = []
    for n in nodes:
        cid = n.get("cluster")
        if cid in clusters:
            nodes_by_cluster.setdefault(cid, []).append(n)
        else:
            loose.append(n)

    children_of: dict[str, list[str]] = {}
    roots: list[str] = []
    for cid, c in clusters.items():
        pid = c.get("parent")
        if pid and pid in clusters and pid != cid:
            children_of.setdefault(pid, []).append(cid)
        else:
            roots.append(cid)

    # Drop entirely-empty root subtrees: a cluster tree with NO node anywhere in
    # its descendants is purely decorative (e.g. the model declares an aspirational
    # cloud>vpc>subnet topology skeleton but assigns every real service to a
    # separate, unrelated set of flat tier clusters). Rendering it produces a giant
    # blank box, and — worse — if it's a genuinely NESTED zone it flips
    # has_nested_zones below and disables layered banding for the OTHER, real
    # content roots too, scattering them into one wide row beside the empty box.
    def _subtree_ids(cid: str) -> set[str]:
        ids = {cid}
        for ch in children_of.get(cid, []):
            ids |= _subtree_ids(ch)
        return ids

    def _subtree_has_nodes(cid: str) -> bool:
        return any(nodes_by_cluster.get(x) for x in _subtree_ids(cid))

    empty_roots = {cid for cid in roots if not _subtree_has_nodes(cid)}
    if empty_roots:
        drop = set().union(*(_subtree_ids(cid) for cid in empty_roots))
        roots = [cid for cid in roots if cid not in drop]
        clusters = {cid: c for cid, c in clusters.items() if cid not in drop}
        children_of = {cid: [ch for ch in kids if ch not in drop]
                       for cid, kids in children_of.items() if cid not in drop}

    intent = str(spec.get("layout_intent", "")).lower()
    horiz = not intent.startswith("top")
    # LAYERED mode (the production architecture look): stacked full-width tinted
    # layer bands + a grey cross-cutting sidebar. Chosen explicitly via
    # layout_intent="layered", or by default once there are 3+ top-level layers.
    cross_roots = [cid for cid in roots
                   if _CROSS_CUT.search(f"{clusters[cid].get('label') or ''} "
                                        f"{clusters[cid].get('tier') or ''}")]
    main_roots = [cid for cid in roots if cid not in cross_roots]
    plan = plan or {}
    if plan.get("band_order"):
        # Edge-aware flow order from the layout plan: planned ids first (in plan
        # order), any band the plan didn't know about keeps its spec position.
        planned = [cid for cid in plan["band_order"] if cid in main_roots]
        main_roots = planned + [cid for cid in main_roots if cid not in planned]
    # Topology mode (Workstream 1): honour real containment nesting
    # (cloud>vpc>subnet>az) as concentric boundaries instead of flat bands — BUT
    # ONLY when a zone actually participates in a containment tree (has a zoned
    # parent, or has child clusters). A lone flat `zone` tag with parent="" is NOT
    # topology; disabling layered banding for it would drop every top-level section
    # into a single ultra-wide row (the Azure-diagram regression). Such flat tags
    # are treated as a no-op and render as today's tinted section bands.
    def _is_topology_node(cid: str) -> bool:
        c = clusters[cid]
        return bool(c.get("zone")) and (
            c.get("parent") in clusters or bool(children_of.get(cid)))
    has_nested_zones = any(_is_topology_node(cid) for cid in clusters)
    layered = (intent.startswith("layer") or len(main_roots) >= 3) and not has_nested_zones

    def build_node(n: dict, accent: str | None = None, size_class: str | None = None):
        return _build_node_element(n, cat, provider, accent, size_class)

    def build_cluster(cid: str, depth: int = 0, band_i: int = 0, band_dir: str = "col"):
        c = clusters[cid]
        label = c["label"] if c.get("number") is None else f'{c["number"]} · {c["label"]}'
        sub_frames = [build_cluster(sub, depth + 1, band_dir=band_dir)
                      for sub in children_of.get(cid, [])]
        cnodes = nodes_by_cluster.get(cid, [])
        # Accent colour the member cards inherit (V2 §6.3): the band's identity
        # stroke at depth 0, the sub-frame accent when nested.
        node_accent = (_band_tint(c, band_i)[1] if depth == 0
                       else _accent_stroke(c.get("accent")))
        items: list = []
        if cnodes:
            n_cards = len(cnodes)

            def _size_class(node: dict) -> str:
                # Density-aware (V2 §5.3): dense rows compact, sparse rows with a
                # long subtitle wide, otherwise medium.
                _, sub = _card_texts(node)
                if n_cards > 4:
                    return "compact"
                if n_cards <= 3 and len(sub) > 22:
                    return "wide"
                return "medium"

            items = [build_node(n, node_accent, _size_class(n)) for n in cnodes]
            # The grey cross-cutting SIDEBAR (depth-0 col band) used to always stack
            # cards in a single column, however many — with several cross-cut
            # sections (e.g. Edge&Security + Observability&DevOps) sharing one
            # sidebar, that single column can hold 10+ cards and dominate the whole
            # page height (the row-direction sidebar/main-column join equal-height
            # stretches, so an overly tall sidebar inflates EVERY band). Wrap it into
            # a 2-column grid past a lower threshold than a normal band, same as the
            # row-band/nested-frame wrapping below — this only reshapes cards INSIDE
            # one already-isolated frame, so it carries none of the cross-BAND
            # routing risk that disabled the (still opt-in) grid-of-bands layout.
            is_sidebar = depth == 0 and band_dir == "col"
            wrap_at = 6 if (depth == 0 and band_dir == "row") else (4 if is_sidebar else 3)
            # A plan band_cols entry FORCES grid wrapping from 4 cards up (an
            # unwrapped 5-6 card row is ~2000px wide — the main driver of
            # ultra-wide strip layouts) — otherwise wrap on the usual threshold.
            forced_cols = plan.get("band_cols", {}).get(cid)
            wants_wrap = (len(items) > wrap_at
                          or (forced_cols and len(items) >= 4))
            if wants_wrap and not children_of.get(cid):
                cols = 2 if len(items) <= 8 else 3
                if forced_cols:
                    cols = max(2, min(4, int(forced_cols)))
                # Sidebar cards are often chained by real sequential edges (e.g.
                # WAF -> LB -> CDN -> NAT) whose labels need real breathing room —
                # the row-band grid's tight 22px gap has an edge label spill onto
                # the neighbour card every time (a ~15-char label needs ~100px+).
                grid_gap = 64 if is_sidebar else 22
                items = [grid(f"{cid}__grid", None, "",
                              {"cols": cols, "gap": grid_gap, "stroke": "none"}, items)]
        # In a horizontal layer band the flow reads left→right: direct nodes
        # first, sub-frames after; nested frames keep the frame-first order.
        kids = (items + sub_frames) if (depth == 0 and band_dir == "row") \
            else (sub_frames + items)
        # Topology boundary (Workstream 1): a cluster whose `zone` participates in a
        # real containment tree renders as a concentric nested frame styled by
        # boundary TYPE at EVERY depth — this wins over both the depth-0 band branch
        # and the nested white-frame branch, so cloud>vpc>subnet>az come out as real
        # containment. A flat `zone` tag (no parent/children) is ignored here and
        # falls through to normal band rendering (see _is_topology_node). Inner flow
        # direction follows layout_intent (LR pipeline vs TB stack).
        zone = c.get("zone")
        if zone and _is_topology_node(cid):
            zdir = "row" if horiz else "col"
            return zone_frame(cid, label, zone, provider, kids,
                              opts={"dir": zdir, "gap": 24, "pad": 18})
        gname = _aws_group_for_label(label) if provider == "aws" else None
        if gname:
            return group(cid, gname, label, {"dir": "col", "gap": 20}, kids)
        # Corner logos stay an on-prem/hybrid affordance: GCP/Azure diagrams keep
        # plain frames (no group stencils exist; the icons carry the identity).
        logo = (_container_logo(cat, c)
                if provider not in ("aws", "gcp", "google", "azure", "microsoft")
                else None)
        if depth == 0:
            # Top-level LAYER BAND: pale tint + matching stroke (Gemini/production
            # look) — the band carries the layer identity, icons carry the vendor.
            fill, stroke = _band_tint(c, band_i)
            opts = {"dir": band_dir, "gap": 36 if band_dir == "row" else 18,
                    "pad": 20, "fill": fill, "stroke": stroke, "fs": 13,
                    "align": "top" if band_dir == "row" else "center",
                    "justify": band_dir == "col"}
            if logo:
                opts["cornerIcon"] = logo
            return frame(cid, label.upper(), opts, kids)
        # Nested sub-frame: white card frame with an accent border. Inside a
        # horizontal band, small sub-frames flow row-wise to stay compact.
        sub_dir = "row" if (depth == 1 and band_dir == "row" and len(kids) <= 3
                            and not children_of.get(cid)) else "col"
        opts = {"dir": sub_dir, "gap": 18, "fill": THEME.base,
                "stroke": _accent_stroke(c.get("accent"))}
        if logo:
            opts["cornerIcon"] = logo
        return frame(cid, label, opts, kids)

    if layered:
        band_frames = [build_cluster(cid, 0, i, band_dir="row")
                       for i, cid in enumerate(main_roots)]
        band_frames += [build_node(n) for n in loose]
        grid_bands = intent.startswith("grid")
        if grid_bands and len(band_frames) > 1:
            # Many parallel domains (not a strict sequential pipeline): a 2-column
            # grid keeps the diagram landscape-shaped instead of one long, uniform
            # vertical scroll (the "every diagram looks the same" complaint) and
            # reduces how hard the slide-fit scale has to shrink it. grid()'s cell
            # model sizes every cell to the largest band, so a small band (e.g. a
            # 2-node security layer) gets extra whitespace around it — an accepted
            # trade-off for reusing the existing primitive instead of a bespoke
            # masonry packer.
            bands_col = grid("__bands", None, "",
                             {"cols": 2, "gap": _LAYER_LANE_GAP, "pad": 0, "stroke": "none"},
                             band_frames)
        else:
            bands_col = phantom("__bands", "", {"dir": "col", "gap": _LAYER_LANE_GAP, "pad": 0},
                                band_frames)
        if cross_roots:
            side_frames = [build_cluster(cid, 0, i, band_dir="col")
                           for i, cid in enumerate(cross_roots)]
            sidebar = (side_frames[0] if len(side_frames) == 1 else
                       phantom("__side", "", {"dir": "col", "gap": 26, "pad": 0}, side_frames))
            root = phantom("__root", "", {"dir": "row", "gap": 90, "pad": 0},
                           [sidebar, bands_col])
        else:
            root = bands_col
    else:
        root_dir = "row" if horiz else "col"
        top_children = [build_cluster(cid, 0, i) for i, cid in enumerate(roots)]
        top_children += [build_node(n) for n in loose]
        if not top_children:
            top_children = [box("__empty", "(empty diagram)")]
        root = phantom("__root", "", {"dir": root_dir, "gap": 60}, top_children)

    # contract="bake" freezes the router's obstacle-avoiding waypoints as explicit
    # mxPoints (scaffold would drop them and let draw.io re-route from pins only).
    # flat=True (used for slide embedding) emits absolute geometry at parent="1".
    d = Diagram(spec.get("pattern", "pipeline"), contract="bake", flat=flat)
    render_tree(d, root)

    # In slide mode (flat) the slide chrome supplies the title — adding it to the
    # body too would duplicate it. Only title the body for standalone diagrams.
    title = spec.get("slide_title") or spec.get("diagram_title")
    if title and not flat:
        d.title(title)

    # Hub edge bundling (layout plan): suppressed members are skipped, the
    # bundle's representative edge gets an "(all layers)" label so the reader
    # knows one arrow stands for the whole fan-out.
    suppressed = {tuple(x) for x in plan.get("suppressed_edges", [])}
    rep_keys = {tuple(b.get("rep") or []) for b in plan.get("edge_bundles", [])}
    rep_pair_count = {tuple(b.get("rep") or []): len(b.get("members") or []) + 1
                      for b in plan.get("edge_bundles", [])
                      if b.get("kind") == "pair"}
    flows_seen: list[str] = []
    for e in spec.get("edges", []):
        s, t = e.get("from"), e.get("to")
        if s in d.R and t in d.R:
            label = e.get("label") or ""
            key = (s, t, label)
            if key in suppressed:
                continue
            if key in rep_pair_count:
                n = rep_pair_count[key]
                if f"×{n}" not in label:
                    label = (label + f" (×{n} flows)").strip()
            elif key in rep_keys and "(all layers)" not in label:
                label = (label + " (all layers)").strip()
            flow = str(e.get("flow") or "").lower()
            fc = FLOW_COLORS.get(flow)
            if fc and flow not in flows_seen:
                flows_seen.append(flow)
            dash = (str(e.get("style") or "").lower() == "dashed"
                    or bool(fc and fc[1] == "dashed"))
            d.link(s, t, label,
                   dash=dash, stroke=_flow_color(e.get("flow")))

    # Standalone body legend: one row per flow colour actually used (the slide
    # chrome draws its own legend, so flat mode skips this).
    if not flat and len(flows_seen) >= 2:
        entries = [(f.replace("_", " ").capitalize(), FLOW_COLORS[f][0],
                    FLOW_COLORS[f][1] == "dashed") for f in flows_seen[:6]]
        ly = root["y"] + root["h"] + 28
        d.legend(entries, (root["x"], ly))
        lr = d.R.get("__legend")
        if lr:
            d.page[1] = max(d.page[1], round(lr["y"] + lr["h"] + 50))
    return d, root


def render_spec_to_drawio(spec: dict, name: str = "Architecture",
                          plan: dict | None = None) -> str:
    """Convenience: build from spec and return the full .drawio (mxfile) XML."""
    d, _ = build_tree(spec, plan=plan)
    return d.mxfile(name)


def build_drawio_from_spec(spec: dict, name: str = "Architecture",
                           flat: bool = False,
                           plan: dict | None = None) -> tuple[str, dict]:
    """Build a native .drawio from a render_spec and return (xml, stats).

    stats reports fidelity + routing quality for the caller to log: native icon /
    group counts, and the router's residual edge crossings / parallel overlaps.
    flat=True emits a flat body (parent="1", absolute coords) for slide embedding.
    plan: optional layout_plan (see layout_plan.analyze_layout).
    """
    d, _ = build_tree(spec, flat=flat, plan=plan)
    xml = d.mxfile(name)
    stats = {
        "style_preset": str(spec.get("style_preset") or "icon").lower(),
        "nodes": len(spec.get("nodes", [])),
        "edges": len(spec.get("edges", [])),
        "native_icons": xml.count("resIcon=mxgraph.aws4."),
        "image_icons": xml.count("image=data:image/"),
        "native_groups": xml.count("grIcon=mxgraph.aws4."),
        "edge_cross": getattr(d, "_cross", 0),
        "edge_overlaps": getattr(d, "_overlaps", 0),
    }
    if spec.get("_downgrade_note"):
        stats["downgrade_note"] = spec["_downgrade_note"]
    return xml, stats
