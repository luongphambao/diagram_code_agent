"""A/B measurement harness for the diagram pipeline upgrade (docs/improve/
NANGCAPDIAGRAMAGENT.md + docs/improve/REVIEW-CODEBASE-FIT.md).

Replays the SAME corpus of already-known-good inputs through the render
pipeline before/after a code change and reports deltas — deterministic, no
LLM calls, no network. Two corpus sources, both already in the repo:

  * ``example/*.drawio``        — ingested via drawio_ingest.extract_inventory
                                    + inventory_to_render_spec (the same path
                                    upgrade_drawio() uses).
  * ``artifacts/**/render_spec.json`` (and backend/agent_space/workspaces/**)
                                    — spec already at the render_spec stage,
                                    fed straight into the native renderer.

Usage:
    uv run python -m scripts.ab_diagram_metrics --out baseline.json
    uv run python -m scripts.ab_diagram_metrics --out after.json
    uv run python -m scripts.ab_diagram_metrics --compare baseline.json after.json

Metrics are measured at TWO layers, matching the diagnosis in
REVIEW-CODEBASE-FIT.md: the render_spec (pre-bundle, what the LLM/blueprint
actually declared) and the rendered .drawio (post-bundle, what a viewer
actually sees). Re-wrap/overflow are measured against REAL font metrics
(prettygraph.text_metrics) regardless of what the engine itself uses
internally — that's what makes this catch the bug instead of agreeing with
it, and it's why this script works as a baseline even before the engine is
patched to use the same module.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]  # backend/
REPO = ROOT.parent
for p in (
    "src",
    "src/domain/diagram",
    "src/domain/deck",
    "src/domain/reporting",
    "src/domain/wbs",
    "src/domain/validation",
):
    sys.path.insert(0, str(ROOT / p))

EXAMPLE_DIR = REPO / "example"
ARTIFACTS_DIRS = [REPO / "artifacts", ROOT / "agent_space" / "workspaces"]

_ICON_FAMILY_RX = re.compile(r"shape=mxgraph\.(aws4|azure\w*|gcp\w*|kubernetes|veeam|cisco\w*)\.")
_WEAK_LABEL_RX = re.compile(
    r"^(data|calls?|uses?|flow[s]?|sync|api|request|response|link|connect(s|ion)?|n/?a|tbd|todo|misc|other|various)$",
    re.I,
)


# --------------------------------------------------------------------------- #
# corpus discovery + spec loading
# --------------------------------------------------------------------------- #
def _iter_cases(corpus: list[str]) -> list[tuple[str, str, dict]]:
    """Returns [(name, source_kind, spec)]. source_kind is 'drawio' or 'spec'."""
    cases: list[tuple[str, str, dict]] = []
    if "example" in corpus:
        from drawio_ingest import extract_inventory, inventory_to_render_spec

        for f in sorted(EXAMPLE_DIR.glob("*.drawio")):
            try:
                inv = extract_inventory(str(f))
                if not inv.get("nodes"):
                    continue
                spec = inventory_to_render_spec(inv, style_preset="refined")
            except Exception as exc:  # noqa: BLE001 — surface as a skipped case, not a crash
                print(f"  [skip] {f.name}: ingest failed: {exc}", file=sys.stderr)
                continue
            cases.append((f.stem, "drawio", spec))
    if "artifacts" in corpus:
        seen = set()
        for base in ARTIFACTS_DIRS:
            for f in sorted(base.glob("**/render_spec.json")):
                try:
                    spec = json.loads(f.read_text(encoding="utf-8"))
                except Exception as exc:  # noqa: BLE001
                    print(f"  [skip] {f}: {exc}", file=sys.stderr)
                    continue
                if not spec.get("nodes"):
                    continue
                name = f.parent.name
                if name in seen:
                    name = f"{f.parent.parent.name}-{name}"
                seen.add(name)
                cases.append((name, "spec", spec))
    return cases


# --------------------------------------------------------------------------- #
# spec-layer metrics (pre-bundle — what was actually declared)
# --------------------------------------------------------------------------- #
def _spec_metrics(spec: dict) -> dict:
    nodes = spec.get("nodes") or []
    edges = spec.get("edges") or []
    node_ids = {n.get("id") for n in nodes if n.get("id")}
    touched: set[str] = set()
    for e in edges:
        if e.get("from"):
            touched.add(e["from"])
        if e.get("to"):
            touched.add(e["to"])
    orphans = sorted(node_ids - touched)
    weak = [
        e
        for e in edges
        if not str(e.get("label") or "").strip() or _WEAK_LABEL_RX.match(str(e.get("label") or "").strip())
    ]
    return {
        "spec_nodes": len(node_ids),
        "spec_edges": len(edges),
        "spec_orphans": len(orphans),
        "spec_orphan_ids": orphans[:10],
        "spec_edge_per_node": round(len(edges) / len(node_ids), 3) if node_ids else None,
        "spec_weak_or_empty_labels": len(weak),
    }


# --------------------------------------------------------------------------- #
# rendered-drawio-layer metrics (post-bundle — what a viewer actually sees)
# --------------------------------------------------------------------------- #
def _card_text_metrics(xml: str) -> dict:
    """Re-wrap / overflow, measured with REAL font metrics regardless of
    whether the engine itself has been patched yet — this is the ground
    truth the plan's Patch 1 is meant to make the engine agree with."""
    from prettygraph.text_metrics import wrap as tm_wrap, block_height as tm_block_height
    from validate_drawio import _parse_cells, _is_decor, _is_refined_container  # type: ignore

    cells = _parse_cells(xml)
    has_children = {c["parent"] for c in cells if c["parent"] and c["id"] and not _is_decor(c["id"])}
    badge_ids = {c["id"][:-4] for c in cells if str(c.get("id") or "").endswith("__ic")}

    rewrapped = overflowed = checked = 0
    for c in cells:
        if c["edge"] == "1" or not c["geo"] or not c["id"] or _is_decor(c["id"]):
            continue
        if c["id"] in has_children or _is_refined_container(c["id"]):
            continue
        style = c["style"] or ""
        raw_value = c.get("value") or ""
        if "html=1" not in style or not raw_value:
            continue
        # mxCell `value` is an XML attribute, so the HTML tags rich_card()
        # embeds (<b>/<br>) arrive double-escaped (`&lt;b&gt;...`) — unescape
        # once to get back the markup mxGraph's HTML renderer would interpret.
        value = html.unescape(raw_value)
        m = re.search(r"fontSize=([\d.]+)", style)
        size = float(m.group(1)) if m else 10.5
        bold_title = bool(re.search(r"<b>(.*?)</b>", value, re.S))
        title_text = re.sub("<[^>]+>", "", (re.search(r"<b>(.*?)</b>", value, re.S) or [None, ""])[1])
        rest = re.sub(r"<b>.*?</b>", "", value, flags=re.S)
        body_lines = [re.sub("<[^>]+>", "", part).strip() for part in rest.split("<br>")]
        body_lines = [b for b in body_lines if b]
        declared_lines = 1 + len(body_lines) if title_text else len(body_lines)
        if declared_lines == 0:
            continue
        checked += 1
        pad_x = 24 + (52 if c["id"] in badge_ids else 0)
        pad_y = 20
        avail_w = max(20.0, c["geo"]["w"] - pad_x)
        full_text = "\n".join([title_text] + body_lines) if title_text else "\n".join(body_lines)
        real_lines = 0
        for i, part in enumerate([title_text] + body_lines if title_text else body_lines):
            if not part:
                continue
            real_lines += len(tm_wrap(part, avail_w, size, bold=(bold_title and i == 0)))
        if real_lines > declared_lines:
            rewrapped += 1
        block_h = tm_block_height(full_text, avail_w, size)
        if block_h > c["geo"]["h"] - pad_y:
            overflowed += 1
    return {
        "cards_checked": checked,
        "cards_rewrapped": rewrapped,
        "cards_overflowed": overflowed,
        "cards_rewrapped_pct": round(100 * rewrapped / checked, 1) if checked else None,
        "cards_overflowed_pct": round(100 * overflowed / checked, 1) if checked else None,
    }


def _drawio_metrics(xml: str, stats: dict, plan: dict | None) -> dict:
    from validate_drawio import audit_layout_metrics, production_scorecard, validate_xml

    families = sorted({m for m in _ICON_FAMILY_RX.findall(xml)})
    report = validate_xml(xml, stats=stats)
    metrics = audit_layout_metrics(xml, stats)
    arrow = metrics.get("arrow_clarity") or {}
    sc = production_scorecard(report, stats)
    suppressed = (plan or {}).get("suppressed_edges") or []
    out = {
        "icon_families": families,
        "icon_family_count": len(families),
        "content_aspect_ratio": metrics.get("ratio"),
        "page_fill": metrics.get("page_fill"),
        "visible_edges": arrow.get("visible_edge_count"),
        "bundled_edges": arrow.get("bundled_edge_count"),
        "suppressed_edges_in_plan": len(suppressed),
        "crossings_per_edge": arrow.get("crossings_per_edge"),
        "long_edge_ratio": arrow.get("long_edge_ratio"),
        "label_overlaps": arrow.get("edge_label_overlaps"),
        "production_score": sc.get("total"),
        "production_pass": sc.get("pass"),
        "error_count": report.get("error_count"),
        "warning_count": report.get("warning_count"),
    }
    out.update(_card_text_metrics(xml))
    return out


# --------------------------------------------------------------------------- #
# render one case through the real pipeline (PNG export stubbed: offline + fast)
# --------------------------------------------------------------------------- #
def _render_case(spec: dict) -> tuple[str, dict, dict | None]:
    from backends import set_current_workspace, reset_current_workspace
    import tools.rendering_tools as rt

    with tempfile.TemporaryDirectory(prefix="ab-diagram-") as tmp:
        ws = Path(tmp)
        token = set_current_workspace(ws)
        try:
            with patch.object(rt, "_render_drawio_png", return_value=False):
                stats = rt._render_native_from_spec(dict(spec), ws)
            xml = (ws / "out.drawio").read_text(encoding="utf-8")
            plan = None
            plan_path = ws / "layout_plan.json"
            if plan_path.exists():
                try:
                    plan = json.loads(plan_path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    plan = None
        finally:
            reset_current_workspace(token)
    return xml, stats, plan


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def run(corpus: list[str]) -> dict:
    cases = _iter_cases(corpus)
    if not cases:
        print("No corpus cases found — check --corpus and repo paths.", file=sys.stderr)
    results = {}
    for name, kind, spec in cases:
        print(f"  {name} ({kind}) ...", file=sys.stderr)
        entry = {"source": kind, **_spec_metrics(spec)}
        try:
            xml, stats, plan = _render_case(spec)
            entry.update(_drawio_metrics(xml, stats, plan))
            entry["render_ok"] = True
        except Exception as exc:  # noqa: BLE001 — record the failure, keep going
            entry["render_ok"] = False
            entry["render_error"] = f"{type(exc).__name__}: {exc}"
        results[name] = entry
    return {"cases": results, "summary": _summarize(results)}


def _summarize(results: dict) -> dict:
    def _avg(key: str) -> float | None:
        vals = [v[key] for v in results.values() if isinstance(v.get(key), (int, float))]
        return round(sum(vals) / len(vals), 3) if vals else None

    def _sum(key: str) -> int:
        return sum(int(v.get(key) or 0) for v in results.values())

    n = len(results)
    render_ok = sum(1 for v in results.values() if v.get("render_ok"))
    return {
        "n_cases": n,
        "render_ok": render_ok,
        "spec_orphans_total": _sum("spec_orphans"),
        "spec_edge_per_node_avg": _avg("spec_edge_per_node"),
        "cards_rewrapped_pct_avg": _avg("cards_rewrapped_pct"),
        "cards_overflowed_pct_avg": _avg("cards_overflowed_pct"),
        "icon_family_count_max": max((v.get("icon_family_count") or 0) for v in results.values())
        if results
        else 0,
        "production_score_avg": _avg("production_score"),
        "crossings_per_edge_avg": _avg("crossings_per_edge"),
        "page_fill_avg": _avg("page_fill"),
    }


def _fmt(v) -> str:
    return "-" if v is None else str(v)


def compare(before_path: str, after_path: str) -> None:
    before = json.loads(Path(before_path).read_text(encoding="utf-8"))
    after = json.loads(Path(after_path).read_text(encoding="utf-8"))
    print("## Summary\n")
    print("| metric | before | after | Δ |")
    print("|---|---:|---:|---:|")
    b_sum, a_sum = before.get("summary", {}), after.get("summary", {})
    for key in sorted(set(b_sum) | set(a_sum)):
        b, a = b_sum.get(key), a_sum.get(key)
        delta = ""
        if isinstance(b, (int, float)) and isinstance(a, (int, float)):
            delta = f"{a - b:+.3f}".rstrip("0").rstrip(".")
        print(f"| {key} | {_fmt(b)} | {_fmt(a)} | {delta} |")

    print("\n## Per-case deltas (only cases present in both)\n")
    print(
        "| case | rewrap% before→after | overflow% before→after | spec orphans before→after | prod score before→after |"
    )
    print("|---|---|---|---|---|")
    b_cases, a_cases = before.get("cases", {}), after.get("cases", {})
    for name in sorted(set(b_cases) & set(a_cases)):
        b, a = b_cases[name], a_cases[name]
        print(
            f"| {name} "
            f"| {_fmt(b.get('cards_rewrapped_pct'))}→{_fmt(a.get('cards_rewrapped_pct'))} "
            f"| {_fmt(b.get('cards_overflowed_pct'))}→{_fmt(a.get('cards_overflowed_pct'))} "
            f"| {_fmt(b.get('spec_orphans'))}→{_fmt(a.get('spec_orphans'))} "
            f"| {_fmt(b.get('production_score'))}→{_fmt(a.get('production_score'))} |"
        )
    missing = set(b_cases) ^ set(a_cases)
    if missing:
        print(f"\n(corpus mismatch — cases only on one side, not compared: {sorted(missing)})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default="example,artifacts", help="comma list: example,artifacts")
    ap.add_argument("--out", default="", help="write JSON metrics to this path")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"), help="compare two JSON reports")
    args = ap.parse_args()

    if args.compare:
        compare(*args.compare)
        return

    corpus = [c.strip() for c in args.corpus.split(",") if c.strip()]
    result = run(corpus)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    print(json.dumps(result["summary"], indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
