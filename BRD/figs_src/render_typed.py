"""Standalone renderer for typed diagrams (sequence / erd / state_machine),
dogfooding backend/src/prettygraph/native/* directly — no agent runtime, no
LLM, no sandbox. Used to produce BRD figures from hand-authored specs.

Run from anywhere with BACKEND_SRC on sys.path (see main() below).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_SRC = Path(__file__).resolve().parents[2] / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

OUT_DIR = Path(__file__).resolve().parent / "out"
OUT_DIR.mkdir(exist_ok=True)


def _render_drawio_png_viewer(drawio_path: Path, png_path: Path, scale: int = 2, timeout_s: int = 45) -> bool:
    """Pixel-accurate PNG export via the real diagrams.net web viewer engine
    (same as tools.rendering_tools._render_drawio_png_playwright) — renders
    umlActor/umlLifeline stencils correctly, unlike the offline SVG
    reprojection fallback. Diagram XML travels only in the URL fragment
    (client-side only, never uploaded)."""
    from tools.rendering_tools import _drawio_viewer_fragment
    from playwright.sync_api import sync_playwright

    xml = drawio_path.read_text(encoding="utf-8")
    url = "https://viewer.diagrams.net/?tags=%7B%7D&lightbox=1&edit=_blank#" + _drawio_viewer_fragment(xml)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        try:
            page = browser.new_page(device_scale_factor=scale)
            page.goto(url, wait_until="networkidle", timeout=timeout_s * 1000)
            page.wait_for_selector("svg", timeout=timeout_s * 1000)
            page.wait_for_timeout(400)
            box = page.evaluate(
                """() => {
                const svg = document.querySelector('svg');
                if (!svg) return null;
                const rect = svg.getBoundingClientRect();
                const target = svg.querySelector('g') || svg;
                const b = target.getBBox();
                const vb = svg.viewBox && svg.viewBox.baseVal;
                const sx = (vb && vb.width) ? rect.width / vb.width : 1;
                const sy = (vb && vb.height) ? rect.height / vb.height : 1;
                const vx = vb ? vb.x : 0, vy = vb ? vb.y : 0;
                return {x: rect.left + (b.x - vx) * sx, y: rect.top + (b.y - vy) * sy,
                        width: b.width * sx, height: b.height * sy};
            }"""
            )
            pad = 12
            if box and box["width"] > 0 and box["height"] > 0:
                page.screenshot(
                    path=str(png_path),
                    clip={
                        "x": max(0, box["x"] - pad),
                        "y": max(0, box["y"] - pad),
                        "width": box["width"] + pad * 2,
                        "height": box["height"] + pad * 2,
                    },
                )
            else:
                page.locator("svg").first.screenshot(path=str(png_path))
        finally:
            browser.close()
    return png_path.exists()


def _render_drawio_png_svg(drawio_path: Path, png_path: Path, scale: int = 2) -> bool:
    """Offline fallback: SVG reprojection (no network, lower fidelity for
    exotic UML stencils like umlActor)."""
    from prettygraph.native.svg_emit import to_svg
    from playwright.sync_api import sync_playwright
    import re

    xml = drawio_path.read_text(encoding="utf-8")
    svg = to_svg(xml)
    m = re.search(r'width="([\d.]+)" height="([\d.]+)"', svg)
    w, h = (float(m.group(1)), float(m.group(2))) if m else (1600.0, 1200.0)
    html_doc = f"<!doctype html><html><body style='margin:0'>{svg}</body></html>"
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        try:
            page = browser.new_page(
                viewport={"width": max(1, round(w)), "height": max(1, round(h))},
                device_scale_factor=scale,
            )
            page.set_content(html_doc)
            page.screenshot(path=str(png_path), full_page=True)
        finally:
            browser.close()
    return png_path.exists()


def _render_drawio_png(drawio_path: Path, png_path: Path, scale: int = 2) -> bool:
    if _render_drawio_png_viewer(drawio_path, png_path, scale):
        return True
    print(f"[{png_path.stem}] viewer.diagrams.net export failed, falling back to offline SVG", file=sys.stderr)
    return _render_drawio_png_svg(drawio_path, png_path, scale)


def render_typed_spec(kind: str, spec_dict: dict, out_name: str) -> Path:
    """kind: 'sequence' | 'erd' | 'state_machine'. spec_dict: raw dict matching
    the corresponding Pydantic schema. Writes <out_name>.drawio/.png/.csv under
    figs_src/out/ and returns the PNG path."""
    from prettygraph.native.topology import build_drawio_from_spec
    from prettygraph.native import registry as native_registry
    # Import side-effecting modules so they self-register into RENDERERS.
    import prettygraph.native.sequence  # noqa: F401
    import prettygraph.native.erd  # noqa: F401
    import prettygraph.native.state_machine  # noqa: F401

    if kind == "sequence":
        from tools.schemas.sequence import SequenceSpec
        from tools.analysis.sequence_tools import _build_sequence_render_spec

        validated = SequenceSpec(**spec_dict)
        render_spec = _build_sequence_render_spec(validated)
    elif kind == "erd":
        from tools.schemas.erd import ERDSpec
        from tools.analysis.erd_tools import _build_erd_render_spec

        validated = ERDSpec(**spec_dict)
        render_spec = _build_erd_render_spec(validated)
    elif kind == "state_machine":
        from tools.schemas.state_machine import StateMachineSpec
        from tools.analysis.state_machine_tools import (
            _build_state_machine_render_spec,
            transition_table_csv,
        )

        validated = StateMachineSpec(**spec_dict)
        render_spec = _build_state_machine_render_spec(validated)
    else:
        raise ValueError(f"unsupported kind {kind!r}")

    entry = native_registry.get(kind)
    if entry is None:
        raise RuntimeError(f"kind {kind!r} not registered in prettygraph.native.registry")

    name = render_spec.get("title") or spec_dict.get("title") or kind.title()
    xml, stats = build_drawio_from_spec(render_spec, name, flat=False, plan=None)

    drawio_path = OUT_DIR / f"{out_name}.drawio"
    png_path = OUT_DIR / f"{out_name}.png"
    drawio_path.write_text(xml, encoding="utf-8")

    if entry.lint_kind:
        from domain.validation.diagram_lint import lint

        report = lint(entry.lint_kind, render_spec)
        (OUT_DIR / f"{out_name}.lint.json").write_text(
            json.dumps(report.to_dict(), indent=2), encoding="utf-8"
        )
        if report.to_dict().get("errors"):
            print(f"[{out_name}] LINT ERRORS: {report.to_dict()['errors']}", file=sys.stderr)

    if kind == "state_machine":
        csv_text = transition_table_csv(render_spec)
        (OUT_DIR / f"{out_name}.transitions.csv").write_text(csv_text, encoding="utf-8")

    ok = _render_drawio_png(drawio_path, png_path)
    if not ok:
        raise RuntimeError(f"PNG export failed for {out_name}")
    print(f"[{out_name}] OK — {drawio_path.name}, {png_path.name} ({stats.get('semantic')})")
    return png_path


if __name__ == "__main__":
    # Smoke test: minimal 3-participant sequence, 3-table ERD, 4-state machine.
    render_typed_spec(
        "sequence",
        {
            "title": "Smoke test — sequence",
            "participants": [
                {"id": "u", "label": "User", "kind": "actor"},
                {"id": "fe", "label": "Frontend", "kind": "frontend"},
                {"id": "be", "label": "Backend", "kind": "service"},
            ],
            "messages": [
                {"order": 1, "from": "u", "to": "fe", "label": "Click submit", "kind": "sync"},
                {"order": 2, "from": "fe", "to": "be", "label": "POST /agui", "kind": "sync"},
                {"order": 3, "from": "be", "to": "fe", "label": "200 OK", "kind": "return"},
            ],
            "fragments": [],
            "activations": [{"participant": "be", "start_order": 2, "end_order": 3}],
        },
        "smoke_sequence",
    )
    render_typed_spec(
        "erd",
        {
            "title": "Smoke test — ERD",
            "entities": [
                {
                    "id": "conversations",
                    "name": "conversations",
                    "columns": [
                        {"name": "thread_id", "data_type": "varchar", "primary_key": True},
                        {"name": "name", "data_type": "varchar"},
                    ],
                },
                {
                    "id": "runs",
                    "name": "runs",
                    "columns": [
                        {"name": "run_id", "data_type": "uuid", "primary_key": True},
                        {
                            "name": "thread_id",
                            "data_type": "varchar",
                            "foreign_key": True,
                            "references": "conversations.thread_id",
                        },
                    ],
                },
            ],
            "relationships": [
                {
                    "from_entity": "runs",
                    "from_columns": ["thread_id"],
                    "to_entity": "conversations",
                    "to_columns": ["thread_id"],
                    "cardinality": "one_to_many",
                }
            ],
        },
        "smoke_erd",
    )
    render_typed_spec(
        "state_machine",
        {
            "title": "Smoke test — state machine",
            "states": [
                {"id": "idle", "label": "Idle", "kind": "initial"},
                {"id": "pending", "label": "Pending", "kind": "normal"},
                {"id": "approved", "label": "Approved", "kind": "final"},
                {"id": "rejected", "label": "Rejected", "kind": "normal"},
            ],
            "transitions": [
                {"from": "idle", "to": "pending", "event": "gate_raised"},
                {"from": "pending", "to": "approved", "event": "approve"},
                {"from": "pending", "to": "rejected", "event": "reject"},
                {"from": "rejected", "to": "pending", "event": "resubmit"},
            ],
        },
        "smoke_state_machine",
    )
    print("ALL SMOKE TESTS PASSED")
