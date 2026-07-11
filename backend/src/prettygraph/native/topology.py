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

from .layout_engine import group, frame, grid, icon, box, phantom, render_tree
from .builder import Diagram
from .theme import THEME

try:
    from ..drawio_catalog import load_catalog as _load_catalog, search_icon as _search_icon
    from ..graph_builder import _aws_group_for_label
    from ..constants import PRO_ACCENTS, FLOW_COLORS
except (ImportError, ValueError):  # pragma: no cover - import fallback
    from drawio_catalog import load_catalog as _load_catalog, search_icon as _search_icon  # type: ignore
    from prettygraph.graph_builder import _aws_group_for_label  # type: ignore
    from prettygraph.constants import PRO_ACCENTS, FLOW_COLORS  # type: ignore

_NEUTRAL_STROKE = "#8593A3"
_ICON_SCORE_MIN = 60  # top-hit score to accept a stencil for a node (else a plain box)


def _accent_stroke(accent: str | None) -> str:
    if accent and accent in PRO_ACCENTS:
        return PRO_ACCENTS[accent][1]
    return _NEUTRAL_STROKE


def _flow_color(flow: str | None) -> str | None:
    if flow and flow in FLOW_COLORS:
        return FLOW_COLORS[flow][0]
    return None


def _resolve_node_icon(cat, node: dict) -> str | None:
    """Best ground-truth stencil name for a node (by tech, then label), or None."""
    if not (cat and _search_icon):
        return None
    for query in (node.get("tech"), node.get("label")):
        if not query:
            continue
        hits = _search_icon(cat, query, limit=1, kind="icon")
        if hits and hits[0].get("score", 0) >= _ICON_SCORE_MIN:
            return hits[0]["name"]
    return None


def _node_label(node: dict) -> str:
    tech = node.get("tech") or ""
    label = node.get("label") or node.get("id") or ""
    if tech and tech != label:
        return f"{label}\n{tech}"
    return label


def build_tree(spec: dict):
    """Build a native layout tree (+ Diagram, edges) from a render_spec dict.

    Returns (diagram, root_tree) with the tree already rendered into the diagram.
    """
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

    horiz = not str(spec.get("layout_intent", "")).lower().startswith("top")
    root_dir = "row" if horiz else "col"

    def build_node(n: dict):
        name = _resolve_node_icon(cat, n)
        label = _node_label(n)
        if name:
            return icon(n["id"], name, label)
        return box(n["id"], label, fill=THEME.base, stroke=_accent_stroke(None), fs=11)

    def build_cluster(cid: str):
        c = clusters[cid]
        label = c["label"] if c.get("number") is None else f'{c["number"]} · {c["label"]}'
        kids = [build_cluster(sub) for sub in children_of.get(cid, [])]
        cnodes = nodes_by_cluster.get(cid, [])
        if cnodes:
            items = [build_node(n) for n in cnodes]
            if len(items) > 3 and not children_of.get(cid):
                cols = 2 if len(items) <= 6 else 3
                kids.append(grid(f"{cid}__grid", None, "", {"cols": cols, "gap": 22}, items))
            else:
                kids.extend(items)
        gname = _aws_group_for_label(label) if provider == "aws" else None
        if gname:
            return group(cid, gname, label, {"dir": "col", "gap": 20}, kids)
        return frame(cid, label, {"dir": "col", "gap": 18,
                                  "stroke": _accent_stroke(c.get("accent"))}, kids)

    top_children = [build_cluster(cid) for cid in roots]
    top_children += [build_node(n) for n in loose]
    if not top_children:
        top_children = [box("__empty", "(empty diagram)")]
    root = phantom("__root", "", {"dir": root_dir, "gap": 60}, top_children)

    d = Diagram(spec.get("pattern", "pipeline"))
    render_tree(d, root)

    title = spec.get("slide_title") or spec.get("diagram_title")
    if title:
        d.title(title)

    for e in spec.get("edges", []):
        s, t = e.get("from"), e.get("to")
        if s in d.R and t in d.R:
            d.link(s, t, e.get("label") or "", style=e.get("style"),
                   color=_flow_color(e.get("flow")))
    return d, root


def render_spec_to_drawio(spec: dict, name: str = "Architecture") -> str:
    """Convenience: build from spec and return the full .drawio (mxfile) XML."""
    d, _ = build_tree(spec)
    return d.mxfile(name)
