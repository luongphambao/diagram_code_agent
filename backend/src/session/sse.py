"""Text/JSON extraction and SSE event formatting for the chat activity stream."""

from __future__ import annotations

import json

from domain.reporting.reporting import DEFAULT_REPORT_SECTIONS

from .labels import _display_subagent


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for p in content:
            if isinstance(p, str):
                out.append(p)
            elif isinstance(p, dict) and ("text" in p or p.get("type") in ("text", "output_text")):
                out.append(p.get("text", ""))
        return "".join(out)
    return ""


def _compact_json(value, *, limit: int = 260) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False)
    except Exception:
        text = str(value)
    text = " ".join(text.split())
    return text[:limit] + ("..." if len(text) > limit else "")


def _tool_detail(tool: str, args: dict | None, *, limit: int = 260) -> str:
    """Summarize tool input for UI logs without dumping huge code/prompts."""
    if not isinstance(args, dict) or not args:
        return ""
    if tool == "task":
        sa = args.get("subagent_type") or args.get("subagent") or args.get("name") or "unknown"
        desc = " ".join(str(args.get("description") or args.get("instruction") or args.get("prompt") or "").split())
        return f"{_display_subagent(sa)}: {desc[:180]}{'...' if len(desc) > 180 else ''}"
    if tool == "render_diagram":
        code = str(args.get("code") or "")
        return f"diagram.py code={len(code)} chars"
    if tool == "audit_diagram_code":
        code = str(args.get("code") or "")
        return f"diagram.py code={len(code)} chars"
    if tool == "search_icons":
        provider = args.get("provider")
        return f"query={args.get('query', '')}" + (f", provider={provider}" if provider else "")
    if tool == "search_diagrams_nodes":
        provider = args.get("provider")
        category = args.get("category")
        bits = [f"query={args.get('query', '')}"]
        if provider:
            bits.append(f"provider={provider}")
        if category:
            bits.append(f"category={category}")
        return ", ".join(bits)
    if tool == "analyze_architecture_requirements":
        req = " ".join(str(args.get("requirements", "")).split())
        provider = args.get("provider_preference")
        suffix = f", provider={provider}" if provider else ""
        return f"requirements={req[:160]}{'...' if len(req) > 160 else ''}{suffix}"
    if tool == "resolve_icons":
        icons = args.get("icons") or []
        if isinstance(icons, list):
            labels = [str(x.get("label", "")) for x in icons if isinstance(x, dict)]
            return f"{len(icons)} icons: {', '.join([x for x in labels if x][:8])}"
    if tool == "fetch_logo":
        return f"name={args.get('name', '')}"
    if tool == "propose_blueprint":
        bp = args.get("blueprint") or {}
        if isinstance(bp, dict):
            return (
                f"{bp.get('audience', 'client')}/{bp.get('detail_level', 'architecture')} "
                f"style={bp.get('presentation_style', 'diagram')}, "
                f"pattern={bp.get('pattern', '')}, nodes={len(bp.get('nodes') or [])}, "
                f"clusters={len(bp.get('clusters') or [])}, edges={len(bp.get('edges') or [])}"
            )
    if tool == "propose_diagram_brief":
        brief = args.get("brief") or {}
        if isinstance(brief, dict):
            return (
                f"objective={str(brief.get('objective', ''))[:80]}, "
                f"functional={len(brief.get('functional_requirements') or [])}, "
                f"nonfunctional={len(brief.get('non_functional_requirements') or [])}, "
                f"layout={len(brief.get('layout_constraints') or [])}"
            )
    if tool == "propose_tech_stack":
        stack = args.get("tech_stack") or []
        if isinstance(stack, list):
            layers = [str(x.get("layer", "")) for x in stack if isinstance(x, dict)]
            return f"{len(stack)} layers: {', '.join([x for x in layers if x][:8])}"
    if tool == "generate_pdf_report":
        sections = args.get("include_sections") or DEFAULT_REPORT_SECTIONS
        return f"sections={', '.join(map(str, sections))}"
    if tool == "submit_critique":
        findings = args.get("findings") or []
        if isinstance(findings, list):
            return f"{len(findings)} finding(s)"
    return _compact_json(args, limit=limit)


def _tool_output_detail(content, *, limit: int = 320) -> str:
    text = " ".join(_text_of(content).split())
    return text[:limit] + ("..." if len(text) > limit else "")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"
