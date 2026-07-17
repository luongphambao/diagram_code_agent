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

    # Clusters = container vertices; nodes = leaf vertices with a label or icon.
    clusters, nodes, edges = [], [], []
    for c in cells:
        if _is_decor(c["id"]):
            continue
        if c["vertex"] and _is_container(c):
            label, _ = _split_label(c["value"])
            clusters.append({"id": c["id"], "label": label or c["id"]})
    cluster_ids = {cl["id"] for cl in clusters}
    for c in cells:
        if not c["vertex"] or _is_container(c) or _is_decor(c["id"]):
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
        pos = _abs(c)
        nodes.append({"id": c["id"], "title": title or c["id"], "sub": sub,
                      "cluster": parent, "icon": icon, "_x": pos["x"], "_y": pos["y"]})
    for c in cells:
        if c["edge"] and c["source"] and c["target"]:
            label, _ = _split_label(c["value"])
            edges.append({"id": c["id"], "source": c["source"],
                          "target": c["target"], "label": label})

    node_ids = {n["id"] for n in nodes}
    edges = [e for e in edges if e["source"] in node_ids and e["target"] in node_ids]
    nodes.sort(key=lambda n: (round(n["_y"] / 60), n["_x"]))  # reading order
    for n in nodes:
        n.pop("_x", None)
        n.pop("_y", None)
    return {"title": "", "provider": "generic", "clusters": clusters,
            "nodes": nodes, "edges": edges}


def inventory_to_render_spec(inv: dict, *, provider: str | None = None,
                             title: str | None = None) -> dict:
    """Map an inventory to a render_spec the native engine can rebuild, preserving
    original ids and reusing embedded icons (V2 §2.2 rebuild-geometry-not-semantic)."""
    used_clusters = {n.get("cluster") for n in inv["nodes"] if n.get("cluster")}
    return {
        "provider": provider or inv.get("provider") or "generic",
        "presentation_style": "diagram",  # faithful plain rebuild, no slide chrome
        "diagram_title": title or inv.get("title") or "Upgraded Architecture",
        "clusters": [cl for cl in inv["clusters"] if cl["id"] in used_clusters],
        "nodes": [{"id": n["id"], "label": n["title"], "tech": n.get("sub") or "",
                   "cluster": n.get("cluster"),
                   "icon_data_uri": n.get("icon")} for n in inv["nodes"]],
        "edges": [{"from": e["source"], "to": e["target"],
                   "label": e.get("label") or ""} for e in inv["edges"]],
    }
