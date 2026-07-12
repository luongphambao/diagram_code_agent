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

from .layout_engine import group, frame, grid, icon, box, phantom, render_tree
from .builder import Diagram
from .theme import THEME

try:
    from ..drawio_catalog import (load_catalog as _load_catalog,
                                  search_icon as _search_icon, get_icon as _get_icon)
    from ..graph_builder import _aws_group_for_label
    from ..constants import PRO_ACCENTS, FLOW_COLORS
except (ImportError, ValueError):  # pragma: no cover - import fallback
    from drawio_catalog import (load_catalog as _load_catalog,  # type: ignore
                                search_icon as _search_icon, get_icon as _get_icon)
    from prettygraph.graph_builder import _aws_group_for_label  # type: ignore
    from prettygraph.constants import PRO_ACCENTS, FLOW_COLORS  # type: ignore

_NEUTRAL_STROKE = "#8593A3"
_ICON_SCORE_MIN = 50  # top-hit score to accept a stencil for a node (else a plain box)
# Vendor / filler words that dilute a stencil search ("AWS Lambda" -> "lambda").
_VENDOR_WORDS = {"aws", "amazon", "azure", "gcp", "google", "microsoft", "cloud",
                 "apache", "the", "a", "for", "service", "services", "managed"}

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


def _clean_query(q: str) -> str:
    """Drop vendor/filler words so "AWS Lambda" -> "lambda", "Amazon RDS" -> "rds"."""
    toks = [t for t in re.split(r"[^a-z0-9]+", (q or "").lower())
            if t and t not in _VENDOR_WORDS]
    return " ".join(toks)


def _resolve_node_icon(cat, node: dict) -> str | None:
    """Best ground-truth stencil name for a node (by tech, then label), or None."""
    if not (cat and _search_icon):
        return None
    for raw in (node.get("tech"), node.get("label")):
        if not raw:
            continue
        for query in (_clean_query(raw), raw):  # cleaned first, then the raw text
            if not query:
                continue
            hits = _search_icon(cat, query, limit=1, kind="icon")
            if hits and hits[0].get("score", 0) >= _ICON_SCORE_MIN:
                return hits[0]["name"]
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


def build_tree(spec: dict, flat: bool = False):
    """Build a native layout tree (+ Diagram, edges) from a render_spec dict.

    Returns (diagram, root_tree) with the tree already rendered into the diagram.
    flat=True emits absolute geometry at parent="1" (for slide embedding).
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
        # Non-AWS: the "AWS look" (framed container + corner logo) with a SWAPPABLE
        # logo — on-prem / k8s / db / server etc. — instead of an AWS group stencil.
        # (AWS diagrams keep pure AWS group stencils or plain frames — no mixed logos.)
        opts = {"dir": "col", "gap": 18, "stroke": _accent_stroke(c.get("accent"))}
        logo = _container_logo(cat, c) if provider != "aws" else None
        if logo:
            opts["cornerIcon"] = logo
        return frame(cid, label, opts, kids)

    top_children = [build_cluster(cid) for cid in roots]
    top_children += [build_node(n) for n in loose]
    if not top_children:
        top_children = [box("__empty", "(empty diagram)")]
    root = phantom("__root", "", {"dir": root_dir, "gap": 60}, top_children)

    # contract="bake" freezes the router's obstacle-avoiding waypoints as explicit
    # mxPoints (scaffold would drop them and let draw.io re-route from pins only).
    # flat=True (used for slide embedding) emits absolute geometry at parent="1".
    d = Diagram(spec.get("pattern", "pipeline"), contract="bake", flat=flat)
    render_tree(d, root)

    title = spec.get("slide_title") or spec.get("diagram_title")
    if title:
        d.title(title)

    for e in spec.get("edges", []):
        s, t = e.get("from"), e.get("to")
        if s in d.R and t in d.R:
            d.link(s, t, e.get("label") or "",
                   dash=(str(e.get("style") or "").lower() == "dashed"),
                   stroke=_flow_color(e.get("flow")))
    return d, root


def render_spec_to_drawio(spec: dict, name: str = "Architecture") -> str:
    """Convenience: build from spec and return the full .drawio (mxfile) XML."""
    d, _ = build_tree(spec)
    return d.mxfile(name)


def build_drawio_from_spec(spec: dict, name: str = "Architecture") -> tuple[str, dict]:
    """Build a native .drawio from a render_spec and return (xml, stats).

    stats reports fidelity + routing quality for the caller to log: native icon /
    group counts, and the router's residual edge crossings / parallel overlaps.
    """
    d, _ = build_tree(spec)
    xml = d.mxfile(name)
    stats = {
        "nodes": len(spec.get("nodes", [])),
        "edges": len(spec.get("edges", [])),
        "native_icons": xml.count("resIcon=mxgraph.aws4."),
        "native_groups": xml.count("grIcon=mxgraph.aws4."),
        "edge_cross": getattr(d, "_cross", 0),
        "edge_overlaps": getattr(d, "_overlaps", 0),
    }
    return xml, stats
