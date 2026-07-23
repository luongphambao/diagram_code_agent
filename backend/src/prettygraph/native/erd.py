"""ERD / Database Schema Diagram native renderer — improvement plan MVP-3
phase 3.

Same "compose directly on a Diagram" model as `sequence.py` (see that
module's docstring for why): table layout is FK-dependency-driven, not a
generic flexbox measure/place tree, so `layout_engine.py`'s node-kind
dispatch doesn't fit here either.

Each table is one mxCell PER ROW (header + one cell per column) stacked into
a card, so a foreign-key relationship can point its crow's-foot connector at
the EXACT row it references — via the same real-edge-with-computed-fraction
technique `sequence.py` uses for message rows, not the generic obstacle
router. Crow's-foot notation is drawn with draw.io's native `ERone`/`ERmany`
arrow markers (built into every stock draw.io install, same class of native
shape as `umlLifeline`/`umlFrame` — no catalog stencil lookup needed).

Layout: a simple longest-path layering over the FK dependency graph (referenced
table -> dependent table) places master/lookup tables on the left and the
tables that reference them progressively to the right; tables sharing a layer
stack vertically. This deliberately does NOT reuse `layout_plan.py`/`repair.py`
(those score/repair the ARCHITECTURE renderer's band-and-zone geometry, which
doesn't apply to a table-row layout) — a future pass could still borrow their
edge-crossing SCORING to pick between alternative table orderings within a
layer, but that's not needed for a correct first render.
"""

from __future__ import annotations

from .builder import Diagram, Z_CHROME, Z_EDGE, Z_NODE, _esc
from .theme import THEME

MARGIN_X = 60
MARGIN_Y = 60
LAYER_GAP_X = 120
TABLE_GAP_Y = 40
TABLE_W = 220
HEADER_H = 30
ROW_H = 24

_HEADER_STYLE = (
    f"rounded=0;whiteSpace=wrap;html=1;fillColor={THEME.base_stroke};fontColor=#FFFFFF;"
    "fontStyle=1;align=center;verticalAlign=middle;"
)
_ROW_STYLE = (
    f"rounded=0;whiteSpace=wrap;html=1;fillColor={THEME.base};strokeColor={THEME.base_stroke};"
    "align=left;spacingLeft=8;fontSize=11;verticalAlign=middle;"
)
_PK_ROW_STYLE = _ROW_STYLE + "fontStyle=4;"  # underline, ER convention for PK

_CARDINALITY_ARROWS: dict[str, tuple[str, str]] = {
    # (start marker on the dependent/FK side, end marker on the referenced side)
    "one_to_one": ("ERone", "ERone"),
    "one_to_many": ("ERmany", "ERone"),
    "many_to_many": ("ERmany", "ERmany"),
}


def _column_label(col: dict) -> str:
    badges = []
    if col.get("primary_key"):
        badges.append("PK")
    if col.get("foreign_key"):
        badges.append("FK")
    prefix = f"[{','.join(badges)}] " if badges else ""
    dtype = col.get("data_type") or ""
    nullable = "" if col.get("nullable", True) else " NOT NULL"
    return f"{prefix}{col.get('name', '')}: {dtype}{nullable}"


def _layer_tables(entities: list[dict], relationships: list[dict]) -> dict[str, int]:
    """Longest-path layer per table id: referenced tables get a lower layer
    number than the tables that hold a foreign key into them. Robust to
    cycles (self-reference, circular FK) — a bounded number of relaxation
    passes instead of a strict topological sort, so a cyclic spec still
    renders (lint_erd is what should flag the cycle, not the renderer)."""
    ids = [e["id"] for e in entities if e.get("id")]
    layer = {i: 0 for i in ids}
    edges = [
        (r.get("from_entity"), r.get("to_entity"))
        for r in relationships
        if r.get("from_entity") in layer and r.get("to_entity") in layer
    ]
    for _ in range(len(ids) + 1):
        changed = False
        for dependent, referenced in edges:
            if layer[dependent] <= layer[referenced]:
                layer[dependent] = layer[referenced] + 1
                changed = True
        if not changed:
            break
    return layer


def build_erd_tree(spec: dict, *, flat: bool = False, plan: dict | None = None) -> tuple[Diagram, dict]:
    """Build a native ERD from an erd render_spec (tools/analysis/erd_tools.py's
    projection of ERDSpec). Same (Diagram, root) contract as topology.build_tree."""
    entities = [e for e in spec.get("entities", []) if e.get("id")]
    relationships = [
        r for r in spec.get("relationships", []) if r.get("from_entity") and r.get("to_entity")
    ]
    layer_of = _layer_tables(entities, relationships)

    layers: dict[int, list[dict]] = {}
    for e in entities:
        layers.setdefault(layer_of.get(e["id"], 0), []).append(e)

    table_h: dict[str, int] = {}
    for e in entities:
        table_h[e["id"]] = HEADER_H + max(len(e.get("columns", [])), 1) * ROW_H

    n_layers = max(layers.keys(), default=0) + 1
    page_w = 2 * MARGIN_X + n_layers * (TABLE_W + LAYER_GAP_X)
    page_h = MARGIN_Y

    d = Diagram("erd", contract="bake", flat=flat, page=(round(page_w), 800))

    # column_row[table_id][column_name] -> absolute y of that row's center,
    # kept for _emit_relationship_edge's exitY/entryY fraction math below.
    column_row: dict[str, dict[str, float]] = {}
    table_x: dict[str, float] = {}

    for layer_idx in sorted(layers):
        x = MARGIN_X + layer_idx * (TABLE_W + LAYER_GAP_X)
        y = MARGIN_Y
        for e in layers[layer_idx]:
            tid = e["id"]
            table_x[tid] = x
            h = table_h[tid]
            d._put(tid, "1", x, y, TABLE_W, h, "fillColor=none;strokeColor=none;", "", z=Z_CHROME)
            d.R[tid]["ob"] = True
            d._put(
                f"{tid}_hdr", "1", x, y, TABLE_W, HEADER_H, _HEADER_STYLE, e.get("name") or tid, z=Z_NODE
            )
            cols = e.get("columns") or [{}]
            rows: dict[str, float] = {}
            for i, col in enumerate(e.get("columns", [])):
                ry = y + HEADER_H + i * ROW_H
                style = _PK_ROW_STYLE if col.get("primary_key") else _ROW_STYLE
                d._put(f"{tid}_col_{i}", "1", x, ry, TABLE_W, ROW_H, style, _column_label(col), z=Z_NODE)
                rows[col.get("name", "")] = ry + ROW_H / 2
            column_row[tid] = rows
            y += h + TABLE_GAP_Y
        page_h = max(page_h, y)

    for i, rel in enumerate(relationships):
        _emit_relationship_edge(d, f"rel_{i}", rel, table_x, table_h, column_row)

    d.page[0] = round(page_w)
    d.page[1] = round(page_h + MARGIN_Y)

    title = spec.get("title") or ""
    if title:
        d.text("__title", [0, 20], round(page_w), title, fs=14)
        d._cell_z[d._cell_index["__title"]] = Z_CHROME

    return d, {"kind": "erd", "entities": [e["id"] for e in entities]}


def _emit_relationship_edge(
    d: Diagram,
    eid: str,
    rel: dict,
    table_x: dict[str, float],
    table_h: dict[str, int],
    column_row: dict[str, dict[str, float]],
) -> None:
    src, tgt = rel.get("from_entity"), rel.get("to_entity")
    if src not in d.R or tgt not in d.R:
        return
    src_r, tgt_r = d.R[src], d.R[tgt]
    from_col = (rel.get("from_columns") or [""])[0]
    to_col = (rel.get("to_columns") or [""])[0]
    src_y = column_row.get(src, {}).get(from_col, src_r["y"] + src_r["h"] / 2)
    tgt_y = column_row.get(tgt, {}).get(to_col, tgt_r["y"] + tgt_r["h"] / 2)
    frac_src = 0.0 if src_r["h"] == 0 else (src_y - src_r["y"]) / src_r["h"]
    frac_tgt = 0.0 if tgt_r["h"] == 0 else (tgt_y - tgt_r["y"]) / tgt_r["h"]
    exit_x = 1 if table_x.get(tgt, 0) >= table_x.get(src, 0) else 0
    entry_x = 0 if table_x.get(tgt, 0) >= table_x.get(src, 0) else 1
    start_arrow, end_arrow = _CARDINALITY_ARROWS.get(rel.get("cardinality") or "one_to_many", ("ERmany", "ERone"))
    style = (
        f"edgeStyle=none;rounded=0;html=1;fontSize=10;fontColor={THEME.edge_font_color};"
        f"strokeColor={THEME.edge_stroke};strokeWidth={THEME.edge_stroke_width};"
        f"startArrow={start_arrow};startFill=0;endArrow={end_arrow};endFill=0;"
        f"exitX={exit_x};exitY={frac_src:.4f};exitDx=0;exitDy=0;"
        f"entryX={entry_x};entryY={frac_tgt:.4f};entryDx=0;entryDy=0;"
    )
    d._emit_cell(
        eid,
        f'<mxCell id="{eid}" value="" style="{style}" edge="1" parent="1" '
        f'source="{src}" target="{tgt}"><mxGeometry relative="1" as="geometry"/></mxCell>',
        Z_EDGE,
    )


def erd_semantic_ids(spec: dict) -> tuple[list, list]:
    """(expected_ids, expected_edges) for check_semantic_preservation: every
    table id must survive, plus every declared FK relationship pair."""
    ids = [e["id"] for e in spec.get("entities", []) if e.get("id")]
    edges = [
        (r.get("from_entity"), r.get("to_entity"))
        for r in spec.get("relationships", [])
        if r.get("from_entity") and r.get("to_entity")
    ]
    return ids, edges


def _register() -> None:
    from . import registry

    registry.register(
        registry.RendererEntry(
            kind="erd",
            backend="native",
            tree_builder=build_erd_tree,
            style_preset_label="erd",
            semantic_ids_fn=erd_semantic_ids,
            lint_kind="erd",
        )
    )


_register()


__all__ = ["build_erd_tree", "erd_semantic_ids"]
