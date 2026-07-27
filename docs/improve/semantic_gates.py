"""
Semantic + geometric integrity gates for generated diagrams.

Drop in at: backend/src/domain/validation/semantic_gates.py

WHAT THIS ADDS that validate_drawio.py (1633 lines) does not check:
  I1  orphan leaf nodes            - a component with zero edges is not architecture
  I2  edge / component density     - below 1.0 the page is an inventory, not a design
  I3  weak or placeholder labels   - "(x2 flows)", "(all layers)", "data", "uses", ""
  I4  mixed icon families          - AWS stencils in a GCP or on-prem diagram
  I5  edges with waypoints but no exit/entry anchors - draw.io silently re-routes
  I6  text that re-wraps or overflows its box (needs text_metrics)
  I7  legend classes vs edge classes actually used

Design rule: I1-I5 are HARD (block export). I6 hard for overflow, warn for re-wrap.
Aesthetics (aspect ratio, page fill, crossings) stay as warnings - a slightly busy
but correct diagram is usable; a beautiful one with 29 floating components is not.

Runs standalone for triage:
    python semantic_gates.py path/to/*.drawio
"""
from __future__ import annotations

import html
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

try:
    from ...prettygraph.text_metrics import label_box, line_count, text_width
except Exception:                                                  # standalone / fallback
    try:
        from text_metrics import label_box, line_count, text_width
    except Exception:
        text_width = line_count = label_box = None

# --------------------------------------------------------------------------- lexicons

WEAK_LABEL = re.compile(
    r"^(data|call|calls|use|uses|used|flow|flows|sync|syncs|api|apis|request|response|"
    r"link|links|connect|connects|connection|send|sends|read|write|process|"
    r"integration|interface|n/?a|tbd|todo|misc|other|others|various|etc\.?)$", re.I)

PLACEHOLDER_LABEL = re.compile(
    r"\(\s*(?:all\s+layers|[x×]\s*\d+\s*flows?|\d+\s*flows?|multiple|various|etc\.?)\s*\)"
    r"|\ball\s+layers\b|\bmultiple\s+flows\b|\bgoverned\s+apis\b|\bsystems?\s+sync\b",
    re.I)

ICON_FAMILY = re.compile(
    r"mxgraph\.(aws4|aws3|azure2?|mscae|gcp2?|kubernetes|cisco\w*|veeam|ibm|sap)\.", re.I)

FAMILY_HOSTING = {"aws4": "aws", "aws3": "aws", "azure": "azure", "azure2": "azure",
                  "mscae": "azure", "gcp": "gcp", "gcp2": "gcp"}


@dataclass
class Finding:
    code: str
    severity: str          # "hard" | "warn"
    message: str
    ids: list = field(default_factory=list)

    def __str__(self):
        tag = "HARD" if self.severity == "hard" else "warn"
        extra = f"  [{', '.join(map(str, self.ids[:6]))}{'…' if len(self.ids) > 6 else ''}]" if self.ids else ""
        return f"{tag:4s} {self.code}: {self.message}{extra}"


# --------------------------------------------------------------------------- checks

def check_orphans(nodes, edges) -> list[Finding]:
    """I1 - every leaf component must participate in at least one relationship."""
    deg = {}
    for e in edges:
        for k in ("source", "target"):
            if e.get(k):
                deg[e[k]] = deg.get(e[k], 0) + 1
    leaves = [n for n in nodes if n.get("is_leaf") and not n.get("is_annotation")]
    orph = [n["id"] for n in leaves if deg.get(n["id"], 0) == 0]
    if not orph:
        return []
    return [Finding("I1-orphan", "hard",
                    f"{len(orph)}/{len(leaves)} components have no edge. A component with "
                    f"no relationship is not architecture - connect it, merge it, or "
                    f"delete it.", orph)]


def check_density(nodes, edges) -> list[Finding]:
    """I2 - relationship density. Healthy architecture diagrams sit at 1.3-2.0."""
    leaves = [n for n in nodes if n.get("is_leaf") and not n.get("is_annotation")]
    if len(leaves) < 6:
        return []
    ratio = len(edges) / len(leaves)
    if ratio >= 1.0:
        return []
    return [Finding("I2-density", "hard",
                    f"edge/component = {ratio:.2f} ({len(edges)} edges over {len(leaves)} "
                    f"components). Below 1.00 this page lists components instead of "
                    f"describing a system. Add the missing relationships or reduce the "
                    f"component count.")]


def check_labels(edges, primary_only=True) -> list[Finding]:
    """I3 - an edge label is a contract, not decoration."""
    out, empty, weak, ph = [], [], [], []
    pool = [e for e in edges if e.get("primary", True)] if primary_only else edges
    for e in pool:
        lab = (e.get("label") or "").strip()
        if not lab:
            empty.append(e["id"])
        elif PLACEHOLDER_LABEL.search(lab):
            ph.append(f"{e['id']}={lab!r}")
        elif WEAK_LABEL.match(lab):
            weak.append(f"{e['id']}={lab!r}")
    if ph:
        out.append(Finding("I3-placeholder", "hard",
                           f"{len(ph)} edge labels are auto-generated placeholders. These "
                           f"say nothing to a reviewer.", ph))
    if weak:
        out.append(Finding("I3-weak", "hard",
                           f"{len(weak)} edge labels are generic. A label must state the "
                           f"contract: protocol + auth (e.g. 'HTTPS · mTLS', "
                           f"'AMQP · at-least-once', 'TDS 1.4 encrypted').", weak))
    if empty and pool:
        sev = "hard" if len(empty) > len(pool) * 0.25 else "warn"
        out.append(Finding("I3-unlabelled", sev,
                           f"{len(empty)}/{len(pool)} primary edges are unlabelled "
                           f"({100 * len(empty) // len(pool)}%).", empty))
    return out


def check_icon_family(nodes, hosting=None) -> list[Finding]:
    """I4 - one icon family per page, and it must match the real hosting model."""
    fams = {}
    for n in nodes:
        m = ICON_FAMILY.search(n.get("style", "") or "")
        if m:
            fams.setdefault(m.group(1).lower(), []).append(n["id"])
    out = []
    if len(fams) > 1:
        out.append(Finding("I4-mixed-icons", "hard",
                           f"{len(fams)} icon families on one page: "
                           f"{ {k: len(v) for k, v in fams.items()} }. Pick the family that "
                           f"matches the real hosting model, or use neutral shapes."))
    if hosting:
        h = str(hosting).lower().replace("-", "").replace("_", "")
        onprem = h in {"onprem", "onpremises", "onpremise", "datacentre", "datacenter"}
        for fam, ids in fams.items():
            declared = FAMILY_HOSTING.get(fam)
            if onprem and declared:
                out.append(Finding("I4-hosting-mismatch", "hard",
                                   f"{len(ids)} {fam.upper()} cloud icons on a diagram "
                                   f"declared '{hosting}'. This contradiction destroys "
                                   f"credibility in a review board.", ids))
            elif declared and declared != h and h in {"aws", "azure", "gcp"}:
                out.append(Finding("I4-hosting-mismatch", "hard",
                                   f"{len(ids)} {fam.upper()} icons on a '{hosting}' "
                                   f"diagram.", ids))
    return out


def check_anchors(edges) -> list[Finding]:
    """I5 - a baked waypoint list without exit/entry anchors is a lie.

    draw.io recomputes the perimeter attachment point when exitX/entryX are absent,
    so the route the user opens is not the route the engine computed, scored and
    screenshotted. validate_drawio.py:1107 even defaults to 0.5, making the
    crossing metric agree with a route that will never be drawn.
    """
    loose = [e["id"] for e in edges
             if e.get("waypoints") and (e.get("source") or e.get("target"))
             and not re.search(r"exitX=", e.get("style", "") or "")]
    if not loose:
        return []
    return [Finding("I5-anchor", "hard",
                    f"{len(loose)} edges carry waypoints but no exitX/entryX. draw.io will "
                    f"re-route them and discard the computed layout. Always emit anchors "
                    f"together with waypoints (plus exitPerimeter=0;entryPerimeter=0).",
                    loose)]


def check_text_fit(nodes) -> list[Finding]:
    """I6 - authored text must fit the box the engine froze."""
    if text_width is None:
        return [Finding("I6-skipped", "warn", "text_metrics not importable; text-fit "
                                              "checking disabled.")]
    rewrap, overflow = [], []
    for n in nodes:
        if not n.get("is_leaf") or not n.get("lines"):
            continue
        w, h = n.get("w", 0), n.get("h", 0)
        if w < 40 or h < 16:
            continue
        pad_x, pad_y = n.get("pad_x", 14), n.get("pad_y", 14)
        avail = w - pad_x
        total = 0
        authored = 0
        for ln, size, bold in n["lines"]:
            if not ln:
                continue
            authored += 1
            total += line_count(ln, avail, size, bold)
        if authored and total > authored:
            rewrap.append(n["id"])
        need = sum(line_count(ln, avail, size, bold) * size * 1.2
                   for ln, size, bold in n["lines"] if ln)
        if need > h - pad_y:
            overflow.append(n["id"])
    out = []
    if overflow:
        out.append(Finding("I6-overflow", "hard",
                           f"{len(overflow)} cards: wrapped text is taller than the box - "
                           f"text will be clipped or spill over the border.", overflow))
    if rewrap:
        sev = "hard" if len(rewrap) > max(2, len(nodes) * 0.05) else "warn"
        out.append(Finding("I6-rewrap", sev,
                           f"{len(rewrap)} cards: draw.io will re-wrap text into more lines "
                           f"than the engine assumed. Root cause is usually a char-width "
                           f"estimate instead of real font metrics.", rewrap))
    return out


def check_legend(edges, legend_classes) -> list[Finding]:
    """I7 - the legend must be a function of the data, never hand-written."""
    used = {e.get("contract") or e.get("flow") for e in edges}
    used.discard(None)
    if not used:
        return []
    legend = set(legend_classes or [])
    missing = used - legend
    extra = legend - used
    out = []
    if missing:
        out.append(Finding("I7-legend-missing", "hard",
                           f"edge classes drawn but absent from the legend: "
                           f"{sorted(missing)}. Generate the legend from the set of classes "
                           f"actually used."))
    if extra:
        out.append(Finding("I7-legend-extra", "warn",
                           f"legend declares classes that are never drawn: {sorted(extra)}."))
    return out


def audit(nodes, edges, *, hosting=None, legend_classes=None,
          check_text=True) -> list[Finding]:
    """Run every gate. Returns findings sorted hard-first."""
    f: list[Finding] = []
    f += check_orphans(nodes, edges)
    f += check_density(nodes, edges)
    f += check_labels(edges)
    f += check_icon_family(nodes, hosting)
    f += check_anchors(edges)
    if check_text:
        f += check_text_fit(nodes)
    if legend_classes is not None:
        f += check_legend(edges, legend_classes)
    return sorted(f, key=lambda x: (x.severity != "hard", x.code))


def verdict(findings) -> str:
    return "REVISE" if any(x.severity == "hard" for x in findings) else "PASS"


# --------------------------------------------------------------------- drawio adapter

def _txt(v):
    if not v:
        return []
    v = re.sub(r"</?(div|p)[^>]*>", "<br>", v)
    return [html.unescape(re.sub(r"<[^>]+>", "", p)).strip()
            for p in re.split(r"<br\s*/?>", v)]


def _child_text(cells_by_parent, cid):
    """Text of a cell's children - needed when a card keeps its label in child
    cells (a common pattern: it lets the icon, title and detail lines be placed
    at exact offsets and still move with the card)."""
    out = []
    for ch in cells_by_parent.get(cid, []):
        out += [l for l in _txt(ch.get("value")) if l]
    return out


def parse_drawio(path):
    """Extract (nodes, edges) from a .drawio page in the shape audit() expects.

    Leaf detection: a labelled vertex that does not fully contain another labelled
    vertex. This is what separates real components from zone frames and groups.
    """
    pages = []
    for diagram in ET.parse(path).getroot().findall(".//diagram"):
        cells = list(diagram.iter("mxCell"))
        by_parent = {}
        for c in cells:
            by_parent.setdefault(c.get("parent"), []).append(c)
        geo = {}
        for c in cells:
            g = c.find("mxGeometry")
            if c.get("vertex") == "1" and g is not None and g.get("width"):
                geo[c.get("id")] = (float(g.get("x") or 0), float(g.get("y") or 0),
                                    float(g.get("width")), float(g.get("height")))
        cand = []
        for c in cells:
            st = c.get("style") or ""
            lines = [l for l in _txt(c.get("value")) if l] \
                or _child_text(by_parent, c.get("id"))
            if (c.get("vertex") != "1" or c.get("id") not in geo or not lines
                    or st.startswith("text;") or "shape=image" in st or "group" in st
                    or "fillColor=none" in st):
                continue
            x, y, w, h = geo[c.get("id")]
            if w < 70 or h < 28 or w > 900:
                continue
            cand.append(c)

        ann = re.compile(r"(^|_)(legend|note|footer|title|caption|banner|backbone|tab|"
                         r"kpi|panel|tier|band|zone|group|frame)(_|$)", re.I)

        def contains(a, b, t=2):
            return (a[0] - t <= b[0] and a[1] - t <= b[1]
                    and a[0] + a[2] + t >= b[0] + b[2] and a[1] + a[3] + t >= b[1] + b[3])

        nodes = []
        for c in cells:
            if c.get("vertex") != "1" or c.get("id") not in geo:
                continue
            x, y, w, h = geo[c.get("id")]
            st = c.get("style") or ""
            lines = [l for l in _txt(c.get("value")) if l] \
                or _child_text(by_parent, c.get("id"))
            is_cand = c in cand
            is_leaf = is_cand and not any(
                o is not c and contains(geo[c.get("id")], geo[o.get("id")]) for o in cand)
            m = re.search(r"fontSize=([\d.]+)", st)
            size = float(m.group(1)) if m else 12.0
            bold = "fontStyle=1" in st
            m2 = re.search(r"spacingLeft=(\d+)", st)
            pad_x = (int(m2.group(1)) + 14) if m2 else 14
            nodes.append(dict(
                id=c.get("id"), style=st, x=x, y=y, w=w, h=h,
                is_leaf=is_leaf, is_annotation=bool(st.startswith("text;")
                                                   or ann.search(c.get("id") or "")),
                pad_x=pad_x, pad_y=14,
                lines=[(l, size, bold and i == 0) for i, l in enumerate(lines)]))
        edges = []
        for c in cells:
            if c.get("edge") != "1":
                continue
            g = c.find("mxGeometry")
            wps = []
            if g is not None:
                wps = [(float(p.get("x")), float(p.get("y")))
                       for p in g.findall(".//mxPoint")
                       if p.get("as") is None and p.get("x")]
            lab = " ".join(x for x in _txt(c.get("value")) if x) \
                or " ".join(_child_text(by_parent, c.get("id")))
            edges.append(dict(id=c.get("id"), source=c.get("source"), target=c.get("target"),
                              style=c.get("style") or "", label=lab, waypoints=wps,
                              primary=True))
        pages.append((diagram.get("name") or "page", nodes, edges))
    return pages


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)
    worst = 0
    for path in args:
        for name, nodes, edges in parse_drawio(path):
            leaves = [n for n in nodes if n["is_leaf"]]
            print(f"\n=== {path.split('/')[-1]} :: {name}")
            print(f"    {len(leaves)} leaf components · {len(edges)} edges · "
                  f"ratio {len(edges) / max(1, len(leaves)):.2f}")
            f = audit(nodes, edges)
            for x in f:
                print("   ", x)
            v = verdict(f)
            print(f"    VERDICT: {v}")
            worst = max(worst, 1 if v == "REVISE" else 0)
    sys.exit(worst)
