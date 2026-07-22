"""Edge-aware layout analysis (pre-render, pure Python, 0 LLM tokens).

The topology builder places bands in *spec order* and never consults edges —
so a blueprint whose clusters arrive shuffled renders with the primary flow
zig-zagging across the page, and hub nodes (telemetry/security fan-out) spray
same-label dashed edges across every band. ``analyze_layout`` fixes the plan,
not the pixels: it orders the layer bands along the dominant edge flow,
bundles repetitive hub fan-out into one representative edge, and picks
grid column counts that pull the body toward the ~16:9 production aspect.

Output is a JSON-serializable ``layout_plan`` consumed by
``topology.build_tree(spec, plan=...)`` — every key optional, absence of a
plan is byte-identical to today's behavior.
"""

from __future__ import annotations

import re
from itertools import permutations

try:
    from .topology import _CROSS_CUT, _SIZE_CLASSES
except (ImportError, ValueError):  # pragma: no cover - import fallback
    from prettygraph.native.topology import _CROSS_CUT, _SIZE_CLASSES  # type: ignore

TARGET_RATIO = 1.6
# Hub detection (user-approved bundling): a node with >=5 edges, >=80% of them
# cross-band, whose same-label groups of >=3 collapse to one representative.
_HUB_DEGREE = 5
_HUB_CROSS_SHARE = 0.8
_AGGRESSIVE_HUB_DEGREE = 4
_AGGRESSIVE_HUB_CROSS_SHARE = 0.3
_BUNDLE_MIN = 3
_BUNDLE_EDGE_CAP = 0.4  # default: never suppress more than 40% of all edges
_AGGRESSIVE_BUNDLE_MIN = 2
_AGGRESSIVE_BUNDLE_EDGE_CAP = 0.65
_AGGRESSIVE_BUNDLE_CLASSES = {"control", "monitoring", "security", "registry", "data", "execution", "serving"}
_EXECUTIVE_BUNDLE_MIN_EDGES = 24
_EXECUTIVE_BUNDLE_HUB_DEGREE = 2
# Rough per-card footprint for the aspect estimate (medium size class + gaps).
_EST_CARD_W = (_SIZE_CLASSES["medium"][0] + _SIZE_CLASSES["medium"][1]) / 2 + 22
_EST_CARD_H = 64 + 18
_EST_BAND_CHROME_H = 70  # band title + padding
_EST_PAGE_GAP = 46  # _LAYER_LANE_GAP
_REFINED_SUPPORT_RX = re.compile(
    r"security|secret|iam\b|identity|access|governance|audit|observ|monitor"
    r"|operation|devops|ci\s*/?\s*cd|data|database|storage|state|archive"
    r"|ledger|replication|evidence|content|store|stores|bucket|blob|nas",
    re.IGNORECASE,
)
_REFINED_FLOW_ALIAS = {"security": "control", "serving": "execution"}


def _cluster_maps(spec: dict):
    clusters = {c["id"]: c for c in spec.get("clusters", []) if c.get("id")}
    children_of: dict[str, list[str]] = {}
    roots: list[str] = []
    for cid, c in clusters.items():
        pid = c.get("parent")
        if pid and pid in clusters and pid != cid:
            children_of.setdefault(pid, []).append(cid)
        else:
            roots.append(cid)

    def root_of_cluster(cid: str) -> str:
        seen = set()
        while cid in clusters and cid not in seen:
            seen.add(cid)
            pid = clusters[cid].get("parent")
            if not pid or pid not in clusters or pid == cid:
                return cid
            cid = pid
        return cid

    node_root: dict[str, str] = {}
    nodes_in_root: dict[str, int] = {}
    for n in spec.get("nodes", []):
        nid = n.get("id")
        cid = n.get("cluster")
        if not nid:
            continue
        if cid in clusters:
            r = root_of_cluster(cid)
            node_root[nid] = r
            nodes_in_root[r] = nodes_in_root.get(r, 0) + 1
    return clusters, children_of, roots, node_root, nodes_in_root


def _order_cost(order: list[str], w: dict) -> float:
    pos = {cid: i for i, cid in enumerate(order)}
    cost = 0.0
    for (a, b), n in w.items():
        if a in pos and b in pos:
            cost += n * abs(pos[b] - pos[a])
            if pos[b] < pos[a]:  # upward (against-flow) edge
                cost += 0.5 * n
    return cost


def order_bands(main_roots: list[str], w: dict) -> list[str]:
    """Order layer bands along the dominant flow (minimize weighted edge span).

    Deterministic: exhaustive for <=6 bands (first-minimal in an ordering that
    enumerates near-original permutations first, so ties keep spec order),
    adjacent-pair-swap hill climb otherwise.
    """
    if len(main_roots) <= 1 or not w:
        return list(main_roots)
    if len(main_roots) <= 6:
        best, best_cost = list(main_roots), _order_cost(main_roots, w)
        for perm in permutations(main_roots):
            c = _order_cost(list(perm), w)
            if c < best_cost - 1e-9:
                best, best_cost = list(perm), c
        return best
    order = list(main_roots)
    cost = _order_cost(order, w)
    for _ in range(20):
        improved = False
        for i in range(len(order) - 1):
            cand = order[:i] + [order[i + 1], order[i]] + order[i + 2 :]
            c = _order_cost(cand, w)
            if c < cost - 1e-9:
                order, cost, improved = cand, c, True
        if not improved:
            break
    return order


def _bundle_edges(
    spec: dict,
    node_root: dict,
    band_pos: dict,
    *,
    min_group: int = _BUNDLE_MIN,
    edge_cap: float = _BUNDLE_EDGE_CAP,
    aggressive: bool = False,
) -> tuple[list, list]:
    """Collapse hub fan-out: >=_BUNDLE_MIN same-label same-direction edges from
    one hub become 1 representative edge (nearest band) + suppressed members.

    Returns (edge_bundles, suppressed_edges) — members/suppressed are
    [from, to, label] triples so parallel edges with different labels survive.
    """
    edges = [e for e in spec.get("edges", []) if e.get("from") and e.get("to")]
    total = len(edges)
    if not total:
        return [], []
    node_cluster = {
        n.get("id"): n.get("cluster") for n in spec.get("nodes", []) if n.get("id") and n.get("cluster")
    }
    deg: dict[str, int] = {}
    cross: dict[str, int] = {}
    direct_cross: dict[str, int] = {}
    for e in edges:
        s, t = e["from"], e["to"]
        is_cross = node_root.get(s) != node_root.get(t)
        is_direct_cross = node_cluster.get(s) != node_cluster.get(t)
        for nid in (s, t):
            deg[nid] = deg.get(nid, 0) + 1
            if is_cross:
                cross[nid] = cross.get(nid, 0) + 1
            if is_direct_cross:
                direct_cross[nid] = direct_cross.get(nid, 0) + 1
    hub_degree = _AGGRESSIVE_HUB_DEGREE if aggressive else _HUB_DEGREE
    hub_cross_share = _AGGRESSIVE_HUB_CROSS_SHARE if aggressive else _HUB_CROSS_SHARE
    cross_counts = direct_cross if aggressive else cross
    hubs = {
        nid for nid, d in deg.items() if d >= hub_degree and cross_counts.get(nid, 0) / d >= hub_cross_share
    }

    groups: dict[tuple, list[dict]] = {}
    for e in edges:
        label = (e.get("label") or "").strip().lower()
        # `flow` is the SEMANTIC class (data/control/monitoring/...); `style`
        # ("solid"/"dashed") is a pure line-rendering hint that specs often set
        # on every edge regardless of meaning — grouping on it first would
        # silently merge a control call with a data call that both happen to
        # render solid. flow must win; style is only a fallback when flow is
        # absent entirely.
        cls = str(e.get("flow") or e.get("style") or "").lower()
        if e["from"] in hubs:
            group_label = "" if aggressive and cls in _AGGRESSIVE_BUNDLE_CLASSES else label
            groups.setdefault((e["from"], "out", group_label, cls), []).append(e)
        if e["to"] in hubs:
            group_label = "" if aggressive and cls in _AGGRESSIVE_BUNDLE_CLASSES else label
            groups.setdefault((e["to"], "in", group_label, cls), []).append(e)

    candidates = sorted(
        [
            (k, v)
            for k, v in groups.items()
            if len(v) >= min_group and (not aggressive or not k[3] or k[3] in _AGGRESSIVE_BUNDLE_CLASSES)
        ],
        key=lambda kv: (-len(kv[1]), kv[0]),
    )
    bundles: list[dict] = []
    suppressed: list[list] = []
    seen: set[tuple] = set()
    budget = int(total * edge_cap)

    def _band_dist(e: dict, hub: str) -> tuple:
        other = e["to"] if e["from"] == hub else e["from"]
        hb = band_pos.get(node_root.get(hub, ""), 999)
        ob = band_pos.get(node_root.get(other, ""), 999)
        return (abs(ob - hb), str(other))

    for (hub, _dirn, _label, _style), members in candidates:
        members = [m for m in members if (m["from"], m["to"], m.get("label") or "") not in seen]
        if len(members) < min_group:
            continue
        drop = len(members) - 1
        if len(suppressed) + drop > budget:
            continue
        members = sorted(members, key=lambda e: _band_dist(e, hub))
        rep, rest = members[0], members[1:]
        for m in members:
            seen.add((m["from"], m["to"], m.get("label") or ""))
        bundles.append(
            {
                "kind": "hub",
                "rep": [rep["from"], rep["to"], rep.get("label") or ""],
                "members": [[m["from"], m["to"], m.get("label") or ""] for m in rest],
            }
        )
        suppressed += [[m["from"], m["to"], m.get("label") or ""] for m in rest]

    # Zone-pair aggregation: many-to-many spray between the SAME two bands
    # (>=min_group same-style cross-band edges, no shared hub) collapses to
    # the most central member — grouped by CLASS, not exact label wording.
    # This is what tames "too many arrows" on dense diagrams: five distinctly
    # WORDED calls between the same two zones ("Recommend", "Query LLM",
    # "Find Twins"...) still read as one relationship band on a client
    # diagram — a consulting-grade architecture shows one arrow per
    # relationship, not one per RPC. Same-label collapsing (the historical
    # behaviour) is the label>=3 case of this same grouping.
    pair_groups: dict[tuple, list[dict]] = {}
    for e in edges:
        k = (e["from"], e["to"], e.get("label") or "")
        if k in seen:
            continue
        ra, rb = node_root.get(e["from"]), node_root.get(e["to"])
        if not ra or not rb or ra == rb:
            if not aggressive:
                continue
            ra = node_cluster.get(e["from"])
            rb = node_cluster.get(e["to"])
            if not ra or not rb or ra == rb:
                continue
        # flow (semantic class) must win over style (solid/dashed line hint) —
        # specs often stamp "style": "solid" on every business edge regardless
        # of meaning, and keying on it first would silently fuse a "control"
        # call with an unrelated "data" call that both happen to render solid.
        cls = str(e.get("flow") or e.get("style") or "").lower()
        if cls == "monitoring" and not aggressive:
            # Telemetry fan-in is the hub pass's job (grouped by the shared
            # target node above) — merging it here too would fuse edges that
            # target DIFFERENT hub nodes in the same zone (e.g. "monitoring"
            # and "logging" are two distinct nodes sharing one cluster root)
            # into a single line, silently erasing whichever loses the pick.
            continue
        pair_groups.setdefault((ra, rb, cls), []).append(e)
    for (_ra, _rb, _style), members in sorted(pair_groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(members) < min_group:
            continue
        if aggressive and _style not in _AGGRESSIVE_BUNDLE_CLASSES:
            continue
        drop = len(members) - 1
        if len(suppressed) + drop > budget:
            continue
        # Representative: the member whose endpoints have the highest total
        # degree (the pair a reader would name first), stable-tied by id.
        members = sorted(
            members,
            key=lambda e: (-(deg.get(e["from"], 0) + deg.get(e["to"], 0)), str(e["from"]), str(e["to"])),
        )
        rep, rest = members[0], members[1:]
        for m in members:
            seen.add((m["from"], m["to"], m.get("label") or ""))
        bundles.append(
            {
                "kind": "pair",
                "rep": [rep["from"], rep["to"], rep.get("label") or ""],
                "members": [[m["from"], m["to"], m.get("label") or ""] for m in rest],
            }
        )
        suppressed += [[m["from"], m["to"], m.get("label") or ""] for m in rest]
    return bundles, suppressed


def _bundle_refined_support_edges(
    spec: dict,
    clusters: dict,
    node_root: dict,
    bundles: list,
    suppressed: list,
    *,
    edge_cap: float = _BUNDLE_EDGE_CAP,
    aggressive: bool = False,
) -> tuple[list, list]:
    """Collapse refined-preset support wiring.

    Refined pages reserve visual weight for the main request path. Repeated
    control/monitoring/audit links that fan out from or into the same support
    zone are more readable as one labelled representative ("all layers") than
    as several long dashed lines crossing the body.
    """
    edges = [e for e in spec.get("edges", []) if e.get("from") and e.get("to")]
    if len(edges) < 2:
        return [], []
    node_cluster = {
        n.get("id"): n.get("cluster") for n in spec.get("nodes", []) if n.get("id") and n.get("cluster")
    }

    def _edge_key(e: dict) -> tuple:
        return (e.get("from"), e.get("to"), e.get("label") or "")

    def _class(e: dict) -> str:
        flow = str(e.get("flow") or e.get("style") or "").lower()
        return _REFINED_FLOW_ALIAS.get(flow, flow)

    def _support_root(root_id: str | None) -> bool:
        if not root_id:
            return False
        c = clusters.get(root_id) or {}
        text = f"{root_id} {c.get('label') or ''} {c.get('tier') or ''}"
        return bool(_REFINED_SUPPORT_RX.search(text))

    used = {tuple(x) for x in suppressed}
    for b in bundles:
        rep = tuple(b.get("rep") or [])
        if rep:
            used.add(rep)
        used.update(tuple(m) for m in b.get("members") or [])

    groups: dict[tuple, list[tuple[int, dict]]] = {}
    for i, e in enumerate(edges):
        if _edge_key(e) in used:
            continue
        cls = _class(e)
        if cls not in {"control", "monitoring", "data", "registry", "execution"}:
            continue
        ra, rb = node_root.get(e["from"]), node_root.get(e["to"])
        if ra and rb and ra == rb:
            if not aggressive:
                continue
            ra = node_cluster.get(e["from"])
            rb = node_cluster.get(e["to"])
            if not ra or not rb or ra == rb:
                continue
        if _support_root(ra):
            groups.setdefault((ra, "out"), []).append((i, e))
        if _support_root(rb):
            groups.setdefault((rb, "in"), []).append((i, e))

    budget = int(len(edges) * edge_cap) - len(suppressed)
    if budget <= 0:
        return [], []

    def _rep_rank(item: tuple[int, dict]) -> tuple:
        i, e = item
        label = str(e.get("label") or "").lower()
        preferred = 0 if re.search(r"authori[sz]ation|policy|decision|metrics", label) else 1
        return (preferred, i)

    extra_bundles: list[dict] = []
    extra_suppressed: list[list] = []
    for key, members in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        members = [(i, e) for i, e in members if _edge_key(e) not in used]
        if len(members) < 2:
            continue
        drop = len(members) - 1
        if drop > budget:
            continue
        members = sorted(members, key=_rep_rank)
        rep = members[0][1]
        rest = [e for _i, e in members[1:]]
        bundle = {
            "kind": "hub",
            "rep": [rep["from"], rep["to"], rep.get("label") or ""],
            "members": [[m["from"], m["to"], m.get("label") or ""] for m in rest],
        }
        extra_bundles.append(bundle)
        for e in [rep] + rest:
            used.add(_edge_key(e))
        for m in rest:
            extra_suppressed.append([m["from"], m["to"], m.get("label") or ""])
        budget -= drop
    return extra_bundles, extra_suppressed


def _bundle_refined_executive_edges(
    spec: dict, clusters: dict, node_root: dict, bundles: list, suppressed: list, *, edge_cap: float
) -> tuple[list, list]:
    """Extra-simplify dense refined pages into executive-readable connectors.

    The normal aggressive pass preserves one edge per hub+class. On large client
    architecture diagrams that can still leave several long side-channel arrows
    from the same orchestration/API/support hubs. This pass is deliberately
    gated to dense refined renders and collapses remaining visible hub incident
    edges into a few relationship-level representatives while preserving every
    hidden source edge in ``suppressed_edges`` for semantic recall.
    """
    edges = [e for e in spec.get("edges", []) if e.get("from") and e.get("to")]
    if len(edges) < _EXECUTIVE_BUNDLE_MIN_EDGES:
        return [], []

    node_by_id = {n.get("id"): n for n in spec.get("nodes", []) if n.get("id")}
    node_cluster = {nid: n.get("cluster") for nid, n in node_by_id.items()}

    def _edge_key(e: dict) -> tuple:
        return (e.get("from"), e.get("to"), e.get("label") or "")

    def _class(e: dict) -> str:
        flow = str(e.get("flow") or e.get("style") or "").lower()
        return _REFINED_FLOW_ALIAS.get(flow, flow)

    def _cluster_text(cid: str | None) -> str:
        c = clusters.get(cid or "") or {}
        return f"{cid or ''} {c.get('label') or ''} {c.get('tier') or ''}".lower()

    def _node_text(nid: str | None) -> str:
        n = node_by_id.get(nid or "") or {}
        return f"{nid or ''} {n.get('label') or ''} {n.get('tech') or ''}".lower()

    def _is_supportish(nid: str | None) -> bool:
        cid = node_cluster.get(nid or "")
        rid = node_root.get(nid or "")
        text = f"{_node_text(nid)} {_cluster_text(cid)} {_cluster_text(rid)}"
        return bool(_REFINED_SUPPORT_RX.search(text))

    def _label_for(hub: str, members: list[dict], rep: dict) -> str:
        classes = {_class(e) for e in members if _class(e)}
        text = " ".join([_node_text(hub)] + [str(e.get("label") or "").lower() for e in members])
        if re.search(r"rpa|erp|dms|tms|invoice|bank|system|reconcile", text):
            return "systems sync"
        if re.search(r"workflow|orchestr|approval|exception|queue|review", text):
            return "workflow control"
        if re.search(r"api|gateway|apigee|cloud run|load balancer|armor", text):
            return "governed APIs"
        if re.search(r"iam|rbac|secret|kms|policy|security|govern|authorize", text):
            return "security controls"
        if re.search(r"deploy|build|release|artifact|delivery", text):
            return "delivery flow"
        if re.search(r"document|invoice|statement|storage|bucket|parse|intake", text):
            return "document intake"
        if "registry" in classes or re.search(r"audit|log|ledger|evidence", text):
            return "audit trail"
        if classes == {"monitoring"} or re.search(r"monitor|observ|telemetry|slo|alert", text):
            return "telemetry"
        if re.search(r"pubsub|topic|event|stream|dataflow", text):
            return "event stream"
        label = (rep.get("label") or "").strip()
        return f"{label} (grouped)" if label else "grouped flows"

    suppressed_set = {tuple(x) for x in suppressed}
    visible = [e for e in edges if _edge_key(e) not in suppressed_set]
    if len(visible) < 2:
        return [], []

    deg: dict[str, int] = {}
    support_deg: dict[str, int] = {}
    for e in visible:
        cls = _class(e)
        for nid in (e["from"], e["to"]):
            deg[nid] = deg.get(nid, 0) + 1
            if cls in _AGGRESSIVE_BUNDLE_CLASSES or _is_supportish(nid):
                support_deg[nid] = support_deg.get(nid, 0) + 1
    hubs = {
        nid for nid, d in deg.items() if d >= _EXECUTIVE_BUNDLE_HUB_DEGREE and support_deg.get(nid, 0) >= 2
    }
    if not hubs:
        return [], []

    groups: dict[str, list[dict]] = {}
    for e in visible:
        cls = _class(e)
        if cls not in _AGGRESSIVE_BUNDLE_CLASSES and not (
            _is_supportish(e["from"]) or _is_supportish(e["to"])
        ):
            continue
        for hub in (e["from"], e["to"]):
            if hub not in hubs:
                continue
            other = e["to"] if hub == e["from"] else e["from"]
            # Keep local one-hop card relationships unless the endpoint is a
            # support concern; those usually route inside the same zone cleanly.
            if node_cluster.get(hub) == node_cluster.get(other) and not (
                _is_supportish(hub) or _is_supportish(other)
            ):
                continue
            groups.setdefault(hub, []).append(e)

    budget = int(len(edges) * edge_cap) - len(suppressed)
    if budget <= 0:
        return [], []

    def _rep_rank(e: dict, hub: str) -> tuple:
        label = str(e.get("label") or "").lower()
        cls = _class(e)
        # Prefer outgoing, named business relationships before purely
        # operational side channels.
        direction_penalty = 0 if e["from"] == hub else 1
        side_channel = (
            1
            if (
                cls in {"monitoring", "security", "registry"}
                or re.search(r"telemetry|secret|kms|audit|logs?|release", label)
            )
            else 0
        )
        return (
            direction_penalty,
            side_channel,
            -deg.get(e["from"], 0) - deg.get(e["to"], 0),
            str(e["from"]),
            str(e["to"]),
            label,
        )

    extra_bundles: list[dict] = []
    extra_suppressed: list[list] = []
    used = set(suppressed_set)
    for hub, members in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        members = [e for e in members if _edge_key(e) not in used]
        if len(members) < 2:
            continue
        drop = len(members) - 1
        if drop > budget:
            continue
        members = sorted(members, key=lambda e: _rep_rank(e, hub))
        rep, rest = members[0], members[1:]
        rep_key = _edge_key(rep)
        rest_keys = [_edge_key(e) for e in rest]
        extra_bundles.append(
            {
                "kind": "pair",
                "rep": [rep["from"], rep["to"], rep.get("label") or ""],
                "label": _label_for(hub, members, rep),
                "members": [[m["from"], m["to"], m.get("label") or ""] for m in rest],
            }
        )
        used.add(rep_key)
        used.update(rest_keys)
        for m in rest:
            extra_suppressed.append([m["from"], m["to"], m.get("label") or ""])
        budget -= drop
        if budget <= 0:
            break
    return extra_bundles, extra_suppressed


def _pick_band_cols(main_roots: list[str], nodes_in_root: dict, sidebar_nodes: int) -> dict:
    """Choose per-band grid columns so the predicted body ratio nears 16:9.

    A band_cols entry force-wraps its band from 4 cards up (the builder only
    auto-wraps past 6 in a row band); the same column count is applied to every
    big band — the auto-repair loop refines per-band later if needed.
    """
    big = [cid for cid in main_roots if nodes_in_root.get(cid, 0) >= 4]
    if not big:
        return {}

    def predicted_ratio(cols: int | None) -> float:
        widths, height = [], 0.0
        for cid in main_roots:
            n = nodes_in_root.get(cid, 0)
            if cols and cid in big:
                rows = -(-n // cols)
                widths.append(cols * _EST_CARD_W)
                height += rows * _EST_CARD_H + _EST_BAND_CHROME_H
            else:
                widths.append(max(1, n) * _EST_CARD_W)
                height += _EST_CARD_H + _EST_BAND_CHROME_H
        height += _EST_PAGE_GAP * max(0, len(main_roots) - 1)
        width = max(widths) if widths else 1.0
        if sidebar_nodes:
            width += 2 * _EST_CARD_W + 90
            height = max(height, -(-sidebar_nodes // 2) * _EST_CARD_H)
        return width / max(1.0, height)

    # If the natural (unwrapped) layout already lands near the target band,
    # don't force-wrap anything — wrapping has real routing cost.
    if 1.3 <= predicted_ratio(None) <= 1.9:
        return {}
    best_cols = min((3, 2, 4), key=lambda c: abs(predicted_ratio(c) - TARGET_RATIO))
    if abs(predicted_ratio(best_cols) - TARGET_RATIO) >= abs(predicted_ratio(None) - TARGET_RATIO):
        return {}
    return {cid: best_cols for cid in big}


def analyze_layout(spec: dict, *, aggressive_bundles: bool = False) -> dict:
    """Produce a layout_plan for a render_spec (deterministic, no LLM).

    Keys: band_order, sidebar_roots, band_cols, edge_bundles, suppressed_edges,
    target_ratio, notes. Safe on any spec — degrades to empty/no-op fields.
    """
    clusters, children_of, roots, node_root, nodes_in_root = _cluster_maps(spec)
    notes: list[str] = []

    def _subtree_has_nodes(cid: str) -> bool:
        if nodes_in_root.get(cid):
            return True
        return any(_subtree_has_nodes(ch) for ch in children_of.get(cid, []))

    # nodes_in_root counts by ROOT, so descend checks only need the root flag.
    live_roots = [cid for cid in roots if nodes_in_root.get(cid, 0) > 0]
    cross_roots = [
        cid
        for cid in live_roots
        if _CROSS_CUT.search(f"{clusters[cid].get('label') or ''} {clusters[cid].get('tier') or ''}")
    ]
    main_roots = [cid for cid in live_roots if cid not in cross_roots]

    # Weighted band digraph from cross-band edges (sidebar edges excluded — the
    # sidebar sits beside every band, its edges don't constrain band order).
    w: dict[tuple, int] = {}
    for e in spec.get("edges", []):
        s, t = e.get("from"), e.get("to")
        ra, rb = node_root.get(s), node_root.get(t)
        if not ra or not rb or ra == rb:
            continue
        if ra in cross_roots or rb in cross_roots:
            continue
        if ra in main_roots and rb in main_roots:
            w[(ra, rb)] = w.get((ra, rb), 0) + 1

    band_order = order_bands(main_roots, w)
    if band_order != main_roots:
        notes.append("bands reordered along dominant edge flow")
    band_pos = {cid: i for i, cid in enumerate(band_order)}

    bundle_min = _AGGRESSIVE_BUNDLE_MIN if aggressive_bundles else _BUNDLE_MIN
    bundle_cap = _AGGRESSIVE_BUNDLE_EDGE_CAP if aggressive_bundles else _BUNDLE_EDGE_CAP
    bundles, suppressed = _bundle_edges(
        spec, node_root, band_pos, min_group=bundle_min, edge_cap=bundle_cap, aggressive=aggressive_bundles
    )
    if str(spec.get("style_preset") or "").lower() == "refined":
        eb, es = _bundle_refined_support_edges(
            spec, clusters, node_root, bundles, suppressed, edge_cap=bundle_cap, aggressive=aggressive_bundles
        )
        bundles += eb
        suppressed += es
        if aggressive_bundles:
            eb, es = _bundle_refined_executive_edges(
                spec, clusters, node_root, bundles, suppressed, edge_cap=bundle_cap
            )
            bundles += eb
            suppressed += es
    if bundles:
        notes.append(
            f"bundled {len(suppressed)} repetitive hub edge(s) into {len(bundles)} representative(s)"
        )
    if aggressive_bundles:
        notes.append("aggressive arrow bundling enabled for dense/crossing-heavy layout")

    sidebar_nodes = sum(nodes_in_root.get(cid, 0) for cid in cross_roots)
    band_cols = _pick_band_cols(band_order, nodes_in_root, sidebar_nodes)
    if band_cols:
        notes.append(
            f"grid cols {sorted(set(band_cols.values()))[0]} chosen for "
            f"{len(band_cols)} dense band(s) targeting ratio {TARGET_RATIO}"
        )

    return {
        "schema": 1,
        "band_order": band_order,
        "sidebar_roots": cross_roots,
        "band_cols": band_cols,
        "edge_bundles": bundles,
        "suppressed_edges": suppressed,
        "aggressive_bundles": aggressive_bundles,
        "target_ratio": TARGET_RATIO,
        "notes": notes,
    }
