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
import math
import re
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
_ICON_SEARCH_COUNTS_FILE = WORKSPACE / "icon_search_counts.json"


def clear_stage_markers() -> None:
    """Reset the staged-flow markers at the start of a fresh run."""
    for f in (_TECHSTACK_FILE, _BLUEPRINT_FILE, _CRITIQUE_FILE, _ICON_SEARCH_COUNTS_FILE):
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

def _strip_html_label(label: str) -> str:
    text = re.sub(r"<[^>]+>", " ", label or "")
    return " ".join(text.replace("\\n", " ").split())


def _cluster_nesting(dot_text: str) -> dict[str, str | None]:
    """Best-effort parent map for `subgraph cluster_*` nesting in DOT."""
    parents: dict[str, str | None] = {}
    stack: list[str] = []
    for raw in dot_text.splitlines():
        line = raw.strip()
        m = re.match(r"subgraph\s+cluster_([A-Za-z0-9_.:-]+)\s*\{", line)
        if m:
            cid = m.group(1)
            parents[cid] = stack[-1] if stack else None
            stack.append(cid)
            continue
        if line == "}" and stack:
            stack.pop()
    return parents


def _visual_lint() -> str:
    """Deterministic presentation lint for production-grade diagrams."""
    dot = WORKSPACE / "out.dot"
    sidecar = WORKSPACE / "out.nodes.json"
    if not dot.exists():
        return ""

    try:
        dot_text = dot.read_text(encoding="utf-8", errors="replace")
        g = json.loads(subprocess.run(
            ["dot", "-Tjson", str(dot)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout)
    except Exception:  # noqa: BLE001
        return ""

    blockers: list[str] = []
    warnings: list[str] = []

    try:
        x0, y0, x1, y1 = (float(v) for v in g["bb"].split(","))
        width = max(x1 - x0, 1.0)
        height = max(y1 - y0, 1.0)
        aspect = width / height
        if aspect > 2.6:
            blockers.append(
                f"layout is too wide ({aspect:.2f}:1); fold tiers into sibling rows/columns"
            )
        elif aspect > 2.2:
            warnings.append(
                f"layout is wide ({aspect:.2f}:1); target ~1.4:1 to 2.0:1"
            )
    except Exception:  # noqa: BLE001
        width = height = 1.0

    side: dict = {}
    if sidecar.exists():
        try:
            side = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            side = {}

    for nid, meta in (side.get("nodes") or {}).items():
        label = " ".join(str(meta.get("label") or "").split())
        sublabel = " ".join(str(meta.get("sublabel") or "").split())
        if not label and not sublabel:
            blockers.append(f"empty visible node '{nid}' appears in the diagram")

    if not side:
        for obj in g.get("objects", []):
            name = obj.get("name", "")
            if name.startswith("cluster"):
                continue
            if obj.get("pos") and not _strip_html_label(str(obj.get("label", ""))):
                blockers.append(f"empty visible node '{name}' appears in the diagram")

    clusters = side.get("clusters") or {}
    parents = _cluster_nesting(dot_text)

    def _cluster_name(cid: str) -> str:
        meta = clusters.get(cid, {})
        return f"{cid} {meta.get('label', '')}".lower()

    for cid in parents:
        cname = _cluster_name(cid)
        if not any(term in cname for term in ("data", "database", "db")):
            continue
        parent = parents.get(cid)
        while parent:
            pname = _cluster_name(parent)
            if any(term in pname for term in ("application", "app", "compute")):
                blockers.append(
                    f"data cluster '{cid}' is nested inside application cluster '{parent}'"
                )
                break
            parent = parents.get(parent)

    pos: dict[int, tuple[float, float]] = {}
    for obj in g.get("objects", []):
        if obj.get("pos"):
            try:
                x, y = (float(v) for v in obj["pos"].split(","))
                pos[obj["_gvid"]] = (x, y)
            except Exception:  # noqa: BLE001
                pass
    diag = max((width * width + height * height) ** 0.5, 1.0)
    long_labels: list[str] = []
    for edge in g.get("edges", []):
        label = _strip_html_label(str(edge.get("label", "")))
        if not label:
            continue
        a = pos.get(edge.get("tail"))
        b = pos.get(edge.get("head"))
        if not a or not b:
            continue
        frac = (((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5) / diag
        if frac > 0.5:
            long_labels.append(f'"{label}" spans {frac:.0%} of canvas')
    if long_labels:
        warnings.append(
            "long labeled edges risk spaghetti/stranded labels: "
            + "; ".join(long_labels[:4])
        )

    edge_styles = {
        str(edge.get("style") or "solid")
        for edge in g.get("edges", [])
        if str(edge.get("style") or "solid") != "invis"
    }
    has_legend = any(
        "legend" in str(meta.get("label", "")).lower()
        for meta in (side.get("nodes") or {}).values()
    ) or "legend" in dot_text.lower()
    if len(edge_styles) > 1 and not has_legend:
        warnings.append(
            "mixed edge styles are used without a Legend explaining solid/dashed/dotted lines"
        )

    if not blockers and not warnings:
        return "Visual lint: PASS - no deterministic presentation issues found."

    lines = ["Visual lint:"]
    if blockers:
        lines.append("  BLOCKERS:")
        lines += [f"    - {item}" for item in blockers[:6]]
    if warnings:
        lines.append("  WARNINGS:")
        lines += [f"    - {item}" for item in warnings[:6]]
    lines.append(
        "  Fix blockers before finalize; address warnings unless the approved blueprint forces them."
    )
    return "\n".join(lines)


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
    visual = _visual_lint()
    text = "Rendered out.png successfully. Inspect it and refine if the layout is not clean."
    if audit:
        text += ("\n\n" + audit + "\n\nAct on any audit WARNING before finalizing "
                 "(re-render after fixing). A clean diagram is balanced (~1.3–2:1) "
                 "with every label-bearing edge short.")
    if visual:
        text += (
            "\n\n"
            + visual
            + "\n\nProduction presentation rules: remove empty shapes, keep Data "
            "as a sibling tier (not nested in Application), number orchestration "
            "flows, aggregate observability lines, and add a Legend when multiple "
            "edge styles are used."
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
    """Search the bundled icon pack with BM25-ranked product keywords.

    Returns absolute `.png` paths to use in `Custom(label, "<path>")` when no
    built-in `diagrams` node fits. Optionally restrict to one `provider`
    (e.g. "aws", "azure", "gcp", "onprem", "k8s", "programming", "saas").
    Use icon-pack style keywords, not full marketing labels:
    "AWS App Runner" -> "app runner", "Amazon Aurora PostgreSQL Server" -> "aurora".
    """
    try:
        manifest = json.loads(Path(LOCAL_MANIFEST).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return f"Could not read icon manifest: {exc}"

    canonical = _canonical_icon_keyword(query, provider)
    count = _record_icon_search(canonical, provider)
    if count > 3:
        return (
            f"SEARCH_LIMIT_REACHED: '{canonical}'"
            f"{f' provider={provider}' if provider else ''} was searched {count} times. "
            "Stop searching this icon; use the best prior result, broaden once under a "
            "different query, or omit icon=."
        )

    hits = _icon_hits(manifest, query, provider=provider, limit=12)
    if not hits:
        return (
            f"No icons matched '{query}' (keyword tried: '{canonical}'). "
            "Try a shorter filename-style keyword or fetch_logo()."
        )
    return (
        f"Search attempt {count}/3 for keyword '{canonical}' "
        f"(from query '{query}').\n"
        + "\n".join(hits)
    )


def _record_icon_search(query: str, provider: Optional[str]) -> int:
    """Track repeated searches so one icon cannot consume unbounded tool calls."""
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    provider_key = (provider or "*").strip().lower()
    query_key = " ".join(query.lower().replace("-", " ").replace("_", " ").split())
    key = f"{provider_key}:{query_key}"
    try:
        counts = json.loads(_ICON_SEARCH_COUNTS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        counts = {}
    counts[key] = int(counts.get(key, 0)) + 1
    _ICON_SEARCH_COUNTS_FILE.write_text(json.dumps(counts, indent=2), encoding="utf-8")
    return counts[key]


def _icon_hits(
    manifest: dict,
    query: str,
    *,
    provider: Optional[str] = None,
    limit: int = 10,
) -> list[str]:
    """Return ranked icon paths for one query from an already-loaded manifest."""
    for terms in _icon_keyword_variants(query, provider):
        hits = _rank_icon_hits(manifest, terms, provider=provider, limit=limit)
        if hits:
            return hits
    return []


_ICON_PROVIDER_TERMS = {
    "amazon",
    "aws",
    "azure",
    "cloud",
    "gcp",
    "google",
    "microsoft",
}

_ICON_NOISE_TERMS = {
    "compatible",
    "for",
    "managed",
    "postgres",
    "postgresql",
    "server",
    "serverless",
}

_ICON_PHRASE_ALIASES = {
    "amazon aurora": "aurora",
    "amazon aurora postgresql server": "aurora",
    "application load balancer": "elb application load balancer",
    "app service": "app services",
    "app services": "app services",
    "aurora postgresql": "aurora",
    "aurora postgresql server": "aurora",
    "cloud load balancing": "load balancing",
    "cloud pub sub": "pubsub",
    "cloud run": "run",
    "cloud sql": "sql",
    "container app": "container apps",
    "cosmos db": "cosmos db",
    "ecs": "elastic container service",
    "ecs fargate": "fargate",
    "elastic container service": "elastic container service",
    "entra id": "entra",
    "load balancer": "load balancing",
    "network load balancer": "elb network load balancer",
    "pub sub": "pubsub",
    "rds aurora": "aurora",
    "route53": "route 53",
}

_ICON_TOKEN_ALIASES = {
    "apigateway": ["api", "gateway"],
    "cloudsql": ["sql"],
    "cloudfront": ["cloudfront"],
    "dynamodb": ["dynamodb"],
    "eventbridge": ["eventbridge"],
    "opensearch": ["opensearch"],
    "route53": ["route", "53"],
}


def _tokenize_icon_query(query: str) -> list[str]:
    return [
        t
        for t in query.lower().replace("-", " ").replace("_", " ").replace("/", " ").split()
        if t
    ]


def _terms_from_phrase(phrase: str) -> list[str]:
    return _tokenize_icon_query(phrase)


def _alias_terms(terms: list[str]) -> list[str] | None:
    phrase = " ".join(terms)
    if phrase in _ICON_PHRASE_ALIASES:
        return _terms_from_phrase(_ICON_PHRASE_ALIASES[phrase])
    if len(terms) == 1 and terms[0] in _ICON_TOKEN_ALIASES:
        return _ICON_TOKEN_ALIASES[terms[0]]
    return None


def _icon_keyword_variants(query: str, provider: Optional[str]) -> list[list[str]]:
    raw = _tokenize_icon_query(query)
    if not raw:
        return []

    stripped = [t for t in raw if t not in _ICON_PROVIDER_TERMS]
    relaxed = [t for t in stripped if t not in _ICON_NOISE_TERMS]

    variants: list[list[str]] = []
    for candidate in (
        _alias_terms(stripped),
        _alias_terms(raw),
        relaxed,
        stripped,
        raw,
    ):
        if candidate:
            variants.append(candidate)

    # Provider-specific filename dialects.
    provider_l = provider.lower() if provider else ""
    phrase = " ".join(stripped)
    if provider_l == "aws" and phrase == "load balancer":
        variants.insert(0, ["elastic", "load", "balancing"])
    elif provider_l == "azure" and phrase == "load balancer":
        variants.insert(0, ["load", "balancers"])
    elif provider_l == "gcp" and phrase == "load balancer":
        variants.insert(0, ["load", "balancing"])

    deduped: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for item in variants:
        key = tuple(item)
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _canonical_icon_keyword(query: str, provider: Optional[str]) -> str:
    variants = _icon_keyword_variants(query, provider)
    if not variants:
        return " ".join(_tokenize_icon_query(query))
    return " ".join(variants[0])


def _rank_icon_hits(
    manifest: dict,
    terms: list[str],
    *,
    provider: Optional[str],
    limit: int,
) -> list[str]:
    root = Path(LOCAL_ICONS)
    provider_l = provider.lower() if provider else None
    query_terms = [t for t in terms if t]
    if not query_terms:
        return []

    docs: list[tuple[str, str, str, list[str], str]] = []

    for prov, cats in manifest.get("providers", {}).items():
        if provider_l and prov.lower() != provider_l:
            continue
        for cat, names in cats.items():
            for name in names:
                sub = name if cat == "_root" else f"{cat}/{name}"
                path = str(root / prov / f"{sub}.png")
                name_terms = _tokenize_icon_query(name)
                cat_terms = _tokenize_icon_query(cat)
                prov_terms = _tokenize_icon_query(prov)
                tokens = (name_terms * 4) + (cat_terms * 2) + prov_terms
                normalized_name = " ".join(name_terms)
                docs.append((path, normalized_name, cat.lower(), tokens, name))

    if not docs:
        return []

    n_docs = len(docs)
    avg_len = sum(len(tokens) for *_prefix, tokens, _name in docs) / max(n_docs, 1)
    dfs: dict[str, int] = {}
    for term in query_terms:
        dfs[term] = sum(1 for *_prefix, tokens, _name in docs if term in set(tokens))

    k1 = 1.4
    b = 0.75
    query_phrase = " ".join(query_terms)
    significant_terms = [
        term
        for term in query_terms
        if term not in _ICON_NOISE_TERMS and term not in _ICON_PROVIDER_TERMS
    ]
    scored: list[tuple[float, str]] = []

    for path, normalized_name, cat, tokens, raw_name in docs:
        token_counts = {t: tokens.count(t) for t in set(tokens)}
        doc_len = max(len(tokens), 1)
        score = 0.0
        matched_terms = 0
        matched_significant_terms = 0

        for term in query_terms:
            tf = token_counts.get(term, 0)
            if tf <= 0:
                continue
            matched_terms += 1
            if term in significant_terms:
                matched_significant_terms += 1
            df = max(dfs.get(term, 0), 1)
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            denom = tf + k1 * (1 - b + b * doc_len / max(avg_len, 1))
            score += idf * (tf * (k1 + 1)) / denom

        if matched_terms == 0:
            continue
        if significant_terms and matched_significant_terms == 0:
            continue

        # Deterministic boosts keep exact icon filename matches above broad BM25 hits.
        if normalized_name == query_phrase:
            score += 8.0
        elif all(term in normalized_name.split() for term in query_terms):
            score += 4.0
        elif query_phrase in normalized_name:
            score += 3.0
        if any(term in cat for term in query_terms):
            score += 0.8
        if provider_l:
            score += 0.5

        scored.append((score, path))

    return [
        path
        for _, path in sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]
    ]


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
    return path or f"NOT_FOUND: no verified logo for '{name}'. Use a built-in node or omit icon=."


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
    visual = _visual_lint()
    text = "Here is the rendered diagram to review."
    if audit:
        text += "\n\nObjective layout audit (read this FIRST):\n" + audit
    if visual:
        text += "\n\nDeterministic visual lint (read this too):\n" + visual
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
    visual = _visual_lint()
    if "BLOCKERS:" in visual:
        return (
            "Visual lint BLOCKED finalize. Send these findings back to the drawer, "
            "re-render, re-export drawio, and re-run the critic before final review.\n\n"
            + visual
        )
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
