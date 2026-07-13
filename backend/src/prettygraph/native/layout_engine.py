"""Declarative layout engine ported from drawio-ai-kit/src/layout-engine.mjs.

You DECLARE the nested structure (group/frame/grid + icon/box); the engine
COMPUTES all x/y/w/h — frames hug their children snugly, rows/columns spread out
evenly. NO hardcoded coordinates. Pure geometry (no I/O, no Graphviz).

    tree = group("region", "group_region", "AWS Region", {"dir": "row"}, [
        group("acc", "group_account", "Account", {"dir": "col"}, [
            icon("s3", "s3", "S3"),
        ]),
    ])
    render_tree(d, tree)          # engine lays everything out + sizes the page
    d.title("...")
    d.link("a", "b", "...")

Nodes are plain dicts (mirroring the kit's mutable JS objects); the engine sets
``w/h`` in measure and ``x/y`` in place, then emits into a Diagram builder.
"""

from __future__ import annotations

from .theme import THEME, stage_stroke

ICON = 48


# --------------------------------------------------------------------------- #
# node creators
# --------------------------------------------------------------------------- #
def icon(id, name, label="", **opts):
    return {"kind": "icon", "id": id, "name": name, "label": label, **opts}


def _auto_box(label):
    """A box auto-sizes to its label (longest wrapped line -> w, line count -> h)."""
    lines = str(label if label is not None else "").split("\n")
    max_len = max([1] + [len(l) for l in lines])
    return {
        "w": min(260, max(120, round(max_len * 6.6 + 28))),
        "h": max(44, len(lines) * 18 + 26),
    }


def box(id, label="", **opts):
    a = _auto_box(label)
    node = {"kind": "box", "id": id, "label": label, **opts}
    node["w"] = opts.get("w", a["w"])
    node["h"] = opts.get("h", a["h"])
    return node


def card(id, icon_name, title, sub="", **opts):
    """Rounded card node: catalog icon on the LEFT, bold title + grey sub-label.
    icon_name may be None (text-only card)."""
    return {"kind": "card", "id": id, "icon": icon_name or None,
            "title": title, "sub": sub, "label": title, **opts}


def group(id, gname, label="", opts=None, children=None):
    opts = opts or {}
    children = children if children is not None else []
    return {
        "kind": "group", "id": id, "gname": gname or None, "label": label,
        "children": children,
        "dir": opts.get("dir", "row"), "gap": opts.get("gap", 30),
        "pad": opts.get("pad", 24),
        "header": (opts.get("header", 36) if label else opts.get("header", 14)),
        "align": opts.get("align", "center"),
        "fill": opts.get("fill"), "stroke": opts.get("stroke"),
        "fs": opts.get("fs"),
        # a catalog icon drawn at the container's top-left (Azure/GCP frames).
        "cornerIcon": opts.get("cornerIcon"),
        # min gap enforced between children when routing lanes pass between them.
        "routeGap": opts.get("routeGap", 0),
    }


def frame(id, label, opts=None, children=None):
    """A group with no AWS stencil = a plain square frame (logical layers/bands)."""
    return group(id, None, label, opts, children)


def phantom(id, label="", opts=None, children=None):
    """Invisible layout-only wrapper: lays out like a group but emits NO mxCell;
    its children reparent to the nearest visible ancestor."""
    opts = opts or {}
    children = children if children is not None else []
    return {
        "kind": "phantom", "id": id, "gname": None, "label": label,
        "children": children,
        "dir": opts.get("dir", "row"), "gap": opts.get("gap", 30),
        "pad": opts.get("pad", 24),
        "header": (opts.get("header", 36) if label else opts.get("header", 14)),
        "align": opts.get("align", "center"),
        "fill": opts.get("fill"), "stroke": opts.get("stroke"),
        "cornerIcon": opts.get("cornerIcon"), "routeGap": opts.get("routeGap", 0),
    }


def grid(id, gname, label="", opts=None, children=None):
    """Grid of ``cols`` columns; children laid out evenly, each cell = the largest."""
    opts = opts or {}
    children = children if children is not None else []
    return {
        "kind": "grid", "id": id, "gname": gname or None, "label": label,
        "children": children,
        "cols": max(1, opts.get("cols", 2)), "gap": opts.get("gap", 30),
        "pad": opts.get("pad", 24),
        "header": (opts.get("header", 36) if label else opts.get("header", 14)),
        "fill": opts.get("fill"), "stroke": opts.get("stroke"),
    }


def pool(id, label, opts=None, children=None):
    """BPMN swimlane pool: a sparse (lane, phase) grid. Each child carries
    ``lane``/``col`` indices; empty cells stay blank."""
    opts = opts or {}
    children = children if children is not None else []
    return {
        "kind": "pool", "id": id, "gname": None, "label": label,
        "children": children,
        "lanes": opts.get("lanes", []), "phases": opts.get("phases", []),
        "orientation": opts.get("orientation", "horizontal"),
        "gap": opts.get("gap", 40), "pad": opts.get("pad", 16),
        "laneLabel": opts.get("laneLabel", 110),
        "phaseLabel": opts.get("phaseLabel", 26),
        "fill": opts.get("fill"), "stroke": opts.get("stroke"),
    }


# --------------------------------------------------------------------------- #
# themed creators (apply THEME so diagrams inherit the house style)
# --------------------------------------------------------------------------- #
def stage(id, i, label, children=None, opts=None):
    """Pipeline STAGE frame i (0-based) -> white fill, per-stage coloured border."""
    o = {"dir": "col", "gap": THEME.gap_item, "fill": THEME.base,
         "stroke": stage_stroke(i)}
    o.update(opts or {})
    return group(id, None, label, o, children or [])


def band(id, label, children=None, opts=None):
    """Cross-cutting band (governance/security/ops) — white fill, neutral border, row."""
    o = {"dir": "row", "gap": 36, "fill": THEME.base, "stroke": THEME.band_stroke}
    o.update(opts or {})
    return group(id, None, label, o, children or [])


def subnet(id, label, children=None, opts=None):
    """Subnet frame (AWS group_subnet stencil); colour comes from the label."""
    o = {"dir": "col", "gap": THEME.gap_item}
    o.update(opts or {})
    return group(id, "group_subnet", label, o, children or [])


def endpoint(id, label, opts=None):
    """Source / consumer endpoint card (entry/exit of the diagram)."""
    o = {"fill": THEME.endpoint, "stroke": THEME.endpoint_stroke, "bold": True}
    o.update(opts or {})
    return box(id, label, **o)


def oss_box(id, label, opts=None):
    """Plain OSS / component box (theme-aware white)."""
    o = {"fill": THEME.base, "stroke": THEME.base_stroke, "fs": THEME.font_small}
    o.update(opts or {})
    return box(id, label, **o)


def onprem_frame(id, label, children=None, opts=None):
    """On-premise / external site frame (AWS corporate-data-center group stencil)."""
    o = {"dir": "row", "gap": 26, "fill": THEME.base, "stroke": THEME.onprem_stroke}
    o.update(opts or {})
    return group(id, "group_corporate_data_center", label, o, children or [])


# --------------------------------------------------------------------------- #
# measure: assign w,h (bottom-up)
# --------------------------------------------------------------------------- #
def _m_icon(n):
    n["w"] = max(96, min(200, (len(n.get("label") or "")) * 7 + 24))
    n["h"] = ICON + 34  # icon + label below


def _m_box(n):
    pass  # w,h provided by box()


def _m_card(n):
    ic = 30 if n.get("icon") else 0
    text_w = max(len(n.get("title") or "") * 7.2, len(n.get("sub") or "") * 5.8)
    n["w"] = n.get("w") or round(min(260, max(150, text_w + ic + 44)))
    n["h"] = n.get("h") or 54


def _m_pool(n):
    for c in n["children"]:
        _measure(c)
    horiz = n["orientation"] != "vertical"
    lane_n = max(1, len(n["lanes"]) or 1)
    n["cols"] = max([1] + [(c.get("col", 0) + 1) for c in n["children"]])
    phase_n = len(n["phases"])
    n["phaseLabel"] = n["phaseLabel"] if phase_n else 0
    n["cellW"] = max([80] + [(c.get("w") or 0) for c in n["children"]])
    n["cellH"] = max([40] + [(c.get("h") or 0) for c in n["children"]]) + 14
    content_w = (n["cols"] * n["cellW"] + n["gap"] * (n["cols"] - 1)
                 if horiz else lane_n * n["cellW"])
    content_h = (lane_n * n["cellH"]
                 if horiz else n["cols"] * n["cellH"] + n["gap"] * (n["cols"] - 1))
    n["header"] = 34 if n["label"] else 0
    if horiz:
        n["w"] = n["pad"] * 2 + n["laneLabel"] + content_w
        n["h"] = n["header"] + n["phaseLabel"] + n["pad"] * 2 + content_h
    else:
        n["w"] = n["pad"] * 2 + content_w + n["phaseLabel"]
        n["h"] = n["header"] + n["pad"] * 2 + n["laneLabel"] + content_h
    if n["label"]:
        n["w"] = max(n["w"], (len(n["label"]) * 6.6) // 1 + n["pad"] * 2)


def _measure_container(n):
    """Shared measure for group + grid: recurse, size, floor by title width."""
    for c in n["children"]:
        _measure(c)
    ch, p, head = n["children"], n["pad"], n["header"]
    eg = max(n["gap"], n.get("routeGap", 0) or 0)

    def _sum(f):
        return sum(f(c) for c in ch)

    def _max(f):
        return max([0] + [f(c) for c in ch])

    if n["kind"] == "grid":
        import math
        rows = math.ceil(len(ch) / n["cols"]) if ch else 0
        n["cellW"] = _max(lambda c: c["w"])
        n["cellH"] = _max(lambda c: c["h"])
        n["w"] = p * 2 + n["cols"] * n["cellW"] + n["gap"] * (n["cols"] - 1)
        n["h"] = head + p * 2 + rows * n["cellH"] + n["gap"] * max(0, rows - 1)
    elif n["dir"] == "row":
        # equal-height siblings: stretch container blocks in a row to the tallest
        # so side-by-side frames share a bottom edge (leaf icons/boxes keep size).
        max_h = _max(lambda c: c["h"])
        for c in ch:
            if c["kind"] in ("group", "grid", "pool"):
                c["h"] = max(c["h"], max_h)
        n["w"] = p * 2 + _sum(lambda c: c["w"]) + eg * max(0, len(ch) - 1)
        n["h"] = head + p * 2 + _max(lambda c: c["h"])
    else:  # col
        n["w"] = p * 2 + _max(lambda c: c["w"])
        n["h"] = head + p * 2 + _sum(lambda c: c["h"]) + eg * max(0, len(ch) - 1)

    # floor by title width: a frame is never narrower than its label.
    if n["label"]:
        import math
        n["w"] = max(n["w"], math.ceil(len(n["label"]) * 6.6) + p * 2)


# --------------------------------------------------------------------------- #
# place: assign x,y (top-down)
# --------------------------------------------------------------------------- #
def _p_grid(n):
    inner_x = n["x"] + n["pad"]
    inner_top = n["y"] + n["header"] + n["pad"]
    for i, c in enumerate(n["children"]):
        r, col = divmod(i, n["cols"])
        cell_x = inner_x + col * (n["cellW"] + n["gap"])
        cell_y = inner_top + r * (n["cellH"] + n["gap"])
        _place(c, cell_x + (n["cellW"] - c["w"]) / 2,
               cell_y + (n["cellH"] - c["h"]) / 2)


def _p_pool(n):
    horiz = n["orientation"] != "vertical"
    content_x = (n["x"] + n["pad"] + n["laneLabel"] if horiz else n["x"] + n["pad"])
    content_y = (n["y"] + n["header"] + n["phaseLabel"] + n["pad"] if horiz
                 else n["y"] + n["header"] + n["pad"] + n["laneLabel"])
    for c in n["children"]:
        lane, col = c.get("lane", 0), c.get("col", 0)
        cell_x = (content_x + col * (n["cellW"] + n["gap"]) if horiz
                  else content_x + lane * n["cellW"])
        cell_y = (content_y + lane * n["cellH"] if horiz
                  else content_y + col * (n["cellH"] + n["gap"]))
        _place(c, round(cell_x + (n["cellW"] - c["w"]) / 2),
               round(cell_y + (n["cellH"] - c["h"]) / 2))


def _p_group(n):
    inner_x = n["x"] + n["pad"]
    inner_top = n["y"] + n["header"] + n["pad"]
    inner_w = n["w"] - n["pad"] * 2
    inner_h = n["h"] - n["header"] - n["pad"] * 2
    eg = max(n["gap"], n.get("routeGap", 0) or 0)
    if n["dir"] == "row":
        total_w = (sum(c["w"] for c in n["children"])
                   + eg * max(0, len(n["children"]) - 1))
        cx = inner_x + max(0, (inner_w - total_w) / 2)
        for c in n["children"]:
            cy = inner_top if n["align"] == "top" else inner_top + (inner_h - c["h"]) / 2
            _place(c, cx, cy)
            cx += c["w"] + eg
    else:
        cy = inner_top
        for c in n["children"]:
            cx = inner_x if n["align"] == "left" else inner_x + (inner_w - c["w"]) / 2
            _place(c, cx, cy)
            cy += c["h"] + eg


# --------------------------------------------------------------------------- #
# emit: output into the Diagram builder
# --------------------------------------------------------------------------- #
def _e_icon(d, n, parent):
    d.icon(n["id"], n["name"], [round(n["x"] + (n["w"] - ICON) / 2), n["y"]],
           parent=parent, label=n["label"])


def _e_box(d, n, parent):
    if n.get("style"):  # curated raw style (e.g. BPMN) — leaf obstacle
        r = d._put(n["id"], parent, n["x"], n["y"], n["w"], n["h"], n["style"], n["label"])
        r["ob"] = True
        return
    d.box(n["id"], [n["x"], n["y"]], [n["w"], n["h"]], n["label"], parent=parent,
          fill=n.get("fill"), stroke=n.get("stroke"), round=n.get("round", False),
          va=n.get("va", "middle"), bold=n.get("bold", False), fs=n.get("fs", 11))


def _e_group(d, n, parent):
    if n.get("gname"):
        d.group(n["id"], n["gname"], [n["x"], n["y"]], [n["w"], n["h"]], n["label"],
                parent=parent, fill=n.get("fill"), stroke=n.get("stroke"))
    elif n.get("cornerIcon"):
        ci = 22
        style = (f"rounded=0;whiteSpace=wrap;html=1;fillColor={n.get('fill') or '#FFFFFF'};"
                 f"strokeColor={n.get('stroke') or '#999999'};fontColor=#1A1A1A;fontSize=12;"
                 f"fontStyle=1;verticalAlign=top;align=left;spacingLeft={ci + 12};spacingTop=8;")
        r = d._put(n["id"], parent, n["x"], n["y"], n["w"], n["h"], style, n["label"])
        r["ob"] = False
        d.corner_icon(f"{n['id']}__ci", n["cornerIcon"],
                      [round(n["x"] + 8), round(n["y"] + 7)], ci, n["id"])
    else:
        # stroke "none" = layout-only wrapper (no border) -> ob None so router ignores it.
        d.box(n["id"], [n["x"], n["y"]], [n["w"], n["h"]], n["label"], parent=parent,
              va="top", bold=True, fill=n.get("fill") or "#FFFFFF",
              stroke=n.get("stroke") or "#999999",
              ob=(None if n.get("stroke") == "none" else False))
    for c in n["children"]:
        _emit(d, c, n["id"])


def _e_phantom(d, n, parent):
    d.phantoms.add(n["id"])
    for c in n["children"]:
        _emit(d, c, parent)  # reparent children straight through to visible ancestor


def _e_pool(d, n, parent):
    _emit_pool(d, n, parent)


def _emit_pool(d, n, parent):
    horiz = n["orientation"] != "vertical"
    lane_n = max(1, len(n["lanes"]) or 1)
    cols = n["cols"]
    phase_n = len(n["phases"])
    content_w = (cols * n["cellW"] + n["gap"] * (cols - 1) if horiz else lane_n * n["cellW"])
    content_h = (lane_n * n["cellH"] if horiz else cols * n["cellH"] + n["gap"] * (cols - 1))
    content_x = (n["x"] + n["pad"] + n["laneLabel"] if horiz else n["x"] + n["pad"])
    content_y = (n["y"] + n["header"] + n["phaseLabel"] + n["pad"] if horiz
                 else n["y"] + n["header"] + n["pad"] + n["laneLabel"])
    pool_fill = n.get("fill") or "#FFFFFF"
    pool_stroke = n.get("stroke") or "#5A6B7B"
    hair, band_alt, label_fill = "#D8E0E8", "#F5F8FB", "#EEF2F7"

    def _frame(fid, x, y, w, h, style, label):
        return d._put(fid, n["id"], round(x), round(y), round(w), round(h), style, label)

    d.box(n["id"], [n["x"], n["y"]], [n["w"], n["h"]], n["label"], parent=parent,
          fill=pool_fill, stroke=pool_stroke, round=False, ob=False, va="top",
          bold=True, fs=13)
    for i in range(lane_n):
        if horiz:
            _frame(f"{n['id']}__band{i}", content_x, content_y + i * n["cellH"],
                   content_w, n["cellH"],
                   f"rounded=0;whiteSpace=wrap;html=1;fillColor={band_alt if i % 2 else '#FFFFFF'};"
                   f"strokeColor={hair};container=1;", "")
        else:
            _frame(f"{n['id']}__band{i}", n["x"] + n["pad"] + i * n["cellW"], content_y,
                   n["cellW"], content_h,
                   f"rounded=0;whiteSpace=wrap;html=1;fillColor={band_alt if i % 2 else '#FFFFFF'};"
                   f"strokeColor={hair};container=1;", "")
        if horiz:
            lx, ly, lw, lh = n["x"] + n["pad"], content_y + i * n["cellH"], n["laneLabel"], n["cellH"]
        else:
            lx, ly, lw, lh = n["x"] + n["pad"] + i * n["cellW"], n["y"] + n["header"] + n["pad"], n["cellW"], n["laneLabel"]
        _frame(f"{n['id']}__lane{i}", lx, ly, lw, lh,
               f"rounded=0;whiteSpace=wrap;html=1;fillColor={label_fill};strokeColor={hair};"
               "verticalAlign=middle;align=center;fontStyle=1;fontSize=11;container=1;",
               n["lanes"][i] if i < len(n["lanes"]) else "")
    if phase_n:
        for j in range(phase_n):
            frm = (j * cols) // phase_n
            to = ((j + 1) * cols) // phase_n
            last = j == phase_n - 1
            if horiz:
                px = content_x + frm * (n["cellW"] + n["gap"])
                pw = (to - frm) * (n["cellW"] + n["gap"]) - (n["gap"] if last else 0)
                py, ph = n["y"] + n["header"], n["phaseLabel"]
            else:
                py = content_y + frm * (n["cellH"] + n["gap"])
                ph = (to - frm) * (n["cellH"] + n["gap"]) - (n["gap"] if last else 0)
                px, pw = n["x"] + n["pad"] + content_w + n["gap"], n["phaseLabel"]
            _frame(f"{n['id']}__phase{j}", px, py, pw, ph,
                   f"rounded=0;whiteSpace=wrap;html=1;fillColor={pool_fill};strokeColor={hair};"
                   "verticalAlign=middle;align=center;fontStyle=1;fontSize=11;container=1;",
                   n["phases"][j] if j < len(n["phases"]) else "")
    for c in n["children"]:
        _emit(d, c, n["id"])


# --------------------------------------------------------------------------- #
# per-kind registry + dispatch
# --------------------------------------------------------------------------- #
_LAYOUT = {
    "icon":    {"measure": _m_icon,            "place": None,     "emit": _e_icon},
    "box":     {"measure": _m_box,             "place": None,     "emit": _e_box},
    "group":   {"measure": _measure_container, "place": _p_group, "emit": _e_group},
    "grid":    {"measure": _measure_container, "place": _p_grid,  "emit": _e_group},
    "pool":    {"measure": _m_pool,            "place": _p_pool,  "emit": _e_pool},
    "phantom": {"measure": _measure_container, "place": _p_group, "emit": _e_phantom},
}


def _measure(n):
    _LAYOUT[n["kind"]]["measure"](n)


def _place(n, x, y):
    n["x"], n["y"] = round(x), round(y)  # set for ALL kinds (even icon/box)
    t = _LAYOUT[n["kind"]]
    if t["place"]:
        t["place"](n)


def _emit(d, n, parent):
    _LAYOUT[n["kind"]]["emit"](d, n, parent)


def render_tree(d, root, origin=(40, 70)):
    """Compute the layout for the tree + emit into Diagram d; auto-set the page."""
    x, y = origin
    _measure(root)
    _place(root, x, y)
    _emit(d, root, "1")
    d.page = [round(root["x"] + root["w"] + 40), round(root["y"] + root["h"] + 50)]
    return root
