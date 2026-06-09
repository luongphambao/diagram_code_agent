"""Author production-quality architecture diagrams in the centvra/deepstream style.

The mingrammer `diagrams` default node (icon on top, label below, no box) can't
reproduce the reference look: a rounded, semantically-COLORED box with the icon
on the LEFT and a bold label on the right, inside tinted nested clusters, with a
title/subtitle and gray edge labels. So this helper emits Graphviz DOT with
HTML-like node labels (icon + text in a filled rounded box) — rendered to PNG by
`dot` — plus a sidecar so the same diagram exports to an editable .drawio where
each node is a draw.io `shape=label` (icon-left + colored box), not a flat image.

LLM-friendly API::

    g = Pretty("Deployment Architecture", subtitle="example", direction="LR",
               icons_root="/icons")
    g.cluster("svc", "Service Tier", kind="Compute")
    # Icon paths are `<provider>/<category>/<name>.png` under icons_root. Use the
    # vendor that matches the stack — AWS, Azure, GCP, OCI all work the same way:
    g.box("alb", "Load Balancer", kind="network",
          icon="aws/network/elastic-load-balancing.png")        # AWS
    # azure: icon="azure/network/load-balancers.png"
    # gcp:   icon="gcp/network/load-balancing.png"
    g.box("app", "App Service", kind="compute",
          icon="azure/compute/app-services.png", parent="svc")  # Azure
    g.box("db", "Cloud SQL", kind="data",
          icon="gcp/database/sql.png")                          # GCP
    g.link("alb", "app", label="API Call")
    g.link("app", "db", label="SQL")
    g.render("/workspace/out")          # -> out.png, out.dot, out.nodes.json
    g.to_drawio("/workspace/out")       # -> out.drawio  (editable, same logos)
"""

from __future__ import annotations

import base64
import html
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

# --- Semantic palette (fill, stroke) — distilled from the reference diagrams --- #
# Node "kind" -> colored box. Keep names intuitive so the model picks them right.
NODE_KINDS: dict[str, tuple[str, str]] = {
    "source": ("#e6ecff", "#4C78A8"),   # inputs / clients / I/O          (blue)
    "io": ("#e6ecff", "#4C78A8"),
    "network": ("#f2e6ff", "#8E6FB6"),   # LB / gateway / VPC networking   (purple)
    "compute": ("#e6ffee", "#82b366"),   # services / GPU / processing     (green)
    "process": ("#e6ffee", "#82b366"),
    "messaging": ("#ffe6e6", "#b85450"),  # queue / broker / events        (red)
    "data": ("#e6ecff", "#3b5b92"),      # databases / stores              (deep blue)
    "monitoring": ("#fff5e6", "#d79b00"),  # metrics / logs / calibration  (orange)
    "aux": ("#fff5e6", "#d79b00"),
    "security": ("#ffe6e6", "#c0504d"),  # IAM / secrets                   (red)
    "neutral": ("#f5f5f5", "#999999"),   # notes / "..." collapse          (gray)
}
# Cluster tint, stroke — cloud-neutral palette (tints by tier, applies to any
# provider; originally distilled from AWS-CloudFormation-Diagrams).
CLUSTER_KINDS: dict[str, tuple[str, str]] = {
    "Compute": ("#fff5e6", "#e0b878"),
    "Database": ("#e6ecff", "#9db0d6"),
    "IoT": ("#e6ffee", "#9cc99c"),
    "Management": ("#ffe6f2", "#d9a6c2"),
    "Network": ("#f2e6ff", "#c3aede"),
    "Security": ("#ffe6e6", "#d9a3a3"),
    "Storage": ("#e6ffe6", "#a3cca3"),
    "Neutral": ("#fafafa", "#cfcfcf"),
}

# --- "pro" theme palette --------------------------------------------------- #
# A cohesive, modern accent set. Each entry: (card_fill, accent, section_fill).
# In pro theme a stage = a section tinted `section_fill` with an accent header +
# numbered badge; its boxes are `card_fill` cards with an `accent` border. Stages
# are assigned accents in declaration order (PRO_ORDER), or pin one via accent=.
PRO_ACCENTS: dict[str, tuple[str, str, str]] = {
    "blue":   ("#E3EDFD", "#2563EB", "#F4F8FE"),
    "cyan":   ("#DEF3F9", "#0891B2", "#F2FBFD"),
    "teal":   ("#DEF3EF", "#0D9488", "#F2FBF9"),
    "violet": ("#ECE4FD", "#7C3AED", "#F8F5FE"),
    "indigo": ("#E5E8FD", "#4F46E5", "#F5F6FE"),
    "green":  ("#E0F4E9", "#059669", "#F2FBF6"),
    "amber":  ("#FCEFD7", "#D97706", "#FEF9EF"),
    "rose":   ("#FBE3E8", "#E11D48", "#FEF4F6"),
    "slate":  ("#E7EBF0", "#475569", "#F5F7F9"),
}
PRO_ORDER = ["blue", "cyan", "teal", "violet", "indigo", "green"]
PRO_EDGE = "#334155"        # strong slate for pro edges
PRO_TITLE = "#0F172A"       # near-black title
PRO_MUTED = "#64748B"       # muted sublabel / subtitle

EDGE_COLOR = "#5A6573"      # crisp slate — readable but not harsh
EDGE_FONTCOLOR = "#3f4a57"
FONT = "Helvetica"
# Page fit: a GENEROUS cap (inches) so wide layouts aren't crushed to tiny text.
# `size` only shrinks an oversized layout — a small diagram keeps its natural,
# legible size; a large one caps here instead of being squeezed onto A4.
PAGE_SIZE = "20,13"
SLIDE_SIZE = 2048
SLIDE_HERO_H = 620
SLIDE_MARGIN = 38
SLIDE_PANEL_PAD = 26


def _esc(s: str) -> str:
    """Escape text for an HTML-like Graphviz label."""
    return html.escape(s or "", quote=True)


def _xml(s: str | None) -> str:
    """Escape text for draw.io XML attributes."""
    return xml_escape(s or "", {'"': "&quot;"})


@dataclass
class _Node:
    id: str
    label: str
    kind: str
    icon: str | None
    sublabel: str | None
    parent: str | None


@dataclass
class _Cluster:
    id: str
    label: str
    kind: str
    parent: str | None
    number: int | None = None      # pro theme: numbered badge in the header
    accent: str | None = None      # pro theme: pin an accent (key of PRO_ACCENTS)


@dataclass
class _Edge:
    a: str
    b: str
    label: str | None
    style: str
    color: str | None
    penwidth: float | None = None
    ltail: str | None = None       # clip edge tail to this cluster (compound)
    lhead: str | None = None       # clip edge head to this cluster (compound)
    constraint: bool | None = None  # False => edge does not affect ranking
    taillabel: str | None = None   # label near source — avoids midpoint float on long edges


@dataclass
class Pretty:
    title: str
    subtitle: str | None = None
    direction: str = "LR"
    icons_root: str = "/icons"
    splines: str = "ortho"   # right-angle edges => clean, blocky, enterprise look
    size: str = PAGE_SIZE    # cap drawing to ~A4 landscape (compact / printable)
    node_width: float | None = None   # pts; fixed inner box width  -> uniform boxes
    node_height: float | None = None  # pts; fixed inner box height -> uniform boxes
    theme: str = "default"            # "pro" => premium palette + numbered badges
    dpi: int | None = None            # raster DPI; pro defaults to 160 (crisp)
    nodes: dict[str, _Node] = field(default_factory=dict)
    clusters: dict[str, _Cluster] = field(default_factory=dict)
    edges: list[_Edge] = field(default_factory=list)
    same_ranks: list[list[str]] = field(default_factory=list)

    # ---- authoring API ---- #
    def cluster(self, id: str, label: str, kind: str = "Neutral",
                *, parent: str | None = None, number: int | None = None,
                accent: str | None = None) -> str:
        self.clusters[id] = _Cluster(id, label, kind, parent, number, accent)
        return id

    def box(self, id: str, label: str, kind: str = "process",
            *, icon: str | None = None, sublabel: str | None = None,
            parent: str | None = None) -> str:
        self.nodes[id] = _Node(id, label, kind, icon, sublabel, parent)
        return id

    def link(self, a: str, b: str, *, label: str | None = None,
             style: str = "solid", color: str | None = None,
             penwidth: float | None = None, ltail: str | None = None,
             lhead: str | None = None, constraint: bool | None = None,
             taillabel: str | None = None) -> None:
        self.edges.append(_Edge(a, b, label, style, color, penwidth,
                                ltail, lhead, constraint, taillabel))

    def same_rank(self, ids: list[str]) -> None:
        """Force nodes onto the same row (clean replica grids)."""
        self.same_ranks.append(list(ids))

    # ---- icon resolution ---- #
    def _icon_path(self, icon: str | None) -> str | None:
        if not icon:
            return None
        p = Path(icon)
        if not p.is_absolute():
            p = Path(self.icons_root) / icon
        return str(p) if p.exists() else None

    # ---- style resolution (theme-aware; shared by DOT + drawio sidecar) ---- #
    def _accent_map(self) -> dict[str, tuple[str, str, str]]:
        """cluster id -> (card_fill, accent, section_fill) for the pro theme."""
        cached = getattr(self, "_amap_cache", None)
        if cached is not None:
            return cached
        amap: dict[str, tuple[str, str, str]] = {}
        i = 0
        for cid, c in self.clusters.items():
            if c.parent is not None:
                continue
            if c.accent and c.accent in PRO_ACCENTS:
                amap[cid] = PRO_ACCENTS[c.accent]
            else:
                amap[cid] = PRO_ACCENTS[PRO_ORDER[i % len(PRO_ORDER)]]
                i += 1
        for cid, c in self.clusters.items():        # nested clusters inherit
            if c.parent is not None:
                amap[cid] = amap.get(c.parent, PRO_ACCENTS["slate"])
        self._amap_cache = amap
        return amap

    def _node_style(self, n: _Node) -> tuple[str, str, str | None, str]:
        """Return (fill, stroke, title_color, sublabel_color)."""
        if self.theme == "pro":
            acc = self._accent_map().get(n.parent) if n.parent else None
            return (acc[0] if acc else "#F1F5F9",
                    acc[1] if acc else "#94A3B8", PRO_TITLE, PRO_MUTED)
        fill, stroke = NODE_KINDS.get(n.kind, NODE_KINDS["neutral"])
        return fill, stroke, None, "#667085"

    def _cluster_style(self, cid: str) -> tuple[str, str]:
        """Return (fill, stroke) for a cluster box."""
        if self.theme == "pro":
            acc = self._accent_map().get(cid, PRO_ACCENTS["slate"])
            return acc[2], acc[1]
        c = self.clusters[cid]
        return CLUSTER_KINDS.get(c.kind, CLUSTER_KINDS["Neutral"])

    def _cluster_label_pro(self, c: _Cluster) -> str:
        """A numbered accent badge + accent title (HTML-like cluster label)."""
        accent = self._accent_map().get(c.id, PRO_ACCENTS["slate"])[1]
        badge = ""
        if c.number is not None:
            badge = (f'<TD BGCOLOR="{accent}" WIDTH="24" HEIGHT="24" ALIGN="CENTER" '
                     f'VALIGN="MIDDLE"><FONT COLOR="#FFFFFF" POINT-SIZE="14"><B>'
                     f'{c.number}</B></FONT></TD><TD WIDTH="8"></TD>')
        return ('<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="2">'
                f'<TR>{badge}<TD ALIGN="LEFT"><FONT COLOR="{accent}" '
                f'POINT-SIZE="15"><B>{_esc(c.label)}</B></FONT></TD></TR></TABLE>')

    # ---- DOT generation ---- #
    def _node_dot(self, n: _Node) -> str:
        fill, stroke, title_c, sub_c = self._node_style(n)
        icon = self._icon_path(n.icon)
        label_html = (f'<FONT COLOR="{title_c}"><B>{_esc(n.label)}</B></FONT>'
                      if title_c else f'<B>{_esc(n.label)}</B>')
        if n.sublabel:
            label_html += (f'<BR/><FONT POINT-SIZE="11" COLOR="{sub_c}">'
                           f'{_esc(n.sublabel)}</FONT>')
        # Uniform boxes: when node_width is set, every box is a fixed-size table
        # (icon flush-left, text fills the rest) so all boxes align identically.
        fixed = self.node_width is not None
        align = "LEFT" if (icon or fixed) else "CENTER"
        if icon:
            cell = (
                '<TR>'
                f'<TD FIXEDSIZE="TRUE" WIDTH="36" HEIGHT="36">'
                f'<IMG SRC="{icon}" SCALE="TRUE"/></TD>'
                '<TD WIDTH="10"></TD>'
                f'<TD ALIGN="LEFT" BALIGN="LEFT"><FONT POINT-SIZE="13">'
                f'{label_html}</FONT></TD>'
                '</TR>'
            )
        else:
            cell = (f'<TR><TD ALIGN="{align}" BALIGN="{align}">'
                    f'<FONT POINT-SIZE="13">{label_html}</FONT></TD></TR>')
        table_attrs = 'BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="2"'
        if fixed:
            th = self.node_height or self.node_width
            table_attrs += (f' WIDTH="{self.node_width:.0f}" '
                            f'HEIGHT="{th:.0f}" FIXEDSIZE="TRUE"')
        table = f'<TABLE {table_attrs}>{cell}</TABLE>'
        return (f'  "{n.id}" [fillcolor="{fill}", color="{stroke}", '
                f'label=<{table}>];')

    def _cluster_block(self, cid: str, depth: int) -> list[str]:
        c = self.clusters[cid]
        fill, stroke = self._cluster_style(cid)
        pro = self.theme == "pro"
        label_html = self._cluster_label_pro(c) if pro else f'<B>{_esc(c.label)}</B>'
        lines = [
            f'{"  " * depth}subgraph cluster_{c.id} {{',
            f'{"  " * depth}  style="rounded,filled"; fillcolor="{fill}"; '
            f'color="{stroke}"; penwidth={"1.6" if pro else "1.2"};',
            f'{"  " * depth}  labeljust="l"; fontsize="14"; '
            f'fontname="{FONT}"; fontcolor="#5a6270";',
            f'{"  " * depth}  label=<{label_html}>;',
        ]
        # child clusters
        for sub in self.clusters.values():
            if sub.parent == cid:
                lines += self._cluster_block(sub.id, depth + 1)
        # child nodes
        for n in self.nodes.values():
            if n.parent == cid:
                lines.append(f'{"  " * depth}{self._node_dot(n)}')
        lines.append(f'{"  " * depth}}}')
        return lines

    def to_dot(self) -> str:
        pro = self.theme == "pro"
        tcolor = PRO_TITLE if pro else "#000000"
        tsize = "22" if pro else "20"
        title = (f'<B><FONT POINT-SIZE="{tsize}" COLOR="{tcolor}">'
                 f'{_esc(self.title)}</FONT></B>')
        if self.subtitle:
            title += (f'<BR/><FONT POINT-SIZE="11" COLOR="{PRO_MUTED if pro else "#8a8a8a"}">'
                      f'{_esc(self.subtitle)}</FONT>')
        dpi = self.dpi or (192 if pro else 168)
        nodesep, ranksep = ("0.5", "0.95") if pro else ("0.5", "0.9")
        edge_color = PRO_EDGE if pro else EDGE_COLOR
        node_pen = "1.5" if pro else "1.4"
        arrowhead = ' arrowhead="vee"' if pro else ""
        out = [
            "digraph G {",
            f'  rankdir="{self.direction}"; bgcolor="white"; pad="0.5";',
            # `size` only caps an oversized layout (never upscales) and we drop
            # `ratio="compress"` so text/icons keep their natural, legible size.
            f'  size="{self.size}";' + (f' dpi="{dpi}";' if dpi else ""),
            f'  labelloc="t"; labeljust="l"; label=<{title}>;',
            f'  fontname="{FONT}"; splines="{self.splines}"; '
            f'nodesep="{nodesep}"; ranksep="{ranksep}"; compound="true"; newrank="true";',
            f'  node [shape="box", style="rounded,filled", fontname="{FONT}", '
            f'penwidth="{node_pen}", margin="{"0.22,0.13" if pro else "0.2,0.12"}"];',
            f'  edge [color="{edge_color}", fontname="{FONT}", '
            f'fontsize="12", fontcolor="{EDGE_FONTCOLOR}", arrowsize="0.9", '
            f'penwidth="1.6"{arrowhead}];',
        ]
        # clusters (top-level only; nested handled recursively)
        for c in self.clusters.values():
            if c.parent is None:
                out += self._cluster_block(c.id, 1)
        # ungrouped nodes
        for n in self.nodes.values():
            if n.parent is None:
                out.append(self._node_dot(n))
        # same-rank groups
        for grp in self.same_ranks:
            ids = " ".join(f'"{i}"' for i in grp)
            out.append(f"  {{rank=same; {ids}}}")
        # edges
        for e in self.edges:
            attrs = []
            if e.label:
                # White-backed HTML label: stays readable and visually "anchored"
                # to its edge instead of floating loose on the canvas.
                lbl = (
                    '<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" '
                    'CELLPADDING="3" BGCOLOR="white"><TR><TD>'
                    f'<FONT POINT-SIZE="12" COLOR="{EDGE_FONTCOLOR}">'
                    f'{_esc(e.label)}</FONT></TD></TR></TABLE>>'
                )
                attrs.append(f'label={lbl}')
            if e.taillabel:
                tlbl = (
                    '<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" '
                    'CELLPADDING="2" BGCOLOR="white"><TR><TD>'
                    f'<FONT POINT-SIZE="11" COLOR="{EDGE_FONTCOLOR}">'
                    f'{_esc(e.taillabel)}</FONT></TD></TR></TABLE>>'
                )
                attrs.append(f'taillabel={tlbl}')
                attrs.append('labeldistance="2.0"')
            if e.style and e.style != "solid":
                attrs.append(f'style="{e.style}"')
            if e.color:
                attrs.append(f'color="{e.color}"')
            if e.penwidth:
                attrs.append(f'penwidth="{e.penwidth}"')
            if e.ltail:
                attrs.append(f'ltail="{e.ltail}"')
            if e.lhead:
                attrs.append(f'lhead="{e.lhead}"')
            if e.constraint is False:
                attrs.append("constraint=false")
            a = f" [{', '.join(attrs)}]" if attrs else ""
            out.append(f'  "{e.a}" -> "{e.b}"{a};')
        out.append("}")
        return "\n".join(out)

    # ---- render ---- #
    def render(self, out_basename: str) -> str:
        """Write ``<base>.dot`` + ``<base>.png`` + ``<base>.nodes.json``.

        Returns the PNG path. Raises CalledProcessError with dot's stderr on a
        layout/syntax failure so the agent can fix the script.
        """
        dot_path = f"{out_basename}.dot"
        png_path = f"{out_basename}.png"
        Path(dot_path).write_text(self.to_dot(), encoding="utf-8")
        subprocess.run(["dot", "-Tpng", dot_path, "-o", png_path],
                       check=True, capture_output=True, text=True)
        self._write_sidecar(f"{out_basename}.nodes.json")
        return png_path

    def _write_sidecar(self, path: str) -> None:
        # Resolve styles through the same theme-aware helpers the DOT uses, so the
        # editable .drawio matches the rendered PNG (incl. the pro palette).
        node_meta = {}
        for n in self.nodes.values():
            fill, stroke, _, _ = self._node_style(n)
            node_meta[n.id] = {
                "label": n.label, "sublabel": n.sublabel, "kind": n.kind,
                "fill": fill, "stroke": stroke, "icon": self._icon_path(n.icon),
                "shadow": 1 if self.theme == "pro" else 0,
            }
        cluster_meta = {}
        for c in self.clusters.values():
            fill, stroke = self._cluster_style(c.id)
            label = c.label if c.number is None else f"{c.number} · {c.label}"
            cluster_meta[c.id] = {"label": label, "fill": fill, "stroke": stroke}
        data = {"title": self.title, "subtitle": self.subtitle,
                "nodes": node_meta, "clusters": cluster_meta}
        Path(path).write_text(json.dumps(data), encoding="utf-8")

    def to_drawio(self, out_basename: str) -> str:
        """Build an editable .drawio from the laid-out .dot + sidecar styling."""
        return dot_to_drawio(f"{out_basename}.dot", f"{out_basename}.nodes.json",
                             f"{out_basename}.drawio")


# --------------------------------------------------------------------------- #
# .dot (+ sidecar) -> .drawio : nodes become draw.io `shape=label` (icon+box).
# --------------------------------------------------------------------------- #
def _b64(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return "data:image/png," + base64.b64encode(Path(path).read_bytes()).decode()
    except OSError:
        return None


def audit_layout(dot_path: str, png_path: str | None = None) -> str:
    """Objective post-render layout check — surfaced to the agent each render.

    Lays out the .dot once (``dot -Tjson``) and reports two signals the eye is
    bad at judging quickly:
      * page aspect ratio (a >2.5:1 strip reads as cramped / tiny text);
      * label-bearing edges whose endpoints sit far apart (these are exactly the
        edges whose labels STRAND loose on the canvas).
    Returns a short multi-line verdict with concrete fixes, or "" if it can't run.
    """
    import math

    try:
        g = json.loads(subprocess.run(["dot", "-Tjson", dot_path],
                                      capture_output=True, text=True,
                                      check=True).stdout)
    except Exception:  # noqa: BLE001 — audit is best-effort, never break a render
        return ""
    try:
        x0, y0, x1, y1 = (float(v) for v in g["bb"].split(","))
    except Exception:  # noqa: BLE001
        return ""
    W, Hh = max(x1 - x0, 1.0), max(y1 - y0, 1.0)
    aspect = W / Hh
    diag = math.hypot(W, Hh)

    pos: dict[int, tuple[float, float]] = {}
    n_clusters = 0
    for o in g.get("objects", []):
        if o.get("name", "").startswith("cluster"):
            n_clusters += 1
        elif o.get("pos"):
            cx, cy = (float(v) for v in o["pos"].split(","))
            pos[o["_gvid"]] = (cx, cy)

    node_pts = list(pos.values())
    occupied: set[tuple[int, int]] = set()
    central_pts = 0
    for cx, cy in node_pts:
        nx, ny = (cx - x0) / W, (cy - y0) / Hh
        occupied.add((min(int(nx * 3), 2), min(int(ny * 3), 2)))
        if 0.30 <= nx <= 0.70 and 0.30 <= ny <= 0.70:
            central_pts += 1

    long_labeled: list[str] = []
    dashed_edges = 0
    labeled_edges = 0
    for e in g.get("edges", []):
        if "dashed" in str(e.get("style", "")):
            dashed_edges += 1
        if not e.get("label"):
            continue
        labeled_edges += 1
        a, b = pos.get(e.get("tail")), pos.get(e.get("head"))
        if not a or not b:
            continue
        frac = math.hypot(a[0] - b[0], a[1] - b[1]) / diag
        if frac > 0.45:
            txt = re.sub(r"<[^>]+>", "", e["label"]).strip() or "(unlabeled)"
            long_labeled.append(f'"{txt}" ({frac:.0%} of canvas)')

    lines = [f"Layout audit: aspect {aspect:.2f}:1"
             + (" — OK" if 0.55 <= aspect <= 2.3 else
                " — TOO WIDE, fold cross-cutting tiers into a 2nd row (≤5 columns)"
                if aspect > 2.3 else " — very tall, consider direction='LR'"),
             f"  clusters: {n_clusters}"]
    if long_labeled:
        lines.append("  STRAND RISK — these labeled edges span far; their labels "
                     "may float loose. Move the endpoints into adjacent/stacked "
                     "clusters so the edge (and label) stays short:")
        lines += [f"    - {s}" for s in long_labeled[:5]]
    else:
        lines.append("  no long-stranding edge labels — good")
    if len(node_pts) >= 8 and central_pts == 0:
        lines.append("  SPARSE CENTER — no nodes in the central canvas. This often "
                     "means a huge blank hole; fold the diagram into a balanced "
                     "2-row grid or add a hub/summary stage in the center.")
    # Graphviz coordinates use y-up. Row 0 is bottom, row 2 is top.
    if ((0, 0) in occupied or (1, 0) in occupied) and (
        (2, 1) in occupied or (2, 2) in occupied
    ) and (1, 1) not in occupied:
        lines.append("  L-SHAPE WARNING — nodes are packed along the bottom and "
                     "right edge with the center empty. Re-layout into a 3x2/4x2 "
                     "grid; do not use a long bottom flow then a vertical tower.")
    edge_count = len(g.get("edges", []))
    if edge_count and dashed_edges > max(4, edge_count * 0.35):
        lines.append(f"  SIDE-CHANNEL FANOUT — {dashed_edges}/{edge_count} edges "
                     "are dashed. Collapse observability/security/control lines "
                     "to one cluster-level dashed edge per concern.")
    return "\n".join(lines)


def dot_to_drawio(dot_path: str, sidecar_path: str, out_path: str) -> str:
    """Lay out the .dot with Graphviz and emit a styled, editable .drawio."""
    js = subprocess.run(["dot", "-Tjson", dot_path],
                        capture_output=True, text=True, check=True).stdout
    g = json.loads(js)
    side = json.loads(Path(sidecar_path).read_text(encoding="utf-8"))
    snodes, sclusters = side.get("nodes", {}), side.get("clusters", {})

    x0, y0, x1, y1 = (float(v) for v in g["bb"].split(","))
    H = y1
    cells: list[str] = []
    gvid_to_cell: dict[int, str] = {}

    for o in g.get("objects", []):
        name = o.get("name", "")
        # clusters
        if name.startswith("cluster"):
            if not o.get("bb"):
                continue
            cid = name[len("cluster"):]
            meta = sclusters.get(cid, {})
            cx0, cy0, cx1, cy1 = (float(v) for v in o["bb"].split(","))
            gx, gy, gw, gh = cx0, H - cy1, cx1 - cx0, cy1 - cy0
            style = (
                f"rounded=1;arcSize=4;whiteSpace=wrap;html=1;"
                f"fillColor={meta.get('fill', '#fafafa')};"
                f"strokeColor={meta.get('stroke', '#cfcfcf')};verticalAlign=top;"
                "align=left;spacingLeft=10;spacingTop=6;fontSize=12;fontStyle=1;"
                "fontColor=#5a6270;"
            )
            cells.append(
                f'<mxCell id="c{o["_gvid"]}" value="{html.escape(meta.get("label", ""))}" '
                f'style="{style}" vertex="1" parent="1"><mxGeometry x="{gx:.0f}" '
                f'y="{gy:.0f}" width="{gw:.0f}" height="{gh:.0f}" as="geometry"/></mxCell>'
            )
            continue
        # nodes
        if not o.get("pos") or name not in snodes:
            continue
        meta = snodes[name]
        cx, cy = (float(v) for v in o["pos"].split(","))
        w = float(o.get("width", "1.4")) * 72.0
        h = float(o.get("height", "0.6")) * 72.0
        gx, gy = cx - w / 2.0, (H - cy) - h / 2.0
        cid = f"n{o['_gvid']}"
        gvid_to_cell[o["_gvid"]] = cid
        lbl = meta["label"] + (("\n" + meta["sublabel"]) if meta.get("sublabel") else "")
        b64 = _b64(meta.get("icon"))
        shadow = ";shadow=1" if meta.get("shadow") else ""
        if b64:
            style = (
                f"shape=label;html=1;rounded=1;arcSize=12;whiteSpace=wrap;"
                f"image={b64};imageAlign=left;imageVerticalAlign=middle;"
                f"imageWidth=34;imageHeight=34;spacingLeft=44;align=left;"
                f"fontSize=13;fontStyle=1;fontColor=#222222;"
                f"fillColor={meta['fill']};strokeColor={meta['stroke']}{shadow};"
            )
        else:
            style = (
                f"rounded=1;whiteSpace=wrap;html=1;fontSize=13;fontStyle=1;"
                f"fontColor=#222222;fillColor={meta['fill']};"
                f"strokeColor={meta['stroke']};"
            )
        cells.append(
            f'<mxCell id="{cid}" value="{html.escape(lbl)}" style="{style}" '
            f'vertex="1" parent="1"><mxGeometry x="{gx:.0f}" y="{gy:.0f}" '
            f'width="{max(w, 130):.0f}" height="{max(h, 52):.0f}" as="geometry"/></mxCell>'
        )

    for i, e in enumerate(g.get("edges", [])):
        src, tgt = gvid_to_cell.get(e.get("tail")), gvid_to_cell.get(e.get("head"))
        if not src or not tgt:
            continue
        style = (
            "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;"
            f"endFill=1;strokeColor={EDGE_COLOR};fontSize=12;fontColor={EDGE_FONTCOLOR};"
            "labelBackgroundColor=#FFFFFF;"
        )
        cells.append(
            f'<mxCell id="e{i}" value="{html.escape(e.get("label") or "")}" '
            f'style="{style}" edge="1" parent="1" source="{src}" target="{tgt}">'
            '<mxGeometry relative="1" as="geometry"/></mxCell>'
        )

    xml = (
        '<mxfile host="app.diagrams.net"><diagram name="architecture" id="d1">'
        '<mxGraphModel dx="1400" dy="900" grid="0" guides="1" tooltips="1" '
        'connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        f'pageWidth="{x1 - x0:.0f}" pageHeight="{y1 - y0:.0f}" math="0" shadow="0">'
        '<root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>"
    )
    Path(out_path).write_text(xml, encoding="utf-8")
    return xml


# --------------------------------------------------------------------------- #
# Region compositing — stack independently-laid-out regions vertically.
#
# Graphviz auto-layout cannot pin a cross-cutting band (e.g. an "Operational
# Controls" governance strip) to the bottom of an LR flow. The clean fix is to
# lay out each region on its own (where graphviz excels) and stack them:
#   * the FLOW region (the numbered stages + arrows + feedback loop), and
#   * one or more BAND regions (a single horizontal row).
# `vstack_pngs` composes the rendered PNGs; `merge_drawios_vertical` merges the
# editable .drawio files with the same vertical offsets so both stay in sync.
# --------------------------------------------------------------------------- #
def vstack_pngs(png_paths: list[str], out_png: str, gap: int = 26,
                bg: tuple[int, int, int] = (255, 255, 255)) -> None:
    """Stack PNGs top-to-bottom into one image, each centered horizontally."""
    from PIL import Image  # lazy import: prettygraph stays usable without PIL
    imgs = [Image.open(p).convert("RGBA") for p in png_paths]
    w = max(im.width for im in imgs)
    h = sum(im.height for im in imgs) + gap * (len(imgs) - 1)
    canvas = Image.new("RGBA", (w, h), (*bg, 255))
    y = 0
    for im in imgs:
        canvas.paste(im, ((w - im.width) // 2, y))
        y += im.height + gap
    canvas.convert("RGB").save(out_png)


def _page_dims(xml: str) -> tuple[float, float]:
    m = re.search(r'pageWidth="([\d.]+)" pageHeight="([\d.]+)"', xml)
    return (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)


def merge_drawios_vertical(xmls: list[str], out_path: str, gap: int = 26) -> str:
    """Merge .drawio XMLs into one, stacking each below the previous (centered).

    Cell ids are namespaced per region (``r{i}…``) so they never collide, and
    every geometry is shifted by the region's (xoff, yoff).
    """
    dims = [_page_dims(x) for x in xmls]
    maxw = max(w for w, _ in dims) if dims else 0.0
    total_h = sum(h for _, h in dims) + gap * (len(xmls) - 1)
    body: list[str] = []
    y = 0.0
    for i, (xml, (w, h)) in enumerate(zip(xmls, dims)):
        xoff = (maxw - w) / 2.0
        yoff = y
        m = re.search(r"<root>(.*)</root>", xml, re.S)
        inner = m.group(1) if m else ""
        inner = re.sub(r'<mxCell id="0"/>\s*<mxCell id="1" parent="0"/>', "", inner)
        for pfx in ('id="c', 'id="n', 'id="e',
                    'source="c', 'source="n', 'target="c', 'target="n'):
            inner = inner.replace(pfx, pfx.replace('="', f'="r{i}'))

        def _bump(mt: "re.Match[str]") -> str:
            return (f'<mxGeometry x="{float(mt.group(1)) + xoff:.0f}" '
                    f'y="{float(mt.group(2)) + yoff:.0f}"')

        inner = re.sub(r'<mxGeometry x="(-?[\d.]+)" y="(-?[\d.]+)"', _bump, inner)
        body.append(inner)
        y += h + gap
    xml_out = (
        '<mxfile host="app.diagrams.net"><diagram name="architecture" id="d1">'
        '<mxGraphModel dx="1400" dy="900" grid="0" guides="1" tooltips="1" '
        'connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        f'pageWidth="{maxw:.0f}" pageHeight="{total_h:.0f}" math="0" shadow="0">'
        '<root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        + "".join(body) + "</root></mxGraphModel></diagram></mxfile>"
    )
    Path(out_path).write_text(xml_out, encoding="utf-8")
    return xml_out


def _font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    names = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ) if bold else (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _gradient(size: tuple[int, int]):
    from PIL import Image

    w, h = size
    c1, c2, c3 = (4, 18, 22), (15, 57, 128), (17, 166, 142)
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        vy = y / max(h - 1, 1)
        for x in range(w):
            vx = x / max(w - 1, 1)
            mid = vx * 0.75 + vy * 0.25
            if mid < 0.52:
                t = mid / 0.52
                col = tuple(round(c1[i] * (1 - t) + c2[i] * t) for i in range(3))
            else:
                t = (mid - 0.52) / 0.48
                col = tuple(round(c2[i] * (1 - t) + c3[i] * t) for i in range(3))
            px[x, y] = col
    return img


def _draw_centered_text(draw, xy: tuple[int, int], text: str, font, fill,
                        max_width: int, line_gap: int = 8) -> int:
    words = (text or "").split()
    if not words:
        return xy[1]
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    y = xy[1]
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        draw.text((xy[0] - (box[2] - box[0]) / 2, y), line, font=font, fill=fill)
        y += (box[3] - box[1]) + line_gap
    return y


def _normal_legend(legend) -> list[dict[str, str]]:
    if not legend:
        return []
    out: list[dict[str, str]] = []
    for item in legend:
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("name") or "").strip()
            color = str(item.get("color") or "#5A6573").strip()
            style = str(item.get("style") or "solid").strip()
        else:
            vals = list(item)
            label = str(vals[0]) if vals else ""
            color = str(vals[1]) if len(vals) > 1 else "#5A6573"
            style = str(vals[2]) if len(vals) > 2 else "solid"
        if label:
            out.append({"label": label, "color": color, "style": style})
    return out


def _compose_slide_png(body_png: str, out_png: str, *, title: str,
                       kicker: str | None, brand: str | None,
                       diagram_title: str | None, legend) -> dict:
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (SLIDE_SIZE, SLIDE_SIZE), "white")
    canvas.paste(_gradient((SLIDE_SIZE, SLIDE_HERO_H)), (0, 0))
    draw = ImageDraw.Draw(canvas)

    if brand:
        draw.text((SLIDE_SIZE - SLIDE_MARGIN, 54), brand, font=_font(58, bold=True),
                  fill="white", anchor="ra")
    if kicker:
        _draw_centered_text(draw, (SLIDE_SIZE // 2, 284), kicker, _font(68),
                            (248, 250, 252), 1550)
    _draw_centered_text(draw, (SLIDE_SIZE // 2, 390), title, _font(78, bold=True),
                        "white", 1850, line_gap=12)

    panel_x, panel_y = SLIDE_MARGIN, SLIDE_HERO_H + 34
    panel_w = SLIDE_SIZE - SLIDE_MARGIN * 2
    panel_h = SLIDE_SIZE - panel_y - SLIDE_MARGIN
    draw.rounded_rectangle((panel_x, panel_y, panel_x + panel_w, panel_y + panel_h),
                           radius=4, fill="white", outline="#D7DEE8", width=2)

    caption = diagram_title or "System Architecture"
    cap_font = _font(34, bold=True)
    cap_box = draw.textbbox((0, 0), caption, font=cap_font)
    draw.text((SLIDE_SIZE // 2 - (cap_box[2] - cap_box[0]) / 2, panel_y + 22),
              caption, font=cap_font, fill="#0F172A")

    legend_items = _normal_legend(legend)
    legend_h = 118 if legend_items else 0
    body = Image.open(body_png).convert("RGBA")
    max_w = panel_w - SLIDE_PANEL_PAD * 2
    max_h = panel_h - 82 - legend_h - SLIDE_PANEL_PAD
    body.thumbnail((max_w, max_h), Image.LANCZOS)
    body_x = panel_x + (panel_w - body.width) // 2
    body_y = panel_y + 74
    canvas.paste(body, (body_x, body_y), body)

    if legend_items:
        lx, ly = panel_x + 26, panel_y + panel_h - legend_h + 18
        lw, lh = 260, legend_h - 36
        draw.rounded_rectangle((lx, ly, lx + lw, ly + lh), radius=8,
                               fill="#FFFFFF", outline="#CBD5E1", width=2)
        draw.text((lx + 16, ly + 12), "LEGEND", font=_font(17, bold=True),
                  fill="#334155")
        yy = ly + 40
        for item in legend_items[:4]:
            color = item["color"]
            if item["style"] == "dashed":
                for x in range(lx + 18, lx + 72, 16):
                    draw.line((x, yy + 9, x + 9, yy + 9), fill=color, width=3)
            else:
                draw.line((lx + 18, yy + 9, lx + 72, yy + 9), fill=color, width=3)
            draw.text((lx + 84, yy), item["label"], font=_font(16), fill="#334155")
            yy += 24

    canvas.save(out_png, quality=95)
    return {
        "panel": [panel_x, panel_y, panel_w, panel_h],
        "body": [body_x, body_y, body.width, body.height],
        "legend_count": len(legend_items),
    }


def _drawio_text_cell(cid: str, value: str, x: float, y: float, w: float, h: float,
                      *, size: int, color: str = "#0F172A", bold: bool = False,
                      align: str = "center", fill: str = "none",
                      stroke: str = "none") -> str:
    style = (
        "text;html=1;strokeColor={stroke};fillColor={fill};align={align};"
        "verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize={size};"
        "fontColor={color};fontStyle={bold};"
    ).format(stroke=stroke, fill=fill, align=align, size=size,
             color=color, bold=1 if bold else 0)
    return (f'<mxCell id="{cid}" value="{_xml(value)}" style="{style}" vertex="1" '
            f'parent="1"><mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" '
            f'height="{h:.0f}" as="geometry"/></mxCell>')


def _drawio_rect_cell(cid: str, x: float, y: float, w: float, h: float,
                      *, fill: str, stroke: str = "none", rounded: int = 0,
                      shadow: int = 0) -> str:
    style = (
        f"rounded={rounded};whiteSpace=wrap;html=1;fillColor={fill};"
        f"strokeColor={stroke};shadow={shadow};"
    )
    return (f'<mxCell id="{cid}" value="" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" '
            f'height="{h:.0f}" as="geometry"/></mxCell>')


def _transform_drawio_body(xml: str, *, x: float, y: float, scale: float,
                           prefix: str = "body_") -> str:
    m = re.search(r"<root>(.*)</root>", xml, re.S)
    inner = m.group(1) if m else ""
    inner = re.sub(r'<mxCell id="0"/>\s*<mxCell id="1" parent="0"/>', "", inner)
    for attr in ("id", "source", "target"):
        inner = re.sub(fr'{attr}="([^"]+)"',
                       lambda mt: f'{attr}="{prefix}{mt.group(1)}"', inner)
    inner = inner.replace(f'parent="{prefix}1"', 'parent="1"')

    def _geo(mt: "re.Match[str]") -> str:
        gx = float(mt.group(1)) * scale + x
        gy = float(mt.group(2)) * scale + y
        gw = float(mt.group(3)) * scale
        gh = float(mt.group(4)) * scale
        return (f'<mxGeometry x="{gx:.0f}" y="{gy:.0f}" width="{gw:.0f}" '
                f'height="{gh:.0f}"')

    return re.sub(
        r'<mxGeometry x="(-?[\d.]+)" y="(-?[\d.]+)" width="([\d.]+)" height="([\d.]+)"',
        _geo,
        inner,
    )


def _compose_slide_drawio(body_xml: str, out_path: str, *, title: str,
                          kicker: str | None, brand: str | None,
                          diagram_title: str | None, legend, body_box: list[int],
                          panel: list[int]) -> str:
    body_w, body_h = _page_dims(body_xml)
    bx, by, bw, bh = body_box
    scale = min(bw / body_w, bh / body_h) if body_w and body_h else 1.0
    body_inner = _transform_drawio_body(body_xml, x=bx, y=by, scale=scale)

    cells: list[str] = [
        _drawio_rect_cell("slide_bg", 0, 0, SLIDE_SIZE, SLIDE_SIZE, fill="#FFFFFF"),
        _drawio_rect_cell("slide_hero", 0, 0, SLIDE_SIZE, SLIDE_HERO_H,
                          fill="#075985"),
        _drawio_rect_cell("slide_panel", panel[0], panel[1], panel[2], panel[3],
                          fill="#FFFFFF", stroke="#D7DEE8", rounded=1, shadow=1),
    ]
    if brand:
        cells.append(_drawio_text_cell("slide_brand", brand, SLIDE_SIZE - 368, 44,
                                       330, 70, size=36, color="#FFFFFF",
                                       bold=True, align="right"))
    if kicker:
        cells.append(_drawio_text_cell("slide_kicker", kicker, 244, 258, 1560, 86,
                                       size=42, color="#F8FAFC"))
    cells.append(_drawio_text_cell("slide_title", title, 90, 352, 1868, 132,
                                   size=50, color="#FFFFFF", bold=True))
    cells.append(_drawio_text_cell("slide_diagram_title",
                                   diagram_title or "System Architecture",
                                   panel[0] + 30, panel[1] + 18, panel[2] - 60, 48,
                                   size=26, color="#0F172A", bold=True))

    legend_items = _normal_legend(legend)
    if legend_items:
        lx, ly, lw, lh = panel[0] + 26, panel[1] + panel[3] - 100, 260, 82
        cells.append(_drawio_rect_cell("legend_box", lx, ly, lw, lh,
                                       fill="#FFFFFF", stroke="#CBD5E1", rounded=1))
        cells.append(_drawio_text_cell("legend_title", "LEGEND", lx + 12, ly + 8,
                                       94, 24, size=13, color="#334155",
                                       bold=True, align="left"))
        yy = ly + 36
        for i, item in enumerate(legend_items[:4]):
            style = "dashed=1;" if item["style"] == "dashed" else ""
            cells.append(
                f'<mxCell id="legend_line_{i}" value="" style="endArrow=none;html=1;'
                f'rounded=0;strokeWidth=3;{style}strokeColor={_xml(item["color"])};" '
                f'edge="1" parent="1"><mxGeometry width="50" height="50" relative="1" '
                f'as="geometry"><mxPoint x="{lx + 18:.0f}" y="{yy + 10:.0f}" as="sourcePoint"/>'
                f'<mxPoint x="{lx + 72:.0f}" y="{yy + 10:.0f}" as="targetPoint"/>'
                f'</mxGeometry></mxCell>'
            )
            cells.append(_drawio_text_cell(f"legend_label_{i}", item["label"],
                                           lx + 84, yy, 148, 22, size=12,
                                           color="#334155", align="left"))
            yy += 24

    xml_out = (
        '<mxfile host="app.diagrams.net"><diagram name="architecture" id="d1">'
        '<mxGraphModel dx="1400" dy="900" grid="0" guides="1" tooltips="1" '
        'connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        f'pageWidth="{SLIDE_SIZE}" pageHeight="{SLIDE_SIZE}" math="0" shadow="0">'
        '<root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        + "".join(cells) + body_inner + "</root></mxGraphModel></diagram></mxfile>"
    )
    Path(out_path).write_text(xml_out, encoding="utf-8")
    return xml_out


def render_slide(g: Pretty, out_basename: str, *, title: str,
                 kicker: str | None = None, brand: str | None = None,
                 diagram_title: str | None = None, legend=None) -> str:
    """Render ``g`` inside a 2048x2048 production slide.

    The body diagram remains fully audit/exportable as ``out.dot`` and
    ``out.nodes.json``. The final ``out.png`` is a composed square slide, and
    ``out.drawio`` contains editable hero text, legend, clusters, nodes, and edges.
    """
    out = Path(out_basename)
    png_path = f"{out_basename}.png"
    drawio_path = f"{out_basename}.drawio"
    marker_path = f"{out_basename}.slide.json"

    body_png = g.render(out_basename)
    body_xml = g.to_drawio(out_basename)
    layout = _compose_slide_png(
        body_png, png_path, title=title, kicker=kicker, brand=brand,
        diagram_title=diagram_title or g.title, legend=legend,
    )
    _compose_slide_drawio(
        body_xml, drawio_path, title=title, kicker=kicker, brand=brand,
        diagram_title=diagram_title or g.title, legend=legend,
        body_box=layout["body"], panel=layout["panel"],
    )
    Path(marker_path).write_text(json.dumps({
        "type": "slide",
        "title": title,
        "kicker": kicker,
        "brand": brand,
        "diagram_title": diagram_title or g.title,
        "png": str(out.with_suffix(".png")),
        "drawio": str(out.with_suffix(".drawio")),
        "dot": str(out.with_suffix(".dot")),
    }, indent=2), encoding="utf-8")
    return png_path


if __name__ == "__main__":  # quick self-check render
    import sys
    base = sys.argv[1] if len(sys.argv) > 1 else "/tmp/pretty_demo"
    g = Pretty("Demo — Pretty Style", subtitle="self-check", direction="LR",
               icons_root="/icons")
    g.cluster("app", "Application", kind="Compute")
    g.box("user", "User", kind="source")
    g.box("api", "API Service", kind="compute", sublabel="FastAPI", parent="app")
    g.box("db", "PostgreSQL", kind="data")
    g.link("user", "api", label="request")
    g.link("api", "db", label="SQL")
    print(g.render(base))
