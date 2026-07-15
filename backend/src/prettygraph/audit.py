"""Post-render layout audit tools."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from runtime.subprocess_utils import run_graphviz

from .graph_builder import _est_text_w


def audit_layout(dot_path: str, png_path: str | None = None) -> str:
    """Objective post-render layout check — surfaced to the agent each render."""
    try:
        g = json.loads(run_graphviz(["dot", "-Tjson", dot_path],
                                    capture_output=True, text=True,
                                    check=True).stdout)
    except Exception:  # noqa: BLE001
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
             + (" — OK" if 0.55 <= aspect <= 2.1 else
                " — TOO WIDE for the slide panel, fold cross-cutting tiers into a 2nd row (≤5 columns)"
                if aspect > 2.1 else " — very tall, consider direction='LR'"),
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
    fill = len(occupied) / 9.0
    if len(node_pts) >= 12 and fill < 0.67:
        lines.append(
            f"  LOW FILL — only {len(occupied)}/9 canvas cells occupied "
            f"({fill:.0%}). The page reads airy. Grid-pack each multi-node region "
            "(g.grid_cluster / the engine now auto-packs ≥3-node regions), add the "
            "missing per-node detail, and keep connected regions adjacent so the "
            "layout fills instead of stranding boxes in blank bands.")
    if ((0, 0) in occupied or (1, 0) in occupied) and (
        (2, 1) in occupied or (2, 2) in occupied
    ) and (1, 1) not in occupied:
        lines.append("  L-SHAPE WARNING — nodes are packed along the bottom and "
                     "right edge with the center empty. Re-layout into a 3x2/4x2 "
                     "grid; do not use a long bottom flow then a vertical tower.")
    if len(node_pts) >= 6:
        bottom_frac = sum(1 for _, y in node_pts if (y - y0) / Hh < 0.30) / len(node_pts)
        right_frac = sum(1 for x, _ in node_pts if (x - x0) / W > 0.65) / len(node_pts)
        if bottom_frac > 0.50 and right_frac > 0.40:
            lines.append(
                f"  L-SHAPE WARNING (density) — "
                f"{bottom_frac:.0%} of nodes in bottom 30%, {right_frac:.0%} in right 35%. "
                "Rebuild as a balanced 3x2 or 4x2 grid."
            )
    edge_count = len(g.get("edges", []))
    if edge_count and dashed_edges > max(4, edge_count * 0.35):
        lines.append(f"  SIDE-CHANNEL FANOUT — {dashed_edges}/{edge_count} edges "
                     "are dashed. Collapse observability/security/control lines "
                     "to one cluster-level dashed edge per concern.")
    if n_clusters >= 7 and aspect > 1.9:
        lines.append(
            f"  CLUSTER STRIP — {n_clusters} clusters in a {aspect:.1f}:1 strip. "
            "Long crossing edges are inevitable at this width. REQUIRED FIX: "
            "stack the cross-cutting tiers (Security, Observability, CI/CD, "
            "Infrastructure) under their adjacent main-flow tier using invisible "
            "spine + same_rank so the layout folds to ≤5 primary columns. "
            "See the stacking recipe in the pro-style skill.")
    lines += _audit_text_fit(dot_path)
    return "\n".join(lines)


def _audit_text_fit(dot_path: str) -> list[str]:
    """Report cards whose text outgrew node_width (they were auto-widened)."""
    try:
        sidecar = Path(dot_path).with_name(
            Path(dot_path).name.replace(".dot", ".nodes.json"))
        side = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    st = side.get("style") or {}
    nw = st.get("node_width")
    if not nw:
        return []
    title_s, sub_s, icon_s = st.get("title", 13), st.get("sub", 11), st.get("icon", 36)
    over: list[str] = []
    for meta in side.get("nodes", {}).values():
        icon_w = (icon_s + 10) if meta.get("icon") else 0
        need = max(_est_text_w(meta.get("label") or "", title_s, bold=True),
                   _est_text_w(meta.get("sublabel") or "", sub_s)) + icon_w + 24
        if need > nw:
            fits = int((nw - icon_w - 24) / (0.62 * title_s))
            over.append(f'"{meta.get("label")}" needs ~{need:.0f}pt > '
                        f'node_width {nw}pt (<= {fits} chars fits)')
    if not over:
        return []
    return (["  TEXT OVERFLOW — these cards were auto-widened so text stays "
             "inside the box, breaking uniform card width. Shorten the label / "
             "move detail to the sublabel (use fit_labels), or raise node_width:"]
            + [f"    - {s}" for s in over[:6]])
