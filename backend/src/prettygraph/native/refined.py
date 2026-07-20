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
_ENTRY_RX = re.compile(
    r"network|ingress|\bedge\b|gateway|channel|source|presenting|producer|input",
    re.I)
_OUTCOME_RX = re.compile(r"outcome|consum|downstream|client|dashboard|notification",
                         re.I)
_FUTURE_RX = re.compile(r"future|phase\s*2|deferred|roadmap|planned", re.I)
# External dependency tiers (identity providers, partner SaaS, third-party APIs)
# belong in a sidebar next to what they connect to — NOT the ops/governance band,
# even though "identity"/"access" also hit the ops regex.
_EXTERNAL_RX = re.compile(r"external|third.?party|partner|\bsaas\b|vendor|"
                          r"upstream provider", re.I)
_SUPPORT_STATE_RX = re.compile(
    r"\b(data|database|storage|state|archive|ledger|replication|evidence"
    r"|content|store|stores|bucket|blob|nas)\b",
    re.I)

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


# "Hard" ops — telemetry/governance that belongs in the cross-cutting band even
# when nested inside a VPC (CloudWatch, audit). Distinct from "soft" ops words
# (security/access) that, inside a network boundary, are main-plane edge zones.
_HARD_OPS_RX = re.compile(r"monitor|cloudwatch|logg?ing|\blogs?\b|metric|telemetry"
                          r"|observ|governance|complian|audit|ci[-/ ]?cd|devops", re.I)
_NET_ZONES = {"vpc", "subnet", "subnet_public", "subnet_private", "az"}


def _inside_network(c: dict, clusters: dict | None) -> bool:
    """True if the cluster (or an ancestor) is a VPC/subnet/AZ boundary — i.e.
    it lives on the data/compute plane, not the cross-cutting ops band."""
    cur, guard = c, 0
    while cur and guard < 20:
        if str(cur.get("zone") or "").lower() in _NET_ZONES:
            return True
        cur = (clusters or {}).get(cur.get("parent"))
        guard += 1
    return False


def _role_of(c: dict, clusters: dict | None = None) -> str:
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
    # A zone inside a VPC/subnet is data-plane (main) unless it's clearly
    # telemetry/governance — this keeps "Access & Security" (edge, in-VPC) in the
    # main row while "Identity & Access" (top-level) stays in the ops band.
    if _inside_network(c, clusters):
        return "ops" if _HARD_OPS_RX.search(text) else "main"
    if _EXTERNAL_RX.search(text) and _SUPPORT_STATE_RX.search(text):
        return "ops"
    # External entry lanes (bank channels, sources, presenters) are the start of
    # the left-to-right story. Pure third-party dependencies remain sidebars.
    if _EXTERNAL_RX.search(text) and _ENTRY_RX.search(text):
        return "main"
    if _EXTERNAL_RX.search(text):
        return "sidebar"
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
    # Floor of 56px: every card now carries a 38px left icon badge, which needs
    # 8px top + ~10px bottom clearance even on title-only cards.
    return max(56, _CARD_PAD_H + (8 + _LINE_H * len(lines) if lines else 8))


_MON_RX = re.compile(r"monitor|cloudwatch|logg?ing|\blogs?\b|metric|telemetry"
                     r"|alarm|observ", re.I)
_CTRL_RX = re.compile(r"\biam\b|identity|least.priv|access|policy|permission"
                      r"|secret|auth", re.I)


def _label_box_free(cx: float, cy: float, label: str,
                    card_rects: list[dict]) -> bool:
    """True when a label box centred at (cx, cy) clears every card. Box size
    mirrors validate_drawio's edge-label estimate (6.6px/char × 14px)."""
    w = max(30.0, len(label) * 6.6)
    x0, x1 = cx - w / 2, cx + w / 2
    y0, y1 = cy - 8, cy + 8
    for r in card_rects:
        if (x0 < r["x"] + r["w"] and x1 > r["x"]
                and y0 < r["y"] + r["h"] and y1 > r["y"]):
            return False
    return True


def _label_offset(src_r: dict, tgt_r: dict, top_bound: float | None,
                  label: str = "",
                  card_rects: list[dict] | None = None) -> tuple[float, float] | None:
    """Nudge a same-row edge label off the direct line so it clears the source/
    target cards instead of sitting on top of them (the raw-midpoint default —
    fine for the reference's generous card gaps, not for tightly-packed
    upgraded layouts). Horizontal-dominant edges only: label goes into the open
    strip above the row (below the row if that strip is inside the zone tab),
    and the chosen strip is verified card-free when card_rects are supplied.
    Vertical-dominant and long cross-band edges are left to the router: their
    polylines are now A*-routed through card-free corridors, so the native
    midpoint placement already sits clear of cards."""
    scx = src_r["x"] + src_r["w"] / 2
    scy = src_r["y"] + src_r["h"] / 2
    tcx = tgt_r["x"] + tgt_r["w"] / 2
    tcy = tgt_r["y"] + tgt_r["h"] / 2
    if abs(tcx - scx) < abs(tcy - scy):
        return None  # vertical-dominant: routed corridor placement
    if abs(tcy - scy) > 80:
        return None  # long cross-band: routed corridor placement
    mid_x = (scx + tcx) / 2
    mid_y = (scy + tcy) / 2
    top = min(src_r["y"], tgt_r["y"])
    bottom = max(src_r["y"] + src_r["h"], tgt_r["y"] + tgt_r["h"])
    above, below = top - 20, bottom + 18
    candidates = [above, below] if (top_bound is None or above - 8 >= top_bound) \
        else [below, above]
    for want_y in candidates:
        dy = max(-70.0, min(70.0, want_y - mid_y))  # bounded, never a runaway
        if abs(dy) <= 1:
            continue
        if card_rects is None or _label_box_free(mid_x, mid_y + dy, label, card_rects):
            return (0.0, dy)
    return None


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


# --- refined zone content model: header/footer spanning "distributor" cards,
# subzone column frames (AZ/subnet boxes nested inside a zone), per-card
# sub-tint. This is what lifts the output from "boxes in bands" to the authored
# reference look (playbook §8.5 main-flow-plus-support, §10.3 sub-grouping). --- #
_SUBZONE_W = 176      # dashed AZ/subnet sub-frame outer width inside a zone
_SUBZONE_PAD = 10     # inner pad between sub-frame border and its cards
_SUBZONE_TOP = 26     # room at the sub-frame top for its label pill


def _card_fill_stroke(n: dict, zone_hue: str):
    """(fill, stroke) for a card: a per-card ``hue`` sub-tints it (playbook
    §10.3 — colour-sub-group a component inside a differently-hued zone, e.g.
    an orange EBS card in a teal compute zone); otherwise white on the zone's
    card stroke. fill=None => rich_card's white default."""
    h = str(n.get("hue") or "").lower()
    if h in RT.ZONE_HUES:
        return RT.ZONE_HUES[h][2], RT.CARD_STROKES.get(h, RT.ZONE_HUES[h][1])
    return None, RT.CARD_STROKES.get(zone_hue, "#D0D5DD")


def _zone_content(members: list[dict]) -> dict:
    """Partition a zone's cards into header spans, subzone/auto columns and
    footer spans. ``span``: "header"|"footer" => a full-zone-width distributor
    card. ``subzone``: str | {id,label,kind} => cards sharing it stack inside
    one dashed sub-frame column (AZ/subnet nesting)."""
    headers, footers, body = [], [], []
    for n in members:
        sp = str(n.get("span") or "").lower()
        (headers if sp == "header" else footers if sp == "footer"
         else body).append(n)
    columns: list[dict] = []
    sub_ix: dict[str, int] = {}
    plain: list[dict] = []
    for n in body:
        sz = n.get("subzone")
        if sz:
            szid = sz if isinstance(sz, str) else str(sz.get("id") or sz.get("label"))
            if szid not in sub_ix:
                sub_ix[szid] = len(columns)
                label = szid if isinstance(sz, str) else str(sz.get("label") or szid)
                kind = "az" if isinstance(sz, str) else str(sz.get("kind") or "az")
                columns.append({"sub": {"id": szid, "label": label, "kind": kind},
                                "cards": []})
            columns[sub_ix[szid]]["cards"].append(n)
        else:
            plain.append(n)
    if plain:
        pcols = max(1, (len(plain) + _MAX_ROWS - 1) // _MAX_ROWS)
        per = (len(plain) + pcols - 1) // pcols or 1
        for ci in range(pcols):
            chunk = plain[ci * per:(ci + 1) * per]
            if chunk:
                columns.append({"sub": None, "cards": chunk})
    return {"headers": headers, "footers": footers, "columns": columns}


def _col_card_w(col: dict) -> int:
    return (_SUBZONE_W - 2 * _SUBZONE_PAD) if col["sub"] else _CARD_W


def _measure_content(content: dict) -> tuple[int, int]:
    """Zone (w, h) from its content model — kept in lockstep with _emit_content."""
    gap = RT.GEO["card_gap"]
    pad = RT.GEO["zone_pad"]
    col_ws, col_hs = [], []
    for col in content["columns"]:
        col_ws.append(_col_card_w(col) + (2 * _SUBZONE_PAD if col["sub"] else 0))
        ch = (_SUBZONE_TOP if col["sub"] else 0)
        ch += sum(_card_h(_body_lines(n)) + gap for n in col["cards"]) - gap
        if col["sub"]:
            ch += _SUBZONE_PAD
        col_hs.append(max(0, ch))
    cols_w = (sum(col_ws) + gap * (len(col_ws) - 1)) if col_ws else 0
    cols_h = max(col_hs) if col_hs else 0
    hh = sum(_card_h(_body_lines(n)) + gap for n in content["headers"])
    fh = sum(_card_h(_body_lines(n)) + gap for n in content["footers"])
    w = max(cols_w, _CARD_W) + 2 * pad
    h = 46 + hh + cols_h + fh + 8
    return max(w, 170), max(h, 120)


def build_refined(spec: dict, plan: dict | None = None):
    """Compose the refined page. Returns (Diagram, pseudo_root_rect) — the same
    contract as topology.build_tree so build_drawio_from_spec needs no change."""
    clusters = {c["id"]: c for c in spec.get("clusters", []) if c.get("id")}
    nodes = [dict(n) for n in spec.get("nodes", []) if n.get("id")]
    edges = list(spec.get("edges", []))
    # diagram_types.py "sequence" preset: a numbered request walkthrough reads
    # every declared edge as a step, not just the "data"-classified subset the
    # numbered-flow badges normally chain through (a control/serving-flow hop
    # is just as much "step 3" as a data hop in a walkthrough).
    sequence_mode = str(spec.get("layout_intent", "")).lower() == "sequence"

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

    _SUB_ZONES = {"az": "az", "subnet": "subnet", "subnet_public": "subnet",
                  "subnet_private": "subnet"}

    def _interior_subzone(cid: str, tgt: str) -> dict | None:
        """The AZ/subnet the node sat in before section-collapse, so the refined
        page can redraw it as a dashed sub-frame (AZ nesting on the upgrade
        path). Prefer the AZ level; fall back to the closest subnet."""
        cur, best, guard = cid, None, 0
        while cur and cur != tgt and guard < 20:
            zk = _SUB_ZONES.get(str((clusters.get(cur) or {}).get("zone") or "").lower())
            if zk == "az":
                return {"id": cur, "label": clusters[cur].get("label") or cur, "kind": "az"}
            if zk == "subnet" and best is None:
                best = {"id": cur, "label": clusters[cur].get("label") or cur, "kind": "subnet"}
            cur = (clusters.get(cur) or {}).get("parent")
            guard += 1
        return best

    if numbered:
        for n in nodes:
            cid = n.get("cluster")
            if cid in clusters and cid not in numbered:
                tgt = _nearest_numbered(cid)
                if tgt:
                    if not n.get("subzone"):
                        sz = _interior_subzone(cid, tgt)
                        if sz:
                            n["subzone"] = sz
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

    # Main-flow order: the source's own section numbers are the author's reading
    # order — sort by them first (stable, so plan/spec order breaks ties among
    # duplicates and unnumbered zones sink to the end).
    def _num_key(z: str):
        n = clusters[z].get("number")
        return int(n) if str(n).isdigit() else 999

    role_by_zone = {z: _role_of(clusters[z], clusters) for z in order}

    def _support_state_zone(z: str) -> bool:
        c = clusters[z]
        text = f"{z} {c.get('label') or ''} {c.get('tier') or ''}"
        tier = str(c.get("tier") or "").lower()
        return tier in ("data", "storage", "database") or bool(_SUPPORT_STATE_RX.search(text))

    # Dense pipeline pages read better when passive state/data zones sit in the
    # support shelf instead of forcing a fifth main column or a short second row.
    # Explicit roles still win; this only rebalances inferred roles.
    if sum(1 for z in order if role_by_zone.get(z) == "main") > 4:
        candidates = [z for z in order
                      if role_by_zone.get(z) == "main"
                      and not clusters[z].get("role")
                      and _support_state_zone(z)]
        for z in sorted(candidates, key=_num_key, reverse=True):
            if sum(1 for x in order if role_by_zone.get(x) == "main") <= 4:
                break
            role_by_zone[z] = "ops"

    def _layout_role(z: str) -> str:
        return role_by_zone.get(z, _role_of(clusters[z], clusters))

    mains = [z for z in order if _layout_role(z) == "main"]
    ops = [z for z in order if _layout_role(z) == "ops"]
    sides = [z for z in order if _layout_role(z) in ("sidebar", "future")]
    if not mains:  # never render an empty main row
        mains, ops, sides = order, [], []
        role_by_zone = {z: "main" for z in order}
    mains.sort(key=_num_key)

    # ---- auto-glue (playbook §14): one note per category, first match wins,
    # never overriding a spec-authored note ---- #
    used_glue: set[str] = set()
    for z in mains + ops + sides:
        role = _layout_role(z)
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
                 "span": "footer", "label": title, "body": lines})
            used_glue.add(cat)

    # ---- measure zones ---- #
    def _zone_geom(zid: str, horizontal: bool = False) -> dict:
        members = nodes_by_cluster.get(zid, [])
        if horizontal:
            cards = [(n, _body_lines(n)) for n in members]
            w = 30 + sum(min(300, max(150, _CARD_W)) + 14 for _ in cards)
            h = 40 + max((_card_h(l) for _, l in cards), default=60) + 20
            return {"cards": cards, "w": max(w, 170), "h": max(h, 120)}
        content = _zone_content(members)
        w, h = _measure_content(content)
        return {"content": content, "w": w, "h": h}

    geo_main = {z: _zone_geom(z) for z in mains}
    geo_side = {z: _zone_geom(z) for z in sides}

    d = Diagram(spec.get("pattern", "pipeline"), contract="bake", flat=True,
                page=(RT.GEO["page_w"], RT.GEO["page_h"]))
    d.grid = True
    margin = RT.GEO["margin"]

    # Vendor-logo resolution: an attached icon_data_uri (GCP/Azure raster, set by
    # _bake_icon_plan) wins; otherwise resolve a native catalog stencil
    # (AWS). Cards render whichever as a small top-right badge.
    provider = str(spec.get("provider") or "").lower()
    try:
        from .topology import _resolve_node_icon as _rni, _load_catalog as _lc
        _cat = _lc() if _lc else None
    except Exception:  # noqa: BLE001
        _cat, _rni = None, None

    def _node_icon(n: dict):
        img = n.get("icon_data_uri")
        if img:
            return None, img
        name = n.get("icon")
        if not name and _cat is not None and _rni is not None:
            try:
                name = _rni(_cat, n, provider)
            except Exception:  # noqa: BLE001
                name = None
        return name, None

    # ---- place main zones: left->right rows of ≤N (playbook aspect target).
    # N is an auto_repair plan knob (refined_zones_per_row) so the deterministic
    # repair loop can trade row count against aspect ratio / page fill. ---- #
    zones_per_row = 6
    if plan:
        try:
            zpr = int(plan.get("refined_zones_per_row") or 0)
            if zpr:
                zones_per_row = min(6, max(3, zpr))
        except (TypeError, ValueError):
            pass
    n_rows = max(1, -(-len(mains) // zones_per_row))
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
    # reference's cross-cutting strip under the cloud), wrapping if needed ---- #
    # Align the band under the cloud/VPC span (zones with a boundary ancestor),
    # not the full page — otherwise it pokes out under external zones like Sources.
    def _has_boundary_ancestor(zid: str) -> bool:
        cur, guard = clusters[zid].get("parent"), 0
        while cur and guard < 20:
            if cur in boundary_ids:
                return True
            cur = (clusters.get(cur) or {}).get("parent")
            guard += 1
        return False
    cloud_mains = [z for z in mains if _has_boundary_ancestor(z) and z in zone_rects]
    if cloud_mains:
        band_left = min(zone_rects[z]["x"] for z in cloud_mains)
        band_right = max(zone_rects[z]["x"] + zone_rects[z]["w"] for z in cloud_mains)
    else:
        band_left, band_right = margin, max(main_right, content_right)
    # Composition reflow: by default the ops shelves pack across the FULL
    # content width (including under the sidebar column) so several ops zones
    # share a row and the bottom-right of the page doesn't sit empty. The
    # legacy cloud-aligned band survives behind an auto_repair plan knob.
    ops_pack = True
    if plan is not None and "refined_ops_pack" in (plan or {}):
        ops_pack = bool(plan["refined_ops_pack"])
    if ops_pack:
        band_right = max(band_right, content_right)
    ops_rects: dict[str, dict] = {}
    oy = max(main_bottom, (sy - RT.GEO["zone_gap"] - RT.GEO["tab_overlap"])
             if sides else 0) + _OPS_GAP
    avail = band_right - band_left
    ox, row_h_ops = band_left, 0
    for z in ops:
        g = _zone_geom(z, horizontal=True)
        w = min(g["w"], avail)
        if ox > band_left and ox + w > band_left + avail:  # wrap band row
            oy += row_h_ops + RT.GEO["zone_gap"] + RT.GEO["tab_overlap"]
            ox, row_h_ops = band_left, 0
        ops_rects[z] = {"x": ox, "y": oy, "w": w, "h": g["h"], "cards": g["cards"]}
        zone_rects[z] = ops_rects[z]
        ox += w + RT.GEO["zone_gap"]
        row_h_ops = max(row_h_ops, g["h"])
    content_bottom = max([r["y"] + r["h"] for r in zone_rects.values()] or [600])

    # ---- emit boundaries first (behind zones, same z-bucket, stable order) ---- #
    # Nesting depth staggers the pad so an outer boundary (AWS Cloud) extends
    # further out than an inner one (VPC) even when both wrap the same top row —
    # otherwise their folder tabs land on the same corner and overlap.
    def _b_anc(bid: str) -> int:
        n, cur, guard = 0, clusters[bid].get("parent"), 0
        while cur and guard < 20:
            if cur in boundary_ids:
                n += 1
            cur = (clusters.get(cur) or {}).get("parent")
            guard += 1
        return n
    max_anc = max((_b_anc(b) for b in boundary_ids), default=0)
    for bid in boundary_ids:
        # Wrap only main-row members: the ops band is full-width and would balloon
        # the box out under external zones; the sidebar sits outside the cloud.
        members = [zone_rects[z] for z in _descendant_zones(bid)
                   if _layout_role(z) == "main" and z in zone_rects]
        if not members:
            continue
        pad = 18 + (max_anc - _b_anc(bid)) * 22
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
        role = _layout_role(z)
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
        def _render(n, xy, wh, span=False, zone_hue=hue):
            fill, cstroke = _card_fill_stroke(n, zone_hue)
            if str(n.get("kind") or "") == "note":
                d.note_card(n["id"], xy, wh, n.get("label") or n["id"],
                            _body_lines(n), fill=fill, stroke=cstroke or "#D0D5DD")
            else:
                iname, img = (None, None) if span else _node_icon(n)
                d.rich_card(n["id"], xy, wh, n.get("label") or n["id"],
                            _body_lines(n), fill=fill, stroke=cstroke,
                            align="center" if span else "left",
                            icon_name=iname, image_data_uri=img,
                            dashed=str(n.get("scope") or "") == "future")

        if z in ops_rects:  # horizontal band
            cards = ops_rects[z]["cards"]
            cx = rect["x"] + RT.GEO["zone_pad"] + 6
            n_cards = max(1, len(cards))
            cw = min(320, max(170, (rect["w"] - 40 - 14 * n_cards) // n_cards))
            for n, lines in cards:
                _render(n, [cx, rect["y"] + 40], [cw, _card_h(lines)])
                cx += cw + 14
        else:  # vertical: header spans / subzone columns / footer spans
            content = ((geo_main.get(z) or geo_side.get(z) or {}).get("content")
                       or _zone_content(nodes_by_cluster.get(z, [])))
            pad = RT.GEO["zone_pad"]
            gap = RT.GEO["card_gap"]
            inner_x = rect["x"] + pad
            inner_w = rect["w"] - 2 * pad
            cy = rect["y"] + 46
            for n in content["headers"]:
                h = _card_h(_body_lines(n))
                _render(n, [inner_x, cy], [inner_w, h], span=True)
                cy += h + gap
            col_top = cy
            cx = inner_x
            col_bottoms = [col_top]
            for col in content["columns"]:
                cw = _col_card_w(col)
                frame_w = cw + (2 * _SUBZONE_PAD if col["sub"] else 0)
                ccx = cx + (_SUBZONE_PAD if col["sub"] else 0)
                ccy = col_top + (_SUBZONE_TOP if col["sub"] else 0)
                for n in col["cards"]:
                    h = _card_h(_body_lines(n))
                    _render(n, [ccx, ccy], [cw, h])
                    ccy += h + gap
                bottom = ccy - gap
                if col["sub"]:
                    fh = bottom - col_top + _SUBZONE_PAD
                    d.boundary_rect(f"bnd_{z}_{col['sub']['id']}", [cx, col_top],
                                    [frame_w, fh], col["sub"]["kind"],
                                    col["sub"]["label"])
                    bottom += _SUBZONE_PAD
                col_bottoms.append(bottom)
                cx += frame_w + gap
            cy = max(col_bottoms)
            for n in content["footers"]:
                h = _card_h(_body_lines(n))
                _render(n, [inner_x, cy], [inner_w, h], span=True)
                cy += h + gap

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
    rep_labels = {tuple(b.get("rep") or []): b.get("label")
                  for b in plan.get("edge_bundles", [])
                  if b.get("label")}
    # Zone-pair bundle representatives get a multiplicity tag ("×N") instead of
    # the hub bundles' "(all layers)" phrasing.
    rep_pair_count = {tuple(b.get("rep") or []): len(b.get("members") or []) + 1
                      for b in plan.get("edge_bundles", [])
                      if b.get("kind") == "pair"}
    node_by_id = {n["id"]: n for n in nodes}
    side_set = set(sides)
    # Left-to-right position of each main zone — an edge between two ADJACENT
    # main zones just follows the backbone spine, so its label is redundant and
    # only clutters the narrow inter-zone gap (playbook §13.7). Labels on edges
    # to the ops band / sidebar / skip-level zones (the non-obvious ones) stay.
    main_x_order = sorted((z for z in mains if z in zone_rects),
                          key=lambda z: zone_rects[z]["x"])
    main_pos = {z: i for i, z in enumerate(main_x_order)}

    def _ectx(nid: str) -> tuple[str, bool]:
        n = node_by_id.get(nid) or {}
        cid = n.get("cluster")
        c = clusters.get(cid) or {}
        txt = f"{n.get('label') or ''} {c.get('label') or ''}"
        return txt, cid in side_set
    # Obstacle rects for collision-aware label placement (computed once).
    card_rects = [r for r in d.R.values() if r.get("ob")]
    data_chain: list[tuple[str, str]] = []  # card->card data edges (flow badges)
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
        is_bundle_rep = key in rep_pair_count or key in rep_keys
        if key in rep_labels:
            label = str(rep_labels[key])
        # Playbook §13.7: only label when the relationship isn't obvious from
        # source→target. Two cards in the SAME zone are adjacent and self-evident,
        # so drop the label — this is what declutters a dense diagram's centre
        # (the colour already carries the flow type). Cross-zone flows keep labels.
        # A bundle REPRESENTATIVE is exempt: its label is the only place the
        # "(×N flows)"/"(all layers)" multiplicity tag renders, so blanking it
        # here would leave a base-less "(×3 flows)" floating with no verb.
        s_cl = node_by_id.get(s, {}).get("cluster")
        t_cl = node_by_id.get(t_, {}).get("cluster")
        if is_bundle_rep and not label:
            label = "Flows"  # bundle rep with no label of its own — give the tag a stem
        elif label and s_cl is not None and s_cl == t_cl and not is_bundle_rep:
            label = ""  # same-zone adjacency is self-evident
        elif (label and s_cl in main_pos and t_cl in main_pos
              and abs(main_pos[s_cl] - main_pos[t_cl]) == 1 and not is_bundle_rep):
            label = ""  # adjacent main zones follow the backbone L->R
        if key in rep_pair_count:
            n = rep_pair_count[key]
            if f"×{n}" not in label:
                label = (label + f" (×{n} flows)").strip()
        elif key in rep_keys and "(all layers)" not in label:
            label = (label + " (all layers)").strip()
        if cls == "future" and "future" not in label.lower():
            label = (label + " (future)").strip()
        label_offset = None
        if label:
            src_zone = zone_rects.get(node_by_id.get(s, {}).get("cluster"))
            top_bound = (src_zone["y"] + 18) if src_zone else None
            label_offset = _label_offset(d.R[sid], d.R[tid], top_bound,
                                         label, card_rects)
        # style_extra (NOT style): the class styling is appended after the
        # router's base style, so these edges go through the deterministic
        # A*/NUDGE router (obstacle avoidance, ports, baked waypoints) instead
        # of being emitted raw for draw.io to route blindly at render time.
        d.link(sid, tid, label, id=f"e_{sid}_{tid}", stroke=color, dash=dashed,
               label_offset=label_offset,
               style_extra=(f"strokeWidth={width};endArrow=block;endFill=1;"
                            f"fontFamily={RT.FONT};fontSize={RT.TYPE_SCALE['edge']};"
                            f"fontColor={RT.INK['body']};labelBackgroundColor=#FFFFFF;"))
        if ((cls == "data" or sequence_mode) and not str(sid).startswith("zone_")
                and not str(tid).startswith("zone_")):
            data_chain.append((sid, tid))

    # ---- numbered flow badges (consulting-deck reading order) ---- #
    # Walk the longest simple chain of data-class edges from the entry side and
    # drop an 18px numbered chip at each hop's source, so a client can read the
    # primary request path 1..n without tracing arrows. spec.numbered_flow=False
    # opts out.
    if spec.get("numbered_flow", True) and data_chain:
        out_map: dict[str, list[str]] = {}
        indeg: dict[str, int] = {}
        for a, b in data_chain:
            out_map.setdefault(a, []).append(b)
            indeg[b] = indeg.get(b, 0) + 1
        starts = [a for a in out_map if not indeg.get(a)]
        cur = min(starts, key=lambda a: (d.R[a]["x"], d.R[a]["y"])) if starts \
            else min(out_map, key=lambda a: (d.R[a]["x"], d.R[a]["y"]))
        seq: list[tuple[str, str]] = []
        walked: set[tuple[str, str]] = set()
        while cur in out_map and len(seq) < 9:
            nxts = [t for t in out_map[cur] if (cur, t) not in walked]
            if not nxts:
                break
            ra = d.R[cur]
            nxt = min(nxts, key=lambda t: (abs(d.R[t]["y"] - ra["y"]), d.R[t]["x"]))
            walked.add((cur, nxt))
            seq.append((cur, nxt))
            cur = nxt
        if len(seq) < 3:
            seq = []  # a 1-2 hop "chain" numbers nothing worth reading
        for i, (a, b) in enumerate(seq, 1):
            ra, rb = d.R[a], d.R[b]
            if rb["x"] >= ra["x"] + ra["w"]:          # exits right
                bx, by = ra["x"] + ra["w"] + 4, ra["y"] + ra["h"] / 2 - 21
            elif rb["x"] + rb["w"] <= ra["x"]:        # exits left
                bx, by = ra["x"] - 22, ra["y"] + ra["h"] / 2 - 21
            elif rb["y"] >= ra["y"]:                  # exits bottom
                bx, by = ra["x"] + ra["w"] / 2 + 6, ra["y"] + ra["h"] + 4
            else:                                      # exits top
                bx, by = ra["x"] + ra["w"] / 2 + 6, ra["y"] - 22
            if any(bx < r["x"] + r["w"] and bx + 18 > r["x"]
                   and by < r["y"] + r["h"] and by + 18 > r["y"]
                   for r in card_rects):
                continue  # never drop a chip ON a card — skip that hop instead
            chip = d._put(f"flow_badge_{i}", "1", bx, by, 18, 18,
                          "ellipse;html=1;fillColor=#1D4ED8;strokeColor=#FFFFFF;"
                          f"strokeWidth=1;fontFamily={RT.FONT};fontColor=#FFFFFF;"
                          "fontSize=9;fontStyle=1;align=center;verticalAlign=middle;",
                          str(i), z=Z_CHROME)
            chip["ob"] = False

    # ---- legend footer (content-sized, not full-width) ---- #
    fy = content_bottom + RT.GEO["footer_lane"] + 15
    entries = [(RT.EDGE_LEGEND_LABELS[f], RT.EDGE_CLASSES[f][0],
                RT.EDGE_CLASSES[f][2]) for f in legend_flows]
    meta = spec.get("metadata") or {}
    meta_html = "<br>".join(f"<b>{k.title()}:</b> {v}" for k, v in meta.items()
                            if v) if isinstance(meta, dict) else str(meta)
    scope_note = spec.get("scope_note") or (
        "Current target architecture. Original page retained for audit and "
        "requirement comparison." if spec.get("source_page") else "")
    # Width = what the swatches + optional meta/scope cards actually need
    # (mirrors legend_band's internal layout) — a full-width legend band for
    # three entries reads as filler on a client deliverable.
    legend_w = 30 + sum(55 + max(90, round(len(str(lbl)) * 6.5) + 10) + 30
                        for lbl, _c, _d in entries) + 20
    legend_w = max(legend_w, 25 + 280 + 20)  # never narrower than the title row
    if meta_html:
        legend_w += 240
    if scope_note:
        legend_w += 360
    legend_w = min(legend_w, page_w - 2 * margin)
    # Swatch row only -> shallow band; the 145px default exists for the
    # scope/metadata cards.
    legend_h = 145 if (meta_html or scope_note) else 100
    d.legend_band("footer", [margin, fy], legend_w, entries,
                  scope_note=scope_note, metadata=meta_html, h=legend_h)

    # ---- background + page ---- #
    page_h = max(900, fy + legend_h + 35)
    d.page = [page_w, page_h]
    bg = d._put("__bg", "1", 0, 0, page_w, page_h,
                f"html=1;fillColor={RT.CHROME['bg']};strokeColor=none;", "",
                z=-1)  # behind every z-bucket
    bg["ob"] = False

    root = {"x": margin, "y": _ZONE_TOP, "w": content_right - margin,
            "h": content_bottom - _ZONE_TOP}
    return d, root
