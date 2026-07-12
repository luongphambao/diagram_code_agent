"""Deterministic structural + design linter for .drawio files.

Catches mistakes that vision self-check is slow and unreliable at:
  - Dangling edge endpoints
  - Duplicate or reserved cell ids
  - Broken parent references
  - Invented stencil names (resIcon/grIcon not in the catalog)   [errors]
  - (warnings) Off-grid geometry, overlapping sibling nodes, missing aspect=fixed
  - (advice) aesthetics, AWS conventions, edge geometry/clearance — ported from
    drawio-ai-kit/src/core.mjs so a render+vision pass can be skipped for these.

Runs without launching draw.io — fast pre-check before visual review.

CLI usage:
  python3 validate_drawio.py diagram.drawio [--strict] [--profile aws_native|generic|auto]

Programmatic usage:
  from .validate_drawio import validate_file
  report = validate_file("/workspace/out.drawio")
  # -> {"errors": [...], "warnings": [...], "advice": [...],
  #     "error_count": N, "warning_count": N, "advice_count": N, "ok": bool}
"""
import argparse
import re
import sys
import xml.etree.ElementTree as ET

RESERVED = {"0", "1"}


def _rect(cell: ET.Element) -> tuple[float, float, float, float] | None:
    """Return (x, y, w, h) floats for a cell's geometry, or None if absent/bad."""
    g = cell.find("mxGeometry")
    if g is None:
        return None
    try:
        return (float(g.get("x", "0")), float(g.get("y", "0")),
                float(g.get("width", "nan")), float(g.get("height", "nan")))
    except ValueError:
        return None


def _overlap(a: tuple, b: tuple) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def check_page(diagram: ET.Element) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for one <diagram> page."""
    name = diagram.get("name", "?")
    model = diagram.find("mxGraphModel")
    if model is None:
        if (diagram.text or "").strip():
            return [], [f"page {name!r}: compressed, skipped (cannot lint)"]
        return [f"page {name!r}: no <mxGraphModel>"], []
    root = model.find("root")
    cells = root.findall("mxCell") if root is not None else []
    errors, warns = [], []
    ids: dict[str, ET.Element] = {}
    for c in cells:
        cid = c.get("id")
        if cid in ids:
            errors.append(f"duplicate id {cid!r}")
        ids[cid] = c
    parents = {c.get("parent") for c in cells}
    for c in cells:
        cid, parent = c.get("id"), c.get("parent")
        is_v, is_e = c.get("vertex") == "1", c.get("edge") == "1"
        if parent is not None and parent not in ids:
            errors.append(f"cell {cid!r} parent {parent!r} does not exist")
        for end in ("source", "target"):
            ref = c.get(end)
            if ref and ref not in ids:
                errors.append(f"edge {cid!r} {end} {ref!r} does not exist")
        if (is_v or is_e) and cid in RESERVED:
            errors.append(f"cell {cid!r} reuses reserved id 0/1")
        if is_v:
            r = _rect(c)
            if r is None or any(v != v for v in r):
                errors.append(f"vertex {cid!r} has missing/invalid geometry")
            else:
                x, y, w, h = r
                if w <= 0 or h <= 0:
                    warns.append(f"vertex {cid!r} non-positive size {w:g}x{h:g}")
                if x < 0 or y < 0:
                    warns.append(f"vertex {cid!r} negative position ({x:g},{y:g})")
    # Sibling overlap — only leaf vertices (containers legitimately wrap children).
    boxes = [(c.get("id"), c.get("parent"), _rect(c)) for c in cells
             if c.get("vertex") == "1" and c.get("id") not in parents and _rect(c)
             and not any(v != v for v in _rect(c))]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (ia, pa, ra), (ib, pb, rb) = boxes[i], boxes[j]
            if pa == pb and _overlap(ra, rb):
                warns.append(f"vertices {ia!r} and {ib!r} overlap")
    return errors, warns


# ----------------------------------------------------------------------------- #
# Catalog / design audits — ported from drawio-ai-kit/src/core.mjs.
# These operate on the raw XML string (regex), independent of the ET structural
# checks above, so the `advice` list matches the kit's `audit.advice` output.
# ----------------------------------------------------------------------------- #

_FAMILY = "mxgraph.aws4"
_RE_RESICON = re.compile(r"resIcon=mxgraph\.aws4\.([a-z0-9_]+)")
_RE_GRICON = re.compile(r"grIcon=mxgraph\.aws4\.([a-z0-9_]+)")
_RE_SHAPE = re.compile(r"shape=mxgraph\.aws4\.([a-zA-Z0-9_]+)")
_RE_OPENCELL = re.compile(r"<mxCell\b[^>]*?>")
_KNOWN_SHAPE_WORDS = {"resourceIcon", "resourceIcon2", "group", "groupCenter", "productIcon"}


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\b{name}="([^"]*)"', tag)
    return m.group(1) if m else None


def check_stencils(xml: str, strict: bool = False) -> tuple[list[str], list[str]]:
    """Validate every resIcon/grIcon/shape name against the catalog.

    Guards against the AI inventing stencil names (which render blank). Returns
    (errors, warnings); near matches are suggested. Degrades gracefully to no-op
    if the catalog cannot be loaded.
    """
    try:
        import drawio_catalog as dc
        cat = dc.load_catalog()
    except Exception:  # noqa: BLE001 — catalog optional; skip stencil check
        return [], []
    if not cat.valid_names:
        return [], []
    errors, warns = [], []
    incomplete = bool(cat.meta.get("incomplete"))

    def check(name: str, where: str) -> None:
        if name in cat.valid_names:
            return
        sugg = [s["name"] for s in dc.search_icon(cat, name.replace("_", " "), limit=3)]
        msg = f"Stencil not found in catalog: {_FAMILY}.{name} (at {where})"
        if sugg:
            msg += f" — suggestions: {', '.join(sugg)}"
        if strict or not incomplete:
            errors.append(msg)
        else:
            warns.append(msg + " (catalog in seed form; may be incomplete)")

    for n in _RE_RESICON.findall(xml):
        check(n, "resIcon")
    for n in _RE_GRICON.findall(xml):
        check(n, "grIcon")
    for n in (s for s in _RE_SHAPE.findall(xml) if s not in _KNOWN_SHAPE_WORDS):
        check(n, "shape")

    # lint: resourceIcon styles should carry aspect=fixed (else they distort on resize)
    for c in re.findall(r'style="[^"]*mxgraph\.aws4\.resourceIcon[^"]*"', xml):
        if "aspect=fixed" not in c:
            warns.append("resourceIcon missing 'aspect=fixed' → icon may distort when resized.")
            break
    return errors, warns


def audit_aesthetics(xml: str) -> list[str]:
    """Font-size / palette / fan-out / icon-size consistency advisories."""
    advice: list[str] = []
    font_sizes = sorted({int(m) for m in re.findall(r"fontSize=(\d+)", xml)})
    if len(font_sizes) > 4:
        advice.append(f"Too many font sizes ({len(font_sizes)}): "
                      f"[{', '.join(map(str, font_sizes))}] — limit to 3–4 sizes.")
    big = [s for s in font_sizes if s >= 16]
    if big:
        advice.append(f"Font sizes too large [{', '.join(map(str, big))}] — use ≤ 14 for labels.")

    fills: list[str] = []
    for tag in _RE_OPENCELL.findall(xml):
        st = _attr(tag, "style") or ""
        if re.search(r"mxgraph\.aws4\.(resourceIcon|group)", st):
            continue
        fm = re.search(r"fillColor=([^;\"}]+)", st)
        if fm:
            fills.append(fm.group(1).strip().lower())
    uniq_fills = list({c for c in fills if c and c not in ("none", "default")})
    if len(uniq_fills) > 8:
        advice.append(f"Palette too scattered ({len(uniq_fills)} background colors) — "
                      "use a limited palette; reserve strong colors for accents.")
    if uniq_fills and "light-dark(" not in xml:
        advice.append("Consider light-dark(...) color tokens so the diagram looks good "
                      "in both light & dark mode.")

    edges = []
    for tag in _RE_OPENCELL.findall(xml):
        if _attr(tag, "edge") != "1":
            continue
        edges.append({"source": _attr(tag, "source"), "style": _attr(tag, "style") or ""})
    by_source: dict[str, list[dict]] = {}
    for e in edges:
        if e["source"]:
            by_source.setdefault(e["source"], []).append(e)
    for src, lst in by_source.items():
        if len(lst) < 3:
            continue
        if all("rounded=1" in e["style"] for e in lst):
            advice.append(f'Fan-out branch from "{src}" ({len(lst)} edges) should use '
                          "rounded=0 (sharp corners).")
        if all(not re.search(r"(exitX|entryX)=", e["style"]) for e in lst):
            advice.append(f'Pin connection points (exitX/entryX) for the fan-out branch '
                          f'from "{src}" so the parallel edges align.')

    icon_w = [int(m) for m in re.findall(
        r'<mxCell\b[^>]*resourceIcon[^>]*>\s*<mxGeometry\b[^>]*\bwidth="([\d.]+)"', xml)]
    uniq_w = sorted(set(icon_w))
    if len(uniq_w) > 2:
        advice.append(f"Inconsistent icon sizes [{', '.join(map(str, uniq_w))}] — "
                      "use a single size (e.g. 48 or 78).")
    return advice


# AWS group nesting hierarchy: lower number = outermost.
_GROUP_LEVEL = {
    "group_aws_cloud": 0, "group_aws_cloud_alt": 0, "group_account": 0,
    "group_corporate_data_center": 0, "group_on_premise": 0, "group_region": 0,
    "group_vpc": 2, "group_vpc2": 2, "group_availability_zone": 3,
    "group_subnet": 4, "group_security_group": 5,
}

# Managed / global AWS services that belong in the AWS Cloud band, NOT nested
# inside a VPC/subnet (rules/aws-architecture.md: "Managed/global services live
# outside the VPC"). Kept tight to the unambiguously-global ones to avoid false
# positives. Stencil names as they appear in mxgraph.aws4.*.
_MANAGED_GLOBAL = {
    "s3", "identity_and_access_management", "key_management_service",
    "cloudwatch", "route_53", "organizations", "dynamodb", "cloudfront",
}


def audit_aws_conventions(xml: str) -> list[str]:
    """Recolored icons / wrong nesting order / rounded frames in AWS diagrams."""
    advice: list[str] = []
    try:
        import drawio_catalog as dc
        cat = dc.load_catalog()
    except Exception:  # noqa: BLE001
        cat = None

    cells = []
    for tag in _RE_OPENCELL.findall(xml):
        cells.append({"id": _attr(tag, "id"), "parent": _attr(tag, "parent"),
                      "edge": _attr(tag, "edge"), "style": _attr(tag, "style") or ""})
    by_id = {c["id"]: c for c in cells if c["id"]}

    if cat:
        for c in cells:
            m = re.search(r"resIcon=mxgraph\.aws4\.([a-zA-Z0-9_]+)", c["style"])
            if not m:
                continue
            entry = cat.by_name.get(m.group(1))
            if not entry or not entry.get("color"):
                continue
            fm = re.search(r"fillColor=([^;]+)", c["style"])
            if not fm:
                continue
            used = fm.group(1).strip().lower()
            if used.startswith("light-dark"):
                continue
            if used != str(entry["color"]).strip().lower():
                advice.append(f'Icon "{m.group(1)}" recolored (fillColor={fm.group(1).strip()} '
                              f'≠ standard {entry["color"]}) — keep the category color.')

    def group_tok(style: str) -> str | None:
        m = re.search(r"grIcon=mxgraph\.aws4\.([a-zA-Z0-9_]+)", style)
        return m.group(1) if m else None

    def ancestor_levels(c: dict) -> list[int]:
        out, p, guard = [], by_id.get(c["parent"]), 0
        while p and guard < 50:
            guard += 1
            g = group_tok(p["style"])
            if g is not None and g in _GROUP_LEVEL:
                out.append(_GROUP_LEVEL[g])
            p = by_id.get(p["parent"])
        return out

    all_levels = [_GROUP_LEVEL[g] for c in cells
                  if (g := group_tok(c["style"])) is not None and g in _GROUP_LEVEL]
    for c in cells:
        g = group_tok(c["style"])
        if g is None or g not in _GROUP_LEVEL:
            continue
        lvl = _GROUP_LEVEL[g]
        if lvl == 0:
            continue
        if any(l < lvl for l in all_levels) and not any(l < lvl for l in ancestor_levels(c)):
            advice.append(f'Group "{g}" should be nested inside a higher-level group '
                          "(AWS Cloud→Region→VPC→AZ→Subnet→SG) — currently flat/wrong order.")

    rounded = [c["id"] or "?" for c in cells
               if c["edge"] != "1" and re.search(r"(?:^|;)rounded=1", c["style"])
               and "mxgraph.aws4." not in c["style"]
               and not re.search(r"(?:^|;)text;", c["style"])]
    if rounded:
        shown = ", ".join(rounded[:6]) + ("…" if len(rounded) > 6 else "")
        advice.append(f"Rounded frame(s) found ({len(rounded)}: {shown}) — "
                      "AWS diagrams use SQUARE corners; set rounded=0.")

    # Managed/global services must sit outside the VPC (rules/aws-architecture.md).
    def _enclosing_vpc(c: dict) -> str | None:
        p, guard = by_id.get(c["parent"]), 0
        while p and guard < 50:
            guard += 1
            g = group_tok(p["style"])
            if g is not None and _GROUP_LEVEL.get(g, 0) >= _GROUP_LEVEL["group_vpc"]:
                return g
            p = by_id.get(p["parent"])
        return None

    misplaced = []
    for c in cells:
        m = re.search(r"resIcon=mxgraph\.aws4\.([a-zA-Z0-9_]+)", c["style"])
        if not m or m.group(1) not in _MANAGED_GLOBAL:
            continue
        inside = _enclosing_vpc(c)
        if inside:
            misplaced.append(f"{m.group(1)} (in {inside})")
    if misplaced:
        shown = ", ".join(misplaced[:5]) + ("…" if len(misplaced) > 5 else "")
        advice.append(f"Managed/global service(s) nested inside a VPC/subnet ({shown}) — "
                      "S3/IAM/KMS/CloudWatch/Route 53/DynamoDB/CloudFront are global; "
                      "place them in the AWS Cloud band, outside the VPC.")
    return advice


def _parse_cells(xml: str) -> list[dict]:
    """Parse every mxCell with geometry + waypoints; resolve absolute coords."""
    out = []
    for ch in xml.split("<mxCell")[1:]:
        end = ch.find(">")
        head, body = ch[:end + 1], ch[end + 1:]

        def a(n: str, _h=head) -> str | None:
            m = re.search(rf'\b{n}="([^"]*)"', _h)
            return m.group(1) if m else None

        geo = None
        g = re.search(r"<mxGeometry\b[^>]*?(?:/>|>)", body)
        if g:
            t = g.group(0)
            gx = re.search(r'\bx="(-?[\d.]+)"', t)
            gy = re.search(r'\by="(-?[\d.]+)"', t)
            gw = re.search(r'\bwidth="([\d.]+)"', t)
            gh = re.search(r'\bheight="([\d.]+)"', t)
            if gx and gy and gw and gh:
                geo = {"x": float(gx.group(1)), "y": float(gy.group(1)),
                       "w": float(gw.group(1)), "h": float(gh.group(1))}
        wp = [{"x": float(m.group(1)), "y": float(m.group(2))}
              for m in re.finditer(r'<mxPoint\s+x="(-?[\d.]+)"\s+y="(-?[\d.]+)"\s*/>', body)]
        out.append({"id": a("id"), "parent": a("parent"), "source": a("source"),
                    "target": a("target"), "edge": a("edge"), "value": a("value"),
                    "style": a("style") or "", "hasPoints": 'as="points"' in body,
                    "wp": wp, "geo": geo, "absGeo": None})
    by_id = {c["id"]: c for c in out if c["id"]}
    for c in out:
        if not c["geo"]:
            continue
        ax, ay, p, guard = c["geo"]["x"], c["geo"]["y"], by_id.get(c["parent"]), 0
        while p and p["geo"] and guard < 50:
            guard += 1
            ax += p["geo"]["x"]
            ay += p["geo"]["y"]
            p = by_id.get(p["parent"])
        c["absGeo"] = {"x": ax, "y": ay, "w": c["geo"]["w"], "h": c["geo"]["h"]}
    return out


def _num(style: str, k: str):
    m = re.search(rf"(?:^|;){k}=([\d.]+)", style)
    return float(m.group(1)) if m else None


def audit_edge_labels(xml: str) -> list[str]:
    """Labels on bent (L/Z) routes without a waypoint tend to sit on the bend."""
    advice: list[str] = []
    cells = _parse_cells(xml)
    geo_of = {c["id"]: (c["absGeo"] or c["geo"]) for c in cells if c["geo"] and c["id"]}

    def point(g, fx, fy):
        return {"x": g["x"] + (fx if fx is not None else 0.5) * g["w"],
                "y": g["y"] + (fy if fy is not None else 0.5) * g["h"]}

    for c in cells:
        if c["edge"] != "1":
            continue
        label = (c["value"] or "").strip()
        if not label or c["hasPoints"]:
            continue
        sg, tg = geo_of.get(c["source"]), geo_of.get(c["target"])
        if not sg or not tg:
            continue
        ep = point(sg, _num(c["style"], "exitX"), _num(c["style"], "exitY"))
        np_ = point(tg, _num(c["style"], "entryX"), _num(c["style"], "entryY"))
        straight = abs(ep["y"] - np_["y"]) <= 8 or abs(ep["x"] - np_["x"]) <= 8
        if not straight:
            advice.append(f'Edge label "{label}" sits on a bent route (L/Z) — '
                          "add one waypoint in the middle of the corridor.")
    return advice


def audit_geometry(xml: str) -> list[str]:
    """Child spilling its frame / overlapping siblings / stacked arrowheads."""
    advice: list[str] = []
    cells = _parse_cells(xml)
    by_id = {c["id"]: c for c in cells if c["id"]}
    has_children = {c["parent"] for c in cells if c["parent"]}
    TOL = 3
    box = lambda c: c["absGeo"] or c["geo"]
    is_text = lambda c: bool(re.search(r"(?:^|;)text;", c["style"])) or c["id"] == "__title"
    is_container = lambda c: bool(re.search(r"container=1|shape=mxgraph\.aws4\.group|grIcon=", c["style"])) or c["id"] in has_children
    is_vertex = lambda c: c["edge"] != "1" and c["geo"] and c["id"] and not is_text(c)

    def contains(a, b):
        return (b["x"] >= a["x"] - TOL and b["y"] >= a["y"] - TOL
                and b["x"] + b["w"] <= a["x"] + a["w"] + TOL
                and b["y"] + b["h"] <= a["y"] + a["h"] + TOL)

    for c in cells:
        if not is_vertex(c):
            continue
        p = by_id.get(c["parent"])
        if not p or not p["geo"]:
            continue
        cb, pb = box(c), box(p)
        if (cb["x"] < pb["x"] - TOL or cb["y"] < pb["y"] - TOL
                or cb["x"] + cb["w"] > pb["x"] + pb["w"] + TOL
                or cb["y"] + cb["h"] > pb["y"] + pb["h"] + TOL):
            advice.append(f'Cell "{c["id"]}" spills outside its container "{c["parent"]}" — '
                          "enlarge the frame or shrink/reposition the child.")

    sibs_of: dict[str, list[dict]] = {}
    for c in cells:
        if not is_vertex(c) or is_container(c):
            continue
        sibs_of.setdefault(c["parent"], []).append(c)
    seen = set()
    for sibs in sibs_of.values():
        for i in range(len(sibs)):
            for j in range(i + 1, len(sibs)):
                a, b = box(sibs[i]), box(sibs[j])
                ix = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
                iy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
                if ix <= TOL or iy <= TOL:
                    continue
                if contains(a, b) or contains(b, a):
                    continue
                min_area = min(a["w"] * a["h"], b["w"] * b["h"])
                if ix * iy < min_area * 0.2:
                    continue
                key = tuple(sorted([sibs[i]["id"], sibs[j]["id"]]))
                if key in seen:
                    continue
                seen.add(key)
                advice.append(f'Cells "{sibs[i]["id"]}" and "{sibs[j]["id"]}" overlap — '
                              "space them apart.")

    entry_count: dict[str, int] = {}
    for c in cells:
        if c["edge"] != "1" or not c["target"]:
            continue
        ex = (re.search(r"entryX=([\d.]+)", c["style"]) or [None, "c"])[1]
        ey = (re.search(r"entryY=([\d.]+)", c["style"]) or [None, "c"])[1]
        k = f'{c["target"]}@{ex},{ey}'
        entry_count[k] = entry_count.get(k, 0) + 1
    for k, n in entry_count.items():
        if n > 1:
            advice.append(f'{n} edges enter "{k.split("@")[0]}" at the same point — '
                          "spread their entry points (fan-in).")
    return advice


def _segs_intersect(p1, p2, p3, p4) -> bool:
    def o(a, b, c):
        v = (b["y"] - a["y"]) * (c["x"] - b["x"]) - (b["x"] - a["x"]) * (c["y"] - b["y"])
        return (v > 0) - (v < 0)
    o1, o2, o3, o4 = o(p1, p2, p3), o(p1, p2, p4), o(p3, p4, p1), o(p3, p4, p2)
    return o1 != o2 and o3 != o4 and o1 != 0 and o2 != 0 and o3 != 0 and o4 != 0


def audit_edges(xml: str) -> list[str]:
    """Long detour connectors / tangled crossings / edges crossing unrelated nodes."""
    advice: list[str] = []
    cells = _parse_cells(xml)
    box_of = lambda c: c["absGeo"] or c["geo"]
    geo_of = {c["id"]: box_of(c) for c in cells if c["edge"] != "1" and (c["absGeo"] or c["geo"]) and c["id"]}
    if not geo_of:
        return advice
    minx = min(g["x"] for g in geo_of.values())
    miny = min(g["y"] for g in geo_of.values())
    maxx = max(g["x"] + g["w"] for g in geo_of.values())
    maxy = max(g["y"] + g["h"] for g in geo_of.values())
    W, H = max(1, maxx - minx), max(1, maxy - miny)
    center = lambda g: {"x": g["x"] + g["w"] / 2, "y": g["y"] + g["h"] / 2}

    segs = []
    for c in cells:
        if c["edge"] != "1" or not c["source"] or not c["target"]:
            continue
        s, t = geo_of.get(c["source"]), geo_of.get(c["target"])
        if not s or not t:
            continue
        segs.append({"a": center(s), "b": center(t), "src": c["source"], "tgt": c["target"]})
    if not segs:
        return advice

    longs = [e for e in segs if abs(e["a"]["y"] - e["b"]["y"]) > 0.45 * H
             or abs(e["a"]["x"] - e["b"]["x"]) > 0.55 * W]
    if len(longs) >= 3:
        names = [f'{e["src"]}→{e["tgt"]}' for e in longs[:4]]
        advice.append(f"Long connector(s) spanning most of the diagram ({len(longs)}: "
                      f"{', '.join(names)}{'…' if len(longs) > 4 else ''}) — place these "
                      "nodes closer; keep shared resources next to their consumers.")

    crossings = 0
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            e, f = segs[i], segs[j]
            if e["src"] in (f["src"], f["tgt"]) or e["tgt"] in (f["src"], f["tgt"]):
                continue
            if _segs_intersect(e["a"], e["b"], f["a"], f["b"]):
                crossings += 1
    if crossings > max(4, round(len(segs) * 0.3)):
        advice.append(f"{crossings} edge crossings — the flow looks tangled. Align the main "
                      "flow on one row (spine) and group fan-out/fan-in through a shared lane.")

    on_edge = lambda g, fx, fy: {"x": g["x"] + (fx if fx is not None else 0.5) * g["w"],
                                 "y": g["y"] + (fy if fy is not None else 0.5) * g["h"]}
    holds = lambda p, q: (q["x"] >= p["x"] - 2 and q["y"] >= p["y"] - 2
                          and q["x"] + q["w"] <= p["x"] + p["w"] + 2
                          and q["y"] + q["h"] <= p["y"] + p["h"] + 2)

    def seg_hits_rect(a, b, r):
        ix = min(r["w"], r["h"]) * 0.3
        return (max(a["x"], b["x"]) > r["x"] + ix and min(a["x"], b["x"]) < r["x"] + r["w"] - ix
                and max(a["y"], b["y"]) > r["y"] + ix and min(a["y"], b["y"]) < r["y"] + r["h"] - ix)

    has_children = {c["parent"] for c in cells if c["parent"]}
    is_container = lambda c: c["id"] in has_children or bool(
        re.search(r"container=1|shape=mxgraph\.aws4\.group|grIcon=", c["style"]))
    vts = [{"id": c["id"], "r": box_of(c)} for c in cells
           if c["edge"] != "1" and c["id"] and (c["absGeo"] or c["geo"])
           and not is_container(c) and not re.search(r"(?:^|;)text;", c["style"])]
    vts = [v for v in vts if v["r"]["w"] > 2 and v["r"]["h"] > 2]
    hit: dict[str, None] = {}  # insertion-ordered set (mirror JS Set order)
    for c in cells:
        if c["edge"] != "1" or not c["source"] or not c["target"]:
            continue
        sg, tg = geo_of.get(c["source"]), geo_of.get(c["target"])
        if not sg or not tg:
            continue
        poly = ([on_edge(sg, _num(c["style"], "exitX"), _num(c["style"], "exitY"))]
                + (c["wp"] or [])
                + [on_edge(tg, _num(c["style"], "entryX"), _num(c["style"], "entryY"))])
        for v in vts:
            if v["id"] in (c["source"], c["target"]):
                continue
            if holds(v["r"], sg) or holds(v["r"], tg):
                continue
            for i in range(len(poly) - 1):
                if seg_hits_rect(poly[i], poly[i + 1], v["r"]):
                    hit[f'{c["source"]}→{c["target"]} ⟂ {v["id"]}'] = None
                    break
    if hit:
        shown = ", ".join(list(hit)[:4]) + ("…" if len(hit) > 4 else "")
        advice.append(f"Edge(s) run THROUGH a node they don't connect to ({shown}) — "
                      "keep clearance: route around it or move the node.")

    # Floating arrowheads: an edge anchored to a transparent leaf (not a real
    # container). has_children guards out AWS Cloud/Region/AZ/VPC group frames —
    # those legitimately use fillColor=none.
    def _is_empty_leaf(c: dict) -> bool:
        if c["edge"] == "1" or c["id"] in has_children:
            return False
        style = c["style"] or ""
        if re.search(r"(?:^|;)text;", style) or c["id"] == "__title":
            return False
        return "fillColor=none" in style and "grIcon=" not in style

    empty_leaves = {c["id"] for c in cells if c["id"] and _is_empty_leaf(c)}
    floaters: list[str] = []
    for c in cells:
        if c["edge"] != "1":
            continue
        if c["target"] and c["target"] in empty_leaves:
            floaters.append(f'{c["source"]}→{c["target"]}')
        if c["source"] and c["source"] in empty_leaves:
            floaters.append(f'{c["source"]}→{c["target"]} (source)')
    if floaters:
        uniq = list(dict.fromkeys(floaters))
        shown = ", ".join(uniq[:4]) + ("…" if len(floaters) > 4 else "")
        advice.append(f"Edge(s) connect to an invisible leaf node ({shown}) — "
                      "anchor to a solid icon card instead of a transparent placeholder.")
    return advice


def audit_xml(xml: str, profile: str = "auto") -> list[str]:
    """Run the design audits and return the combined advice list.

    profile:
      - "aws_native": run all audits (recolor/nesting/rounded-frame conventions).
      - "generic":    skip AWS-specific conventions (keep aesthetics + geometry + edges).
      - "auto":       aws_native if the XML uses mxgraph.aws4.*, else generic.
    """
    if profile == "auto":
        profile = "aws_native" if "mxgraph.aws4." in xml else "generic"
    advice = audit_aesthetics(xml)
    if profile == "aws_native":
        advice += audit_aws_conventions(xml)
    advice += audit_edge_labels(xml)
    advice += audit_geometry(xml)
    advice += audit_edges(xml)
    return advice


def validate_file(path: str, profile: str = "auto") -> dict:
    """Lint a .drawio file. Returns a report dict with errors, warnings, advice, ok."""
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError) as exc:
        return {"errors": [f"cannot parse file: {exc}"], "warnings": [], "advice": [],
                "error_count": 1, "warning_count": 0, "advice_count": 0, "ok": False}
    pages = tree.getroot().findall("diagram") or [tree.getroot()]
    errors, warns = [], []
    for page in pages:
        e, w = check_page(page)
        errors += e
        warns += w
    advice: list[str] = []
    try:
        xml = ""
        try:
            xml = open(path, encoding="utf-8").read()
        except OSError:
            xml = ""
        if xml and "</mxGraphModel>" in xml:  # skip compressed/empty pages
            se, sw = check_stencils(xml)
            errors += se
            warns += sw
            advice = audit_xml(xml, profile)
    except Exception:  # noqa: BLE001 — design audits are best-effort
        pass
    return {
        "errors": errors,
        "warnings": warns,
        "advice": advice,
        "error_count": len(errors),
        "warning_count": len(warns),
        "advice_count": len(advice),
        "ok": len(errors) == 0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Lint a .drawio file for structural + design issues.")
    ap.add_argument("file")
    ap.add_argument("--strict", action="store_true", help="treat warnings as failure too")
    ap.add_argument("--profile", default="auto", choices=["auto", "aws_native", "generic"],
                    help="which design audits to run (default: auto-detect)")
    args = ap.parse_args()
    try:  # advice/warnings contain unicode (≤, →) — force UTF-8 on Windows consoles
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    report = validate_file(args.file, profile=args.profile)
    for a in report["advice"]:
        print(f"advice: {a}")
    for w in report["warnings"]:
        print(f"warning: {w}")
    for e in report["errors"]:
        print(f"error: {e}")
    print(f"{report['error_count']} error(s), {report['warning_count']} warning(s), "
          f"{report['advice_count']} advice")
    if not report["ok"] or (args.strict and report["warning_count"]):
        sys.exit(1)


def findings_from_validation(result: dict) -> list:
    """Convert validate_file() result → list[SolutionFinding] for the finding_store lifecycle.

    Errors become diagram_structural/patch_blueprint (high severity — must fix).
    Warnings become diagram_layout/auto_repair (medium — can auto-fix or waive).
    Advice becomes diagram_style/none (low — informational, no action required).
    entity_ids is intentionally empty; stable_finding_id keys on dimension+title so
    the same defect produces the same SF- id across runs.
    """
    from solution_validator import SolutionFinding
    findings = []
    for msg in result.get("errors", []):
        findings.append(SolutionFinding(
            severity="high",
            dimension="diagram_structural",
            artifact_type="blueprint",
            entity_ids=[],
            title=msg[:120],
            detail=msg,
            repair_strategy="patch_blueprint",
        ))
    for msg in result.get("warnings", []):
        findings.append(SolutionFinding(
            severity="medium",
            dimension="diagram_layout",
            artifact_type="blueprint",
            entity_ids=[],
            title=msg[:120],
            detail=msg,
            repair_strategy="auto_repair",
        ))
    for msg in result.get("advice", []):
        findings.append(SolutionFinding(
            severity="low",
            dimension="diagram_style",
            artifact_type="blueprint",
            entity_ids=[],
            title=msg[:120],
            detail=msg,
            repair_strategy="none",
        ))
    return findings


if __name__ == "__main__":
    main()
