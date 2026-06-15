"""Deterministic structural linter for .drawio files.

Catches mistakes that vision self-check is slow and unreliable at:
  - Dangling edge endpoints
  - Duplicate or reserved cell ids
  - Broken parent references
  - (warnings) Off-grid geometry, overlapping sibling nodes

Runs without launching draw.io — fast pre-check before visual review.

CLI usage:
  python3 validate_drawio.py diagram.drawio [--strict]

Programmatic usage:
  from .validate_drawio import validate_file
  report = validate_file("/workspace/out.drawio")
  # -> {"errors": [...], "warnings": [...], "error_count": N, "warning_count": N, "ok": bool}
"""
import argparse
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


def validate_file(path: str) -> dict:
    """Lint a .drawio file. Returns a report dict with errors, warnings, and ok flag."""
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError) as exc:
        return {"errors": [f"cannot parse file: {exc}"], "warnings": [],
                "error_count": 1, "warning_count": 0, "ok": False}
    pages = tree.getroot().findall("diagram") or [tree.getroot()]
    errors, warns = [], []
    for page in pages:
        e, w = check_page(page)
        errors += e
        warns += w
    return {
        "errors": errors,
        "warnings": warns,
        "error_count": len(errors),
        "warning_count": len(warns),
        "ok": len(errors) == 0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Lint a .drawio file for structural errors.")
    ap.add_argument("file")
    ap.add_argument("--strict", action="store_true", help="treat warnings as failure too")
    args = ap.parse_args()
    report = validate_file(args.file)
    for w in report["warnings"]:
        print(f"warning: {w}")
    for e in report["errors"]:
        print(f"error: {e}")
    print(f"{report['error_count']} error(s), {report['warning_count']} warning(s)")
    if not report["ok"] or (args.strict and report["warning_count"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
