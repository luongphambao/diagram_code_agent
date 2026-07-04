"""Rendering tools: render_diagram, export_drawio, audit_diagram_code,
finalize_diagram, declare_poster_grid, list_saved_diagrams, plan_style_sizes,
fit_labels, visualize_code_structure."""

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
from reporting import record_artifact_inventory, record_report_step
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


def _audit_add(findings: list[dict], severity: str, rule: str, detail: str, suggestion: str) -> None:
    findings.append({
        "severity": severity,
        "rule": rule,
        "detail": detail,
        "suggestion": suggestion,
    })


def _audit_code(code: str) -> dict:
    """Static audit of a diagram script for known `diagrams`/Graphviz pitfalls.

    Pure function (no execution, no file writes). Runs automatically inside
    `render_diagram` as a pre-flight gate, so the model no longer needs a
    separate audit tool call carrying the full script a second time.
    """
    findings: list[dict] = []
    raw_diagram = "Diagram(" in code
    pretty = "Pretty(" in code or "render_slide(" in code

    if raw_diagram:
        if "filename=\"out\"" not in code and "filename='out'" not in code and "filename=\"/workspace/out\"" not in code and "filename='/workspace/out'" not in code:
            _audit_add(
                findings, "high", "output_filename",
                "Raw Diagram(...) code does not visibly set filename=\"out\".",
                "Use Diagram(..., filename=\"out\", outformat=[\"png\", \"dot\"], show=False).",
            )
        if "outformat" not in code:
            _audit_add(
                findings, "high", "output_format",
                "Raw Diagram(...) code does not set outformat.",
                "Set outformat=[\"png\", \"dot\"] so PNG and DOT are produced for draw.io export.",
            )
        if "show=False" not in code:
            _audit_add(
                findings, "medium", "show_false",
                "Raw Diagram(...) code does not visibly set show=False.",
                "Use show=False to avoid opening a viewer during automated rendering.",
            )

    if pretty and not re.search(r"\.render\(\s*[\"'](?:/workspace/)?out[\"']", code) and "render_slide(" not in code:
        _audit_add(
            findings, "high", "pretty_output",
            "Pretty code does not visibly render to out.",
            "End diagram-only scripts with g.render(\"out\") or slide scripts with render_slide(g, \"out\", ...).",
        )

    if re.search(r"graph_attr\s*=.*fontsize", code, re.DOTALL) and "edge_attr" not in code and "node_attr" not in code:
        _audit_add(
            findings, "medium", "font_defaults",
            "fontsize appears only in graph_attr; that does not reliably size all node/edge labels.",
            "Use node_attr for node label defaults, edge_attr for edge label defaults, or Edge(fontsize=...) for an explicit edge.",
        )

    if "xlabel=" in code:
        _audit_add(
            findings, "medium", "floating_xlabel",
            "Edge(xlabel=...) can float in open space and detach visually from the arrow.",
            "Prefer short Edge(label=...), taillabel/headlabel for endpoint labels, or move/stack clusters so the edge is short.",
        )

    if re.search(r"\b(pos|x|y)\s*=", code):
        _audit_add(
            findings, "medium", "manual_positioning",
            "Manual pos/x/y-style positioning is present; Graphviz dot usually ignores fixed positions.",
            "Control layout through direction, declaration order, same_rank, invisible spine edges, minlen, and simpler clusters.",
        )

    if re.search(r"Cluster\([^)]*graph_attr\s*=[^)]*orientation", code, re.DOTALL) or "orientation" in code:
        _audit_add(
            findings, "low", "cluster_orientation",
            "Cluster orientation hints are present; cluster-local ordering is often not dependable in diagrams/Graphviz.",
            "Use main graph direction, declaration order, same_rank/invisible edges, or collapse repeated nodes.",
        )

    for match in re.finditer(r"range\(([^)]*)\)", code):
        nums = [int(n) for n in re.findall(r"\d+", match.group(1))]
        if nums:
            start = nums[0] if len(nums) > 1 else 0
            stop = nums[1] if len(nums) > 1 else nums[0]
            if abs(stop - start) >= 6:
                _audit_add(
                    findings, "medium", "large_replicas",
                    f"Loop {match.group(0)} may create many similar nodes, which often produces unstable cluster ordering.",
                    "Collapse replicas into one node labeled with the count, or show at most two representatives plus an ellipsis.",
                )
                break

    edge_labels = re.findall(r"Edge\([^)]*label\s*=\s*[\"']([^\"']+)[\"']", code)
    for label in edge_labels:
        flat = " ".join(label.split())
        if len(flat) > 28 or "\n" in label:
            _audit_add(
                findings, "low", "long_edge_label",
                f"Long edge label detected: {flat[:60]}",
                "Keep edge labels short, ideally 1-4 words; move detail into node sublabels or a legend.",
            )
            break

    if re.search(r"unhealthy|not healthy|failed|down", code, re.IGNORECASE) and not re.search(r"color\s*=\s*[\"']#?(?:d|c|e|f|red)", code, re.IGNORECASE):
        _audit_add(
            findings, "low", "health_status",
            "Health/status language appears without an obvious red/error visual encoding.",
            "Show degraded status with a red/dashed edge, a small status node, or a red security/alert concern rather than trying to mutate built-in node borders.",
        )

    is_slide = "render_slide(" in code
    cluster_count = code.count("g.cluster(")
    is_poster = "flow_layout=False" in code or (
        "density='poster'" in code or 'density="poster"' in code
    )
    has_link = "g.link(" in code
    has_cross_cluster_edge = has_link  # any edge could be cross-cluster; we check below

    if is_slide and cluster_count >= 6:
        has_numbered = "number=" in code

        if is_poster:
            # Poster / wall-grid mode: require structural grid for each plane.
            has_grid = "grid_cluster(" in code or "poster_grid(" in code
            has_invis_spine = has_grid or 'style="invis"' in code or "style='invis'" in code

            if not has_invis_spine:
                _audit_add(
                    findings, "high", "poster_missing_spine",
                    f"Poster mode ({cluster_count} clusters) has no grid structure — "
                    "planes will sprawl and the layout will be sparse.",
                    "Pack each region: g.grid_cluster(region_id, cols=2 or 3) after its "
                    "boxes, and set Pretty(..., flow_layout=False) + direction='LR'.",
                )
            if "grid_cluster(" not in code and "poster_grid(" in code:
                _audit_add(
                    findings, "medium", "poster_uses_legacy_grid",
                    "Poster uses g.poster_grid (single-column ranks) instead of dense "
                    "in-plane grids — the diagram will read sparse, not like the reference.",
                    "Replace poster_grid with one g.grid_cluster(region_id, cols=N) per "
                    "plane so each plane packs into a dense logo grid.",
                )
        else:
            # Flow mode (default): require cross-cluster edges for visible connections.
            if not has_link:
                _audit_add(
                    findings, "high", "flow_missing_edges",
                    f"Flow mode ({cluster_count} clusters) has no g.link() calls — "
                    "clusters will be disconnected islands with no visible flow.",
                    "Add real cross-cluster g.link() edges for the primary data flow. "
                    "In flow_layout=True mode these edges pull the layout AND show "
                    "connections between zones — they are mandatory.",
                )
            elif cluster_count >= 4 and code.count("g.link(") < cluster_count - 1:
                _audit_add(
                    findings, "medium", "flow_few_cross_cluster_edges",
                    f"Flow mode has {code.count('g.link(')} edges for {cluster_count} "
                    "clusters — many zones may appear disconnected.",
                    "Add cross-cluster g.link() edges to connect every zone to the "
                    "primary flow. The connections are what make the diagram readable.",
                )

        if not has_numbered:
            _audit_add(
                findings, "high", "missing_cluster_numbers",
                f"Diagram with {cluster_count} clusters has no number= arguments.",
                "Add number=1, number=2, ... to every top-level g.cluster() call.",
            )

    if not findings:
        return {"verdict": "PASS", "findings": []}
    verdict = "REVISE" if any(f["severity"] in {"high", "medium"} for f in findings) else "PASS_WITH_NOTES"
    return {"verdict": verdict, "findings": findings}


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
        proc = subprocess.run(
            [sys.executable, "diagram.py"],
            cwd=str(current_workspace()),
            capture_output=True,
            text=True,
            timeout=RENDER_TIMEOUT_S,
        )
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
            from gv_to_drawio import convert
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
        from validate_drawio import validate_file
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
        from .analysis_tools import _diagram_gate_note
        gate_note = _diagram_gate_note(block=False)
    except Exception:  # noqa: BLE001
        pass

    return f"Wrote out.drawio ({out.stat().st_size} bytes).{lint}{archive_note}{gate_note}"


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
