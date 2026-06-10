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
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Literal, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from pydantic import BaseModel, ConfigDict, Field

from .backends import LOCAL_ICONS, LOCAL_MANIFEST, WORKSPACE
from .findings import DiagramFinding, format_critique, prune
from .quality_logger import get_current_run

# Stage markers written under WORKSPACE so the staged tools can enforce order.
_TECHSTACK_FILE = WORKSPACE / "tech_stack.json"
_BLUEPRINT_FILE = WORKSPACE / "blueprint.json"
_CRITIQUE_FILE = WORKSPACE / "critique.json"


def clear_stage_markers() -> None:
    """Reset the staged-flow markers at the start of a fresh run."""
    for f in (_TECHSTACK_FILE, _BLUEPRINT_FILE, _CRITIQUE_FILE):
        if f.exists():
            f.unlink()

RENDER_TIMEOUT_S = 180
# Max width of the image handed BACK to the model to inspect. The full-resolution
# out.png is kept on disk for the user — this only shrinks the copy that goes into
# the conversation (it is re-sent every turn, so a smaller copy saves context).
INSPECT_MAX_WIDTH = 800

# out.* artifacts produced by a render, cleaned before each run.
_OUT_NAMES = ("out.png", "out.dot", "out.drawio", "out.nodes.json", "out.slide.json")

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
    _stage_helpers()
    for n in _OUT_NAMES:
        p = WORKSPACE / n
        if p.exists():
            p.unlink()
    (WORKSPACE / "diagram.py").write_text(code, encoding="utf-8")

    _qrun = get_current_run()
    _attempt = len(_qrun._renders) + 1 if _qrun else 1

    try:
        proc = subprocess.run(
            [sys.executable, "diagram.py"],
            cwd=str(WORKSPACE),
            capture_output=True,
            text=True,
            timeout=RENDER_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        err_msg = f"Render TIMED OUT after {RENDER_TIMEOUT_S}s. Simplify the diagram or fix infinite work."
        if _qrun:
            _qrun.render_attempt(_attempt, success=False, error="TIMEOUT")
        return ToolMessage(
            content=err_msg,
            name="render_diagram",
            tool_call_id=tool_call_id,
            status="error",
        )

    png = WORKSPACE / "out.png"
    if proc.returncode != 0 or not png.exists():
        err = (proc.stderr or proc.stdout or "").strip()
        if _qrun:
            _qrun.render_attempt(_attempt, success=False, error=err[-400:])
        return ToolMessage(
            content=f"Render FAILED (exit {proc.returncode}). Fix the code and retry.\n\n{err[-3000:]}",
            name="render_diagram",
            tool_call_id=tool_call_id,
            status="error",
        )

    if _qrun:
        _qrun.render_attempt(_attempt, success=True)
    b64, mime = _inspection_image_b64(png)
    audit = _layout_audit()
    text = "Rendered out.png successfully. Inspect it and refine if the layout is not clean."
    if audit:
        text += ("\n\n" + audit + "\n\nAct on any audit WARNING before finalizing "
                 "(re-render after fixing). A clean diagram is balanced (~1.3–2:1) "
                 "with every label-bearing edge short.")
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
    _qrun = get_current_run()
    if _qrun:
        _qrun.mcp_not_used("export_drawio")
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
    return f"Wrote out.drawio ({out.stat().st_size} bytes)."


@tool
async def validate_drawio_output() -> str:
    """Validate the exported out.drawio XML via the draw.io MCP service.

    Call this AFTER export_drawio() succeeds. The MCP service checks the XML
    for structural errors and returns a validation report. Requires the MCP
    server to be running (MCP_URL env var, default http://localhost:6002/mcp).
    If the server is unreachable the tool degrades gracefully and returns a
    warning — do NOT block the workflow on MCP unavailability.
    """
    out = WORKSPACE / "out.drawio"
    if not out.exists():
        return "No out.drawio found — call export_drawio first."
    xml = out.read_text(encoding="utf-8", errors="replace")
    _qrun = get_current_run()
    try:
        from .mcp_client import mcp_tools
        async with mcp_tools() as tools:
            validator = next((t for t in tools if "validate" in t.name.lower()), None)
            if validator is None:
                tool_names = [t.name for t in tools]
                if _qrun:
                    _qrun.mark_mcp_used(tool_names)
                return (
                    f"MCP connected (tools: {tool_names}) but no validate_drawio tool found. "
                    "Skipping validation."
                )
            result = await validator.ainvoke({"xml": xml})
            result_text = str(result)
            if _qrun:
                _qrun.mark_mcp_used([validator.name])
            return f"MCP validation result:\n{result_text}"
    except Exception as exc:
        if _qrun:
            _qrun.mcp_not_used("validate_drawio_output")
        return (
            f"MCP server unavailable ({exc.__class__.__name__}: {exc}) — "
            "skipping validation. The drawio file was produced by the local converter."
        )


@tool
def search_icons(query: str, provider: Optional[str] = None) -> str:
    """Search the bundled icon pack for matching icon paths.

    Returns absolute `.png` paths to use in `Custom(label, "<path>")` when no
    built-in `diagrams` node fits. Optionally restrict to one `provider`
    (e.g. "aws", "azure", "gcp", "onprem", "k8s", "programming", "saas").
    """
    hits = _search_icon_hits(query, provider)
    if not hits:
        return f"No icons matched '{query}'. Try fewer/broader terms or fetch_logo()."
    return "\n".join(hits)


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
    (WORKSPACE / "icon_plan.json").write_text(
        json.dumps(resolved, indent=2), encoding="utf-8"
    )
    return json.dumps(resolved, indent=2)


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


# ---------------------------------------------------------------------------
# MCP-based draw.io XML tools (new flow: generate XML → MCP render → out.drawio)
# ---------------------------------------------------------------------------

@tool
async def resolve_drawio_stencil(provider: str, keyword: str) -> str:
    """Resolve a native draw.io stencil style string for a cloud service icon.

    Returns the style string (e.g. 'shape=mxgraph.aws4.resourceIcon;resIcon=...')
    ready to paste into an mxCell style attribute, or 'NOT_FOUND: ...' if unavailable.
    provider: 'aws'|'azure'|'gcp'|'k8s'|'alibabacloud'|'ibm'|'network'|'cisco'
    keyword: short service name, e.g. 'ecs', 'load balancer', 'sql database'.
    """
    try:
        from .mcp_client import mcp_tools
        async with mcp_tools() as tools:
            t = next((x for x in tools if "resolve_stencil" in x.name.lower()), None)
            if t is None:
                return "NOT_FOUND: resolve_stencil tool unavailable on MCP server"
            result = str(await t.ainvoke({"provider": provider, "keyword": keyword}))
            for line in result.splitlines():
                if line.strip().startswith("style:"):
                    return line.split("style:", 1)[1].strip()
            if "no stencil found" in result.lower() or "not found" in result.lower():
                return f"NOT_FOUND: {result[:120]}"
            return result
    except Exception as exc:
        return f"NOT_FOUND: MCP unavailable ({exc.__class__.__name__}: {exc})"


@tool
async def search_drawio_stencils(query: str, provider: Optional[str] = None) -> str:
    """Fuzzy-search the stencil catalog for draw.io icon style strings.

    Use when resolve_drawio_stencil returns NOT_FOUND, or to discover available
    stencil names for a service area. Returns up to 10 matches.
    provider optionally restricts: 'aws', 'azure', 'gcp', 'k8s', etc.
    """
    try:
        from .mcp_client import mcp_tools
        async with mcp_tools() as tools:
            t = next((x for x in tools if "search_stencils" in x.name.lower()), None)
            if t is None:
                return "search_stencils tool unavailable on MCP server"
            args: dict = {"query": query, "limit": 10}
            if provider:
                args["provider"] = provider
            return str(await t.ainvoke(args))
    except Exception as exc:
        return f"MCP unavailable ({exc.__class__.__name__}: {exc})"


@tool
def embed_logo(name: str) -> str:
    """Fetch a brand logo and return it as a data URI for embedding in draw.io XML.

    Use for logos NOT in the stencil catalog (resolve_drawio_stencil returned NOT_FOUND).
    Returns 'data:image/png;base64,<b64>' — paste this directly into the mxCell style:
        style='shape=image;image=data:image/png;base64,<b64>;verticalLabelPosition=bottom;...'
    Returns NOT_FOUND if no logo is available.
    """
    try:
        from .logo_fetch import get_logo
        path = get_logo(name, LOCAL_ICONS, str(WORKSPACE))
    except Exception as exc:
        return f"NOT_FOUND: {exc}"
    if not path or path.startswith("NOT_FOUND"):
        return f"NOT_FOUND: no verified logo for '{name}'"
    b64 = base64.standard_b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


@tool
async def render_xml_preview(
    xml: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> ToolMessage:
    """Render mxGraphModel XML to PNG via the draw.io MCP service.

    Pass the COMPLETE mxGraphModel XML string. Writes out.png and out_draft.xml,
    then returns the PNG for inspection. Fix and re-call if layout is off (≤3 total).
    Call save_drawio(xml) once the diagram looks good — do NOT call it every render.
    """
    if not _BLUEPRINT_FILE.exists():
        return ToolMessage(
            content="Get the architecture approved first: call propose_tech_stack, "
                    "then propose_blueprint, before rendering.",
            name="render_xml_preview",
            tool_call_id=tool_call_id,
            status="error",
        )
    _qrun = get_current_run()
    _attempt = len(_qrun._renders) + 1 if _qrun else 1
    WORKSPACE.mkdir(parents=True, exist_ok=True)

    try:
        from .mcp_client import mcp_tools
        async with mcp_tools() as tools:
            renderer = next((x for x in tools if "render_drawio_png" in x.name.lower()), None)
            if renderer is None:
                if _qrun:
                    _qrun.render_attempt(_attempt, success=False, error="render_drawio_png tool not found")
                return ToolMessage(
                    content="render_drawio_png MCP tool not available.",
                    name="render_xml_preview",
                    tool_call_id=tool_call_id,
                    status="error",
                )
            result = str(await renderer.ainvoke({"xml": xml}))

        marker = "base64: data:image/png;base64,"
        if marker not in result:
            if _qrun:
                _qrun.render_attempt(_attempt, success=False, error=result[:200])
            return ToolMessage(
                content=f"Render FAILED:\n{result[:3000]}",
                name="render_xml_preview",
                tool_call_id=tool_call_id,
                status="error",
            )

        b64_data = result.split(marker, 1)[1].strip()
        png_bytes = base64.b64decode(b64_data)
        (WORKSPACE / "out.png").write_bytes(png_bytes)
        (WORKSPACE / "out_draft.xml").write_text(xml, encoding="utf-8")

        if _qrun:
            _qrun.render_attempt(_attempt, success=True)

        b64_inspect, mime = _inspection_image_b64(WORKSPACE / "out.png")
        return ToolMessage(
            content_blocks=[
                {"type": "text", "text": (
                    "Rendered out.png successfully. Inspect the image. "
                    "Refine the XML and call render_xml_preview again if needed (≤3 total), "
                    "then call save_drawio(xml) to finalize."
                )},
                {"type": "image", "base64": b64_inspect, "mime_type": mime},
            ],
            name="render_xml_preview",
            tool_call_id=tool_call_id,
            status="success",
        )
    except Exception as exc:
        if _qrun:
            _qrun.render_attempt(_attempt, success=False, error=str(exc)[:200])
        return ToolMessage(
            content=f"Render FAILED ({exc.__class__.__name__}): {exc}",
            name="render_xml_preview",
            tool_call_id=tool_call_id,
            status="error",
        )


@tool
async def save_drawio(xml: str) -> str:
    """Validate and save the final mxGraphModel XML as out.drawio + final out.png.

    Call this ONCE after render_xml_preview confirms the diagram looks good.
    Validates XML via MCP (auto-fixes minor issues), writes out.drawio, and
    re-renders out.png from the validated XML. Degrades gracefully if MCP is down.
    """
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    _qrun = get_current_run()
    final_xml = xml

    try:
        from .mcp_client import mcp_tools
        async with mcp_tools() as tools:
            validator = next((x for x in tools if "validate_drawio" in x.name.lower()), None)
            fix_report = "OK"
            if validator:
                val_text = str(await validator.ainvoke({"xml": xml}))
                if _qrun:
                    _qrun.mark_mcp_used([validator.name])
                if "Fixed XML:" in val_text:
                    final_xml = val_text.split("Fixed XML:", 1)[1].strip()
                    fix_report = val_text.split("Fixed XML:")[0].strip() or "auto-fixed"
                else:
                    fix_report = val_text.split("\n")[0][:80]

            (WORKSPACE / "out.drawio").write_text(final_xml, encoding="utf-8")

            renderer = next((x for x in tools if "render_drawio_png" in x.name.lower()), None)
            if renderer:
                render_text = str(await renderer.ainvoke({"xml": final_xml}))
                marker = "base64: data:image/png;base64,"
                if marker in render_text:
                    (WORKSPACE / "out.png").write_bytes(
                        base64.b64decode(render_text.split(marker, 1)[1].strip())
                    )

        size = (WORKSPACE / "out.drawio").stat().st_size
        return f"Saved out.drawio ({size} bytes) and updated out.png.\nValidation: {fix_report}"

    except Exception as exc:
        (WORKSPACE / "out.drawio").write_text(final_xml, encoding="utf-8")
        size = (WORKSPACE / "out.drawio").stat().st_size
        return (
            f"MCP unavailable ({exc.__class__.__name__}: {exc}) — "
            f"wrote out.drawio ({size} bytes) without validation."
        )


# ---------------------------------------------------------------------------
# Staged Human-in-the-loop tools (gated via interrupt_on in agent.py)
# Each call PAUSES for human review before it executes; the structured args
# become the card the frontend renders.
# ---------------------------------------------------------------------------

class TechChoice(BaseModel):
    """One layer of the recommended technology stack."""
    layer: str = Field(description="the layer name, one word: frontend|backend|database|cache|queue|auth|infra|monitoring|cdn|search")
    choice: str = Field(description="the specific technology chosen for this layer")
    rationale: str = Field("", description="1-2 sentence reason tied to the requirements")
    alternatives: list[str] = Field(default_factory=list, description="a couple of alternatives")


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
        "diagram",
        description="slide for production/presentation output; diagram for body-only output",
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
    nodes: list[BPNode] = Field(default_factory=list)
    clusters: list[BPCluster] = Field(default_factory=list)
    edges: list[BPEdge] = Field(default_factory=list)


@tool
def propose_tech_stack(tech_stack: list[TechChoice]) -> str:
    """Propose the technology stack for the user to review and approve.

    `tech_stack` is a LIST of layers, each an object
    {layer, choice, rationale, alternatives} — one entry per relevant layer
    (frontend, backend, database, cache, queue, auth, infra, monitoring, cdn,
    search…). This PAUSES for human approval — only call it once you have
    analysed the requirements.
    """
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    as_dict = {
        t.layer: {"choice": t.choice, "rationale": t.rationale, "alternatives": t.alternatives}
        for t in tech_stack
    }
    _TECHSTACK_FILE.write_text(json.dumps(as_dict, indent=2), encoding="utf-8")
    return (
        "Tech stack APPROVED. Next: design the architecture and call "
        "propose_blueprint with the components, clusters and connections."
    )


@tool
def propose_blueprint(blueprint: Blueprint) -> str:
    """Propose the architecture blueprint for the user to review and approve.

    PAUSES for human approval. Call this AFTER the tech stack is approved.
    """
    if not _TECHSTACK_FILE.exists():
        return "Get the tech stack approved first by calling propose_tech_stack."
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    _BLUEPRINT_FILE.write_text(
        blueprint.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
    )
    return (
        "Blueprint APPROVED. Next: write the diagram code, call render_diagram, "
        "look at the PNG and refine, call export_drawio, then finalize_diagram."
    )


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
    _qrun = get_current_run()
    if _qrun:
        _qrun.inspect_called(audit)
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
    result = format_critique(findings)
    _qrun = get_current_run()
    if _qrun:
        _qrun.critique_submitted(findings, result)
    return result


@tool
def finalize_diagram() -> str:
    """Submit the rendered diagram for the user's final review and approval.

    PAUSES for human review. Call this only AFTER render_diagram succeeded and
    export_drawio produced out.drawio.
    """
    if not (WORKSPACE / "out.png").exists():
        return "No rendered diagram yet — call render_diagram (and export_drawio) first."
    return "Diagram finalized and approved by the user."


DIAGRAM_TOOLS = [
    propose_tech_stack,
    propose_blueprint,
    resolve_drawio_stencil,
    search_drawio_stencils,
    embed_logo,
    render_xml_preview,
    save_drawio,
    inspect_diagram,
    submit_critique,
    finalize_diagram,
]

# Main agent tools: gate/planning only — no rendering or icon search.
MAIN_TOOLS = [propose_tech_stack, propose_blueprint, finalize_diagram]

# Drawer subagent tools: MCP-based XML generation flow.
DRAWER_TOOLS = [resolve_drawio_stencil, search_drawio_stencils, embed_logo,
                render_xml_preview, save_drawio]

# Critic subagent tools: read-only review of the rendered diagram.
CRITIC_TOOLS = [inspect_diagram, submit_critique]

# Tools that require human approval before they run (interrupt_on in agent.py).
GATE_TOOL_NAMES = ["propose_tech_stack", "propose_blueprint", "finalize_diagram"]
