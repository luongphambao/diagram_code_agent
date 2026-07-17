"""Ingest an existing .drawio file into a semantic inventory (V2 §8/§9).

The "upgrade an existing diagram" path: parse a user-supplied .drawio, extract
its semantic inventory (nodes + subtitles + edges + cluster membership) and any
EMBEDDED icon data URIs, then hand a render_spec back to the native engine so it
rebuilds the GEOMETRY (layout, cards, routing, styling) while PRESERVING the
semantics, the original ids, and the icons — never re-authoring meaning.

Two sources of truth (V2 §2.1): semantics/ids/icons come from the old file;
geometry/colour/typography/routing are rebuilt deterministically.
"""

from __future__ import annotations

import base64
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zlib

# V2 §8: reuse an embedded icon straight from the source style string.
_IMAGE_URI_RE = re.compile(r"(?:^|;)image=(data:image/[^;,]+;base64,[^;]+)")


def extract_image_uri(style: str | None) -> str | None:
    """Return the embedded ``data:image/...;base64,...`` URI in a style, or None."""
    if not style:
        return None
    m = _IMAGE_URI_RE.search(style)
    return m.group(1) if m else None


def _inflate(text: str) -> str:
    """Inflate a compressed <diagram> payload (base64 + raw deflate + url-quote),
    mirroring the export side in rendering_tools (-zlib.MAX_WBITS)."""
    raw = base64.b64decode(text)
    try:
        inflated = zlib.decompress(raw, -zlib.MAX_WBITS)
    except zlib.error:
        inflated = zlib.decompress(raw)  # fall back to zlib-wrapped
    return urllib.parse.unquote(inflated.decode("utf-8"))


def _model_roots(path: str) -> list[ET.Element]:
    """Return the <root> element of every page, inflating compressed pages."""
    tree = ET.parse(path)
    root = tree.getroot()
    roots: list[ET.Element] = []
    diagrams = root.findall("diagram") or ([root] if root.tag == "mxGraphModel" else [])
    for d in diagrams:
        model = d.find("mxGraphModel") if d.tag == "diagram" else d
        if model is None and d.tag == "diagram" and (d.text or "").strip():
            try:
                model = ET.fromstring(_inflate(d.text.strip()))
            except Exception:  # noqa: BLE001 — skip a page we cannot inflate
                model = None
        if model is not None:
            r = model.find("root") if model.tag == "mxGraphModel" else model
            if r is not None:
                roots.append(r)
    if not roots:  # bare mxGraphModel at the top
        m = root.find(".//mxGraphModel")
        if m is not None and m.find("root") is not None:
            roots.append(m.find("root"))
    return roots


def first_page_model_xml(path: str) -> str:
    """Serialize the FIRST page's <mxGraphModel> uncompressed — used by the
    refined upgrade path to append the source verbatim as an "Original Source"
    page (playbook §3: always preserve the original)."""
    root = ET.parse(path).getroot()
    if root.tag == "mxGraphModel":
        return ET.tostring(root, encoding="unicode")
    d = root.find("diagram")
    if d is None:
        raise ValueError(f"no <diagram> page in {path}")
    model = d.find("mxGraphModel")
    if model is None and (d.text or "").strip():
        model = ET.fromstring(_inflate(d.text.strip()))
    if model is None:
        raise ValueError(f"first page of {path} has no mxGraphModel")
    return ET.tostring(model, encoding="unicode")


def _split_label(value: str | None) -> tuple[str, str]:
    """(title, subtitle) from an mxCell HTML value — first line vs the rest."""
    if not value:
        return "", ""
    v = html.unescape(value)
    parts = re.split(r"<br\s*/?>|</div>|<div[^>]*>|\n", v, flags=re.I)
    lines = [re.sub(r"<[^>]+>", "", p).strip() for p in parts]
    lines = [ln for ln in lines if ln]
    if not lines:
        return "", ""
    return lines[0], " ".join(lines[1:])


def _geo(cell: ET.Element) -> dict | None:
    g = cell.find("mxGeometry")
    if g is None:
        return None
    try:
        return {"x": float(g.get("x", "0")), "y": float(g.get("y", "0")),
                "w": float(g.get("width", "0")), "h": float(g.get("height", "0"))}
    except ValueError:
        return None


def extract_inventory(path: str) -> dict:
    """Parse a .drawio into a semantic inventory dict:

    {title, provider, clusters:[{id,label}], nodes:[{id,title,sub,cluster,icon}],
     edges:[{id,source,target,label}]}.

    Nodes are ordered by source position (top-to-bottom, left-to-right) so the
    rebuild preserves the original reading order. Icons carry embedded data URIs.
    """
    cells: list[dict] = []
    for r in _model_roots(path):
        for c in r.iter("mxCell"):
            cid = c.get("id")
            if not cid or cid in ("0", "1"):
                continue
            cells.append({
                "id": cid, "parent": c.get("parent"),
                "vertex": c.get("vertex") == "1", "edge": c.get("edge") == "1",
                "source": c.get("source"), "target": c.get("target"),
                "value": c.get("value") or "", "style": c.get("style") or "",
                "geo": _geo(c),
            })
    by_id = {c["id"]: c for c in cells}
    has_children = {c["parent"] for c in cells if c["parent"]}

    def _is_container(c: dict) -> bool:
        return (c["vertex"] and c["id"] in has_children) or bool(
            re.search(r"container=1|group;|shape=.*group|swimlane", c["style"]))

    def _abs(c: dict) -> dict:
        x, y, guard = 0.0, 0.0, 0
        cur = c
        while cur and cur.get("geo") and guard < 50:
            x += cur["geo"]["x"]
            y += cur["geo"]["y"]
            cur = by_id.get(cur.get("parent"))
            guard += 1
        return {"x": x, "y": y}

    # Engine-generated decorative/chrome cells must never re-ingest as content:
    # shadows/accents/zone pills/sub-icons ("__sh"/"__ac"/"__pill"/"__ic"
    # suffixes) and grid/legend/title scaffolding ("__grid"/"__legend"/"__title").
    _DECOR = ("__sh", "__ac", "__pill", "__ic", "__grid", "__legend", "__title")

    def _is_decor(cid: str | None) -> bool:
        return bool(cid) and (cid.endswith(_DECOR) or cid.startswith(("__legend", "__title")))

    def _box(c: dict) -> dict | None:
        if not c.get("geo"):
            return None
        p = _abs(c)
        return {"x": p["x"], "y": p["y"], "w": c["geo"]["w"], "h": c["geo"]["h"]}

    def _center_in(inner: dict, outer: dict) -> bool:
        cx, cy = inner["x"] + inner["w"] / 2, inner["y"] + inner["h"] / 2
        return (outer["x"] <= cx <= outer["x"] + outer["w"]
                and outer["y"] <= cy <= outer["y"] + outer["h"])

    _ZONE_HINT = re.compile(r"\bvpc\b|\bvnet\b|availability|\baz\b"
                            r"|\bus-(east|west)-\d[a-f]?\b|\baws\b|\bazure\b"
                            r"|\bgcp\b|\bcloud\b|on[- ]?prem", re.I)

    # Clusters = container vertices; nodes = leaf vertices with a label or icon.
    clusters, nodes, edges = [], [], []
    for c in cells:
        if _is_decor(c["id"]):
            continue
        if c["vertex"] and _is_container(c):
            label, _ = _split_label(c["value"])
            clusters.append({"id": c["id"], "label": label or c["id"],
                             "_style": c["style"], "_pid": c.get("parent")})
    cluster_ids = {cl["id"] for cl in clusters}

    # SPATIAL containment inference (playbook §4): flat files (ChatGPT-style,
    # everything parent="1") express grouping purely by geometry — a labeled
    # rect drawn behind ≥2 substantial vertices IS a section/zone even though
    # nothing is XML-nested inside it. Without this, a flat source ingests as
    # one giant loose-node pile.
    vert_cells = [c for c in cells if c["vertex"] and c["geo"]
                  and not _is_decor(c["id"])]
    boxes = {c["id"]: _box(c) for c in vert_cells}
    substantial = [c for c in vert_cells
                   if boxes[c["id"]]["w"] * boxes[c["id"]]["h"] >= 2000]
    unlabeled_cands: list[dict] = []
    for c in vert_cells:
        if c["id"] in cluster_ids or _is_container(c):
            continue
        b = boxes[c["id"]]
        if b["w"] * b["h"] < 25000:
            continue
        contained = [o for o in substantial
                     if o["id"] != c["id"] and _center_in(boxes[o["id"]], b)
                     and boxes[o["id"]]["w"] * boxes[o["id"]]["h"] < b["w"] * b["h"] * 0.8]
        if not contained:
            continue
        label, _ = _split_label(c["value"])
        cl = {"id": c["id"], "label": label,
              "_style": c["style"], "_pid": c.get("parent"), "_spatial": True}
        clusters.append(cl)
        cluster_ids.add(c["id"])
        if not label:
            unlabeled_cands.append(cl)
    # Unlabeled boundaries adopt the tiny label-pill hugging their top edge
    # (the "VPC" chip pattern). A pill goes to the candidate whose top edge is
    # CLOSEST — several nested boundaries can share the same top strip.
    if unlabeled_cands:
        pills = [p for p in vert_cells
                 if p["id"] not in cluster_ids and p["geo"]["h"] <= 32
                 and p["geo"]["w"] * p["geo"]["h"] <= 8000
                 and _split_label(p["value"])[0]]
        for p in pills:
            pb = boxes[p["id"]]
            near = [cl for cl in unlabeled_cands if not cl["label"]
                    and _center_in(pb, boxes[cl["id"]])
                    and abs(pb["y"] - boxes[cl["id"]]["y"]) <= 30]
            if near:
                best = min(near, key=lambda cl: abs(pb["y"] - boxes[cl["id"]]["y"]))
                best["label"] = _split_label(p["value"])[0]
        for cl in list(unlabeled_cands):
            if not cl["label"]:
                if _ZONE_HINT.search(cl["id"]):
                    cl["label"] = cl["id"].replace("_", " ").replace("-", " ").title()
                else:  # nameless big rect: not a meaningful section — retract
                    clusters.remove(cl)
                    cluster_ids.discard(cl["id"])

    # Spatial cluster nesting: parent = smallest other cluster fully containing it.
    cl_boxes = {cl["id"]: boxes.get(cl["id"]) for cl in clusters}
    for cl in clusters:
        if not cl.get("_spatial"):
            continue
        b = cl_boxes[cl["id"]]
        best = None
        for other in clusters:
            ob = cl_boxes.get(other["id"])
            if other["id"] == cl["id"] or not ob or not b:
                continue
            if (ob["x"] <= b["x"] + 2 and ob["y"] <= b["y"] + 2
                    and ob["x"] + ob["w"] >= b["x"] + b["w"] - 2
                    and ob["y"] + ob["h"] >= b["y"] + b["h"] - 2):
                if best is None or ob["w"] * ob["h"] < best[1]:
                    best = (other["id"], ob["w"] * ob["h"])
        if best:
            cl["_pid"] = best[0]
    # Original container nesting + topology-zone guess ("_"-prefixed: consumed
    # only by the refined upgrade path; the icon path must keep seeing today's
    # flat cluster list, or upgrades would flip into topology nesting mode).
    _ZONE_RX = [("vpc", re.compile(r"\bvpc\b|\bvnet\b", re.I)),
                ("az", re.compile(r"availability|\baz\b|\bus-(east|west)-\d[a-f]\b", re.I)),
                ("onprem", re.compile(r"on[- ]?prem|data ?cent", re.I)),
                ("cloud", re.compile(r"\baws\b|\bazure\b|\bgcp\b|\bcloud\b", re.I))]
    for cl in clusters:
        pid, guard = cl.pop("_pid", None), 0
        while pid and pid not in cluster_ids and guard < 20:
            pid = (by_id.get(pid) or {}).get("parent")
            guard += 1
        if pid in cluster_ids and pid != cl["id"]:
            cl["_parent"] = pid
        style = cl.pop("_style", "")
        text = f"{cl['label']} {style}"
        for kind, rx in _ZONE_RX:
            if rx.search(text):
                cl["_zone"] = kind
                break
    linked: set[str] = set()
    for c in cells:
        if c["edge"]:
            linked.update(x for x in (c["source"], c["target"]) if x)

    title_guess = ""
    page_w = max((boxes[c["id"]]["x"] + boxes[c["id"]]["w"]
                  for c in vert_cells), default=0)
    raw_nodes: list[dict] = []
    for c in cells:
        if (not c["vertex"] or _is_container(c) or _is_decor(c["id"])
                or c["id"] in cluster_ids):
            continue
        icon = extract_image_uri(c["style"])
        title, sub = _split_label(c["value"])
        if not (title or sub or icon):
            continue  # pure decoration — skip

        def _real_cluster(pid: str | None) -> str | None:
            guard = 0
            while pid and guard < 20:  # walk past skipped decor containers (__grid)
                if pid in cluster_ids:
                    return pid
                pid = (by_id.get(pid) or {}).get("parent")
                guard += 1
            return None

        parent = _real_cluster(c["parent"])
        b = boxes.get(c["id"])
        if parent is None and b:
            # flat file: membership = smallest spatial cluster containing centre
            best = None
            for cl in clusters:
                cb = cl_boxes.get(cl["id"])
                if cb and _center_in(b, cb):
                    if best is None or cb["w"] * cb["h"] < best[1]:
                        best = (cl["id"], cb["w"] * cb["h"])
            parent = best[0] if best else None
        pos = _abs(c)
        raw_nodes.append({"id": c["id"], "title": title or c["id"], "sub": sub,
                          "cluster": parent, "icon": icon,
                          "_labeled": bool(title or sub), "_box": b,
                          "_x": pos["x"], "_y": pos["y"]})

    # Chrome filtering + icon merging (flat real-world files carry title boxes,
    # legend swatches, metadata cards and loose icon glyphs as ordinary cells):
    legendish = {cl["id"] for cl in clusters
                 if str(cl["label"]).strip().lower() in ("legend", "metadata", "notes")}
    labeled = [n for n in raw_nodes if n["_labeled"] and n["_box"]]
    for n in raw_nodes:
        b, area = n["_box"], 0.0
        if b:
            area = b["w"] * b["h"]
        if n["id"] in linked:
            keep = True
        elif n["cluster"] in legendish:
            keep = False  # legend/metadata internals
        elif not n["_labeled"]:
            # unlabeled icon glyph: merge into the labeled card it sits on, else drop
            host = next((h for h in labeled if h["id"] != n["id"] and not h["icon"]
                         and b and _center_in(b, h["_box"])), None)
            if host is not None and n["icon"]:
                host["icon"] = n["icon"]
            keep = False
        elif (not title_guess and b and b["y"] < 100 and page_w
              and b["w"] >= 0.4 * page_w):
            title_guess = (n["title"] + (f" — {n['sub']}" if n["sub"] else "")).strip()
            keep = False  # the diagram's own title box, not a component
        elif area and area < 3000:
            keep = False  # badges / label pills ("T4", "VPC") without edges
        elif str(n["title"]).strip().lower() in ("legend", "metadata", "notes"):
            keep = False
        else:
            keep = True
        n["_keep"] = keep
    nodes = [n for n in raw_nodes if n["_keep"]]
    clusters = [cl for cl in clusters if cl["id"] not in legendish]
    cluster_ids -= legendish

    for c in cells:
        if c["edge"] and c["source"] and c["target"]:
            label, _ = _split_label(c["value"])
            edges.append({"id": c["id"], "source": c["source"],
                          "target": c["target"], "label": label})

    node_ids = {n["id"] for n in nodes}
    edges = [e for e in edges if e["source"] in node_ids and e["target"] in node_ids]
    nodes.sort(key=lambda n: (round(n["_y"] / 60), n["_x"]))  # reading order
    for n in nodes:
        for k in ("_x", "_y", "_box", "_labeled", "_keep"):
            n.pop(k, None)

    # Leading "N ·" section numbers in cluster labels become explicit numbers
    # (the engine renders its own "N · LABEL" tab — keeping both would double).
    for cl in clusters:
        m = re.match(r"\s*(\d+)\s*[·.:\-–]\s*(.+)", str(cl["label"]))
        if m:
            cl["number"] = int(m.group(1))
            cl["label"] = m.group(2).strip()
    return {"title": title_guess, "provider": "generic", "clusters": clusters,
            "nodes": nodes, "edges": edges}


def _wrap_body(text: str, width: int = 32, max_lines: int = 3) -> list[str]:
    """Split a long subtitle into short refined card body lines (playbook §12.4)."""
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


def inventory_to_render_spec(inv: dict, *, provider: str | None = None,
                             title: str | None = None,
                             style_preset: str = "") -> dict:
    """Map an inventory to a render_spec the native engine can rebuild, preserving
    original ids and reusing embedded icons (V2 §2.2 rebuild-geometry-not-semantic).

    ``style_preset="refined"`` targets the typographic playbook preset: card
    subtitles become 2-4 short body lines, and the source's container nesting /
    topology-zone guesses ("_parent"/"_zone" from extract_inventory) surface as
    cluster parent/zone so the refined page can draw visual cloud/VPC boundaries.
    The default (icon) path is byte-identical to before.
    """
    refined = str(style_preset).lower() == "refined"
    used_clusters = {n.get("cluster") for n in inv["nodes"] if n.get("cluster")}
    clusters = [cl for cl in inv["clusters"] if cl["id"] in used_clusters]
    if refined:
        # Keep ancestor wrapper containers too — they become visual boundaries.
        by_id = {cl["id"]: cl for cl in inv["clusters"]}
        keep = {cl["id"] for cl in clusters}
        for cl in list(clusters):
            pid = cl.get("_parent")
            while pid and pid in by_id and pid not in keep:
                keep.add(pid)
                clusters.append(by_id[pid])
                pid = by_id[pid].get("_parent")
        clusters = [{k: v for k, v in cl.items() if not k.startswith("_")}
                    | ({"parent": cl["_parent"]} if cl.get("_parent") else {})
                    | ({"zone": cl["_zone"]} if cl.get("_zone") else {})
                    for cl in clusters]
    nodes = []
    for n in inv["nodes"]:
        node = {"id": n["id"], "label": n["title"], "tech": n.get("sub") or "",
                "cluster": n.get("cluster"), "icon_data_uri": n.get("icon")}
        if refined and n.get("sub"):
            node["body"] = _wrap_body(n["sub"])
        nodes.append(node)
    spec = {
        "provider": provider or inv.get("provider") or "generic",
        "presentation_style": "diagram",  # faithful plain rebuild, no slide chrome
        "diagram_title": title or inv.get("title") or "Upgraded Architecture",
        "clusters": clusters,
        "nodes": nodes,
        "edges": [{"from": e["source"], "to": e["target"],
                   "label": e.get("label") or ""} for e in inv["edges"]],
    }
    if refined:
        spec["style_preset"] = "refined"
    return spec
