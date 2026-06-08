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
from typing import Annotated, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from pydantic import BaseModel, ConfigDict, Field

from .backends import LOCAL_ICONS, LOCAL_MANIFEST, WORKSPACE
from .findings import DiagramFinding, format_critique, prune

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
_OUT_NAMES = ("out.png", "out.dot", "out.drawio", "out.nodes.json")

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
            content=f"Render TIMED OUT after {RENDER_TIMEOUT_S}s. Simplify the diagram or fix infinite work.",
            name="render_diagram",
            tool_call_id=tool_call_id,
            status="error",
        )

    png = WORKSPACE / "out.png"
    if proc.returncode != 0 or not png.exists():
        err = (proc.stderr or proc.stdout or "").strip()
        return ToolMessage(
            content=f"Render FAILED (exit {proc.returncode}). Fix the code and retry.\n\n{err[-3000:]}",
            name="render_diagram",
            tool_call_id=tool_call_id,
            status="error",
        )

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
    return f"Wrote out.drawio ({out.stat().st_size} bytes)."


@tool
def search_icons(query: str, provider: Optional[str] = None) -> str:
    """Search the bundled icon pack for matching icon paths.

    Returns absolute `.png` paths to use in `Custom(label, "<path>")` when no
    built-in `diagrams` node fits. Optionally restrict to one `provider`
    (e.g. "aws", "azure", "gcp", "onprem", "k8s", "programming", "saas").
    """
    try:
        manifest = json.loads(Path(LOCAL_MANIFEST).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return f"Could not read icon manifest: {exc}"

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
                    if len(hits) >= 30:
                        break
    if not hits:
        return f"No icons matched '{query}'. Try fewer/broader terms or fetch_logo()."
    return "\n".join(hits)


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
    return format_critique(findings)


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
    render_diagram,
    export_drawio,
    search_icons,
    fetch_logo,
    inspect_diagram,
    submit_critique,
    finalize_diagram,
]

# Main agent tools: gate/planning only — no rendering or icon search.
MAIN_TOOLS = [propose_tech_stack, propose_blueprint, finalize_diagram]

# Drawer subagent tools: everything needed for the render-refine loop.
DRAWER_TOOLS = [search_icons, fetch_logo, render_diagram, export_drawio]

# Critic subagent tools: read-only review of the rendered diagram.
CRITIC_TOOLS = [inspect_diagram, submit_critique]

# Tools that require human approval before they run (interrupt_on in agent.py).
GATE_TOOL_NAMES = ["propose_tech_stack", "propose_blueprint", "finalize_diagram"]
