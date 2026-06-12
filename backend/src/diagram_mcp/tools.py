"""Custom tools for the diagram deep agent.

The agent has NO shell. Everything that needs to *run* code or touch the
network lives here as an explicit tool:

  - render_diagram : write & execute the generated `diagrams` code → out.png/out.dot,
                     and hand the rendered PNG back to the model to inspect.
  - export_drawio  : convert out.dot → editable out.drawio (embeds logos).
  - search_icons   : look up exact icon paths in the bundled pack.
  - fetch_logo     : resolve/download a brand logo not in the pack.

All file artifacts live under WORKSPACE (the agent's default FilesystemBackend root).
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Literal, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from pydantic import BaseModel, ConfigDict, Field

from .architecture_advisor import analyze_requirements
from .backends import LOCAL_ICONS, LOCAL_MANIFEST, LOCAL_NODE_CATALOG, WORKSPACE
from .findings import DiagramFinding, format_critique, prune, verdict_for
from .reporting import (
    DEFAULT_REPORT_SECTIONS,
    REPORT_EVIDENCE_NAME,
    ReportRenderError,
    generate_report,
    record_artifact_inventory,
    record_report_step,
)

# Stage markers written under WORKSPACE so the staged tools can enforce order.
_ARCH_ANALYSIS_FILE = WORKSPACE / "architecture_analysis.json"
_BRIEF_FILE = WORKSPACE / "diagram_brief.json"
_TECHSTACK_FILE = WORKSPACE / "tech_stack.json"
_BLUEPRINT_FILE = WORKSPACE / "blueprint.json"
_CRITIQUE_FILE = WORKSPACE / "critique.json"


_RENDER_COUNT_FILE = WORKSPACE / "render_count.json"
_ICON_SEARCH_BUDGET_FILE = WORKSPACE / "icon_search_budget.json"
_NODE_SEARCH_BUDGET_FILE = WORKSPACE / "node_search_budget.json"
_REVISION_COUNT_FILE = WORKSPACE / "revision_count.json"
_TOOL_SUMMARY_FILE = WORKSPACE / "tool_budget_summary.json"
_ICON_PLAN_FILE = WORKSPACE / "icon_plan.json"
# Per-round render budget: soft nudge at 3 (finalize with what you have), hard
# refusal at 6 (the #1 cause of "run limit 80/80" was an endless fix->render
# loop chasing audit warnings that cannot be fully resolved).
RENDER_SOFT_CAP = 3
RENDER_HARD_CAP = 6
ICON_SEARCH_PER_QUERY_CAP = 3
ICON_SEARCH_DEFAULT_TOTAL_CAP = 12
NODE_SINGLE_SEARCH_WARN = 3
NODE_SINGLE_SEARCH_HARD_CAP = 6
CRITIC_REVISION_HARD_CAP = 2

def _read_json_file(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default

def _write_json_file(path: Path, value) -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")

def _bump_tool_summary(tool_name: str, **extra) -> None:
    summary = _read_json_file(_TOOL_SUMMARY_FILE, {"tool_counts": {}})
    counts = summary.setdefault("tool_counts", {})
    counts[tool_name] = int(counts.get(tool_name, 0)) + 1
    for key, value in extra.items():
        if key.endswith("_hits"):
            summary[key] = int(summary.get(key, 0)) + int(value)
        else:
            summary[key] = value
    _write_json_file(_TOOL_SUMMARY_FILE, summary)


def _render_count() -> int:
    try:
        return int(json.loads(_RENDER_COUNT_FILE.read_text(encoding="utf-8"))["count"])
    except Exception:  # noqa: BLE001
        return 0


def _bump_render_count() -> int:
    n = _render_count() + 1
    _RENDER_COUNT_FILE.write_text(json.dumps({"count": n}), encoding="utf-8")
    _bump_tool_summary("render_diagram", render_attempts=n)
    return n


def _reset_round_budgets() -> None:
    for f in (_RENDER_COUNT_FILE, _ICON_SEARCH_BUDGET_FILE, _NODE_SEARCH_BUDGET_FILE):
        if f.exists():
            f.unlink()


def reset_render_count() -> None:
    """New design / new revision round -> fresh render budget."""
    _reset_round_budgets()


def _reset_revision_count() -> None:
    if _REVISION_COUNT_FILE.exists():
        _REVISION_COUNT_FILE.unlink()


def clear_stage_markers() -> None:
    """Reset the staged-flow markers at the start of a fresh run."""
    for f in (
        _ARCH_ANALYSIS_FILE, _BRIEF_FILE, _TECHSTACK_FILE, _BLUEPRINT_FILE,
        _CRITIQUE_FILE, _REVISION_COUNT_FILE, _TOOL_SUMMARY_FILE,
        _ICON_SEARCH_BUDGET_FILE, _NODE_SEARCH_BUDGET_FILE,
        WORKSPACE / REPORT_EVIDENCE_NAME,
    ):
        if f.exists():
            f.unlink()
    _reset_round_budgets()

RENDER_TIMEOUT_S = 180
# Max width of the image handed BACK to the model to inspect. The full-resolution
# out.png is kept on disk for the user — this only shrinks the copy that goes into
# the conversation (it is re-sent every turn, so a smaller copy saves context).
INSPECT_MAX_WIDTH = 800

# out.* artifacts produced by a render, cleaned before each run.
_OUT_NAMES = (
    "out.png", "out.body.png", "out.dot", "out.drawio", "out.nodes.json",
    "out.slide.json",
)

# prettygraph.py must be importable by the generated diagram.py (pretty style does
# `from prettygraph import Pretty`). Stage a copy into the workspace.
_PRETTYGRAPH_SRC = Path(__file__).with_name("prettygraph.py").read_text(encoding="utf-8")


def _stage_helpers() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    pg = WORKSPACE / "prettygraph.py"
    if not pg.exists() or pg.read_text(encoding="utf-8") != _PRETTYGRAPH_SRC:
        pg.write_text(_PRETTYGRAPH_SRC, encoding="utf-8")


def _layout_audit() -> str:
    """Best-effort layout audit for the last render (advisory; "" if unavailable)."""
    dot = WORKSPACE / "out.dot"
    png = WORKSPACE / "out.png"
    if not dot.exists() or not png.exists():
        return ""
    try:
        from .prettygraph import audit_layout
        return audit_layout(str(dot), str(png))
    except Exception:  # noqa: BLE001 — audit is advisory, never fail over it
        return ""


def _search_icon_hits(query: str, provider: Optional[str] = None, *, limit: int = 30) -> list[str]:
    try:
        manifest = json.loads(Path(LOCAL_MANIFEST).read_text(encoding="utf-8"))
    except Exception:
        return []

    terms = [t for t in query.lower().replace("-", " ").replace("_", " ").split() if t]
    root = Path(LOCAL_ICONS)
    hits: list[str] = []
    for prov, cats in manifest.get("providers", {}).items():
        if provider and prov.lower() != provider.lower():
            continue
        for cat, names in cats.items():
            for name in names:
                hay = f"{prov} {cat} {name}".lower()
                if all(t in hay for t in terms):
                    sub = name if cat == "_root" else f"{cat}/{name}"
                    hits.append(str(root / prov / f"{sub}.png"))
                    if len(hits) >= limit:
                        return hits
    return hits

def _icon_rel(path: str) -> str:
    try:
        return str(Path(path).relative_to(Path(LOCAL_ICONS))).replace("\\", "/")
    except Exception:
        return path

def _icon_key(query: str, provider: Optional[str]) -> str:
    prov = (provider or "").strip().lower()
    q = " ".join((query or "").lower().replace("-", " ").replace("_", " ").split())
    return f"{prov}:{q}"

def _icon_search_total_cap(state: dict) -> int:
    planned = state.get("planned_icons")
    if isinstance(planned, int) and planned > 0:
        return planned * ICON_SEARCH_PER_QUERY_CAP
    return ICON_SEARCH_DEFAULT_TOTAL_CAP

def _icon_search_state() -> dict:
    return _read_json_file(
        _ICON_SEARCH_BUDGET_FILE,
        {"counts": {}, "cache": {}, "total_calls": 0, "planned_icons": 0},
    )

def _save_icon_search_state(state: dict) -> None:
    _write_json_file(_ICON_SEARCH_BUDGET_FILE, state)

def _node_search_state() -> dict:
    return _read_json_file(_NODE_SEARCH_BUDGET_FILE, {"single_calls": 0, "batch_calls": 0})

def _save_node_search_state(state: dict) -> None:
    _write_json_file(_NODE_SEARCH_BUDGET_FILE, state)


def _tokens(text: str) -> list[str]:
    return [t for t in text.lower().replace("-", " ").replace("_", " ").split() if t]


def _node_search_hits(query: str, provider: str = "", category: str = "", *, limit: int = 10) -> list[dict]:
    try:
        catalog = json.loads(Path(LOCAL_NODE_CATALOG).read_text(encoding="utf-8"))
    except Exception:
        return []
    terms = _tokens(query)
    if not terms:
        return []
    provider_filter = provider.strip().lower()
    category_filter = category.strip().lower()
    scored: list[dict] = []
    for prov, cats in catalog.items():
        if provider_filter and provider_filter != str(prov).lower():
            continue
        if not isinstance(cats, dict):
            continue
        for cat, classes in cats.items():
            if category_filter and category_filter != str(cat).lower():
                continue
            for class_name in classes or []:
                hay = f"{prov} {cat} {class_name}".lower()
                class_lower = str(class_name).lower()
                if not all(term in hay for term in terms):
                    continue
                score = 0
                query_flat = "".join(terms)
                class_flat = class_lower.replace("_", "").replace("-", "")
                if class_lower == query.lower():
                    score += 100
                elif class_flat == query_flat:
                    score += 90
                elif class_lower.startswith(query.lower()):
                    score += 55
                score += sum(10 for term in terms if term in class_lower)
                if provider_filter and provider_filter == str(prov).lower():
                    score += 8
                if category_filter and category_filter == str(cat).lower():
                    score += 5
                scored.append({
                    "provider": prov,
                    "category": cat,
                    "class_name": class_name,
                    "import_path": f"diagrams.{prov}.{cat}.{class_name}",
                    "score": score,
                })
    scored.sort(key=lambda item: (-item["score"], item["provider"], item["category"], item["class_name"]))
    return scored[: max(1, min(limit, 50))]


def _inspection_image_b64(png_path: Path) -> tuple[str, str]:
    """Return (base64, mime) of a context-friendly copy of the rendered PNG.

    Downscale to <= INSPECT_MAX_WIDTH and JPEG-compress so the image that lands in
    the conversation is small. Falls back to the raw PNG if Pillow is unavailable.
    """
    try:
        import io
        from PIL import Image

        im = Image.open(png_path).convert("RGB")
        if im.width > INSPECT_MAX_WIDTH:
            h = round(im.height * INSPECT_MAX_WIDTH / im.width)
            im = im.resize((INSPECT_MAX_WIDTH, h), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=65, optimize=True)
        return base64.standard_b64encode(buf.getvalue()).decode("ascii"), "image/jpeg"
    except Exception:  # noqa: BLE001 — never fail a render over the preview copy
        return base64.standard_b64encode(png_path.read_bytes()).decode("ascii"), "image/png"


def _audit_add(findings: list[dict], severity: str, rule: str, detail: str, suggestion: str) -> None:
    findings.append({
        "severity": severity,
        "rule": rule,
        "detail": detail,
        "suggestion": suggestion,
    })


@tool
def audit_diagram_code(code: str) -> str:
    """Statically audit a diagram script for known `diagrams`/Graphviz pitfalls.

    Call this before `render_diagram` and after substantial edits. It does not
    execute code or write files; it catches common layout traps such as missing
    `out` render settings, over-specific edge positioning, unstable large
    clusters, floating `xlabel`s, and global font settings in the wrong attr bag.
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

    if is_slide and cluster_count >= 6:
        # poster_grid() auto-generates the spine + per-column same_rank, so it
        # satisfies both structural requirements on its own.
        has_grid = "poster_grid(" in code
        has_invis_spine = has_grid or 'style="invis"' in code or "style='invis'" in code
        has_numbered = "number=" in code
        has_same_rank = has_grid or "same_rank(" in code

        if not has_invis_spine:
            _audit_add(
                findings, "high", "poster_missing_spine",
                f"Poster mode ({cluster_count} clusters) has no grid structure.",
                "Call g.poster_grid([row1 anchors], [row2 anchors]) — it builds the invisible spine for you.",
            )
        if not has_numbered:
            _audit_add(
                findings, "high", "poster_missing_numbers",
                "Poster mode: top-level clusters have no number= argument.",
                "Add number=1, number=2, ... to every top-level g.cluster() call.",
            )
        if not has_same_rank:
            _audit_add(
                findings, "medium", "poster_missing_same_rank",
                "Poster mode has no column alignment — rows may not align across columns.",
                "Call g.poster_grid([row1 anchors], [row2 anchors]) to sync row/column positions.",
            )

    if not findings:
        return json.dumps({"verdict": "PASS", "findings": []}, indent=2)
    verdict = "REVISE" if any(f["severity"] in {"high", "medium"} for f in findings) else "PASS_WITH_NOTES"
    return json.dumps({"verdict": verdict, "findings": findings}, indent=2)


@tool
def render_diagram(
    code: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> ToolMessage:
    """Render a `diagrams` (mingrammer) Python script and return the resulting image.

    Pass the COMPLETE Python script as `code`. It must render to `out.png` AND
    `out.dot` in the working directory, e.g.:
        Diagram("...", filename="out", outformat=["png", "dot"], show=False, ...)
    (pretty style: `Pretty(...).render("out")`).

    On success the rendered PNG is returned so you can LOOK at it and refine.
    On failure the error output is returned so you can fix the code and retry.
    """
    if not _BLUEPRINT_FILE.exists():
        return ToolMessage(
            content="Get the architecture approved first: call propose_tech_stack, "
                    "then propose_blueprint, before rendering.",
            name="render_diagram",
            tool_call_id=tool_call_id,
            status="error",
        )
    if _render_count() >= RENDER_HARD_CAP:
        next_step = (
            "Keep the existing out.png: call export_drawio(), then return your "
            "summary listing residual audit warnings."
            if (WORKSPACE / "out.png").exists()
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
        p = WORKSPACE / out_name
        if p.exists():
            p.unlink()
    (WORKSPACE / "diagram.py").write_text(code, encoding="utf-8")

    try:
        proc = subprocess.run(
            [sys.executable, "diagram.py"],
            cwd=str(WORKSPACE),
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

    png = WORKSPACE / "out.png"
    if proc.returncode != 0 or not png.exists():
        err = (proc.stderr or proc.stdout or "").strip()
        return ToolMessage(
            content=f"Render #{attempt}/{RENDER_HARD_CAP} FAILED (exit {proc.returncode}). "
                    f"Fix the code and retry only if under budget.\n\n{err[-3000:]}",
            name="render_diagram",
            tool_call_id=tool_call_id,
            status="error",
        )

    b64, mime = _inspection_image_b64(png)
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
        WORKSPACE,
        "render_diagram",
        summary=f"Rendered out.png successfully on attempt {attempt}.",
        data={
            "attempt": attempt,
            "audit": audit,
            "artifacts": record_artifact_inventory(WORKSPACE),
        },
    )
    return ToolMessage(
        content_blocks=[
            {"type": "text", "text": text},
            {"type": "image", "base64": b64, "mime_type": mime},
        ],
        name="render_diagram",
        tool_call_id=tool_call_id,
        status="success",
    )


@tool
def export_drawio() -> str:
    """Convert the last rendered out.dot into an editable out.drawio (with embedded logos).

    Call this once the diagram looks good. Produces out.drawio next to out.png.
    """
    dot = WORKSPACE / "out.dot"
    out = WORKSPACE / "out.drawio"
    sidecar = WORKSPACE / "out.nodes.json"
    slide = WORKSPACE / "out.slide.json"
    if slide.exists() and out.exists():
        return f"Slide drawio already ready ({out.stat().st_size} bytes); not overwriting."
    if not dot.exists():
        return "No out.dot found — call render_diagram first."
    try:
        if sidecar.exists():
            from .prettygraph import dot_to_drawio
            dot_to_drawio(str(dot), str(sidecar), str(out))
        else:
            from .gv_to_drawio import convert
            convert(str(dot), str(out))
    except Exception as exc:  # noqa: BLE001 — surface to the agent
        return f"export_drawio failed: {exc}"
    if not out.exists():
        return "export_drawio produced no file."
    record_report_step(
        WORKSPACE,
        "export_drawio",
        summary=f"Created editable draw.io artifact ({out.stat().st_size} bytes).",
        data={"artifacts": record_artifact_inventory(WORKSPACE)},
    )
    return f"Wrote out.drawio ({out.stat().st_size} bytes)."


@tool
def search_icons(query: str, provider: Optional[str] = None) -> str:
    """Search the bundled icon pack for matching icon paths.

    Returns absolute `.png` paths to use in `Custom(label, "<path>")` when no
    built-in `diagrams` node fits. Optionally restrict to one `provider`
    (e.g. "aws", "azure", "gcp", "onprem", "k8s", "programming", "saas").
    """
    state = _icon_search_state()
    key = _icon_key(query, provider)
    cache = state.setdefault("cache", {})
    if key in cache:
        cached = cache[key]
        _bump_tool_summary("search_icons", icon_search_cache_hits=1)
        return json.dumps({**cached, "cached": True}, indent=2)

    total_cap = _icon_search_total_cap(state)
    total_calls = int(state.get("total_calls", 0))
    counts = state.setdefault("counts", {})
    key_count = int(counts.get(key, 0))
    if total_calls >= total_cap or key_count >= ICON_SEARCH_PER_QUERY_CAP:
        result = {
            "status": "BUDGET_EXHAUSTED",
            "query": query,
            "provider": provider,
            "total_calls": total_calls,
            "total_cap": total_cap,
            "query_calls": key_count,
            "query_cap": ICON_SEARCH_PER_QUERY_CAP,
            "instruction": (
                "Stop searching this icon. Use an existing icon_plan.json path, "
                "omit icon=, or use one generic fallback."
            ),
        }
        _bump_tool_summary("search_icons_budget_exhausted")
        return json.dumps(result, indent=2)

    counts[key] = key_count + 1
    state["total_calls"] = total_calls + 1
    hits = _search_icon_hits(query, provider, limit=5)
    result = {
        "status": "FOUND" if hits else "NOT_FOUND",
        "query": query,
        "provider": provider,
        "hits": [{"path": p, "icon": _icon_rel(p)} for p in hits[:5]],
        "instruction": (
            "Use one returned icon path. If NOT_FOUND, try at most one broader "
            "different keyword, then omit icon= or fetch_logo for a brand."
            if hits
            else "Try at most one broader different keyword, then omit icon= "
                 "or fetch_logo for a brand."
        ),
    }
    cache[key] = result
    _save_icon_search_state(state)
    _bump_tool_summary("search_icons", icon_search_total_calls=state["total_calls"])
    return json.dumps(result, indent=2)


@tool
def search_diagrams_nodes(query: str = "", provider: str = "", category: str = "",
                          limit: int = 10, queries: Optional[list[str]] = None) -> str:
    """Search built-in `diagrams` node classes using the local node catalog.

    Use this before writing raw `from diagrams.<provider>.<category> import X`
    imports. It returns verified import paths from `resources/node_catalog.json`.
    Use `resolve_icons` / `search_icons` only when no built-in node fits.

    BATCH: pass `queries=["redis", "cloud run", ...]` to resolve ALL planned
    imports in ONE call (returns {query: hits}). Do not call once per node.
    """
    state = _node_search_state()
    if queries:
        state["batch_calls"] = int(state.get("batch_calls", 0)) + 1
        _save_node_search_state(state)
        _bump_tool_summary("search_diagrams_nodes_batch")
        return json.dumps(
            {q: _node_search_hits(q, provider, category, limit=limit) for q in queries},
            indent=2)
    single_calls = int(state.get("single_calls", 0)) + 1
    state["single_calls"] = single_calls
    _save_node_search_state(state)
    _bump_tool_summary("search_diagrams_nodes_single", node_single_searches=single_calls)
    if single_calls > NODE_SINGLE_SEARCH_HARD_CAP:
        return json.dumps({
            "status": "BUDGET_EXHAUSTED",
            "query": query,
            "instruction": (
                "Stop one-by-one node searches. Batch remaining terms with "
                "queries=[...] or use already returned imports."
            ),
            "single_calls": single_calls,
            "single_call_cap": NODE_SINGLE_SEARCH_HARD_CAP,
        }, indent=2)
    hits = _node_search_hits(query, provider, category, limit=limit)
    payload: dict = {"status": "OK", "query": query, "hits": hits}
    if single_calls > NODE_SINGLE_SEARCH_WARN:
        payload["warning"] = (
            "Too many single node searches. Batch remaining terms with queries=[...]."
        )
    return json.dumps(payload, indent=2)


class IconRequest(BaseModel):
    """One planned icon lookup for batch resolution."""
    label: str = Field(description="visible node/component label")
    provider: str = Field("", description="provider subtree, e.g. aws|azure|gcp|onprem|programming|saas")
    icon_keyword: str = Field(description="short filename-style search term, e.g. redis|run|sql|pubsub")


@tool
def resolve_icons(icons: list[IconRequest]) -> str:
    """Resolve a planned batch of icon lookups in one tool call.

    Returns JSON entries with a best matching absolute `path` and prettygraph
    relative `icon`. Also writes `icon_plan.json` in the workspace so revision
    tasks can reuse prior choices instead of searching again.
    """
    state = _icon_search_state()
    if state.get("resolved_this_round") and _ICON_PLAN_FILE.exists():
        cached = _read_json_file(_ICON_PLAN_FILE, [])
        _bump_tool_summary("resolve_icons_cached")
        return json.dumps({
            "status": "ALREADY_RESOLVED_THIS_ROUND",
            "instruction": (
                "Reuse icon_plan.json. Use search_icons only for new NOT_FOUND "
                "items with a different keyword."
            ),
            "icons": cached,
        }, indent=2)

    root = Path(LOCAL_ICONS)
    resolved: list[dict] = []
    for item in icons:
        hits = _search_icon_hits(item.icon_keyword, item.provider or None, limit=5)
        best = hits[0] if hits else ""
        rel = ""
        if best:
            try:
                rel = str(Path(best).relative_to(root)).replace("\\", "/")
            except Exception:
                rel = best
        resolved.append({
            "label": item.label,
            "provider": item.provider,
            "icon_keyword": item.icon_keyword,
            "status": "FOUND" if best else "NOT_FOUND",
            "path": best or None,
            "icon": rel or None,
            "alternatives": hits[1:5],
            "tried_keywords": [item.icon_keyword],
        })
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    _ICON_PLAN_FILE.write_text(json.dumps(resolved, indent=2), encoding="utf-8")
    state.update({
        "resolved_this_round": True,
        "planned_icons": len({(i.provider.lower(), i.icon_keyword.lower()) for i in icons}),
        "total_calls": 0,
        "counts": {},
        "cache": {},
    })
    _save_icon_search_state(state)
    _bump_tool_summary("resolve_icons", planned_icons=state["planned_icons"])
    return json.dumps(resolved, indent=2)


@tool
def plan_style_sizes(
    node_count: int,
    longest_label_chars: int = 22,
    longest_sublabel_chars: int = 26,
    output: Literal["slide", "diagram", "poster"] = "slide",
) -> str:
    """Decide icon/text sizes for a prettygraph render BEFORE writing the script.

    Deterministic sizing from diagram density: sparse client-facing diagrams get
    bigger icons and text (small fixed sizes look diluted inside large cards);
    dense diagrams get compact cards. Returns JSON with a `sizes` block, a
    ready-to-paste `pretty_kwargs` string for `Pretty(...)`, and `notes` with any
    label-length warnings. Re-run after trimming nodes or when the critic flags
    small/unreadable text.

    Args:
        node_count: number of VISIBLE boxes planned (after collapsing replicas).
        longest_label_chars: character count of the longest node title.
        longest_sublabel_chars: character count of the longest sublabel.
        output: "slide" (pro slide canvas), "diagram" (plain render), or
                "poster" (dense numbered-section grid, 25-40 nodes).
    """
    import math

    if node_count <= 8:
        density, node_h, title = "sparse", 66, 17
    elif node_count <= 14:
        density, node_h, title = "medium", 60, 16
    elif node_count <= 22:
        density, node_h, title = "dense", 54, 14
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
    if node_count > 18 and output == "slide":
        notes.append("18+ visible nodes on a slide reads cramped — collapse "
                     "replicas/aggregate side concerns, or use output='poster'.")
    if output == "poster":
        notes.append(
            "Poster mode: use a 2-row grid with 6-9 numbered sections. "
            "Row 1 = client-facing tiers (Client→Orchestration→Inference→Storage), "
            "Row 2 = platform tiers (Ingestion→Parsing→VDB→Observability/Auth). "
            "Pin columns with an invisible spine + same_rank across both rows. "
            "Nested sub-clusters inside sections are encouraged. "
            "Target aspect 1.2-2.2."
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
        "pretty_kwargs": ", ".join(f"{k}={v}" for k, v in sizes.items()),
        "notes": notes,
    }
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    (WORKSPACE / "style_plan.json").write_text(
        json.dumps(plan, indent=2), encoding="utf-8"
    )
    return json.dumps(plan, indent=2)


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


@tool
def fit_labels(
    nodes: list[NodeText],
    edge_labels: Optional[list[str]] = None,
    node_width: int = 0,
    icon_size: int = 0,
    title_size: int = 0,
    sublabel_size: int = 0,
) -> str:
    """Check node/edge text against the planned card size and shorten what overflows.

    Text MUST stay inside its card: cards that outgrow `node_width` get
    auto-widened at render (breaking uniform width), so fix the text FIRST.
    Size args default to the last `plan_style_sizes` result (`style_plan.json`).
    Returns JSON per node: `fits`, char budgets, and a deterministic
    `suggestion` (parenthetical -> sublabel, standard abbreviations, vendor
    prefix drop). Entries with `still_too_long: true` need a manual rename.
    Edge labels longer than ~4 words are flagged with a trimmed suggestion.
    """
    plan_sizes: dict = {}
    plan_file = WORKSPACE / "style_plan.json"
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
        title_fits = len(item.label) <= max_title
        sub_fits = len(item.sublabel) <= max_sub
        entry: dict = {"label": item.label, "fits": title_fits and sub_fits}
        if not title_fits:
            new_label, moved, steps = _shorten(item.label,
                                               lambda t: len(t) <= max_title)
            if steps:
                sub = item.sublabel or ""
                if moved:
                    sub = f"{moved} · {sub}".strip(" ·") if sub else moved
                entry["suggestion"] = {"label": new_label, "sublabel": sub,
                                       "steps": steps}
            if len(new_label) > max_title:
                entry["still_too_long"] = True
                entry["hint"] = (f"rename manually to <= {max_title} chars "
                                 "(or raise node_width and re-run plan_style_sizes)")
        if not sub_fits:
            new_sub, _, steps = _shorten(item.sublabel,
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

    out = {
        "card": {"node_width": node_width, "icon_size": icon_size,
                 "title_size": title_size, "sublabel_size": sublabel_size},
        "max_title_chars": max_title,
        "max_sublabel_chars": max_sub,
        "nodes": results,
        "edges": edge_results,
        "overflowing": sum(1 for r in results if not r["fits"]),
    }
    return json.dumps(out, indent=2, ensure_ascii=False)


@tool
def fetch_logo(name: str) -> str:
    """Resolve a brand/product logo not in the pack (e.g. 'Supabase', 'NVIDIA Jetson').

    Searches the local pack, then Iconify, then favicon; downloads & validates.
    Returns an absolute PNG path to use in `Custom(label, "<path>")`, or NOT_FOUND.
    """
    try:
        from .logo_fetch import get_logo
        path = get_logo(name, LOCAL_ICONS, str(WORKSPACE))
    except Exception as exc:  # noqa: BLE001
        return f"NOT_FOUND: fetch_logo error: {exc}"
    return path or f"NOT_FOUND: no verified logo for '{name}'. Use a built-in node or search_icons()."


@tool
def analyze_architecture_requirements(requirements: str, provider_preference: str = "") -> str:
    """Analyze architecture requirements into deterministic planning signals.

    This is not a human-approval gate. Use it after reading the user prompt and
    attached requirement docs, before `propose_diagram_brief`. It writes
    `architecture_analysis.json` so the brief, tech stack, blueprint, and critic
    can stay aligned on pattern, scale, security, provider, and scope signals.
    """
    analysis = analyze_requirements(requirements, provider_preference)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    _ARCH_ANALYSIS_FILE.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    record_report_step(
        WORKSPACE,
        "analyze_architecture_requirements",
        summary=(
            f"Detected {analysis.get('application_type', 'application')} workload, "
            f"{analysis.get('scale_level', 'unspecified')} scale, "
            f"{analysis.get('security_level', 'unspecified')} security, "
            f"provider={analysis.get('provider_preference') or 'cloud-neutral'}."
        ),
        data=analysis,
    )
    return json.dumps(analysis, indent=2)


# ---------------------------------------------------------------------------
# Staged Human-in-the-loop tools (gated via interrupt_on in agent.py)
# Each call PAUSES for human review before it executes; the structured args
# become the card the frontend renders.
# ---------------------------------------------------------------------------

class DiagramBrief(BaseModel):
    """Requirements-derived diagram brief used before tech stack and blueprint."""

    objective: str = Field(description="one concise sentence describing what the diagram must communicate")
    application_type: str = Field("", description="application type from architecture analysis, e.g. web_application|api_service|data_analytics")
    scale_level: str = Field("", description="scale signal from architecture analysis: small|medium|large|enterprise")
    security_level: str = Field("", description="security signal from architecture analysis: basic|standard|high|critical")
    provider_preference: str = Field("", description="cloud/provider signal, e.g. aws|azure|gcp|oci|onprem")
    analysis_signals: list[str] = Field(
        default_factory=list,
        description="short copied signals from architecture_analysis.json: capabilities, constraints, selected pattern hints",
    )
    stakeholders: list[str] = Field(
        default_factory=list,
        description="intended readers/reviewers, e.g. cloud/devops, security, developers, management",
    )
    functional_requirements: list[str] = Field(
        default_factory=list,
        description="architecture capabilities that must appear or be represented in the diagram",
    )
    non_functional_requirements: list[str] = Field(
        default_factory=list,
        description="quality constraints such as scalability, availability, security, governance, maintainability",
    )
    layout_constraints: list[str] = Field(
        default_factory=list,
        description="visual/layout constraints and simplification choices for the diagram",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="explicit assumptions made when the prompt/docs do not fully specify details",
    )


class TechCriteria(BaseModel):
    """1–5 scoring dimensions for a technology choice (1 = best, 5 = worst on cost/complexity/lock-in)."""
    cost: int = Field(3, ge=1, le=5, description="1=very low cost, 5=very high cost")
    ops_complexity: int = Field(3, ge=1, le=5, description="1=simple to operate, 5=high operational burden")
    scalability: int = Field(3, ge=1, le=5, description="1=limited, 5=highly scalable")
    vendor_lockin: int = Field(3, ge=1, le=5, description="1=fully portable, 5=deeply vendor-locked")
    team_fit: int = Field(3, ge=1, le=5, description="1=unfamiliar to team, 5=strong team expertise")


class TechAlternative(BaseModel):
    """An alternative technology with rejection rationale and optional scoring."""
    name: str = Field(description="technology name")
    why_rejected: str = Field("", description="one sentence: why this alternative was not chosen for this context")
    criteria: Optional[TechCriteria] = Field(default=None, description="optional 1-5 scores for this alternative")


class CostRange(BaseModel):
    """Assumption-based monthly cost estimate in USD (always a range)."""
    min_usd: int = Field(0, ge=0)
    max_usd: int = Field(0, ge=0)


class UserScaleAssumptions(BaseModel):
    mau: Optional[int] = None
    dau: Optional[int] = None
    peak_concurrent: Optional[int] = None
    peak_rps: Optional[int] = None
    growth_rate_yoy_pct: Optional[int] = None


class DataAssumptions(BaseModel):
    initial_gb: Optional[int] = None
    growth_gb_per_month: Optional[int] = None
    read_write_ratio: str = ""


class TeamAssumptions(BaseModel):
    size: Optional[int] = None
    skill_level: str = ""
    devops_maturity: str = ""


class SolutionAssumptions(BaseModel):
    budget_tier: str = ""
    monthly_budget_range_usd: Optional[CostRange] = None
    users: Optional[UserScaleAssumptions] = None
    data: Optional[DataAssumptions] = None
    team: Optional[TeamAssumptions] = None
    project_phase: str = ""
    availability_target: str = ""
    latency_target_p99_ms: Optional[int] = None
    compliance: list[str] = Field(default_factory=list)
    primary_region: str = ""
    confirm_with_customer: list[str] = Field(
        default_factory=list,
        description="assumptions NOT yet confirmed by the customer — the senior-SA hedge list",
    )


class TechRisk(BaseModel):
    risk: str
    mitigation: str = ""


class ScalingPhase(BaseModel):
    phase: str
    trigger: str = ""
    changes: list[str] = Field(default_factory=list)
    est_monthly_cost_usd: Optional[CostRange] = None


class TechChoice(BaseModel):
    """One layer of the recommended technology stack."""
    layer: str = Field(
        description=(
            "the layer name — core layers: frontend, backend, database, auth, infra, monitoring, networking, security; "
            "conditional layers: cache, queue, cdn, search, storage, ci_cd, analytics, ai_ml, integration"
        )
    )
    choice: str = Field(description="the specific technology chosen for this layer")
    rationale: str = Field("", description="1-2 sentence reason tied to the requirements")
    cost_tier: str = Field("$$", description="relative cost: $=low, $$=medium, $$$=high")
    decision_criteria: Optional[TechCriteria] = Field(
        default=None,
        description="1-5 scores for the CHOSEN technology on cost, ops_complexity, scalability, vendor_lockin, team_fit",
    )
    alternatives: list[TechAlternative] = Field(
        default_factory=list,
        description="rejected alternatives with why_rejected and optional criteria scores",
    )
    estimated_monthly_cost_usd: Optional[CostRange] = Field(
        default=None,
        description="assumption-based cost range for this layer in USD/month",
    )
    capacity_sizing: str = Field(
        "",
        description="instance type/count WITH the math — e.g. '2× Fargate 0.5vCPU, autoscale 2–6 — sized for ~150 RPS peak × 2 headroom'",
    )
    performance_target: str = Field(
        "",
        description="measurable target tied to an NFR — e.g. 'p99 ≤ 120 ms at 150 RPS'",
    )
    risks: list[TechRisk] = Field(
        default_factory=list,
        description="1-2 risks for this layer with mitigation",
    )


class WAFPillar(BaseModel):
    """Coverage of one AWS Well-Architected Framework pillar in the blueprint."""
    addressed_by: list[str] = Field(
        default_factory=list,
        description="node IDs or key_decision labels that address this pillar",
    )
    gaps: list[str] = Field(
        default_factory=list,
        description="known gaps — explicitly declare rather than leave empty; gaps are allowed when stated",
    )


class PillarCoverage(BaseModel):
    """Well-Architected Framework 6-pillar coverage."""
    operational_excellence: WAFPillar = Field(default_factory=WAFPillar)
    security: WAFPillar = Field(default_factory=WAFPillar)
    reliability: WAFPillar = Field(default_factory=WAFPillar)
    performance_efficiency: WAFPillar = Field(default_factory=WAFPillar)
    cost_optimization: WAFPillar = Field(default_factory=WAFPillar)
    sustainability: WAFPillar = Field(default_factory=WAFPillar)


class NFRMapping(BaseModel):
    """Maps one non-functional requirement to the mechanism(s) and nodes that satisfy it."""
    nfr: str = Field(description="the NFR text, ideally measurable: e.g. '99.9% uptime SLA'")
    mechanism: str = Field(description="how this NFR is addressed: e.g. 'Multi-AZ RDS + ALB health checks'")
    node_ids: list[str] = Field(default_factory=list, description="blueprint node IDs implementing this mechanism")


class BPNode(BaseModel):
    id: str = Field(description="unique snake_case id")
    label: str = Field(description="human-readable component name")
    tech: str = Field("", description="technology for this node")
    cluster: str = Field("", description="id of the cluster this node belongs to")
    type: str = Field("", description="service|database|queue|cache|gateway|external|lb|cdn")


class BPCluster(BaseModel):
    id: str = Field(description="unique snake_case id")
    label: str = Field(description="tier / group name")
    tier: str = Field("", description="frontend|backend|data|infra|external|security")


class BPEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from", description="source node id")
    to: str = Field(description="target node id")
    label: str = Field("", description="operation or protocol label")
    protocol: str = Field("", description="HTTP|gRPC|AMQP|TCP|WebSocket|SQL|Redis")


class Blueprint(BaseModel):
    """A structured architecture blueprint."""
    audience: str = Field(
        "client",
        description="target reader for the diagram; default client for customer-facing architecture diagrams",
    )
    detail_level: str = Field(
        "architecture",
        description="architecture|engineering|code; default architecture hides implementation details",
    )
    layout_intent: str = Field(
        "left_to_right_pipeline",
        description="intended visual flow, e.g. left_to_right_pipeline or top_down_stack",
    )
    presentation_style: Literal["slide", "diagram"] = Field(
        "slide",
        description="slide (default): production output with the gradient hero "
                    "title band + caption + legend; diagram: body-only output, "
                    "ONLY when the user explicitly asks for a plain/raw diagram",
    )
    density: Literal["standard", "poster"] = Field(
        "standard",
        description="standard (default): client-facing slide with 12-18 nodes, "
                    "aggregating cross-cutting concerns. "
                    "poster: 25-40 nodes in 6-9 numbered sections across a 2-row grid — "
                    "use when the source document describes a large platform (15+ components, "
                    "5+ tiers) and full component coverage matters more than visual sparseness. "
                    "Pass density to the drawer so it calls plan_style_sizes(output='poster').",
    )
    slide_title: str = Field(
        "",
        description="large slide hero title; default to the system/product name when presentation_style=slide",
    )
    slide_kicker: str = Field(
        "",
        description="small hero kicker/subtitle above the slide title",
    )
    brand: str = Field(
        "",
        description="brand text shown in the slide top-right; omit when unknown",
    )
    diagram_title: str = Field(
        "",
        description="caption above the architecture panel inside a slide",
    )
    pattern: str = Field(description="microservices|monolith|serverless|event-driven|hybrid")
    pattern_rationale: str = Field("", description="2-3 sentences: why this architecture pattern fits these requirements")
    key_decisions: list[str] = Field(
        default_factory=list,
        description="3-6 concrete design decisions & trade-offs: data flow, scaling/performance, "
                    "availability/HA, security/auth, storage, integration — one sentence each",
    )
    c4_level: Literal["context", "container"] = Field(
        "container",
        description="C4 diagram level: container (default, full component view) or context (5-8 nodes, "
                    "system boundaries + external actors only — use for executive/client slide audience)",
    )
    pillar_coverage: Optional[PillarCoverage] = Field(
        default=None,
        description="Well-Architected Framework 6-pillar coverage; for each pillar list node IDs / "
                    "key decisions that address it, and any known gaps. Gaps are allowed when declared.",
    )
    nfr_mapping: list[NFRMapping] = Field(
        default_factory=list,
        description="Maps each NFR from the diagram brief to the mechanism and blueprint nodes that satisfy it. "
                    "Use measurable NFRs when possible (SLA %, RPO minutes, latency ms).",
    )
    nodes: list[BPNode] = Field(default_factory=list)
    clusters: list[BPCluster] = Field(default_factory=list)
    edges: list[BPEdge] = Field(default_factory=list)


@tool
def propose_diagram_brief(brief: DiagramBrief) -> str:
    """Record the diagram requirements brief before recommending a tech stack.

    This is not a human-approval gate. Use it after reading the user's prompt and
    any attached documents, before propose_tech_stack. It captures objective,
    stakeholders, requirements, constraints, and assumptions so later blueprint
    and rendering decisions stay grounded and simplification choices are explicit.
    """
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    _BRIEF_FILE.write_text(brief.model_dump_json(indent=2), encoding="utf-8")
    record_report_step(
        WORKSPACE,
        "propose_diagram_brief",
        summary=(
            f"Recorded diagram brief with {len(brief.functional_requirements)} functional "
            f"and {len(brief.non_functional_requirements)} non-functional requirements."
        ),
        data=brief.model_dump(),
    )
    return (
        "Diagram brief recorded. Next: propose the technology stack with "
        "propose_tech_stack."
    )


@tool
def propose_tech_stack(
    tech_stack: list[TechChoice],
    assumptions: Optional[SolutionAssumptions] = None,
    scaling_roadmap: Optional[list[ScalingPhase]] = None,
    estimated_total_monthly_cost_usd: Optional[CostRange] = None,
) -> str:
    """Propose the technology stack for the user to review and approve.

    `tech_stack` is a LIST of layers, each an object with layer, choice, rationale,
    cost_tier, decision_criteria, alternatives, estimated_monthly_cost_usd,
    capacity_sizing, performance_target, risks.

    Core layers (always consider): frontend, backend, database, auth, infra,
    monitoring, networking, security.
    Conditional layers (add when requirements call for it): cache, queue, cdn,
    search, storage, ci_cd, analytics, ai_ml, integration.

    `assumptions` captures the sizing basis (budget, user scale, data, team,
    availability, compliance) BEFORE listing tech choices — state assumptions
    explicitly, put unconfirmed ones in confirm_with_customer.

    `scaling_roadmap` is a 2-3 phase roadmap with measurable triggers.
    `estimated_total_monthly_cost_usd` is the sum across all layers.

    This PAUSES for human approval — only call it once you have analysed the
    requirements. If rejected you get the user's note — revise and propose again.
    """
    if not _BRIEF_FILE.exists():
        return "Create the diagram brief first by calling propose_diagram_brief."
    WORKSPACE.mkdir(parents=True, exist_ok=True)

    layers_dict = {
        t.layer: {
            "choice": t.choice,
            "rationale": t.rationale,
            "cost_tier": t.cost_tier,
            "decision_criteria": t.decision_criteria.model_dump() if t.decision_criteria else None,
            "alternatives": [
                a.model_dump() if isinstance(a, TechAlternative) else {"name": str(a), "why_rejected": ""}
                for a in t.alternatives
            ],
            "estimated_monthly_cost_usd": t.estimated_monthly_cost_usd.model_dump() if t.estimated_monthly_cost_usd else None,
            "capacity_sizing": t.capacity_sizing,
            "performance_target": t.performance_target,
            "risks": [r.model_dump() if isinstance(r, TechRisk) else r for r in t.risks],
        }
        for t in tech_stack
    }

    as_dict: dict = {
        "assumptions": assumptions.model_dump() if assumptions else None,
        "layers": layers_dict,
        "scaling_roadmap": [p.model_dump() if isinstance(p, ScalingPhase) else p for p in (scaling_roadmap or [])],
        "estimated_total_monthly_cost_usd": estimated_total_monthly_cost_usd.model_dump() if estimated_total_monthly_cost_usd else None,
    }

    warnings: list[str] = []

    if not assumptions:
        warnings.append(
            "No sizing assumptions recorded — a senior proposal states budget, user scale, and concurrency explicitly."
        )
    elif not assumptions.confirm_with_customer:
        warnings.append(
            "confirm_with_customer is empty — list every assumption that has NOT been validated by the customer."
        )

    layers_without_cost = [t.layer for t in tech_stack if not t.estimated_monthly_cost_usd]
    if layers_without_cost:
        warnings.append(f"Layers missing cost estimate: {', '.join(layers_without_cost)}.")

    if estimated_total_monthly_cost_usd and assumptions and assumptions.monthly_budget_range_usd:
        budget_max = assumptions.monthly_budget_range_usd.max_usd
        if estimated_total_monthly_cost_usd.max_usd > budget_max:
            warnings.append(
                f"Total cost ceiling ${estimated_total_monthly_cost_usd.max_usd}/mo exceeds budget "
                f"${budget_max}/mo — adjust design or re-scope."
            )

    if estimated_total_monthly_cost_usd:
        layer_min_sum = sum(
            t.estimated_monthly_cost_usd.min_usd for t in tech_stack if t.estimated_monthly_cost_usd
        )
        if layer_min_sum > estimated_total_monthly_cost_usd.max_usd:
            warnings.append(
                f"Sum of layer minimums (${layer_min_sum}/mo) exceeds stated total maximum "
                f"(${estimated_total_monthly_cost_usd.max_usd}/mo) — cost estimates are inconsistent."
            )

    analysis_file = WORKSPACE / "architecture_analysis.json"
    if analysis_file.exists():
        try:
            import json as _json
            analysis = _json.loads(analysis_file.read_text(encoding="utf-8"))
            sec_level = (analysis.get("security_level") or "").lower()
            layer_names = {t.layer for t in tech_stack}
            if sec_level in ("high", "critical"):
                for required in ("security", "networking"):
                    if required not in layer_names:
                        warnings.append(
                            f"security_level is '{sec_level}' but layer '{required}' is missing — "
                            "add it or document why it's omitted."
                        )
        except Exception:
            pass

    _TECHSTACK_FILE.write_text(json.dumps(as_dict, indent=2), encoding="utf-8")
    record_report_step(
        WORKSPACE,
        "propose_tech_stack",
        summary=f"Approved technology stack covering {len(layers_dict)} layer(s).",
        data=as_dict,
    )

    result = (
        "Tech stack APPROVED. Next: design the architecture and call "
        "propose_blueprint with the components, clusters and connections."
    )
    if warnings:
        result += "\n\nSoft warnings (informational — does not block):\n" + "\n".join(f"• {w}" for w in warnings)
    return result


def _req_soft_match(requirement: str, candidates: list[str]) -> bool:
    """Return True if any candidate substring-matches the requirement text (case-insensitive)."""
    req_norm = requirement.lower().replace("-", " ").replace("_", " ")
    for c in candidates:
        c_norm = c.lower().replace("-", " ").replace("_", " ")
        terms = [t for t in c_norm.split() if len(t) > 3]
        if terms and any(t in req_norm for t in terms):
            return True
    return False


def _validate_pillar_coverage(blueprint: Blueprint) -> list[str]:
    """Return warning strings for pillars with no addressed_by AND no gaps declared."""
    if blueprint.pillar_coverage is None:
        return ["pillar_coverage not provided — add Well-Architected pillar coverage to the blueprint."]
    warnings: list[str] = []
    coverage = blueprint.pillar_coverage
    for pillar_name in ("operational_excellence", "security", "reliability",
                        "performance_efficiency", "cost_optimization", "sustainability"):
        pillar = getattr(coverage, pillar_name)
        if not pillar.addressed_by and not pillar.gaps:
            warnings.append(
                f"Pillar '{pillar_name}': no addressed_by nodes and no declared gaps — "
                "populate addressed_by with node IDs / decisions, or add a gap with explanation."
            )
    return warnings


def _validate_nfr_mapping(blueprint: Blueprint) -> list[str]:
    """Return unmapped NFRs: NFRs in the brief that have no entry in blueprint.nfr_mapping."""
    if not _BRIEF_FILE.exists():
        return []
    try:
        brief_data = json.loads(_BRIEF_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    brief_nfrs: list[str] = brief_data.get("non_functional_requirements", [])
    if not brief_nfrs:
        return []
    mapped_nfrs = [m.nfr for m in blueprint.nfr_mapping]
    unmapped = [
        nfr for nfr in brief_nfrs
        if not _req_soft_match(nfr, mapped_nfrs)
    ]
    return unmapped


def _validate_req_coverage(blueprint: Blueprint) -> tuple[int, int, list[str]]:
    """Return (covered_count, total_count, list_of_uncovered) for functional requirements."""
    if not _BRIEF_FILE.exists():
        return 0, 0, []
    try:
        brief_data = json.loads(_BRIEF_FILE.read_text(encoding="utf-8"))
    except Exception:
        return 0, 0, []
    func_reqs: list[str] = brief_data.get("functional_requirements", [])
    if not func_reqs:
        return 0, 0, []
    # Candidates: node labels, node IDs, cluster labels, key decisions
    candidates: list[str] = []
    for node in blueprint.nodes:
        if node.label:
            candidates.append(node.label)
        if node.id:
            candidates.append(node.id)
    for cluster in blueprint.clusters:
        if cluster.label:
            candidates.append(cluster.label)
    candidates.extend(blueprint.key_decisions)
    covered = [req for req in func_reqs if _req_soft_match(req, candidates)]
    uncovered = [req for req in func_reqs if not _req_soft_match(req, candidates)]
    return len(covered), len(func_reqs), uncovered


@tool
def propose_blueprint(blueprint: Blueprint) -> str:
    """Propose the architecture blueprint for the user to review and approve.

    PAUSES for human approval. Call this AFTER the tech stack is approved.
    Runs deterministic validators for Well-Architected pillar coverage, NFR mapping,
    and functional requirements coverage — warnings are surfaced but do NOT block approval.
    """
    if not _TECHSTACK_FILE.exists():
        return "Get the tech stack approved first by calling propose_tech_stack."
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    _BLUEPRINT_FILE.write_text(
        blueprint.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
    )

    # --- deterministic validators (warnings only, do not block) ---
    warnings: list[str] = []

    pillar_warns = _validate_pillar_coverage(blueprint)
    if pillar_warns:
        warnings.extend(pillar_warns)

    unmapped_nfrs = _validate_nfr_mapping(blueprint)
    if unmapped_nfrs:
        warnings.append(
            f"NFR mapping: {len(unmapped_nfrs)} NFR(s) from the brief have no nfr_mapping entry: "
            + ", ".join(f'"{n}"' for n in unmapped_nfrs[:5])
        )

    covered, total, uncovered_reqs = _validate_req_coverage(blueprint)
    coverage_line = ""
    if total > 0:
        coverage_pct = round(100 * covered / total)
        coverage_line = f"Coverage: {covered}/{total} functional requirements ({coverage_pct}%)"
        if uncovered_reqs:
            coverage_line += " — missing: " + "; ".join(f'"{r}"' for r in uncovered_reqs[:5])

    record_report_step(
        WORKSPACE,
        "propose_blueprint",
        summary=(
            f"Approved {blueprint.pattern} blueprint with {len(blueprint.nodes)} nodes, "
            f"{len(blueprint.clusters)} clusters, and {len(blueprint.edges)} edges."
            + (f" {coverage_line}." if coverage_line else "")
        ),
        data=blueprint.model_dump(by_alias=True),
    )
    reset_render_count()
    _reset_revision_count()

    result_parts = [
        "Blueprint APPROVED. Next: write the diagram code, call render_diagram, "
        "look at the PNG and refine, call export_drawio, then finalize_diagram.",
    ]
    if coverage_line:
        result_parts.append(coverage_line)
    if warnings:
        result_parts.append(
            "Architect warnings (address before finalizing if possible):\n"
            + "\n".join(f"  ⚠ {w}" for w in warnings)
        )
    return "\n\n".join(result_parts)


# ---------------------------------------------------------------------------
# Critic subagent tools (read-only review of the rendered diagram).
# The critic LOOKS at the already-rendered out.png (it does NOT re-render) and
# files a small set of concrete findings. Keeps the main agent context lean:
# the image only enters the critic's context, never the main agent's.
# ---------------------------------------------------------------------------

@tool
def inspect_diagram(tool_call_id: Annotated[str, InjectedToolCallId]) -> ToolMessage:
    """Load the LAST rendered diagram (out.png) plus its layout audit to review it.

    Read-only — this does NOT render. Returns the rendered PNG so you can LOOK at
    it and the objective layout audit (page aspect ratio + label-bearing edges
    that strand). Call this once, then judge the diagram against the blueprint.
    """
    png = WORKSPACE / "out.png"
    if not png.exists():
        return ToolMessage(
            content="No rendered diagram (out.png) to inspect yet.",
            name="inspect_diagram",
            tool_call_id=tool_call_id,
            status="error",
        )
    b64, mime = _inspection_image_b64(png)
    audit = _layout_audit()
    text = "Here is the rendered diagram to review."
    if audit:
        text += "\n\nObjective layout audit (read this FIRST):\n" + audit
    return ToolMessage(
        content_blocks=[
            {"type": "text", "text": text},
            {"type": "image", "base64": b64, "mime_type": mime},
        ],
        name="inspect_diagram",
        tool_call_id=tool_call_id,
        status="success",
    )


@tool
def submit_critique(findings: list[DiagramFinding]) -> str:
    """Record your diagram review as a list of concrete findings and get the verdict.

    Pass an empty list if the diagram is clean. Each finding is
    `{severity, confidence, category, title, detail, fix_suggestion?, in_blueprint?}`.
    Findings are ranked and capped; the returned text starts with
    `VERDICT: PASS` or `VERDICT: REVISE`. Return that verdict text verbatim as your
    final answer so the architect can act on it.
    """
    kept = prune(findings)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    _CRITIQUE_FILE.write_text(
        json.dumps([f.model_dump() for f in kept], indent=2), encoding="utf-8"
    )
    critique_data = [f.model_dump() for f in kept]
    if verdict_for(kept) == "revise":
        state = _read_json_file(_REVISION_COUNT_FILE, {"count": 0})
        count = int(state.get("count", 0)) + 1
        _write_json_file(_REVISION_COUNT_FILE, {"count": count})
        _bump_tool_summary("submit_critique", critic_revisions=count)
        if count > CRITIC_REVISION_HARD_CAP:
            base = format_critique(kept)
            return (
                f"VERDICT: PASS (revision limit reached: {CRITIC_REVISION_HARD_CAP} "
                "drawer revision rounds already used — proceed to finalize and "
                "mention residual findings)\n"
                + "\n".join(base.splitlines()[1:])
            )
        reset_render_count()  # a revision round gets a fresh render/search budget
    else:
        _bump_tool_summary("submit_critique")
    verdict_text = format_critique(kept)
    record_report_step(
        WORKSPACE,
        "submit_critique",
        status="revise" if verdict_for(kept) == "revise" else "passed",
        summary=verdict_text.splitlines()[0] if verdict_text else "Critic review completed.",
        data={"findings": critique_data},
    )
    return verdict_text


@tool
def finalize_diagram() -> str:
    """Submit the rendered diagram for the user's final review and approval.

    PAUSES for human review. Call this only AFTER render_diagram succeeded and
    export_drawio produced out.drawio.
    """
    if not (WORKSPACE / "out.png").exists():
        return "No rendered diagram yet — call render_diagram (and export_drawio) first."
    record_report_step(
        WORKSPACE,
        "finalize_diagram",
        summary="Diagram finalized and approved by the user.",
        data={"artifacts": record_artifact_inventory(WORKSPACE)},
    )
    return "Diagram finalized and approved by the user."


class PdfReportConfig(BaseModel):
    title: str = Field("", description="Override PDF cover title; defaults to blueprint.slide_title")
    subtitle: str = Field("", description="Cover subtitle/kicker")
    brand: str = Field("", description="Brand name shown on cover; defaults to blueprint.brand")
    include_sections: list[str] = Field(
        default_factory=lambda: DEFAULT_REPORT_SECTIONS.copy(),
        description="Ordered list of sections to include",
    )

@tool(args_schema=PdfReportConfig)
def generate_pdf_report(
    title: str = "",
    subtitle: str = "",
    brand: str = "",
    include_sections: list[str] | None = None,
) -> str:
    """Generate a client-ready HTML + PDF report from approved artifacts.

    Reads the staged architecture artifacts and report_evidence.json, renders
    out.report.html, then renders out.pdf with Playwright Chromium. Call this
    AFTER finalize_diagram is approved.
    """
    try:
        html_path, pdf_path, sections = generate_report(
            WORKSPACE,
            title=title,
            subtitle=subtitle,
            brand=brand,
            include_sections=include_sections,
        )
    except FileNotFoundError as exc:
        return str(exc)
    except ReportRenderError as exc:
        return f"PDF report generation failed: {exc}"
    _bump_tool_summary("generate_pdf_report", pdf_pages=len(sections))
    return f"Wrote {pdf_path} and {html_path} ({len(sections)} sections)."

class GridSection(BaseModel):
    """One section (cluster) in a poster-mode grid row."""
    id: str = Field(description="snake_case id matching the g.cluster() id")
    label: str = Field(description="section label, e.g. '① Client / Access Layer'")
    anchor_node_id: str = Field(description="id of one node inside this section used as a spine anchor")


@tool
def declare_poster_grid(
    row1: list[GridSection],
    row2: list[GridSection],
) -> str:
    """Declare and validate the 2-row grid layout for a poster-mode diagram.

    Call this BEFORE writing prettygraph code when density='poster'.
    Pass the planned sections for row 1 (client-facing tiers) and row 2
    (platform tiers). Returns a ready-to-paste code skeleton with invisible
    spine edges and same_rank anchors.

    Rules enforced:
    - row1 must have 3-6 sections
    - row2 must have 2-5 sections
    - Each section must have a distinct anchor_node_id
    """
    errors: list[str] = []
    if not (3 <= len(row1) <= 6):
        errors.append(f"row1 has {len(row1)} sections; expected 3-6.")
    if not (2 <= len(row2) <= 5):
        errors.append(f"row2 has {len(row2)} sections; expected 2-5.")
    all_anchors = [s.anchor_node_id for s in row1 + row2]
    if len(all_anchors) != len(set(all_anchors)):
        seen: set[str] = set()
        dups = [a for a in all_anchors if a in seen or seen.add(a)]  # type: ignore[func-returns-value]
        errors.append(f"Duplicate anchor_node_ids: {dups}. Each section needs a unique anchor.")
    if errors:
        return json.dumps({"status": "INVALID", "errors": errors}, indent=2)

    anchors1 = [s.anchor_node_id for s in row1]
    anchors2 = [s.anchor_node_id for s in row2]
    n1, n2 = len(anchors1), len(anchors2)

    # One line for the script: Pretty.poster_grid() builds the spine, per-column
    # same_rank, and decorative cross-section edges from these anchor rows.
    call = f"g.poster_grid(\n    {anchors1!r},  # row 1\n    {anchors2!r},  # row 2\n)"

    sections_info = {
        "row1": [{"id": s.id, "label": s.label, "anchor": s.anchor_node_id} for s in row1],
        "row2": [{"id": s.id, "label": s.label, "anchor": s.anchor_node_id} for s in row2],
    }
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    (WORKSPACE / "poster_grid.json").write_text(json.dumps(sections_info, indent=2), encoding="utf-8")

    return json.dumps({
        "status": "OK",
        "columns": {"row1": n1, "row2": n2},
        "poster_grid_call": call,
        "instruction": (
            "Put this ONE call in your script AFTER all g.cluster()/g.box()/g.link() "
            "calls. Do NOT add manual invisible spine or same_rank lines — poster_grid "
            "generates them. Number each top-level g.cluster() with number=1, 2, ..."
        ),
    }, indent=2)


DIAGRAM_TOOLS = [
    analyze_architecture_requirements,
    propose_diagram_brief,
    propose_tech_stack,
    propose_blueprint,
    audit_diagram_code,
    render_diagram,
    export_drawio,
    search_diagrams_nodes,
    search_icons,
    resolve_icons,
    plan_style_sizes,
    fit_labels,
    declare_poster_grid,
    fetch_logo,
    inspect_diagram,
    submit_critique,
    finalize_diagram,
    generate_pdf_report,
]

# Main agent tools: gate/planning only — no rendering or icon search.
MAIN_TOOLS = [
    analyze_architecture_requirements,
    propose_diagram_brief,
    propose_tech_stack,
    propose_blueprint,
    finalize_diagram,
    generate_pdf_report,
]

# Drawer subagent tools: everything needed for the render-refine loop.
DRAWER_TOOLS = [search_diagrams_nodes, resolve_icons, search_icons, fetch_logo, plan_style_sizes, fit_labels, declare_poster_grid, audit_diagram_code, render_diagram, export_drawio]

# Critic subagent tools: read-only review of the rendered diagram.
CRITIC_TOOLS = [inspect_diagram, submit_critique]

# Tools that require human approval before they run (interrupt_on in agent.py).
GATE_TOOL_NAMES = [
    "propose_tech_stack",
    "propose_blueprint",
    "finalize_diagram",
    "generate_pdf_report",
]
