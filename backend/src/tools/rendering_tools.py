"""Rendering tools: render_diagram (with built-in pre-flight audit),
export_drawio, finalize_diagram, declare_poster_grid, list_saved_diagrams,
visualize_code_structure — plus code-side helpers write_style_and_fit_plans /
_compute_style_plan / _compute_label_fits (style_plan.json + label_fits.json are
pre-computed when the blueprint is approved; audit_diagram_code / plan_style_sizes
/ fit_labels remain as ad-hoc tools but are no longer in DRAWER_TOOLS)."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Literal, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from pydantic import BaseModel, Field

from backends import OUTPUTS_DIR, current_workspace
from domain.reporting.reporting import record_artifact_inventory, record_report_step
from runtime.sandbox.guards import _audit_add, _audit_code
from runtime.sandbox.render_exec import run_render
from .constants import (
    _BLUEPRINT_FILE,
    _OUT_NAMES,
    RENDER_HARD_CAP,
    RENDER_SOFT_CAP,
    RENDER_TIMEOUT_S,
)
from .stage_markers import (
    _archive_session,
    _bump_render_count,
    _bump_tool_summary,
    _inspection_image_b64,
    _layout_audit,
    _render_count,
    _stage_helpers,
    reset_render_count,
    _reset_revision_count,
)


@tool
def audit_diagram_code(code: str) -> str:
    """Statically audit a diagram script for known `diagrams`/Graphviz pitfalls.

    NOTE: render_diagram now runs this audit automatically as a pre-flight gate
    (a REVISE verdict blocks the render without consuming render budget), so a
    separate call is normally unnecessary. Kept for ad-hoc use.
    """
    return json.dumps(_audit_code(code), indent=2)


@tool(parse_docstring=True)
def render_diagram(
    code: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> ToolMessage:
    """Render a `diagrams` (mingrammer) Python script and return the resulting image.

    A static pre-flight audit runs automatically first: any high/medium finding
    blocks the render (WITHOUT consuming render budget) and returns the findings
    to fix — no separate audit call is needed. On success the rendered PNG is
    returned so you can LOOK at it and refine. On failure the error output is
    returned so you can fix the code and retry. Rendering is budget-capped per
    round, so fix known defects rather than re-rendering to chase the same warning.

    When to use: after the blueprint is approved and icons are resolved, to draw
    and iteratively refine the diagram.

    Args:
        code: The COMPLETE Python script. It must render to `out.png` AND `out.dot`
            in the working directory, e.g. Diagram("...", filename="out",
            outformat=["png", "dot"], show=False, ...) — or for pretty style,
            Pretty(...).render("out").
    """
    if not _BLUEPRINT_FILE.exists():
        return ToolMessage(
            content="Get the architecture approved first: call propose_tech_stack, "
                    "then propose_blueprint, before rendering.",
            name="render_diagram",
            tool_call_id=tool_call_id,
            status="error",
        )
    audit_pre = _audit_code(code)
    if audit_pre["verdict"] == "REVISE":
        return ToolMessage(
            content=("PRE-FLIGHT AUDIT blocked this render (NO render budget "
                     "consumed). Fix every high/medium finding below, then call "
                     "render_diagram again with the corrected script:\n"
                     + json.dumps(audit_pre, indent=2)),
            name="render_diagram",
            tool_call_id=tool_call_id,
            status="error",
        )
    if _render_count() >= RENDER_HARD_CAP:
        next_step = (
            "Keep the existing out.png: call export_drawio(), then return your "
            "summary listing residual audit warnings."
            if (current_workspace() / "out.png").exists()
            else "No usable out.png remains. Stop rendering and return a short "
                 "failure summary with the last traceback."
        )
        return ToolMessage(
            content=f"RENDER BUDGET EXHAUSTED ({RENDER_HARD_CAP} renders this round). "
                    f"{next_step} Do NOT keep re-rendering to chase warnings.",
            name="render_diagram",
            tool_call_id=tool_call_id,
            status="error",
        )
    attempt = _bump_render_count()
    _stage_helpers()
    for out_name in _OUT_NAMES:
        p = current_workspace() / out_name
        if p.exists():
            p.unlink()
    (current_workspace() / "diagram.py").write_text(code, encoding="utf-8")

    try:
        proc = run_render(current_workspace(), timeout=RENDER_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return ToolMessage(
            content=f"Render #{attempt}/{RENDER_HARD_CAP} TIMED OUT after {RENDER_TIMEOUT_S}s. "
                    "Simplify the diagram or fix infinite work.",
            name="render_diagram",
            tool_call_id=tool_call_id,
            status="error",
        )

    png = current_workspace() / "out.png"
    if proc.returncode != 0 or not png.exists():
        err = (proc.stderr or proc.stdout or "").strip()
        return ToolMessage(
            content=f"Render #{attempt}/{RENDER_HARD_CAP} FAILED (exit {proc.returncode}). "
                    f"Fix the code and retry only if under budget.\n\n{err[-3000:]}",
            name="render_diagram",
            tool_call_id=tool_call_id,
            status="error",
        )

    audit = _layout_audit()
    text = (f"Rendered out.png successfully (render #{attempt} of "
            f"{RENDER_HARD_CAP} this round). Inspect it and refine if the "
            "layout is not clean.")
    if audit:
        text += "\n\n" + audit
        if attempt < RENDER_SOFT_CAP:
            text += ("\n\nAct on any audit WARNING before finalizing "
                     "(re-render after fixing). A clean diagram is balanced "
                     "(~1.3–2:1) with every label-bearing edge short.")
        else:
            text += (f"\n\nRender budget nearly spent ({attempt}/{RENDER_HARD_CAP}). "
                     "Re-render ONLY for a defect you know exactly how to fix "
                     "(e.g. a specific TEXT OVERFLOW label). Otherwise finalize "
                     "with this image and report residual warnings in your "
                     "summary — do not chase the same warning again.")
    record_report_step(
        current_workspace(),
        "render_diagram",
        summary=f"Rendered out.png successfully on attempt {attempt}.",
        data={
            "attempt": attempt,
            "audit": audit,
            "artifacts": record_artifact_inventory(current_workspace()),
        },
    )
    include_image = os.getenv("RENDER_INCLUDES_IMAGE", "1").lower() not in ("0", "false", "no")
    if include_image:
        b64, mime = _inspection_image_b64(png)
        return ToolMessage(
            content_blocks=[
                {"type": "text", "text": text},
                {"type": "image", "base64": b64, "mime_type": mime},
            ],
            name="render_diagram",
            tool_call_id=tool_call_id,
            status="success",
        )
    return ToolMessage(
        content=text + "\n\nImage saved to out.png — call export_drawio() when satisfied.",
        name="render_diagram",
        tool_call_id=tool_call_id,
        status="success",
    )


@tool
def export_drawio() -> str:
    """Convert the last rendered out.dot into an editable out.drawio (with embedded logos).

    Call this once the diagram looks good. Produces out.drawio next to out.png.
    """
    dot = current_workspace() / "out.dot"
    out = current_workspace() / "out.drawio"
    sidecar = current_workspace() / "out.nodes.json"
    slide = current_workspace() / "out.slide.json"
    if slide.exists() and out.exists():
        return f"Slide drawio already ready ({out.stat().st_size} bytes); not overwriting."
    if not dot.exists():
        return "No out.dot found — call render_diagram first."
    try:
        if sidecar.exists():
            from prettygraph import dot_to_drawio
            dot_to_drawio(str(dot), str(sidecar), str(out))
        else:
            from domain.diagram.gv_to_drawio import convert
            convert(str(dot), str(out))
    except Exception as exc:  # noqa: BLE001 — surface to the agent
        return f"export_drawio failed: {exc}"
    if not out.exists():
        return "export_drawio produced no file."
    record_report_step(
        current_workspace(),
        "export_drawio",
        summary=f"Created editable draw.io artifact ({out.stat().st_size} bytes).",
        data={"artifacts": record_artifact_inventory(current_workspace())},
    )
    # Structural + design lint — fast pre-check before the (slow) visual critic.
    lint = ""
    try:
        from domain.validation.validate_drawio import validate_file
        report = validate_file(str(out))
        lint = (f"\nLint: {report['error_count']} error(s), "
                f"{report['warning_count']} warning(s), "
                f"{report.get('advice_count', 0)} advice.")
        if report["errors"]:
            lint += f" Errors: {'; '.join(report['errors'][:5])}"
        elif report["warnings"]:
            lint += f" Warnings: {'; '.join(report['warnings'][:3])}"
        if report.get("advice"):
            lint += f"\nDesign advice: {'; '.join(report['advice'][:5])}"
    except Exception:  # noqa: BLE001
        pass

    # Archive final artifacts to a timestamped session folder for reuse.
    archive_note = ""
    try:
        dest = _archive_session()
        if dest:
            archive_note = f"\nArchived to: {dest}"
    except Exception:  # noqa: BLE001
        pass

    # Diagram quality gate — convert lint findings to SolutionFindings, persist lifecycle.
    gate_note = ""
    try:
        from .analysis.gates import _diagram_gate_note
        gate_note = _diagram_gate_note(block=False)
    except Exception:  # noqa: BLE001
        pass

    return f"Wrote out.drawio ({out.stat().st_size} bytes).{lint}{archive_note}{gate_note}"


def _find_drawio_cli() -> str | None:
    """Locate the draw.io desktop CLI (env DRAWIO_CLI, PATH, then common installs)."""
    import shutil
    env = os.environ.get("DRAWIO_CLI")
    if env and Path(env).exists():
        return env
    for name in ("drawio", "draw.io"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "draw.io" / "draw.io.exe",
        Path("C:/Program Files/draw.io/draw.io.exe"),
        Path("/usr/bin/drawio"), Path("/opt/drawio/drawio"),
        Path("/Applications/draw.io.app/Contents/MacOS/draw.io"),
    ]
    for p in candidates:
        try:
            if str(p) and p.exists():
                return str(p)
        except OSError:
            continue
    return None


def _drawio_viewer_fragment(xml: str) -> str:
    """Encode .drawio XML into a diagrams.net viewer URL `#R<payload>` fragment.

    Ported from drawio-ai-kit/vendor/encode_drawio_url.py. The viewer's loader
    runs decodeURIComponent on the inflated string, so the XML MUST be
    percent-encoded BEFORE deflating — a literal `%` or non-ASCII label
    otherwise throws "URI malformed" and the diagram never renders.
    """
    import base64
    import urllib.parse
    import zlib
    pre = urllib.parse.quote(xml, safe="!~*'()")
    c = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    compressed = c.compress(pre.encode("utf-8")) + c.flush()
    payload = base64.b64encode(compressed).decode("utf-8").replace("\n", "")
    return "R" + urllib.parse.quote(payload, safe="")


def _render_drawio_png_playwright(drawio_path: Path, png_path: Path,
                                  scale: int = 2, timeout_s: int = 45) -> bool:
    """Fallback PNG export via the diagrams.net web viewer + a headless browser.

    Uses the same Playwright/Chromium already installed for PDF report export
    (see Dockerfile: `playwright install chromium`) — needs no draw.io desktop
    app, no xvfb, no Electron. Requires outbound HTTPS to viewer.diagrams.net;
    the diagram XML travels only in the URL FRAGMENT (never sent over the
    network — fragments are client-side only), so nothing is uploaded.
    Returns False (never raises) on any failure so callers can degrade to
    validator-lint-only, same contract as the desktop-CLI path.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001 — playwright not installed
        return False
    try:
        xml = drawio_path.read_text(encoding="utf-8")
        url = ("https://viewer.diagrams.net/?tags=%7B%7D&lightbox=1&edit=_blank#"
               + _drawio_viewer_fragment(xml))
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            try:
                page = browser.new_page(device_scale_factor=scale)
                page.goto(url, wait_until="networkidle", timeout=timeout_s * 1000)
                page.wait_for_selector("svg", timeout=timeout_s * 1000)
                page.wait_for_timeout(400)  # let the graph finish laying out
                # The viewer's <svg> fills the whole (much larger) lightbox
                # viewport with the diagram anchored top-left — screenshotting
                # the element itself captures mostly blank canvas. Crop to the
                # rendered content's own tight bounding box instead.
                box = page.evaluate("""() => {
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
                }""")
                pad = 12
                if box and box["width"] > 0 and box["height"] > 0:
                    page.screenshot(path=str(png_path), clip={
                        "x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad),
                        "width": box["width"] + pad * 2, "height": box["height"] + pad * 2,
                    })
                else:  # getBBox failed (unexpected DOM) — full element as a last resort
                    page.locator("svg").first.screenshot(path=str(png_path))
            finally:
                browser.close()
    except Exception:  # noqa: BLE001 — degrade gracefully, never raise
        return False
    return png_path.exists()


def _render_drawio_png(drawio_path: Path, png_path: Path, scale: int = 2) -> bool:
    """Render a .drawio to PNG: draw.io desktop CLI first (fast, offline), else
    the Playwright/viewer.diagrams.net fallback (needs outbound HTTPS but no
    desktop app). False if neither is available/works."""
    import shutil
    exe = _find_drawio_cli()
    if exe:
        cmd = [exe, "--export", "--format", "png", "--scale", str(scale), "--border", "20",
               "--output", str(png_path), str(drawio_path), "--no-sandbox"]
        # draw.io desktop is an Electron app; on headless Linux (containers) it
        # needs an X server. Wrap in xvfb-run when available.
        if sys.platform.startswith("linux") and shutil.which("xvfb-run"):
            cmd = ["xvfb-run", "-a", *cmd]
        try:
            subprocess.run(cmd, timeout=120, capture_output=True)
        except (subprocess.SubprocessError, OSError):
            pass
        if png_path.exists():
            return True
    return _render_drawio_png_playwright(drawio_path, png_path, scale)


def _render_native_from_spec(spec: dict, workspace: Path) -> dict:
    """Build out.drawio (+ out.png + out.slide.json for slides) from a render_spec
    via the NATIVE engine. Returns fidelity/routing stats. Shared by the
    export_drawio_native tool and the deterministic pre-render in propose_blueprint.
    """
    from prettygraph.native.topology import build_drawio_from_spec
    out = workspace / "out.drawio"
    name = spec.get("slide_title") or spec.get("diagram_title") or "Architecture"
    # Slide presentations (the default) get the hero-band + legend chrome by wrapping
    # the native body. The embedded body must be FLAT (parent="1", absolute coords)
    # for the slide compositor's _transform_drawio_body.
    presentation = str(spec.get("presentation_style") or "slide").lower()
    xml, stats = build_drawio_from_spec(spec, name, flat=(presentation == "slide"))
    # Semantic count preservation (V2 §15.5) — measured on the native body BEFORE
    # slide composition, which re-prefixes ids. Surfaces silently-dropped nodes/edges.
    try:
        from domain.validation.validate_drawio import check_semantic_preservation
        src_nodes = [n.get("id") for n in spec.get("nodes", [])]
        src_edges = [(e.get("from"), e.get("to")) for e in spec.get("edges", [])]
        _, stats["semantic"] = check_semantic_preservation(src_nodes, src_edges, xml)
    except Exception:  # noqa: BLE001 — best-effort, never block a render
        pass
    if presentation == "slide":
        from prettygraph.slide import compose_native_slide
        compose_native_slide(
            xml, str(out), title=spec.get("slide_title") or name,
            kicker=spec.get("slide_kicker") or None,
            brand=spec.get("brand") or None,
            diagram_title=spec.get("diagram_title") or None,
            legend=spec.get("legend") or [], include_hero=True)
        (workspace / "out.slide.json").write_text(
            json.dumps({"drawio": "out.drawio", "png": "out.png",
                        "engine": "native", "style": "slide"}), encoding="utf-8")
    else:
        out.write_text(xml, encoding="utf-8")
    _render_drawio_png(out, workspace / "out.png")
    try:  # persist stats so the diagram gate / finalize can score without the spec
        (workspace / "out.native_stats.json").write_text(
            json.dumps(stats), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    _reset_drawio_edit_rounds()  # fresh export -> fresh edit_drawio budget
    return stats


@tool
def export_drawio_native() -> str:
    """Build an editable out.drawio straight from render_spec.json with the NATIVE
    layout engine — deterministic geometry, ground-truth stencils (AWS + on-prem +
    OSS/AI-ML packs), an obstacle-avoiding edge router, and full slide chrome. No
    Graphviz, no mingrammer code.

    The DEFAULT for any architecture diagram with a blueprint (all providers, slide
    or plain). Call after propose_blueprint instead of render_diagram + export_drawio.
    Falls back with a clear message if render_spec.json is missing.
    """
    from .constants import _RENDER_SPEC_FILE
    out = current_workspace() / "out.drawio"
    if not _RENDER_SPEC_FILE.exists():
        return "No render_spec.json — call propose_blueprint first (native export needs a blueprint)."
    try:
        spec = json.loads(_RENDER_SPEC_FILE.read_text(encoding="utf-8"))
        stats = _render_native_from_spec(spec, current_workspace())
    except Exception as exc:  # noqa: BLE001 — surface to the agent
        return f"export_drawio_native failed: {exc}"
    if not out.exists():
        return "export_drawio_native produced no file."
    png = current_workspace() / "out.png"
    png_ok = png.exists()
    png_note = (f" out.png rendered ({png.stat().st_size} bytes) — inspect it."
                if png_ok else
                " NOTE: draw.io CLI not found, so no out.png was produced — rely on "
                "the validator lint below (set DRAWIO_CLI or install draw.io desktop to preview).")
    record_report_step(
        current_workspace(),
        "export_drawio_native",
        summary=(f"Native draw.io: {stats['native_icons']} stencils, "
                 f"{stats['native_groups']} group frames ({out.stat().st_size} bytes)."),
        data={"artifacts": record_artifact_inventory(current_workspace()), "native_stats": stats},
    )
    lint = ""
    try:
        from domain.validation.validate_drawio import validate_file
        report = validate_file(str(out))
        lint = (f"\nLint: {report['error_count']} error(s), "
                f"{report['warning_count']} warning(s), "
                f"{report.get('polish_count', 0)} polish gate finding(s), "
                f"{report.get('advice_count', 0)} advice.")
        if report["errors"]:
            lint += f" Errors: {'; '.join(report['errors'][:5])}"
        if report.get("polish"):
            lint += ("\nPOLISH GATE (must fix via edit_drawio): "
                     + "; ".join(report["polish"][:5]))
        if report.get("advice"):
            lint += f"\nDesign advice: {'; '.join(report['advice'][:5])}"
        from domain.validation.validate_drawio import production_scorecard
        sc = production_scorecard(report, stats)
        verdict = ("PASS" if sc["pass"]
                   else "BELOW GATE (need >=85, semantic & relationship = 100%)")
        lint += (f"\nProduction scorecard: {sc['total']}/100 ({verdict}) — "
                 + ", ".join(f"{k}={v}" for k, v in sc["breakdown"].items()))
    except Exception:  # noqa: BLE001
        pass
    vendor_icons = stats["native_icons"] + stats.get("image_icons", 0)
    sem = stats.get("semantic") or {}
    sem_note = ""
    if sem.get("missing_nodes") or sem.get("missing_edges"):
        mn, me = sem.get("missing_nodes", []), sem.get("missing_edges", [])
        sem_note = (f"\nSEMANTIC LOSS: {len(mn)} node(s) and {len(me)} edge(s) from "
                    f"render_spec did NOT render "
                    f"(nodes: {', '.join(map(str, mn[:5]))}) — check their cluster/ids.")
    return (
        f"Wrote out.drawio ({out.stat().st_size} bytes) via native engine.{png_note} "
        f"Fidelity: {vendor_icons}/{stats['nodes']} vendor icons "
        f"({stats['native_icons']} AWS stencils + {stats.get('image_icons', 0)} "
        f"image tiles), {stats['native_groups']} native group frames. "
        f"Routing: {stats['edge_cross']} edge-through-node, "
        f"{stats['edge_overlaps']} parallel overlaps.{sem_note}{lint}\n"
        "If Lint reports gate findings, fix them IN PLACE: read_drawio -> one "
        "batched edit_drawio call (do NOT re-export)."
    )


# --------------------------------------------------------------------------- #
# Targeted .drawio XML editing (read_drawio / edit_drawio)
#
# The hybrid quality loop: the native builder produces a production-styled
# out.drawio deterministically; when the validator/critic still flags issues the
# drawer FIXES THE XML IN PLACE with small ops instead of regenerating —
# mirroring the drawio-ai-kit "author XML → validate → render → loop" workflow.
# --------------------------------------------------------------------------- #

_DRAWIO_EDIT_CAP = 2          # edit_drawio batches per exported diagram
_EDIT_ROUNDS_FILE = ".drawio_edit_rounds"

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _reset_drawio_edit_rounds() -> None:
    p = current_workspace() / _EDIT_ROUNDS_FILE
    if p.exists():
        try:
            p.unlink()
        except OSError:
            pass


def _bump_drawio_edit_rounds() -> int:
    p = current_workspace() / _EDIT_ROUNDS_FILE
    n = 0
    if p.exists():
        try:
            n = int(p.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            n = 0
    n += 1
    p.write_text(str(n), encoding="utf-8")
    return n


def _drawio_edit_rounds() -> int:
    p = current_workspace() / _EDIT_ROUNDS_FILE
    try:
        return int(p.read_text(encoding="utf-8").strip() or 0) if p.exists() else 0
    except (OSError, ValueError):
        return 0


def _style_get(style: str, key: str) -> str | None:
    for part in (style or "").split(";"):
        if "=" in part and part.split("=", 1)[0] == key:
            return part.split("=", 1)[1]
    return None


def _style_set(style: str, key: str, value) -> str:
    """Set/replace ``key=value`` in a draw.io style string; None/"" removes it."""
    parts = [p for p in (style or "").split(";") if p]
    out, done = [], False
    for p in parts:
        if "=" in p and p.split("=", 1)[0] == key:
            done = True
            if value is None or value == "":
                continue
            out.append(f"{key}={value}")
        else:
            out.append(p)
    if not done and value not in (None, ""):
        out.append(f"{key}={value}")
    return ";".join(out) + ";"


def _load_drawio_model(path: Path):
    """Parse out.drawio and return (tree, model_root) where model_root is the
    <root> element holding the mxCells. Raises ValueError on compressed files."""
    import xml.etree.ElementTree as ET
    tree = ET.parse(str(path))
    root = tree.getroot()
    model = root.find(".//mxGraphModel")
    if model is None:
        raise ValueError("no mxGraphModel found — is the diagram compressed? "
                         "Re-export with export_drawio_native.")
    cell_root = model.find("root")
    if cell_root is None:
        raise ValueError("mxGraphModel has no <root>.")
    return tree, cell_root


def _clean_label(value: str, limit: int = 48) -> str:
    txt = _HTML_TAG_RE.sub(" ", value or "").replace("&nbsp;", " ")
    txt = re.sub(r"\s+", " ", txt).strip()
    return (txt[: limit - 1] + "…") if len(txt) > limit else txt


def _shape_summary(style: str) -> str:
    m = re.search(r"resIcon=mxgraph\.aws4\.([a-zA-Z0-9_]+)", style or "")
    if m:
        return f"stencil:{m.group(1)}"
    if "image=data:" in (style or ""):
        return "image-icon"
    m = re.search(r"grIcon=mxgraph\.aws4\.([a-zA-Z0-9_]+)", style or "")
    if m:
        return f"group:{m.group(1)}"
    if (style or "").startswith(("text;", "line;")):
        return (style or "").split(";", 1)[0]
    return "box"


@tool
def read_drawio() -> str:
    """Compact inventory of out.drawio for targeted edits — one line per cell.

    Vertices: `V <id> p=<parent> [x,y w*h] "<label>" fill/stroke/font + shape`.
    Edges: `E <id> <source> -> <target> "<label>" stroke/dashed/pins/waypoints`.
    Coordinates are RELATIVE to the parent cell (absolute when parent is "1").
    Ends with the current validator findings so you know exactly what to fix
    with edit_drawio. Use this instead of reading the raw XML (much cheaper).
    """
    out = current_workspace() / "out.drawio"
    if not out.exists():
        return "No out.drawio — export the diagram first (export_drawio_native)."
    try:
        _, cell_root = _load_drawio_model(out)
    except Exception as exc:  # noqa: BLE001 — surface to the agent
        return f"read_drawio failed: {exc}"
    lines: list[str] = []
    for cell in cell_root.iter("mxCell"):
        cid = cell.get("id") or ""
        if cid in ("0", "1"):
            continue
        style = cell.get("style") or ""
        geo = cell.find("mxGeometry")
        if cell.get("edge") == "1":
            pins = "".join(
                f" {k}={_style_get(style, k)}" for k in
                ("exitX", "exitY", "entryX", "entryY") if _style_get(style, k))
            npts = len(geo.findall(".//mxPoint")) if geo is not None else 0
            bits = [f'E {cid} {cell.get("source")} -> {cell.get("target")}']
            lbl = _clean_label(cell.get("value") or "")
            if lbl:
                bits.append(f'"{lbl}"')
            sc = _style_get(style, "strokeColor")
            if sc:
                bits.append(sc)
            if _style_get(style, "dashed") == "1":
                bits.append("dashed")
            if pins:
                bits.append(pins.strip())
            if npts:
                bits.append(f"wp:{npts}")
            lines.append(" | ".join(bits))
        else:
            g = ""
            if geo is not None:
                g = (f'[{geo.get("x", "0")},{geo.get("y", "0")} '
                     f'{geo.get("width", "?")}x{geo.get("height", "?")}]')
            bits = [f'V {cid} p={cell.get("parent")}', g,
                    f'"{_clean_label(cell.get("value") or "")}"',
                    _shape_summary(style)]
            for k in ("fillColor", "strokeColor", "fontSize"):
                v = _style_get(style, k)
                if v:
                    bits.append(f"{k[0:4]}={v}")
            lines.append(" | ".join(b for b in bits if b))
    if len(lines) > 250:
        lines = lines[:250] + [f"... ({len(lines) - 250} more cells truncated)"]
    lint = ""
    try:
        from domain.validation.validate_drawio import validate_file
        report = validate_file(str(out))
        lint = ("\n\nValidator: "
                f"{report['error_count']} error(s), {report['warning_count']} "
                f"warning(s), {report.get('polish_count', 0)} polish gate, "
                f"{report.get('advice_count', 0)} advice.")
        for kind in ("errors", "warnings", "polish", "advice"):
            for msg in (report.get(kind) or [])[:6]:
                lint += f"\n- [{kind.rstrip('s')}] {msg}"
    except Exception:  # noqa: BLE001
        pass
    rounds_left = max(0, _DRAWIO_EDIT_CAP - _drawio_edit_rounds())
    return ("\n".join(lines) + lint
            + f"\n\nedit_drawio batches left: {rounds_left}. Batch ALL fixes into one call.")


class DrawioOp(BaseModel):
    """One targeted edit operation on out.drawio."""
    op: Literal["set_style", "move", "resize", "set_label",
                "pin_edge", "delete", "add_edge"] = Field(
        description="Operation kind.")
    id: str = Field(description="Target cell id (for add_edge: the NEW edge id).")
    key: Optional[str] = Field(None, description="set_style: style key, e.g. fillColor.")
    value: Optional[str] = Field(
        None, description="set_style: value (empty removes the key). "
                          "set_label: the new label text.")
    x: Optional[float] = Field(None, description="move: new x (relative to parent).")
    y: Optional[float] = Field(None, description="move: new y (relative to parent).")
    dx: Optional[float] = Field(None, description="move: x delta (alternative to x).")
    dy: Optional[float] = Field(None, description="move: y delta (alternative to y).")
    w: Optional[float] = Field(None, description="resize: new width.")
    h: Optional[float] = Field(None, description="resize: new height.")
    exitX: Optional[float] = Field(None, description="pin_edge: source-side X pin (0..1).")
    exitY: Optional[float] = Field(None, description="pin_edge: source-side Y pin (0..1).")
    entryX: Optional[float] = Field(None, description="pin_edge: target-side X pin (0..1).")
    entryY: Optional[float] = Field(None, description="pin_edge: target-side Y pin (0..1).")
    source: Optional[str] = Field(None, description="add_edge: source cell id.")
    target: Optional[str] = Field(None, description="add_edge: target cell id.")
    label: Optional[str] = Field(None, description="add_edge: edge label.")
    dashed: Optional[bool] = Field(None, description="add_edge: dashed line.")
    color: Optional[str] = Field(None, description="add_edge: stroke color hex.")


@tool(parse_docstring=True)
def edit_drawio(
    ops: list[DrawioOp],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> ToolMessage:
    """Apply targeted edits to out.drawio in place, then auto re-validate and re-render out.png.

    FIX the exported diagram instead of regenerating it: batch every fix into ONE
    call (max 2 batches per export). Ops: set_style {id,key,value}, move {id,x,y
    or dx,dy}, resize {id,w,h}, set_label {id,value}, pin_edge {id,exitX,exitY,
    entryX,entryY} (clears baked waypoints), delete {id} (also drops its edges),
    add_edge {id,source,target,label,color,dashed}. Use read_drawio first to see
    cell ids, geometry and current validator findings.

    Args:
        ops: The list of edit operations to apply, in order.
    """
    out = current_workspace() / "out.drawio"
    if not out.exists():
        return ToolMessage(content="No out.drawio to edit — export the diagram first.",
                           name="edit_drawio", tool_call_id=tool_call_id, status="error")
    if _drawio_edit_rounds() >= _DRAWIO_EDIT_CAP:
        return ToolMessage(
            content=f"EDIT BUDGET EXHAUSTED ({_DRAWIO_EDIT_CAP} edit batches). Keep the "
                    "current out.drawio and report residual findings in your summary.",
            name="edit_drawio", tool_call_id=tool_call_id, status="error")
    import xml.etree.ElementTree as ET
    try:
        tree, cell_root = _load_drawio_model(out)
    except Exception as exc:  # noqa: BLE001
        return ToolMessage(content=f"edit_drawio failed to parse: {exc}",
                           name="edit_drawio", tool_call_id=tool_call_id, status="error")
    cells = {c.get("id"): c for c in cell_root.iter("mxCell") if c.get("id")}
    applied: list[str] = []
    failed: list[str] = []

    def _geo(cell):
        g = cell.find("mxGeometry")
        if g is None:
            g = ET.SubElement(cell, "mxGeometry", {"as": "geometry"})
        return g

    for op in ops:
        cell = cells.get(op.id)
        if op.op != "add_edge" and cell is None:
            failed.append(f"{op.op} {op.id}: unknown id")
            continue
        try:
            if op.op == "set_style":
                if not op.key:
                    failed.append(f"set_style {op.id}: missing key")
                    continue
                cell.set("style", _style_set(cell.get("style") or "", op.key, op.value))
                applied.append(f"set_style {op.id} {op.key}={op.value}")
            elif op.op == "move":
                g = _geo(cell)
                nx = op.x if op.x is not None else float(g.get("x") or 0) + (op.dx or 0)
                ny = op.y if op.y is not None else float(g.get("y") or 0) + (op.dy or 0)
                g.set("x", f"{nx:.0f}")
                g.set("y", f"{ny:.0f}")
                applied.append(f"move {op.id} -> {nx:.0f},{ny:.0f}")
            elif op.op == "resize":
                g = _geo(cell)
                if op.w is not None:
                    g.set("width", f"{op.w:.0f}")
                if op.h is not None:
                    g.set("height", f"{op.h:.0f}")
                applied.append(f"resize {op.id}")
            elif op.op == "set_label":
                cell.set("value", op.value or "")
                applied.append(f"set_label {op.id}")
            elif op.op == "pin_edge":
                style = cell.get("style") or ""
                for k, v in (("exitX", op.exitX), ("exitY", op.exitY),
                             ("entryX", op.entryX), ("entryY", op.entryY)):
                    if v is not None:
                        style = _style_set(style, k, v)
                        style = _style_set(style, k.replace("X", "Dx").replace("Y", "Dy"), 0)
                cell.set("style", style)
                g = cell.find("mxGeometry")
                if g is not None:  # clear baked waypoints so the pins take effect
                    for arr in list(g.findall("Array")):
                        if arr.get("as") == "points":
                            g.remove(arr)
                applied.append(f"pin_edge {op.id}")
            elif op.op == "delete":
                # Seed with the node + its decorative sub-cells (shadow/accent are
                # parented to the frame, not the card, so cascade-by-parent misses them).
                doomed = {op.id, f"{op.id}__sh", f"{op.id}__ac"}
                for c in list(cell_root.iter("mxCell")):
                    if c.get("parent") in doomed or c.get("source") in doomed \
                            or c.get("target") in doomed:
                        doomed.add(c.get("id"))
                doomed &= {c.get("id") for c in cell_root.iter("mxCell")}
                for c in list(cell_root):
                    if c.get("id") in doomed:
                        cell_root.remove(c)
                cells = {c.get("id"): c for c in cell_root.iter("mxCell") if c.get("id")}
                deleted_ids |= doomed
                applied.append(f"delete {op.id} (+{len(doomed) - 1} dependents)")
            elif op.op == "add_edge":
                if not (op.source in cells and op.target in cells):
                    failed.append(f"add_edge {op.id}: unknown source/target")
                    continue
                if op.id in cells:
                    failed.append(f"add_edge {op.id}: id already exists")
                    continue
                color = op.color or "light-dark(#2D6A9F,#5B9BD5)"
                style = ("edgeStyle=orthogonalEdgeStyle;html=1;rounded=0;jettySize=auto;"
                         f"orthogonalLoop=1;fontSize=10;strokeColor={color};strokeWidth=2;"
                         "labelBackgroundColor=light-dark(#FFFFFF,#0B0F14);"
                         + ("dashed=1;" if op.dashed else ""))
                e = ET.SubElement(cell_root, "mxCell", {
                    "id": op.id, "style": style, "edge": "1", "parent": "1",
                    "source": op.source, "target": op.target})
                if op.label:
                    e.set("value", op.label)
                ET.SubElement(e, "mxGeometry", {"relative": "1", "as": "geometry"})
                cells[op.id] = e
                applied.append(f"add_edge {op.id} {op.source}->{op.target}")
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{op.op} {op.id}: {exc}")

    if not applied:
        return ToolMessage(
            content="No op applied.\n" + "\n".join(f"- {f}" for f in failed),
            name="edit_drawio", tool_call_id=tool_call_id, status="error")

    xml_text = ET.tostring(tree.getroot(), encoding="unicode")
    out.write_text(xml_text, encoding="utf-8")
    rounds = _bump_drawio_edit_rounds()

    lint = ""
    try:
        from domain.validation.validate_drawio import validate_file
        report = validate_file(str(out))
        lint = (f"\nLint: {report['error_count']} error(s), "
                f"{report['warning_count']} warning(s), "
                f"{report.get('polish_count', 0)} polish gate finding(s), "
                f"{report.get('advice_count', 0)} advice.")
        if report["errors"]:
            lint += f" Errors: {'; '.join(report['errors'][:5])}"
        if report.get("polish"):
            lint += f"\nPolish gate: {'; '.join(report['polish'][:5])}"
        if report.get("advice"):
            lint += f"\nDesign advice: {'; '.join(report['advice'][:5])}"
    except Exception:  # noqa: BLE001
        pass
    png = current_workspace() / "out.png"
    png_ok = _render_drawio_png(out, png)
    record_report_step(
        current_workspace(), "edit_drawio",
        summary=f"Applied {len(applied)} drawio edit(s), batch {rounds}/{_DRAWIO_EDIT_CAP}.",
        data={"applied": applied, "failed": failed},
    )
    text = (f"Applied {len(applied)} op(s) (batch {rounds}/{_DRAWIO_EDIT_CAP})."
            + ("\nFailed: " + "; ".join(failed) if failed else "") + lint
            + ("" if png_ok else "\nNOTE: draw.io CLI unavailable — out.png NOT "
                                 "re-rendered; rely on the Lint line."))
    include_image = os.getenv("RENDER_INCLUDES_IMAGE", "1").lower() not in ("0", "false", "no")
    if png_ok and include_image:
        b64, mime = _inspection_image_b64(png)
        return ToolMessage(
            content_blocks=[{"type": "text", "text": text},
                            {"type": "image", "base64": b64, "mime_type": mime}],
            name="edit_drawio", tool_call_id=tool_call_id, status="success")
    return ToolMessage(content=text, name="edit_drawio",
                       tool_call_id=tool_call_id, status="success")


@tool
def list_saved_diagrams() -> str:
    """List all previously saved diagram sessions from the outputs archive.

    Returns a summary of every session folder under the outputs directory,
    including the title, save date, and available files (PNG, drawio, etc.).
    Use this to find diagrams from past sessions for reuse or reference.
    """
    if not OUTPUTS_DIR.exists():
        return "No saved sessions found (outputs directory does not exist yet)."

    sessions = sorted(OUTPUTS_DIR.iterdir(), key=lambda p: p.name, reverse=True)
    sessions = [s for s in sessions if s.is_dir()]
    if not sessions:
        return "No saved sessions found."

    lines: list[str] = [f"Found {len(sessions)} saved session(s):\n"]
    for session in sessions:
        meta_file = session / "meta.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                title = meta.get("title", session.name)
                saved_at = meta.get("saved_at", "")
                files = meta.get("files", [])
                lines.append(f"  [{saved_at}] {title}")
                lines.append(f"    Folder: {session}")
                lines.append(f"    Files: {', '.join(files)}")
            except Exception:  # noqa: BLE001
                lines.append(f"  {session.name} (meta unreadable)")
        else:
            artifacts = [f.name for f in session.iterdir() if f.is_file()]
            lines.append(f"  {session.name}")
            lines.append(f"    Files: {', '.join(artifacts)}")
        lines.append("")

    return "\n".join(lines)


def _compute_style_plan(
    node_count: int,
    longest_label_chars: int = 22,
    longest_sublabel_chars: int = 26,
    output: str = "slide",
) -> dict:
    """Deterministic icon/text sizing for a prettygraph render.

    Pure arithmetic over the render spec — computed CODE-SIDE when
    propose_blueprint writes render_spec.json (write_style_and_fit_plans), so the
    drawer just reads style_plan.json instead of spending a model call on it.
    """
    if node_count <= 8:
        density, node_h, title = "sparse", 66, 17
    elif node_count <= 14:
        density, node_h, title = "medium", 60, 16
    elif node_count <= 22:
        density, node_h, title = "dense", 54, 14
    elif node_count <= 28:
        density, node_h, title = "detailed", 50, 13
    elif output == "poster":
        density, node_h, title = "poster", 46, 12
    else:
        density, node_h, title = "packed", 50, 13
    icon = max(32, min(48, round(node_h * 0.72)))
    sub = max(10, title - 2)
    edge = max(10, title - 2)
    cluster = title + 2

    # Fit the longest text row: lr margins (~32pt) + icon + gap + text width.
    # Helvetica ~0.60em/char bold title, ~0.52em/char sublabel.
    text_w = max(0.60 * title * longest_label_chars,
                 0.52 * sub * longest_sublabel_chars)
    raw_w = 32 + icon + 10 + text_w
    w_cap = 260 if output == "poster" else 380
    w_min = 200 if output == "poster" else 240
    node_w = min(w_cap, max(w_min, math.ceil(raw_w / 10) * 10))

    notes = [
        "Pass pretty_kwargs verbatim into Pretty(...); sizes apply to the PNG "
        "and the exported .drawio identically.",
    ]
    if raw_w > w_cap:
        fit = int((w_cap - 42 - icon) / (0.60 * title))
        notes.append(
            f"Longest label needs ~{raw_w:.0f}pt but cards cap at {w_cap}pt — shorten "
            f"titles to <={fit} chars or move detail into the sublabel."
        )
    if node_count > 18 and output == "slide" and node_count <= 26:
        notes.append(
            f"{node_count} nodes on a standard slide reads cramped — "
            "set blueprint density='detailed' (up to ~28 nodes, sublabel mandatory) "
            "with direction='LR' and flow_layout=True; or collapse replicas to stay under 18."
        )
    if node_count > 28 and output != "poster":
        notes.append(
            f"{node_count} nodes is above the comfortable detailed range (~20-28). "
            "The engine will scale the diagram to fit one 16:9 page — complex "
            "architectures may use more nodes as long as they remain readable after "
            "scaling. Alternatively switch to density='poster' for a wall-grid layout."
        )
    grid_cols = 0
    if output == "slide":
        # Detailed / standard slide: flow-driven layout (the DEFAULT house style).
        # Use direction='LR', flow_layout=True. Only pack large clusters (≥4 nodes)
        # as grids. The drawer should infer grid_cols from the cluster node count:
        # 4-6 nodes → cols=2, 7+ nodes → cols=3.
        grid_cols = 2 if node_count <= 16 else 3
        notes.append(
            "Detailed slide mode (house default — flow-driven): use direction='LR', "
            "flow_layout=True on Pretty(). "
            "Draw REAL cross-cluster edges for the primary flow — these are what pull "
            "the layout and make zone connections visible (mandatory). "
            f"Only call g.grid_cluster(region_id, cols={grid_cols}) for clusters that "
            "have ≥4 child nodes; small clusters size naturally. "
            "Set Pretty(..., flow_layout=True) explicitly (it is the default) so the "
            "engine keeps cross-cluster edges at constraint=true. "
            "Sublabel MANDATORY for every compute/data/network node. "
            "Number every top-level cluster (number=1, 2, ...). "
            "The engine scales the diagram to fit one 16:9 page — do not cut nodes "
            "to force a certain size."
        )
    elif output == "poster":
        # Each region 'plane' is packed as a multi-column logo grid via
        # g.grid_cluster(region_id, cols=grid_cols). 2-3 cols reads densest.
        grid_cols = 2 if node_count <= 24 else 3
        notes.append(
            "Poster mode (wall-grid, use when explicitly requested): group nodes into "
            "4-8 numbered region 'planes' (e.g. Client, Network & Security, "
            "AI/Compute Engine, Data & Storage, Observability & DevOps, Enterprise "
            "Systems). Set Pretty(..., flow_layout=False). "
            f"Pack EACH plane as a logo grid: after declaring its boxes call "
            f"g.grid_cluster(region_id, cols={grid_cols}). "
            "Pick direction by plane count: 5+ planes → direction='LR' (planes "
            "stack into a tall PORTRAIT poster); ≤4 planes → direction='TB'. "
            "Do NOT call g.poster_grid (its single-column ranks fight in-plane grids). "
            "Draw only a few cross-plane edges for the primary flow; they auto-relax "
            "so the grid drives layout. "
            "Every compute/data/network box MUST have a real logo icon + a tech "
            "sublabel. Nested sub-clusters inside a plane (model families, storage "
            "tiers) are encouraged."
        )

    sizes = {
        "node_width": node_w, "node_height": node_h, "icon_size": icon,
        "title_size": title, "sublabel_size": sub, "edge_label_size": edge,
        "cluster_label_size": cluster,
    }
    plan = {
        "node_count": node_count,
        "density": density,
        "output": output,
        "sizes": sizes,
        "grid_cols": grid_cols,
        "pretty_kwargs": ", ".join(f"{k}={v}" for k, v in sizes.items()),
        "notes": notes,
    }
    current_workspace().mkdir(parents=True, exist_ok=True)
    (current_workspace() / "style_plan.json").write_text(
        json.dumps(plan, indent=2), encoding="utf-8"
    )
    return plan


@tool(parse_docstring=True)
def plan_style_sizes(
    node_count: int,
    longest_label_chars: int = 22,
    longest_sublabel_chars: int = 26,
    output: Literal["slide", "diagram", "poster"] = "slide",
) -> str:
    """Decide icon/text sizes for a prettygraph render.

    NOTE: style_plan.json is now pre-computed code-side when the blueprint is
    approved — normally just read that file. Kept for ad-hoc re-planning.

    Args:
        node_count: number of VISIBLE boxes planned (after collapsing replicas).
        longest_label_chars: character count of the longest node title.
        longest_sublabel_chars: character count of the longest sublabel.
        output: "slide" (pro slide canvas), "diagram" (plain render), or "poster".
    """
    return json.dumps(
        _compute_style_plan(node_count, longest_label_chars,
                            longest_sublabel_chars, output),
        indent=2,
    )


class NodeText(BaseModel):
    """One node's visible text, to be checked against the planned card size."""
    label: str = Field(description="node title text")
    sublabel: str = Field("", description="node sublabel text (may be empty)")


# Deterministic, meaning-preserving shortenings tried in order. Vendor prefixes
# are stripped LAST (the icon already carries the brand).
_WORD_ABBREVS = [
    ("PostgreSQL", "Postgres"), ("Kubernetes", "K8s"), ("Database", "DB"),
    ("Application", "App"), ("Configuration", "Config"),
    ("Authentication", "Auth"), ("Authorization", "Authz"),
    ("Management", "Mgmt"), ("Infrastructure", "Infra"),
    ("Repository", "Repo"), ("Environment", "Env"),
]
_VENDOR_PREFIXES = ("Amazon ", "AWS ", "Microsoft ", "Google Cloud ",
                    "Google ", "Azure ", "Alibaba Cloud ", "Oracle ")


def _shorten(text: str, fits) -> tuple[str, str, list[str]]:
    """Shrink `text` until `fits(text)`; returns (text, moved_detail, steps)."""
    steps: list[str] = []
    moved = ""
    if not fits(text):
        m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", text)
        if m and m.group(1):
            text, moved = m.group(1), m.group(2)
            steps.append("moved parenthetical to sublabel")
    for full, short in _WORD_ABBREVS:
        if fits(text):
            break
        if full in text:
            text = text.replace(full, short)
            steps.append(f"{full} -> {short}")
    if not fits(text) and (" / " in text or " + " in text):
        text = text.replace(" / ", "/").replace(" + ", "+")
        steps.append("tightened separators")
    if not fits(text):
        for prefix in _VENDOR_PREFIXES:
            if text.startswith(prefix) and len(text) > len(prefix):
                text = text[len(prefix):]
                steps.append(f"dropped vendor prefix '{prefix.strip()}' (icon shows the brand)")
                break
    return text, moved, steps


def _compute_label_fits(
    nodes: list[dict],
    edge_labels: Optional[list[str]] = None,
    node_width: int = 0,
    icon_size: int = 0,
    title_size: int = 0,
    sublabel_size: int = 0,
) -> dict:
    """Check node/edge text against the planned card size; suggest shortenings.

    Pure text math — computed CODE-SIDE alongside style_plan.json (see
    write_style_and_fit_plans); the drawer reads label_fits.json. *nodes* is a
    list of {"label": ..., "sublabel": ...} dicts.
    """
    plan_sizes: dict = {}
    plan_file = current_workspace() / "style_plan.json"
    if plan_file.exists():
        try:
            plan_sizes = json.loads(plan_file.read_text(encoding="utf-8")).get("sizes", {})
        except Exception:  # noqa: BLE001
            plan_sizes = {}
    node_width = node_width or plan_sizes.get("node_width", 270)
    icon_size = icon_size or plan_sizes.get("icon_size", 36)
    title_size = title_size or plan_sizes.get("title_size", 13)
    sublabel_size = sublabel_size or plan_sizes.get("sublabel_size", 11)

    # Same fit model as the renderer: text cell = node_width - icon column - padding.
    budget = node_width - (icon_size + 10) - 24
    max_title = int(budget / (0.62 * title_size))
    max_sub = int(budget / (0.54 * sublabel_size))

    results = []
    for item in nodes:
        label = str(item.get("label") or "")
        sublabel = str(item.get("sublabel") or "")
        title_fits = len(label) <= max_title
        sub_fits = len(sublabel) <= max_sub
        entry: dict = {"label": label, "fits": title_fits and sub_fits}
        if not title_fits:
            new_label, moved, steps = _shorten(label,
                                               lambda t: len(t) <= max_title)
            if steps:
                sub = sublabel or ""
                if moved:
                    sub = f"{moved} · {sub}".strip(" ·") if sub else moved
                entry["suggestion"] = {"label": new_label, "sublabel": sub,
                                       "steps": steps}
            if len(new_label) > max_title:
                entry["still_too_long"] = True
                entry["hint"] = (f"rename manually to <= {max_title} chars "
                                 "(or raise node_width and re-run plan_style_sizes)")
        if not sub_fits:
            new_sub, _, steps = _shorten(sublabel,
                                         lambda t: len(t) <= max_sub)
            entry.setdefault("suggestion", {})["sublabel"] = new_sub
            entry["sublabel_still_too_long"] = len(new_sub) > max_sub
        results.append(entry)

    edge_results = []
    for lbl in edge_labels or []:
        words = lbl.split()
        ok = len(words) <= 4 and len(lbl) <= 28
        item = {"label": lbl, "fits": ok}
        if not ok:
            item["suggestion"] = " ".join(words[:4])
        edge_results.append(item)

    return {
        "card": {"node_width": node_width, "icon_size": icon_size,
                 "title_size": title_size, "sublabel_size": sublabel_size},
        "max_title_chars": max_title,
        "max_sublabel_chars": max_sub,
        "nodes": results,
        "edges": edge_results,
        "overflowing": sum(1 for r in results if not r["fits"]),
    }


@tool(parse_docstring=True)
def fit_labels(
    nodes: list[NodeText],
    edge_labels: Optional[list[str]] = None,
    node_width: int = 0,
    icon_size: int = 0,
    title_size: int = 0,
    sublabel_size: int = 0,
) -> str:
    """Check node/edge text against the planned card size and shorten what overflows.

    NOTE: label_fits.json is now pre-computed code-side when the blueprint is
    approved — normally just read that file. Kept for ad-hoc re-checks.

    Args:
        nodes: The planned node texts to check (each a NodeText with title/sublabel).
        edge_labels: Optional list of edge label strings to check for over-length.
        node_width: Card width override; defaults to the last `plan_style_sizes` result.
        icon_size: Icon size override; defaults to the last `plan_style_sizes` result.
        title_size: Title font size override; defaults to the last `plan_style_sizes` result.
        sublabel_size: Sublabel font size override; defaults to the last `plan_style_sizes` result.
    """
    out = _compute_label_fits(
        [{"label": n.label, "sublabel": n.sublabel} for n in nodes],
        edge_labels, node_width, icon_size, title_size, sublabel_size,
    )
    return json.dumps(out, indent=2, ensure_ascii=False)


def write_style_and_fit_plans(render_spec: dict) -> None:
    """Compute style_plan.json + label_fits.json code-side from a render spec.

    Called by propose_blueprint right after it writes render_spec.json: both
    outputs are pure deterministic functions of the spec (node count, label
    lengths, edge labels), so making the drawer request them via tool calls
    wasted 2 model calls per round AND created a mimo stringify surface
    (fit_labels(edge_labels='[...]') — real failing trace).
    """
    nodes = render_spec.get("nodes") or []
    node_count = len(nodes)
    labels = [str(n.get("label") or "") for n in nodes]
    sublabels = [str(n.get("tech") or "") for n in nodes]
    output = "poster" if render_spec.get("density") == "poster" else (
        render_spec.get("presentation_style") or "slide")
    plan = _compute_style_plan(
        node_count=node_count,
        longest_label_chars=max([len(s) for s in labels] or [22]),
        longest_sublabel_chars=max([len(s) for s in sublabels] or [26]),
        output=output if output in ("slide", "diagram", "poster") else "slide",
    )
    edge_labels = [str(e.get("label")) for e in (render_spec.get("edges") or [])
                   if e.get("label")]
    fits = _compute_label_fits(
        [{"label": lb, "sublabel": sb} for lb, sb in zip(labels, sublabels)],
        edge_labels,
        node_width=plan["sizes"]["node_width"],
        icon_size=plan["sizes"]["icon_size"],
        title_size=plan["sizes"]["title_size"],
        sublabel_size=plan["sizes"]["sublabel_size"],
    )
    (current_workspace() / "label_fits.json").write_text(
        json.dumps(fits, indent=2, ensure_ascii=False), encoding="utf-8"
    )


@tool(parse_docstring=True)
def visualize_code_structure(project_path: str, mode: str = "imports",
                             language: str = "python", group: bool = True) -> str:
    """Extract and visualize a codebase's module-import graph or class-inheritance hierarchy.

    Returns a JSON graph describing the code structure. After calling this, use the
    returned graph to generate a prettygraph diagram: pass nodes/edges/groups to
    g.cluster()/g.box()/g.link() calls.

    When to use: when a user asks to visualize their codebase, understand
    dependencies, or map class hierarchies.

    Args:
        project_path: Absolute path to the project/package directory.
        mode: "imports" (module-level dependencies) or "classes" (class inheritance).
        language: Currently only "python" is supported.
        group: Group nodes by sub-package into nested clusters (recommended).
    """
    if language != "python":
        return json.dumps({"error": f"language={language!r} not yet supported. Only 'python' available."})
    if not os.path.isdir(project_path):
        return json.dumps({"error": f"project_path {project_path!r} is not a directory."})
    try:
        if mode == "imports":
            from codevis import build_import_graph
            graph = build_import_graph(project_path, group=group)
        elif mode == "classes":
            from codevis import build_class_graph
            graph = build_class_graph(project_path, group=group)
        else:
            return json.dumps({"error": f"mode={mode!r} not recognized. Use 'imports' or 'classes'."})
        return json.dumps(graph, indent=2)
    except Exception as exc:  # noqa: BLE001
        return f"visualize_code_structure error: {exc}"


@tool
def finalize_diagram() -> str:
    """Submit the rendered diagram for the user's final review and approval.

    PAUSES for human review. Call this only AFTER render_diagram succeeded and
    export_drawio produced out.drawio.
    """
    if not (current_workspace() / "out.png").exists():
        return "No rendered diagram yet — call render_diagram (and export_drawio) first."
    record_report_step(
        current_workspace(),
        "finalize_diagram",
        summary="Diagram finalized and approved by the user.",
        data={"artifacts": record_artifact_inventory(current_workspace())},
    )
    return "Diagram finalized and approved by the user."


class GridSection(BaseModel):
    """One region 'plane' (cluster) in a poster-mode layout."""
    id: str = Field(description="snake_case id matching the g.cluster() id")
    label: str = Field(description="section label, e.g. '① Client / Access Layer'")
    anchor_node_id: str = Field(description="id of one node inside this section (first box)")
    cols: int = Field(2, description="columns to pack this plane's boxes into (2-3 reads densest)")


@tool(parse_docstring=True)
def declare_poster_grid(
    row1: list[GridSection],
    row2: list[GridSection],
    row3: list[GridSection] | None = None,
) -> str:
    """Declare and validate the region 'planes' for a poster-mode diagram.

    With direction='TB' the planes render SIDE BY SIDE across the width (like the
    reference poster). Returns a ready-to-paste skeleton of g.grid_cluster(...)
    calls that pack each plane into a dense multi-column logo grid. Rules enforced:
    row1 must have 3-7 sections, row2 must have 2-6, row3 (optional) 0-5, and each
    section must have a distinct anchor_node_id.

    When to use: BEFORE writing prettygraph code when density='poster' (the default).

    Args:
        row1: Region planes for the top row (3-7 GridSection entries).
        row2: Region planes for the second row (2-6 GridSection entries).
        row3: Optional region planes for a third row (0-5 GridSection entries).
    """
    row3 = row3 or []
    errors: list[str] = []
    if not (3 <= len(row1) <= 7):
        errors.append(f"row1 has {len(row1)} sections; expected 3-7.")
    if not (2 <= len(row2) <= 6):
        errors.append(f"row2 has {len(row2)} sections; expected 2-6.")
    if row3 and not (1 <= len(row3) <= 5):
        errors.append(f"row3 has {len(row3)} sections; expected 1-5 when provided.")
    all_sections = row1 + row2 + row3
    all_anchors = [s.anchor_node_id for s in all_sections]
    if len(all_anchors) != len(set(all_anchors)):
        seen: set[str] = set()
        dups = [a for a in all_anchors if a in seen or seen.add(a)]  # type: ignore[func-returns-value]
        errors.append(f"Duplicate anchor_node_ids: {dups}. Each section needs a unique anchor.")
    if errors:
        return json.dumps({"status": "INVALID", "errors": errors}, indent=2)

    n1, n2, n3 = len(row1), len(row2), len(row3)

    # One g.grid_cluster(...) per plane packs its boxes into a dense COLS-wide grid.
    grid_lines = [
        f"g.grid_cluster({s.id!r}, cols={max(1, s.cols)})  # {s.label}"
        for s in all_sections
    ]
    call = "\n".join(grid_lines)

    def _sec(s: GridSection) -> dict:
        return {"id": s.id, "label": s.label, "anchor": s.anchor_node_id,
                "cols": max(1, s.cols)}

    sections_info: dict = {
        "row1": [_sec(s) for s in row1],
        "row2": [_sec(s) for s in row2],
    }
    col_info: dict = {"row1": n1, "row2": n2}
    if row3:
        sections_info["row3"] = [_sec(s) for s in row3]
        col_info["row3"] = n3

    current_workspace().mkdir(parents=True, exist_ok=True)
    (current_workspace() / "poster_grid.json").write_text(json.dumps(sections_info, indent=2), encoding="utf-8")

    return json.dumps({
        "status": "OK",
        "planes": col_info,
        "grid_cluster_calls": call,
        "instruction": (
            "1) Create Pretty(..., direction=<'LR' for 5+ planes (tall portrait "
            "poster, closest to the reference) / 'TB' for ≤4 planes>, theme='pro'). "
            "2) Declare every plane with g.cluster(id, label, number=1,2,...) and add "
            "its boxes with g.box(..., parent=id, icon=<REAL logo>, sublabel=<tech>). "
            "3) AFTER all boxes/links, paste the grid_cluster_calls below — one per "
            "plane — to pack each into a dense logo grid. "
            "4) Add only a few cross-plane g.link(...) for the primary flow; they "
            "auto-relax so the grids drive the layout. "
            "Do NOT call g.poster_grid — it fights the in-plane grids. "
            "Do NOT add manual invisible spine / same_rank lines."
        ),
    }, indent=2)
