"""Pretty class — main authoring API + DOT generation."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from subprocess_utils import run_graphviz

from .constants import (
    CLUSTER_KINDS, EDGE_COLOR, EDGE_FONTCOLOR, FLOW_COLORS, FLOW_GRID_MIN,
    FONT, NODE_KINDS, PAGE_SIZE, PRO_ACCENTS, PRO_EDGE, PRO_MUTED, PRO_ORDER,
    PRO_TITLE,
)

try:
    from ..drawio_catalog import (
        load_catalog as _load_catalog,
        get_icon as _catalog_get_icon,
        search_icon as _catalog_search,
    )
except (ImportError, ValueError):
    try:
        from drawio_catalog import (  # type: ignore[no-redef]
            load_catalog as _load_catalog,
            get_icon as _catalog_get_icon,
            search_icon as _catalog_search,
        )
    except ImportError:
        _load_catalog = None  # type: ignore[assignment]
        _catalog_get_icon = None  # type: ignore[assignment]
        _catalog_search = None  # type: ignore[assignment]


# Keyword → AWS group-stencil name, most specific first (matched against a
# cluster's label, case-insensitive). Lets a native AWS diagram render its
# containers as real ``mxgraph.aws4.group`` frames (official colour + corner
# icon) instead of a plain rounded box. Ground-truth names from catalog/aws.json.
_AWS_GROUP_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("security group", "group_security_group"),
    ("availability zone", "group_availability_zone"),
    ("auto scaling", "group_auto_scaling_group"),
    ("corporate data center", "group_corporate_data_center"),
    ("corporate data centre", "group_corporate_data_center"),
    ("on-premise", "group_on_premise"),
    ("on premise", "group_on_premise"),
    ("on-prem", "group_on_premise"),
    ("data center", "group_corporate_data_center"),
    ("datacenter", "group_corporate_data_center"),
    ("public subnet", "group_subnet"),
    ("private subnet", "group_subnet"),
    ("subnet", "group_subnet"),
    ("aws cloud", "group_aws_cloud_alt"),
    ("region", "group_region"),
    ("account", "group_account"),
    ("vpc", "group_vpc"),
)


def _aws_group_for_label(label: str | None) -> str | None:
    """Best AWS group-stencil name for a cluster label, or None if none fits."""
    text = f" {(label or '').lower()} "
    for keyword, group in _AWS_GROUP_KEYWORDS:
        if keyword in text:
            return group
    return None


def _est_text_w(s: str, size: int, *, bold: bool = False) -> float:
    """Approx Helvetica text width in pts (~0.62em/char bold, ~0.54em regular)."""
    return len(s or "") * size * (0.62 if bold else 0.54)


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
    number: int | None = None
    accent: str | None = None


@dataclass
class _Edge:
    a: str
    b: str
    label: str | None
    style: str
    color: str | None
    penwidth: float | None = None
    ltail: str | None = None
    lhead: str | None = None
    constraint: bool | None = None
    taillabel: str | None = None


@dataclass
class Pretty:
    title: str
    subtitle: str | None = None
    direction: str = "LR"
    icons_root: str = "/icons"
    splines: str = "ortho"
    size: str = PAGE_SIZE
    node_width: float | None = None
    node_height: float | None = None
    theme: str = "default"
    dpi: int | None = None
    icon_size: int | None = None
    title_size: int | None = None
    sublabel_size: int | None = None
    edge_label_size: int | None = None
    cluster_label_size: int | None = None
    nodes: dict[str, _Node] = field(default_factory=dict)
    clusters: dict[str, _Cluster] = field(default_factory=dict)
    edges: list[_Edge] = field(default_factory=list)
    same_ranks: list[list[str]] = field(default_factory=list)
    grid_rows: list[list[str]] = field(default_factory=list)
    cluster_grids: dict[str, int] = field(default_factory=dict)
    flow_layout: bool = True

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
             taillabel: str | None = None, flow: str | None = None) -> None:
        if flow and flow in FLOW_COLORS:
            fcolor, fstyle = FLOW_COLORS[flow]
            if color is None:
                color = fcolor
            if style == "solid":
                style = fstyle
        self.edges.append(_Edge(a, b, label, style, color, penwidth,
                                ltail, lhead, constraint, taillabel))

    def same_rank(self, ids: list[str]) -> None:
        """Force nodes onto the same row (clean replica grids)."""
        self.same_ranks.append(list(ids))

    def poster_grid(self, *rows: list[str]) -> None:
        """Declare a poster grid from per-row anchor node ids (one per section)."""
        self.grid_rows = [list(r) for r in rows if r]

    def grid_cluster(self, cluster_id: str, cols: int = 3) -> None:
        """Pack a cluster's child nodes into a compact ``cols``-wide grid."""
        if cols >= 1:
            self.cluster_grids[cluster_id] = int(cols)

    def _grid_block(self, cid: str, indent: str) -> list[str]:
        cols = self.cluster_grids.get(cid)
        if not cols:
            return []
        members = [n.id for n in self.nodes.values() if n.parent == cid]
        min_members = FLOW_GRID_MIN if self.flow_layout else 2
        if len(members) < min_members:
            return []
        rows = [members[i:i + cols] for i in range(0, len(members), cols)]
        lines: list[str] = []
        for row in rows:
            if len(row) > 1:
                joined = " ".join(f'"{m}"' for m in row)
                lines.append(f'{indent}{{rank=same; {joined}}}')
        for col in range(cols):
            colnodes = [row[col] for row in rows if col < len(row)]
            for a, b in zip(colnodes[:-1], colnodes[1:]):
                lines.append(f'{indent}"{a}" -> "{b}" [style="invis"];')
        return lines

    def _auto_grid(self) -> None:
        if not self.flow_layout:
            return
        for cid in self.clusters:
            if cid in self.cluster_grids:
                continue
            n = sum(1 for nd in self.nodes.values() if nd.parent == cid)
            if n < FLOW_GRID_MIN:
                continue
            self.cluster_grids[cid] = 2 if n <= 6 else 3

    def _top_section(self, node_id: str) -> str | None:
        n = self.nodes.get(node_id)
        cid = n.parent if n else None
        seen: set[str] = set()
        while cid is not None and cid not in seen:
            seen.add(cid)
            c = self.clusters.get(cid)
            if c is None or c.parent is None:
                return cid
            cid = c.parent
        return cid

    # ---- icon resolution ---- #
    def _icon_path(self, icon: str | None) -> str | None:
        if not icon:
            return None
        p = Path(icon)
        if not p.is_absolute():
            p = Path(self.icons_root) / icon
        return str(p) if p.exists() else None

    def _resolve_stencil_name(self, cat: object, icon_path: str | None) -> str | None:
        """Map a node's icon file to a ground-truth draw.io stencil name.

        Direct stem match first (icon filename stem == catalog name); then a
        conservative fuzzy fallback bridging mingrammer naming (hyphens) vs aws4
        catalog naming (underscores), e.g. ``elastic-container-service`` →
        ``elastic_container_service``. Only near-exact matches (score >= 85) are
        accepted, so a fuzzy guess never yields a wrong (blank-rendering) stencil.
        """
        if not (cat and _catalog_get_icon and icon_path):
            return None
        stem = Path(icon_path).stem.lower()
        if _catalog_get_icon(cat, stem):
            return stem
        if not _catalog_search:
            return None
        query = stem.replace("-", " ").replace("_", " ").strip()
        if not query:
            return None
        hits = _catalog_search(cat, query, kind="icon", limit=1)
        if hits and hits[0].get("score", 0) >= 85:
            return hits[0]["name"]
        return None

    # ---- style resolution (theme-aware; shared by DOT + drawio sidecar) ---- #
    def _accent_map(self) -> dict[str, tuple[str, str, str]]:
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
        for cid, c in self.clusters.items():
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
        if self.theme == "pro":
            acc = self._accent_map().get(cid, PRO_ACCENTS["slate"])
            return acc[2], acc[1]
        c = self.clusters[cid]
        return CLUSTER_KINDS.get(c.kind, CLUSTER_KINDS["Neutral"])

    def _sizes(self) -> dict[str, int]:
        return {
            "icon": int(self.icon_size or 36),
            "title": int(self.title_size or 13),
            "sub": int(self.sublabel_size or 11),
            "edge": int(self.edge_label_size or 12),
            "cluster": int(self.cluster_label_size or 15),
        }

    def _node_margin(self) -> str:
        if self.node_width is not None:
            return "0.14,0.08"
        return "0.22,0.13" if self.theme == "pro" else "0.2,0.12"

    def _cluster_label_pro(self, c: _Cluster) -> str:
        accent = self._accent_map().get(c.id, PRO_ACCENTS["slate"])[1]
        csize = self._sizes()["cluster"]
        badge = ""
        if c.number is not None:
            badge = (f'<TD BGCOLOR="{accent}" WIDTH="{csize + 9}" HEIGHT="{csize + 9}" '
                     f'ALIGN="CENTER" VALIGN="MIDDLE"><FONT COLOR="#FFFFFF" '
                     f'POINT-SIZE="{csize - 1}"><B>'
                     f'{c.number}</B></FONT></TD><TD WIDTH="8"></TD>')
        return ('<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="2">'
                f'<TR>{badge}<TD ALIGN="LEFT"><FONT COLOR="{accent}" '
                f'POINT-SIZE="{csize}"><B>{_esc(c.label)}</B></FONT></TD></TR></TABLE>')

    # ---- DOT generation ---- #
    def _node_dot(self, n: _Node) -> str:
        fill, stroke, title_c, sub_c = self._node_style(n)
        icon = self._icon_path(n.icon)
        sz = self._sizes()
        label_html = (f'<FONT COLOR="{title_c}"><B>{_esc(n.label)}</B></FONT>'
                      if title_c else f'<B>{_esc(n.label)}</B>')
        if n.sublabel:
            label_html += (f'<BR/><FONT POINT-SIZE="{sz["sub"]}" COLOR="{sub_c}">'
                           f'{_esc(n.sublabel)}</FONT>')
        fixed = self.node_width is not None
        align = "LEFT" if (icon or fixed) else "CENTER"
        if icon:
            cell = (
                '<TR>'
                f'<TD FIXEDSIZE="TRUE" WIDTH="{sz["icon"]}" HEIGHT="{sz["icon"]}">'
                f'<IMG SRC="{icon}" SCALE="TRUE"/></TD>'
                '<TD WIDTH="10"></TD>'
                f'<TD ALIGN="LEFT" BALIGN="LEFT"><FONT POINT-SIZE="{sz["title"]}">'
                f'{label_html}</FONT></TD>'
                '</TR>'
            )
        else:
            cell = (f'<TR><TD ALIGN="{align}" BALIGN="{align}">'
                    f'<FONT POINT-SIZE="{sz["title"]}">{label_html}</FONT></TD></TR>')
        table_attrs = 'BORDER="0" CELLBORDER="0" CELLSPACING="0" CELLPADDING="2"'
        if fixed:
            need = max(_est_text_w(n.label, sz["title"], bold=True),
                       _est_text_w(n.sublabel or "", sz["sub"]))
            need += (sz["icon"] + 10 if icon else 0) + 24
            tw = max(self.node_width, need)
            th = self.node_height or self.node_width
            if icon:
                th = max(th, sz["icon"] + 10)
            table_attrs += (f' WIDTH="{tw:.0f}" '
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
            f'{"  " * depth}  labeljust="l"; fontsize="{self._sizes()["cluster"] - 1}"; '
            f'fontname="{FONT}"; fontcolor="#5a6270";',
            f'{"  " * depth}  label=<{label_html}>;',
        ]
        for sub in self.clusters.values():
            if sub.parent == cid:
                lines += self._cluster_block(sub.id, depth + 1)
        for n in self.nodes.values():
            if n.parent == cid:
                lines.append(f'{"  " * depth}{self._node_dot(n)}')
        lines += self._grid_block(cid, "  " * depth)
        lines.append(f'{"  " * depth}}}')
        return lines

    def to_dot(self) -> str:
        self._auto_grid()
        pro = self.theme == "pro"
        tcolor = PRO_TITLE if pro else "#000000"
        tsize = "22" if pro else "20"
        title = (f'<B><FONT POINT-SIZE="{tsize}" COLOR="{tcolor}">'
                 f'{_esc(self.title)}</FONT></B>')
        if self.subtitle:
            title += (f'<BR/><FONT POINT-SIZE="11" COLOR="{PRO_MUTED if pro else "#8a8a8a"}">'
                      f'{_esc(self.subtitle)}</FONT>')
        dpi = self.dpi or (192 if pro else 168)
        nodesep, ranksep = ("0.4", "0.8") if pro else ("0.5", "0.9")
        if self.grid_rows:
            nodesep, ranksep = "0.3", "1.5"
        if self.cluster_grids:
            if self.flow_layout:
                nodesep, ranksep = "0.28", "0.7"
            else:
                nodesep, ranksep = "0.18", "0.45"
        edge_color = PRO_EDGE if pro else EDGE_COLOR
        node_pen = "1.5" if pro else "1.4"
        arrowhead = ' arrowhead="vee"' if pro else ""
        sz = self._sizes()
        out = [
            "digraph G {",
            f'  rankdir="{self.direction}"; bgcolor="white"; pad="0.5";',
            f'  size="{self.size}";' + (f' dpi="{dpi}";' if dpi else ""),
            f'  labelloc="t"; labeljust="l"; label=<{title}>;',
            f'  fontname="{FONT}"; splines="{self.splines}"; '
            f'nodesep="{nodesep}"; ranksep="{ranksep}"; compound="true"; newrank="true";',
            f'  node [shape="box", style="rounded,filled", fontname="{FONT}", '
            f'penwidth="{node_pen}", margin="{self._node_margin()}"];',
            f'  edge [color="{edge_color}", fontname="{FONT}", '
            f'fontsize="{sz["edge"]}", fontcolor="{EDGE_FONTCOLOR}", arrowsize="0.9", '
            f'penwidth="1.6"{arrowhead}];',
        ]
        for c in self.clusters.values():
            if c.parent is None:
                out += self._cluster_block(c.id, 1)
        for n in self.nodes.values():
            if n.parent is None:
                out.append(self._node_dot(n))
        for grp in self.same_ranks:
            ids = " ".join(f'"{i}"' for i in grp)
            out.append(f"  {{rank=same; {ids}}}")
        if self.grid_rows:
            gridded = set()
            for gcid in self.cluster_grids:
                top = gcid
                seen: set[str] = set()
                while top is not None and top not in seen:
                    seen.add(top)
                    c = self.clusters.get(top)
                    if c is None or c.parent is None:
                        break
                    top = c.parent
                gridded.add(top)
            for row in self.grid_rows:
                for anchor in row:
                    sec = self._top_section(anchor)
                    if sec is None or sec in gridded:
                        continue
                    members = [nid for nid in self.nodes
                               if self._top_section(nid) == sec]
                    if len(members) > 1:
                        joined = " ".join(f'"{m}"' for m in members)
                        out.append(f"  {{rank=same; {joined}}}")
            for row in self.grid_rows:
                for a, b in zip(row[:-1], row[1:]):
                    out.append(f'  "{a}" -> "{b}" [style="invis"];')
            max_cols = max(len(r) for r in self.grid_rows)
            for col in range(max_cols):
                ids = [r[col] for r in self.grid_rows if col < len(r)]
                if len(ids) > 1:
                    joined = " ".join(f'"{i}"' for i in ids)
                    out.append(f"  {{rank=same; {joined}}}")
        for e in self.edges:
            attrs = []
            anchor_to_tail = False
            if e.label and not e.taillabel and self.flow_layout:
                ta, tb = self._top_section(e.a), self._top_section(e.b)
                anchor_to_tail = ta is not None and tb is not None and ta != tb
            if e.label and not anchor_to_tail:
                lbl = (
                    '<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" '
                    'CELLPADDING="3" BGCOLOR="white"><TR><TD>'
                    f'<FONT POINT-SIZE="{sz["edge"]}" COLOR="{EDGE_FONTCOLOR}">'
                    f'{_esc(e.label)}</FONT></TD></TR></TABLE>>'
                )
                attrs.append(f'label={lbl}')
            if anchor_to_tail:
                albl = (
                    '<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" '
                    'CELLPADDING="2" BGCOLOR="white"><TR><TD>'
                    f'<FONT POINT-SIZE="{sz["edge"]}" COLOR="{EDGE_FONTCOLOR}">'
                    f'{_esc(e.label)}</FONT></TD></TR></TABLE>>'
                )
                attrs.append(f'taillabel={albl}')
                attrs.append('labeldistance="1.6"')
            if e.taillabel:
                tlbl = (
                    '<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" '
                    'CELLPADDING="2" BGCOLOR="white"><TR><TD>'
                    f'<FONT POINT-SIZE="{sz["edge"] - 1}" COLOR="{EDGE_FONTCOLOR}">'
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
            relax = e.constraint is False
            if e.constraint is None and (
                self.grid_rows or (self.cluster_grids and not self.flow_layout)
            ):
                ta, tb = self._top_section(e.a), self._top_section(e.b)
                if ta is not None and tb is not None and ta != tb:
                    relax = True
            if relax:
                attrs.append("constraint=false")
            a = f" [{', '.join(attrs)}]" if attrs else ""
            out.append(f'  "{e.a}" -> "{e.b}"{a};')
        out.append("}")
        return "\n".join(out)

    # ---- render ---- #
    def render(self, out_basename: str, *, dpi_override: int | None = None) -> str:
        """Write ``<base>.dot`` + ``<base>.png`` + ``<base>.nodes.json``."""
        dot_path = f"{out_basename}.dot"
        png_path = f"{out_basename}.png"
        Path(dot_path).write_text(self.to_dot(), encoding="utf-8")
        cmd = ["dot", "-Tpng", dot_path, "-o", png_path]
        if dpi_override:
            cmd.append(f"-Gdpi={dpi_override}")
        run_graphviz(cmd, check=True, capture_output=True, text=True)
        self._write_sidecar(f"{out_basename}.nodes.json")
        return png_path

    def _write_sidecar(self, path: str) -> None:
        _cat = _load_catalog() if _load_catalog else None

        node_meta = {}
        for n in self.nodes.values():
            fill, stroke, _, _ = self._node_style(n)
            icon_path = self._icon_path(n.icon)
            stencil_name = self._resolve_stencil_name(_cat, icon_path)
            node_meta[n.id] = {
                "label": n.label, "sublabel": n.sublabel, "kind": n.kind,
                "fill": fill, "stroke": stroke, "icon": icon_path,
                "shadow": 1 if self.theme == "pro" else 0,
                "stencil_name": stencil_name,
            }
        cluster_meta = {}
        for c in self.clusters.values():
            fill, stroke = self._cluster_style(c.id)
            label = c.label if c.number is None else f"{c.number} · {c.label}"
            cluster_meta[c.id] = {
                "label": label, "fill": fill, "stroke": stroke,
                "group_name": _aws_group_for_label(c.label),
            }
        style = dict(self._sizes())
        if self.node_width is not None:
            style["node_width"] = int(self.node_width)
        if self.node_height is not None:
            style["node_height"] = int(self.node_height)
        data = {"title": self.title, "subtitle": self.subtitle,
                "nodes": node_meta, "clusters": cluster_meta,
                "style": style}
        Path(path).write_text(json.dumps(data), encoding="utf-8")

    def to_drawio(self, out_basename: str) -> str:
        """Build an editable .drawio from the laid-out .dot + sidecar styling."""
        from .drawio import dot_to_drawio
        return dot_to_drawio(f"{out_basename}.dot", f"{out_basename}.nodes.json",
                             f"{out_basename}.drawio")
