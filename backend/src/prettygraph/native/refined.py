"""Refined-preset page composition (playbook look).

Builds the flat typographic document page from a render_spec: header stack
(title / subtitle / backbone strip) -> numbered tinted zones with folder tabs
(main flow left->right, operations band below, outcomes/future sidebar right)
-> visual cloud/VPC boundaries -> semantic glue notes -> legend footer.

Deliberately NOT routed through layout_engine's measure/place tree: the refined
grammar is a page template with a fixed vertical rhythm, not a recursive
container tree. Reuses the Diagram emitters (Stage 1) and the deterministic
edge router (router.build_edges via Diagram.to_xml).

Everything is emitted flat (parent="1", absolute coords) with semantic ids
(zone_* / tab_* / note_* / e_<src>_<tgt>), matching the reference recipe.
"""

from __future__ import annotations

import re

from .builder import Diagram, Z_CHROME
from . import refined_theme as RT

# Role inference when the spec doesn't say (playbook §5 inventory classes).
_OPS_RX = re.compile(r"security|iam\b|monitor|logging|log\b|cloudwatch|governance"
                     r"|compliance|audit|ci[-/ ]?cd|operation|devops|observ"
                     r"|identity|access|foundation", re.I)
# Entry-ish zones ("NETWORK & SECURITY", "ACCESS & EDGE") carry main-flow
# traffic — they beat the ops match (reference: zone 2 sits in the main row).
_ENTRY_RX = re.compile(r"network|ingress|\bedge\b|gateway", re.I)
_OUTCOME_RX = re.compile(r"outcome|consum|downstream|client|dashboard|notification",
                         re.I)
_FUTURE_RX = re.compile(r"future|phase\s*2|deferred|roadmap|planned", re.I)

# Boundary zone kinds recognised from the existing `zone` cluster field.
_BOUNDARY_KINDS = {"cloud": "cloud", "region": "cloud", "account": "cloud",
                   "vpc": "vpc", "az": "az", "onprem": "onprem"}

_CARD_W = 200          # standard refined card width
_CARD_PAD_H = 40       # card height base (title row + padding)
_LINE_H = 15           # per body line
_MAX_ROWS = 4          # cards per zone column before wrapping to a new column
_HEADER_Y = (22, 64, 102)   # title / subtitle / backbone strip y positions
_ZONE_TOP = 185        # top of the main zone row (leaves room for boundary tabs)
_OPS_GAP = 70          # gap between main row and the operations band
_SIDEBAR_GAP = 55      # gap between main row and the outcomes sidebar


def _wrap(text: str, width: int = 32, max_lines: int = 3) -> list[str]:
    """Split free text into short body lines (playbook §12.4)."""
    words = str(text or "").split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                break
        else:
            cur = f"{cur} {w}".strip()
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines


def _body_lines(n: dict) -> list[str]:
    body = [str(l).strip() for l in (n.get("body") or []) if str(l).strip()]
    if body:
        return body[:RT.GEO["body_lines_max"]]
    tech = str(n.get("tech") or "").strip()
    label = str(n.get("label") or "").strip()
    if tech and tech.lower() != label.lower():
        return _wrap(tech)
    return []


def _role_of(c: dict) -> str:
    role = str(c.get("role") or "").lower()
    if role in ("ops", "operations"):
        return "ops"
    if role in ("outcome", "future", "external"):
        return "sidebar" if role != "future" else "future"
    if role in ("actor", "entry", "core", "data"):
        return "main"
    text = f"{c.get('label') or ''} {c.get('tier') or ''}"
    if _FUTURE_RX.search(text):
        return "future"
    if _OPS_RX.search(text) and not _ENTRY_RX.search(text):
        return "ops"
    if _OUTCOME_RX.search(text):
        return "sidebar"
    return "main"


_SECURITY_RX = re.compile(r"security|access|iam\b|auth|identity|ingress", re.I)
_STATE_RX = re.compile(r"redis|cache|database|\bdb\b|state|queue|broker|message", re.I)


def _auto_glue(zone_id: str, cluster: dict, role: str) -> tuple[str, list[str]] | None:
    """Playbook §14 semantic glue: a short rationale note for zones whose
    purpose isn't self-evident from component names alone. Only synthesized
    when the zone has no note already (spec-authored notes always win) — pure
    heuristic on the zone's own label, safe to be generic/conservative."""
    label = str(cluster.get("label") or zone_id)
    text = f"{label} {cluster.get('tier') or ''}"
    if role == "ops" and _SECURITY_RX.search(text):
        return ("Security boundary", ["Gates what reaches downstream."])
    if role == "main" and _STATE_RX.search(text):
        return ("Runtime responsibility", ["Shared state for this pipeline stage."])
    if role == "sidebar":
        return ("Target outcome", ["Consumers act on these results."])
    return None


def _card_h(lines: list[str]) -> int:
    return _CARD_PAD_H + (8 + _LINE_H * len(lines) if lines else 8)


_MON_RX = re.compile(r"monitor|cloudwatch|logg?ing|\blogs?\b|metric|telemetry"
                     r"|alarm|observ", re.I)
_CTRL_RX = re.compile(r"\biam\b|identity|least.priv|access|policy|permission"
                      r"|secret|auth", re.I)


def _label_offset(src_r: dict, tgt_r: dict, top_bound: float | None) -> tuple[float, float] | None:
    """Nudge a same-row edge label off the direct line so it clears the source/
    target cards instead of sitting on top of them (the raw-midpoint default —
    fine for the reference's generous card gaps, not for tightly-packed
    upgraded layouts). Horizontal-dominant edges only: label goes into the open
    strip above the row (below the row if that strip is inside the zone tab).
    Vertical-dominant edges are left alone (minority case, lower risk)."""
    scx = src_r["x"] + src_r["w"] / 2
    scy = src_r["y"] + src_r["h"] / 2
    tcx = tgt_r["x"] + tgt_r["w"] / 2
    tcy = tgt_r["y"] + tgt_r["h"] / 2
    if abs(tcx - scx) < abs(tcy - scy):
        return None  # vertical-dominant: unnudged
    mid_y = (scy + tcy) / 2
    top = min(src_r["y"], tgt_r["y"])
    bottom = max(src_r["y"] + src_r["h"], tgt_r["y"] + tgt_r["h"])
    want_y = top - 20
    if top_bound is not None and want_y - 8 < top_bound:
        want_y = bottom + 18  # no room above (top of zone) -> drop below instead
    dy = want_y - mid_y
    return (0.0, dy) if abs(dy) > 1 else None


def _edge_class(e: dict, ctx: dict | None = None) -> str:
    """Semantic edge class: explicit ``flow`` wins; otherwise infer from the
    endpoints (upgraded sources rarely carry flow tags): edges touching a
    monitoring node/zone are telemetry, edges FROM an IAM/identity node are
    control, sink-to-sink fan-out in the outcomes sidebar is outcome."""
    flow = str(e.get("flow") or "").lower()
    flow = RT.FLOW_ALIAS.get(flow, flow)
    if flow in RT.EDGE_CLASSES:
        return flow
    if str(e.get("scope") or "").lower() == "future":
        return "future"
    if ctx:
        s_txt, t_txt = ctx.get("s_txt", ""), ctx.get("t_txt", "")
        label = str(e.get("label") or "")
        if _MON_RX.search(t_txt) or _MON_RX.search(label):
            return "monitoring"
        if _CTRL_RX.search(s_txt):
            return "control"
        if ctx.get("s_side") and ctx.get("t_side"):
            return "outcome"
    return "data"


def build_refined(spec: dict, plan: dict | None = None):
    """Compose the refined page. Returns (Diagram, pseudo_root_rect) — the same
    contract as topology.build_tree so build_drawio_from_spec needs no change."""
    clusters = {c["id"]: c for c in spec.get("clusters", []) if c.get("id")}
    nodes = [dict(n) for n in spec.get("nodes", []) if n.get("id")]
    edges = list(spec.get("edges", []))

    # Section collapse: real-world sources nest zones deeply (section > az >
    # subnet > card). The refined page reads best as FLAT numbered sections —
    # reassign every node in an unnumbered interior zone to its nearest
    # NUMBERED ancestor section; the interior boundary either becomes a visual
    # boundary rect (zone-tagged, node-free) or disappears.
    numbered = {cid for cid, c in clusters.items()
                if c.get("number") is not None}

    def _nearest_numbered(cid: str) -> str | None:
        cur, guard = cid, 0
        while cur and guard < 20:
            if cur in numbered:
                return cur
            cur = (clusters.get(cur) or {}).get("parent")
            guard += 1
        return None

    if numbered:
        for n in nodes:
            cid = n.get("cluster")
            if cid in clusters and cid not in numbered:
                tgt = _nearest_numbered(cid)
                if tgt:
                    n["cluster"] = tgt

    nodes_by_cluster: dict[str, list[dict]] = {}
    loose: list[dict] = []
    for n in nodes:
        cid = n.get("cluster")
        (nodes_by_cluster.setdefault(cid, []) if cid in clusters
         else loose).append(n)
    if loose:
        clusters.setdefault("__misc", {"id": "__misc", "label": "Components"})
        nodes_by_cluster.setdefault("__misc", []).extend(loose)

    children_of: dict[str, list[str]] = {}
    for cid, c in clusters.items():
        pid = c.get("parent")
        if pid and pid in clusters and pid != cid:
            children_of.setdefault(pid, []).append(cid)

    # Boundary clusters (cloud/vpc/az wrappers with children) render as visual
    # rects over their member zones; every other cluster with nodes is a zone.
    def _descendant_zones(cid: str) -> list[str]:
        out = []
        for ch in children_of.get(cid, []):
            out += ([ch] if ch in zone_ids else []) + _descendant_zones(ch)
        return out

    # A zone-tagged wrapper WITH direct nodes stays a zone (a boundary would
    # orphan its nodes); only childful, node-free wrappers become boundaries.
    boundary_ids = [cid for cid, c in clusters.items()
                    if _BOUNDARY_KINDS.get(str(c.get("zone") or "").lower())
                    and children_of.get(cid) and not nodes_by_cluster.get(cid)]
    zone_ids = [cid for cid in clusters
                if cid not in boundary_ids and nodes_by_cluster.get(cid)]

    # Split zones by role; keep spec (or plan band_order) sequence inside groups.
    order = list(zone_ids)
    if plan and plan.get("band_order"):
        planned = [z for z in plan["band_order"] if z in order]
        order = planned + [z for z in order if z not in planned]
    mains = [z for z in order if _role_of(clusters[z]) == "main"]
    ops = [z for z in order if _role_of(clusters[z]) == "ops"]
    sides = [z for z in order if _role_of(clusters[z]) in ("sidebar", "future")]
    if not mains:  # never render an empty main row
        mains, ops, sides = order, [], []
    # Main-flow order: the source's own section numbers are the author's reading
    # order — sort by them first (stable, so plan/spec order breaks ties among
    # duplicates and unnumbered zones sink to the end).
    def _num_key(z: str):
        n = clusters[z].get("number")
        return int(n) if str(n).isdigit() else 999
    mains.sort(key=_num_key)

    # ---- auto-glue (playbook §14): one note per category, first match wins,
    # never overriding a spec-authored note ---- #
    used_glue: set[str] = set()
    for z in mains + ops + sides:
        role = _role_of(clusters[z])
        cat = ("sidebar" if role == "sidebar"
               else "security" if role == "ops" else "state")
        if cat in used_glue:
            continue
        if any(str(n.get("kind") or "") == "note" for n in nodes_by_cluster.get(z, [])):
            used_glue.add(cat)  # spec already covers this category here
            continue
        glue = _auto_glue(z, clusters[z], role)
        if glue:
            title, lines = glue
            nodes_by_cluster.setdefault(z, []).append(
                {"id": f"note_auto_{z}", "cluster": z, "kind": "note",
                 "label": title, "body": lines})
            used_glue.add(cat)

    # ---- measure zones ---- #
    def _zone_geom(zid: str, horizontal: bool = False) -> dict:
        members = nodes_by_cluster.get(zid, [])
        cards = [(n, _body_lines(n)) for n in members]
        if horizontal:
            w = 30 + sum(min(300, max(150, _CARD_W)) + 14 for _ in cards)
            h = 40 + max((_card_h(l) for _, l in cards), default=60) + 20
        else:
            cols = max(1, (len(cards) + _MAX_ROWS - 1) // _MAX_ROWS)
            per_col = (len(cards) + cols - 1) // cols or 1
            col_hs = []
            for ci in range(cols):
                chunk = cards[ci * per_col:(ci + 1) * per_col]
                col_hs.append(sum(_card_h(l) + RT.GEO["card_gap"] for _, l in chunk))
            w = cols * _CARD_W + (cols + 1) * RT.GEO["zone_pad"]
            h = 46 + (max(col_hs) if col_hs else 60) + 6
        return {"cards": cards, "w": max(w, 170), "h": max(h, 120)}

    geo_main = {z: _zone_geom(z) for z in mains}
    geo_side = {z: _zone_geom(z) for z in sides}

    d = Diagram(spec.get("pattern", "pipeline"), contract="bake", flat=True,
                page=(RT.GEO["page_w"], RT.GEO["page_h"]))
    d.grid = True
    margin = RT.GEO["margin"]

    # ---- place main zones: left->right rows of ≤6 (playbook aspect target) ---- #
    n_rows = max(1, -(-len(mains) // 6))
    per_row = -(-len(mains) // n_rows) if mains else 1
    zone_rects: dict[str, dict] = {}
    ry = _ZONE_TOP
    main_right = margin
    for r in range(n_rows):
        row = mains[r * per_row:(r + 1) * per_row]
        if not row:
            continue
        row_h = max(geo_main[z]["h"] for z in row)
        for z in row:
            geo_main[z]["h"] = row_h  # aligned zone bottoms per row
        x = margin
        for z in row:
            g = geo_main[z]
            zone_rects[z] = {"x": x, "y": ry, "w": g["w"], "h": row_h}
            x += g["w"] + RT.GEO["zone_gap"]
        main_right = max(main_right, x - RT.GEO["zone_gap"])
        ry += row_h + RT.GEO["zone_gap"] + RT.GEO["tab_overlap"]
    main_bottom = ry - RT.GEO["zone_gap"] - RT.GEO["tab_overlap"]

    # ---- sidebar (outcomes / future) ---- #
    sx = main_right + _SIDEBAR_GAP
    sy = _ZONE_TOP
    for z in sides:
        g = geo_side[z]
        zone_rects[z] = {"x": sx, "y": sy, "w": g["w"], "h": g["h"]}
        sy += g["h"] + RT.GEO["zone_gap"] + RT.GEO["tab_overlap"]
    content_right = (sx + max((g["w"] for g in geo_side.values()), default=0)
                     if sides else main_right)

    # ---- operations band: ops zones share ONE horizontal band row (the
    # reference's cross-cutting strip), wrapping to a second row if needed ---- #
    ops_rects: dict[str, dict] = {}
    oy = max(main_bottom, (sy - RT.GEO["zone_gap"] - RT.GEO["tab_overlap"])
             if sides else 0) + _OPS_GAP
    avail = max(main_right, content_right) - margin
    ox, row_h_ops = margin, 0
    for z in ops:
        g = _zone_geom(z, horizontal=True)
        w = min(g["w"], avail)
        if ox > margin and ox + w > margin + avail:  # wrap band row
            oy += row_h_ops + RT.GEO["zone_gap"] + RT.GEO["tab_overlap"]
            ox, row_h_ops = margin, 0
        ops_rects[z] = {"x": ox, "y": oy, "w": w, "h": g["h"], "cards": g["cards"]}
        zone_rects[z] = ops_rects[z]
        ox += w + RT.GEO["zone_gap"]
        row_h_ops = max(row_h_ops, g["h"])
    content_bottom = max([r["y"] + r["h"] for r in zone_rects.values()] or [600])

    # ---- emit boundaries first (behind zones, same z-bucket, stable order) ---- #
    for bid in boundary_ids:
        members = [zone_rects[z] for z in _descendant_zones(bid)]
        if not members:
            continue
        pad = 25
        bx = min(r["x"] for r in members) - pad
        by = min(r["y"] for r in members) - pad - RT.GEO["tab_overlap"]
        bw = max(r["x"] + r["w"] for r in members) + pad - bx
        bh = max(r["y"] + r["h"] for r in members) + pad - by
        kind = _BOUNDARY_KINDS[str(clusters[bid].get("zone")).lower()]
        d.boundary_rect(f"bnd_{bid}", [bx, by], [bw, bh], kind,
                        clusters[bid].get("label") or kind.upper())

    # ---- emit zones + cards ---- #
    hue_i = 0
    legend_flows: list[str] = []
    zone_order = mains + sides + ops
    # Zone numbering: honour spec numbers only when they form a clean unique
    # 1..n sequence (real-world sources routinely carry duplicate section
    # numbers — the playbook demands a coherent reading order, so renumber).
    given = [clusters[z].get("number") for z in zone_order]
    ints = [int(n) for n in given if str(n).isdigit()]
    use_given = (len(ints) == len(zone_order)
                 and sorted(ints) == list(range(1, len(ints) + 1)))
    if use_given:
        zone_order = [z for _, z in sorted(zip(ints, zone_order))]
    zone_no = {z: (int(clusters[z]["number"]) if use_given else i + 1)
               for i, z in enumerate(zone_order)}
    for z in zone_order:
        c = clusters[z]
        rect = zone_rects[z]
        role = _role_of(c)
        hue = str(c.get("hue") or "").lower()
        if hue not in RT.ZONE_HUES:
            if role == "ops":
                hue = "slate"
            elif role in ("sidebar", "future"):
                hue = "green" if role == "sidebar" else "slate"
            else:
                hue = RT.HUE_ORDER[hue_i % (len(RT.HUE_ORDER) - 1)]
                hue_i += 1
        num = zone_no[z]
        zid = z if str(z).startswith("zone_") else f"zone_{z}"
        d.tab_zone(zid, [rect["x"], rect["y"]], [rect["w"], rect["h"]],
                   str(c.get("label") or z).upper(), hue, number=num)
        scope = str(c.get("scope") or ("future" if role == "future" else "")).upper()
        if scope:
            pw = max(60, len(scope) * 6 + 24)
            d.pill(f"tag_{z}", [rect["x"] + rect["w"] - pw - 8, rect["y"] - 11],
                   [pw, 22], scope.replace("_", " "), fill="#FFFFFF",
                   stroke=RT.ZONE_HUES[hue][1],
                   font_color=RT.ZONE_HUES[hue][0], fs=9)
        stroke = RT.CARD_STROKES.get(hue, "#D0D5DD")
        cards = (ops_rects[z]["cards"] if z in ops_rects
                 else geo_main.get(z, geo_side.get(z, {})).get("cards", []))
        if z in ops_rects:  # horizontal band
            cx = rect["x"] + RT.GEO["zone_pad"] + 6
            n_cards = max(1, len(cards))
            cw = min(320, max(170, (rect["w"] - 40 - 14 * n_cards) // n_cards))
            for n, lines in cards:
                h = _card_h(lines)
                if str(n.get("kind") or "") == "note":
                    d.note_card(n["id"], [cx, rect["y"] + 40], [cw, h],
                                n.get("label") or n["id"], lines, stroke=stroke)
                else:
                    d.rich_card(n["id"], [cx, rect["y"] + 40], [cw, h],
                                n.get("label") or n["id"], lines, stroke=stroke,
                                dashed=str(n.get("scope") or "") == "future")
                cx += cw + 14
        else:  # vertical column(s)
            cols = max(1, (len(cards) + _MAX_ROWS - 1) // _MAX_ROWS)
            per_col = (len(cards) + cols - 1) // cols or 1
            for ci in range(cols):
                cy = rect["y"] + 46
                cx = rect["x"] + RT.GEO["zone_pad"] + ci * (_CARD_W + RT.GEO["zone_pad"])
                for n, lines in cards[ci * per_col:(ci + 1) * per_col]:
                    h = _card_h(lines)
                    if str(n.get("kind") or "") == "note":
                        d.note_card(n["id"], [cx, cy], [_CARD_W, h],
                                    n.get("label") or n["id"], lines, stroke=stroke)
                    else:
                        d.rich_card(n["id"], [cx, cy], [_CARD_W, h],
                                    n.get("label") or n["id"], lines, stroke=stroke,
                                    dashed=str(n.get("scope") or "") == "future")
                    cy += h + RT.GEO["card_gap"]

    # ---- header stack ---- #
    # Page hugs the content (playbook §9 canvas table: 1400x900 floor) instead
    # of forcing 1920 — small diagrams shouldn't swim in whitespace.
    page_w = max(1400, content_right + margin)
    title = (spec.get("diagram_title") or spec.get("slide_title")
             or spec.get("title") or "Architecture")
    t = d._put("__title", "1", margin, _HEADER_Y[0], page_w - 2 * margin, 42,
               f"text;html=1;whiteSpace=wrap;align=center;verticalAlign=middle;"
               f"fontFamily={RT.FONT};fontColor={RT.INK['title']};"
               f"fontSize={RT.TYPE_SCALE['title']};fontStyle=1;", title, z=Z_CHROME)
    t["ob"] = False
    subtitle = spec.get("subtitle") or ""
    if subtitle:
        s = d._put("__subtitle", "1", margin, _HEADER_Y[1], page_w - 2 * margin, 24,
                   f"text;html=1;whiteSpace=wrap;align=center;verticalAlign=middle;"
                   f"fontFamily={RT.FONT};fontColor={RT.INK['muted']};"
                   f"fontSize={RT.TYPE_SCALE['subtitle']};", subtitle, z=Z_CHROME)
        s["ob"] = False
    phases = [str(p).upper() for p in (spec.get("backbone") or []) if str(p).strip()]
    if not phases and len(mains) >= 3:
        phases = [str(clusters[z].get("label") or z).upper() for z in mains]
    if phases:
        label = "  →  ".join(phases)
        bw = min(page_w - 2 * margin, max(600, len(label) * 8))
        bb = d.pill("backbone", [round((page_w - bw) / 2), _HEADER_Y[2]], [bw, 36],
                    label, fill=RT.CHROME["strip_fill"],
                    stroke=RT.CHROME["strip_stroke"],
                    font_color=RT.INK["muted"], fs=RT.TYPE_SCALE["backbone"],
                    arc=RT.GEO["arc_zone"], ob=True)

    # ---- edges (honouring the layout plan's hub bundling, like topology) ---- #
    plan = plan or {}
    suppressed = {tuple(x) for x in plan.get("suppressed_edges", [])}
    rep_keys = {tuple(b.get("rep") or []) for b in plan.get("edge_bundles", [])}
    node_by_id = {n["id"]: n for n in nodes}
    side_set = set(sides)

    def _ectx(nid: str) -> tuple[str, bool]:
        n = node_by_id.get(nid) or {}
        cid = n.get("cluster")
        c = clusters.get(cid) or {}
        txt = f"{n.get('label') or ''} {c.get('label') or ''}"
        return txt, cid in side_set
    for e in edges:
        s, t_ = e.get("from"), e.get("to")
        sid = s if s in d.R else (f"zone_{s}" if f"zone_{s}" in d.R else s)
        tid = t_ if t_ in d.R else (f"zone_{t_}" if f"zone_{t_}" in d.R else t_)
        if sid not in d.R or tid not in d.R:
            continue
        key = (s, t_, e.get("label") or "")
        if key in suppressed:
            continue
        s_txt, s_side = _ectx(s)
        t_txt, t_side = _ectx(t_)
        cls = _edge_class(e, {"s_txt": s_txt, "t_txt": t_txt,
                              "s_side": s_side, "t_side": t_side})
        color, width, dashed = RT.EDGE_CLASSES[cls]
        if cls in RT.EDGE_LEGEND_LABELS and cls not in legend_flows:
            legend_flows.append(cls)
        label = e.get("label") or ""
        if key in rep_keys and "(all layers)" not in label:
            label = (label + " (all layers)").strip()
        if cls == "future" and "future" not in label.lower():
            label = (label + " (future)").strip()
        label_offset = None
        if label:
            src_zone = zone_rects.get(node_by_id.get(s, {}).get("cluster"))
            top_bound = (src_zone["y"] + 18) if src_zone else None
            label_offset = _label_offset(d.R[sid], d.R[tid], top_bound)
        d.link(sid, tid, label, id=f"e_{sid}_{tid}", stroke=color, dash=dashed,
               label_offset=label_offset,
               style=(f"strokeWidth={width};endArrow=block;endFill=1;"
                      f"fontFamily={RT.FONT};fontSize={RT.TYPE_SCALE['edge']};"
                      f"fontColor={RT.INK['body']};labelBackgroundColor=#FFFFFF;"))

    # ---- legend footer ---- #
    fy = content_bottom + RT.GEO["footer_lane"] + 15
    entries = [(RT.EDGE_LEGEND_LABELS[f], RT.EDGE_CLASSES[f][0],
                RT.EDGE_CLASSES[f][2]) for f in legend_flows]
    meta = spec.get("metadata") or {}
    meta_html = "<br>".join(f"<b>{k.title()}:</b> {v}" for k, v in meta.items()
                            if v) if isinstance(meta, dict) else str(meta)
    scope_note = spec.get("scope_note") or (
        "Current target architecture. Original page retained for audit and "
        "requirement comparison." if spec.get("source_page") else "")
    d.legend_band("footer", [margin, fy], page_w - 2 * margin, entries,
                  scope_note=scope_note, metadata=meta_html)

    # ---- background + page ---- #
    page_h = max(900, fy + 145 + 35)
    d.page = [page_w, page_h]
    bg = d._put("__bg", "1", 0, 0, page_w, page_h,
                f"html=1;fillColor={RT.CHROME['bg']};strokeColor=none;", "",
                z=-1)  # behind every z-bucket
    bg["ob"] = False

    root = {"x": margin, "y": _ZONE_TOP, "w": content_right - margin,
            "h": content_bottom - _ZONE_TOP}
    return d, root
