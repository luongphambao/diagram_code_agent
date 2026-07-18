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
_BUNDLE_MIN = 3
_BUNDLE_EDGE_CAP = 0.4  # never suppress more than 40% of all edges
# Rough per-card footprint for the aspect estimate (medium size class + gaps).
_EST_CARD_W = (_SIZE_CLASSES["medium"][0] + _SIZE_CLASSES["medium"][1]) / 2 + 22
_EST_CARD_H = 64 + 18
_EST_BAND_CHROME_H = 70   # band title + padding
_EST_PAGE_GAP = 46        # _LAYER_LANE_GAP


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
            cand = order[:i] + [order[i + 1], order[i]] + order[i + 2:]
            c = _order_cost(cand, w)
            if c < cost - 1e-9:
                order, cost, improved = cand, c, True
        if not improved:
            break
    return order


def _bundle_edges(spec: dict, node_root: dict, band_pos: dict) -> tuple[list, list]:
    """Collapse hub fan-out: >=_BUNDLE_MIN same-label same-direction edges from
    one hub become 1 representative edge (nearest band) + suppressed members.

    Returns (edge_bundles, suppressed_edges) — members/suppressed are
    [from, to, label] triples so parallel edges with different labels survive.
    """
    edges = [e for e in spec.get("edges", []) if e.get("from") and e.get("to")]
    total = len(edges)
    if not total:
        return [], []
    deg: dict[str, int] = {}
    cross: dict[str, int] = {}
    for e in edges:
        s, t = e["from"], e["to"]
        is_cross = node_root.get(s) != node_root.get(t)
        for nid in (s, t):
            deg[nid] = deg.get(nid, 0) + 1
            if is_cross:
                cross[nid] = cross.get(nid, 0) + 1
    hubs = {nid for nid, d in deg.items()
            if d >= _HUB_DEGREE and cross.get(nid, 0) / d >= _HUB_CROSS_SHARE}

    groups: dict[tuple, list[dict]] = {}
    for e in edges:
        label = (e.get("label") or "").strip().lower()
        style = str(e.get("style") or e.get("flow") or "").lower()
        if e["from"] in hubs:
            groups.setdefault((e["from"], "out", label, style), []).append(e)
        if e["to"] in hubs:
            groups.setdefault((e["to"], "in", label, style), []).append(e)

    candidates = sorted(
        [(k, v) for k, v in groups.items() if len(v) >= _BUNDLE_MIN],
        key=lambda kv: (-len(kv[1]), kv[0]))
    bundles: list[dict] = []
    suppressed: list[list] = []
    seen: set[tuple] = set()
    budget = int(total * _BUNDLE_EDGE_CAP)

    def _band_dist(e: dict, hub: str) -> tuple:
        other = e["to"] if e["from"] == hub else e["from"]
        hb = band_pos.get(node_root.get(hub, ""), 999)
        ob = band_pos.get(node_root.get(other, ""), 999)
        return (abs(ob - hb), str(other))

    for (hub, _dirn, _label, _style), members in candidates:
        members = [m for m in members
                   if (m["from"], m["to"], m.get("label") or "") not in seen]
        if len(members) < _BUNDLE_MIN:
            continue
        drop = len(members) - 1
        if len(suppressed) + drop > budget:
            continue
        members = sorted(members, key=lambda e: _band_dist(e, hub))
        rep, rest = members[0], members[1:]
        for m in members:
            seen.add((m["from"], m["to"], m.get("label") or ""))
        bundles.append({
            "kind": "hub",
            "rep": [rep["from"], rep["to"], rep.get("label") or ""],
            "members": [[m["from"], m["to"], m.get("label") or ""] for m in rest],
        })
        suppressed += [[m["from"], m["to"], m.get("label") or ""] for m in rest]

    # Zone-pair aggregation: many-to-many spray between the SAME two bands
    # (>=_BUNDLE_MIN same-style cross-band edges, no shared hub) collapses to
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
            continue
        style = str(e.get("style") or e.get("flow") or "").lower()
        pair_groups.setdefault((ra, rb, style), []).append(e)
    for (_ra, _rb, _style), members in sorted(
            pair_groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(members) < _BUNDLE_MIN:
            continue
        drop = len(members) - 1
        if len(suppressed) + drop > budget:
            continue
        # Representative: the member whose endpoints have the highest total
        # degree (the pair a reader would name first), stable-tied by id.
        members = sorted(members, key=lambda e: (-(deg.get(e["from"], 0)
                                                   + deg.get(e["to"], 0)),
                                                 str(e["from"]), str(e["to"])))
        rep, rest = members[0], members[1:]
        for m in members:
            seen.add((m["from"], m["to"], m.get("label") or ""))
        bundles.append({
            "kind": "pair",
            "rep": [rep["from"], rep["to"], rep.get("label") or ""],
            "members": [[m["from"], m["to"], m.get("label") or ""] for m in rest],
        })
        suppressed += [[m["from"], m["to"], m.get("label") or ""] for m in rest]
    return bundles, suppressed


def _pick_band_cols(main_roots: list[str], nodes_in_root: dict,
                    sidebar_nodes: int) -> dict:
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


def analyze_layout(spec: dict) -> dict:
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
    cross_roots = [cid for cid in live_roots
                   if _CROSS_CUT.search(f"{clusters[cid].get('label') or ''} "
                                        f"{clusters[cid].get('tier') or ''}")]
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

    bundles, suppressed = _bundle_edges(spec, node_root, band_pos)
    if bundles:
        notes.append(f"bundled {len(suppressed)} repetitive hub edge(s) into "
                     f"{len(bundles)} representative(s)")

    sidebar_nodes = sum(nodes_in_root.get(cid, 0) for cid in cross_roots)
    band_cols = _pick_band_cols(band_order, nodes_in_root, sidebar_nodes)
    if band_cols:
        notes.append(f"grid cols {sorted(set(band_cols.values()))[0]} chosen for "
                     f"{len(band_cols)} dense band(s) targeting ratio {TARGET_RATIO}")

    return {
        "schema": 1,
        "band_order": band_order,
        "sidebar_roots": cross_roots,
        "band_cols": band_cols,
        "edge_bundles": bundles,
        "suppressed_edges": suppressed,
        "target_ratio": TARGET_RATIO,
        "notes": notes,
    }
