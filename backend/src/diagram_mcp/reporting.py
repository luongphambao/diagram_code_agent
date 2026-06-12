"""Client-ready HTML/PDF report generation for architecture diagrams."""

from __future__ import annotations

import base64
import datetime as dt
import json
import mimetypes
from pathlib import Path
from typing import Any

from jinja2 import Environment


DEFAULT_REPORT_SECTIONS = [
    "cover",
    "executive_summary",
    "requirements_analysis",
    "traceability",
    "solution",
    "techstack",
    "architecture_analysis",
    "step_results",
    "risks",
    "diagram",
]

SECTION_ALIASES = {
    "blueprint": "architecture_analysis",
    "architecture": "architecture_analysis",
    "requirements": "requirements_analysis",
    "executive": "executive_summary",
    "summary": "executive_summary",
    "steps": "step_results",
    "quality": "step_results",
    "risk": "risks",
}

REPORT_EVIDENCE_NAME = "report_evidence.json"


class ReportRenderError(RuntimeError):
    """Raised when HTML-to-PDF rendering cannot complete."""


def read_json_file(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def normalize_sections(sections: list[str] | None) -> list[str]:
    requested = sections or DEFAULT_REPORT_SECTIONS
    out: list[str] = []
    for raw in requested:
        name = SECTION_ALIASES.get(str(raw).strip().lower(), str(raw).strip().lower())
        if name in DEFAULT_REPORT_SECTIONS and name not in out:
            out.append(name)
    return out or DEFAULT_REPORT_SECTIONS.copy()


def _clip_text(value: Any, limit: int = 700) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].rstrip() + ("..." if len(text) > limit else "")


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _data_uri(path: Path) -> str:
    if not path.exists():
        return ""
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _repo_root() -> Path:
    # backend/src/diagram_mcp/reporting.py -> repo root
    return Path(__file__).resolve().parents[3]


def _logo_uri() -> str:
    return _data_uri(_repo_root() / "logo" / "image.png")


def evidence_path(workspace: Path) -> Path:
    return workspace / REPORT_EVIDENCE_NAME


def record_report_step(
    workspace: Path,
    step: str,
    *,
    status: str = "completed",
    summary: str = "",
    data: Any = None,
) -> None:
    """Append one concise workflow result to report_evidence.json."""
    workspace.mkdir(parents=True, exist_ok=True)
    path = evidence_path(workspace)
    evidence = read_json_file(path, {"steps": []})
    steps = evidence.setdefault("steps", [])
    steps.append(
        {
            "timestamp": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "step": step,
            "status": status,
            "summary": _clip_text(summary, 900),
            "data": data,
        }
    )
    path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")


def record_artifact_inventory(workspace: Path) -> list[dict[str, Any]]:
    artifacts = []
    for name, label in (
        ("out.png", "Rendered diagram PNG"),
        ("out.body.png", "Diagram body PNG"),
        ("out.drawio", "Editable draw.io source"),
        ("diagram.py", "Generated diagram code"),
        ("out.report.html", "Client report HTML"),
        ("out.pdf", "Client report PDF"),
    ):
        path = workspace / name
        if path.exists():
            artifacts.append({"name": name, "label": label, "bytes": path.stat().st_size})
    return artifacts


def _tech_items(tech_stack: Any) -> list[dict[str, Any]]:
    if isinstance(tech_stack, list):
        return [item for item in tech_stack if isinstance(item, dict)]
    if isinstance(tech_stack, dict):
        return [
            {"layer": layer, **value} if isinstance(value, dict) else {"layer": layer, "choice": value}
            for layer, value in tech_stack.items()
        ]
    return []


def _components_by_cluster(blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = _as_list(blueprint.get("nodes"))
    clusters = _as_list(blueprint.get("clusters"))
    grouped: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        if isinstance(node, dict):
            grouped.setdefault(str(node.get("cluster") or "unassigned"), []).append(node)

    out = []
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        cid = str(cluster.get("id") or "")
        out.append(
            {
                "id": cid,
                "label": cluster.get("label") or cid or "Architecture tier",
                "tier": cluster.get("tier") or "",
                "nodes": grouped.get(cid, []),
            }
        )
    if not out and nodes:
        out.append({"id": "components", "label": "Architecture Components", "tier": "", "nodes": nodes})
    return out


def _traceability(brief: dict[str, Any], blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    requirements = []
    for kind, items in (
        ("Functional", brief.get("functional_requirements")),
        ("Non-functional", brief.get("non_functional_requirements")),
    ):
        for item in _as_list(items):
            requirements.append({"type": kind, "requirement": str(item)})

    nodes = [n for n in _as_list(blueprint.get("nodes")) if isinstance(n, dict)]
    clusters = [c for c in _as_list(blueprint.get("clusters")) if isinstance(c, dict)]
    component_names = [str(n.get("label") or n.get("id") or "") for n in nodes if n]
    cluster_names = [str(c.get("label") or c.get("id") or "") for c in clusters if c]
    fallback = ", ".join([x for x in (cluster_names[:2] + component_names[:3]) if x]) or "Architecture blueprint"

    rows = []
    for req in requirements[:18]:
        text = req["requirement"].lower()
        matches = []
        for name in component_names + cluster_names:
            terms = [t for t in name.lower().replace("/", " ").replace("-", " ").split() if len(t) > 3]
            if terms and any(t in text for t in terms):
                matches.append(name)
        rows.append(
            {
                **req,
                "mapped_to": ", ".join(dict.fromkeys(matches[:4])) or fallback,
                "coverage": "Addressed in approved blueprint",
            }
        )
    return rows


def _risk_items(
    analysis: dict[str, Any],
    brief: dict[str, Any],
    blueprint: dict[str, Any],
    critique: list[dict[str, Any]],
) -> list[dict[str, str]]:
    risks = []
    for concern in _as_list(analysis.get("concerns"))[:6]:
        risks.append({"type": "Architecture Concern", "detail": str(concern), "recommendation": "Validate during detailed design."})
    for assumption in _as_list(brief.get("assumptions"))[:6]:
        risks.append({"type": "Assumption", "detail": str(assumption), "recommendation": "Confirm with stakeholders before implementation."})
    for finding in critique[:5]:
        if isinstance(finding, dict):
            risks.append(
                {
                    "type": f"Diagram Review: {finding.get('severity', 'note')}",
                    "detail": str(finding.get("title") or finding.get("detail") or "Review finding"),
                    "recommendation": str(finding.get("fix_suggestion") or "Track as a diagram quality note."),
                }
            )
    if not blueprint.get("key_decisions"):
        risks.append(
            {
                "type": "Missing Decision Detail",
                "detail": "The approved blueprint does not include explicit key decisions.",
                "recommendation": "Add explicit design decisions before sharing the report externally.",
            }
        )
    return risks


def _executive_points(
    analysis: dict[str, Any],
    brief: dict[str, Any],
    blueprint: dict[str, Any],
    tech_items: list[dict[str, Any]],
) -> list[str]:
    points = []
    pattern = blueprint.get("pattern")
    if pattern:
        points.append(f"The recommended architecture follows a {str(pattern).replace('_', ' ')} approach.")
    objective = brief.get("objective")
    if objective:
        points.append(str(objective))
    provider = analysis.get("provider_preference") or brief.get("provider_preference")
    scale = analysis.get("scale_level") or brief.get("scale_level")
    security = analysis.get("security_level") or brief.get("security_level")
    context = ", ".join([str(x) for x in (provider, scale, security) if x])
    if context:
        points.append(f"Planning signals indicate {context} requirements.")
    if tech_items:
        points.append(f"The solution stack covers {len(tech_items)} implementation layer(s) with documented rationale and alternatives.")
    decisions = _as_list(blueprint.get("key_decisions"))
    points.extend(str(x) for x in decisions[:3])
    return points[:7] or ["The report packages the approved architecture diagram and planning artifacts for customer review."]


def assemble_report_data(
    workspace: Path,
    *,
    title: str = "",
    subtitle: str = "",
    brand: str = "",
    include_sections: list[str] | None = None,
) -> dict[str, Any]:
    analysis = read_json_file(workspace / "architecture_analysis.json", {})
    brief = read_json_file(workspace / "diagram_brief.json", {})
    tech_stack = read_json_file(workspace / "tech_stack.json", {})
    blueprint = read_json_file(workspace / "blueprint.json", {})
    critique = read_json_file(workspace / "critique.json", [])
    evidence = read_json_file(evidence_path(workspace), {"steps": []})
    tool_summary = read_json_file(workspace / "tool_budget_summary.json", {})

    diagram_path = workspace / "out.body.png"
    if not diagram_path.exists():
        diagram_path = workspace / "out.png"
    if not diagram_path.exists():
        raise FileNotFoundError("No diagram image found; call render_diagram and finalize_diagram first.")

    sections = normalize_sections(include_sections)
    tech = _tech_items(tech_stack)
    artifacts = record_artifact_inventory(workspace)

    report_title = (
        title
        or blueprint.get("slide_title")
        or brief.get("objective")
        or "Architecture Blueprint"
    )
    report_subtitle = subtitle or blueprint.get("slide_kicker") or "Client Architecture Report"
    report_brand = brand or blueprint.get("brand") or ""

    return {
        "sections": sections,
        "title": report_title,
        "subtitle": report_subtitle,
        "brand": report_brand,
        "document_type": "Architecture Document",
        "generated_at": dt.datetime.now(dt.UTC).strftime("%B %d, %Y"),
        "logo_uri": _logo_uri(),
        "diagram_uri": _data_uri(diagram_path),
        "analysis": analysis,
        "brief": brief,
        "tech_items": tech,
        "blueprint": blueprint,
        "components_by_cluster": _components_by_cluster(blueprint),
        "traceability": _traceability(brief, blueprint),
        "risks": _risk_items(analysis, brief, blueprint, critique if isinstance(critique, list) else []),
        "executive_points": _executive_points(analysis, brief, blueprint, tech),
        "evidence_steps": evidence.get("steps", []) if isinstance(evidence, dict) else [],
        "tool_summary": tool_summary,
        "artifacts": artifacts,
        "node_count": len(_as_list(blueprint.get("nodes"))),
        "edge_count": len(_as_list(blueprint.get("edges"))),
        "cluster_count": len(_as_list(blueprint.get("clusters"))),
    }


REPORT_TEMPLATE = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{{ report.title }}</title>
  <style>
    @page { size: A4; margin: 0; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: #172033;
      background: #ffffff;
      font-family: Arial, Helvetica, sans-serif;
      font-size: 12px;
      line-height: 1.45;
    }
    .page {
      min-height: 297mm;
      padding: 19mm 18mm 17mm;
      page-break-after: always;
      position: relative;
      overflow: hidden;
    }
    .page:last-child { page-break-after: auto; }
    .cover {
      color: white;
      background:
        linear-gradient(135deg, rgba(15, 23, 42, .98), rgba(13, 148, 136, .92)),
        #0f172a;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }
    .cover-logo { width: 28mm; height: 28mm; object-fit: contain; }
    .cover-top { display: flex; justify-content: space-between; align-items: flex-start; }
    .brand { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; opacity: .86; }
    .cover h1 { font-size: 42px; line-height: 1.05; margin: 0 0 14px; max-width: 155mm; }
    .cover .subtitle { color: #c8fbf1; font-size: 17px; margin: 0 0 26px; }
    .badge { display: inline-block; border: 1px solid rgba(255,255,255,.32); border-radius: 4px; padding: 8px 12px; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; }
    .cover-footer { display: flex; justify-content: space-between; color: #d9fffa; font-size: 11px; }
    h2 { color: #0f766e; font-size: 25px; margin: 0 0 12px; }
    h3 { color: #172033; font-size: 15px; margin: 22px 0 8px; }
    p { margin: 0 0 8px; }
    .section-kicker { color: #64748b; font-size: 10px; letter-spacing: .12em; text-transform: uppercase; margin-bottom: 5px; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    .metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 14px 0 18px; }
    .metric, .card {
      border: 1px solid #d8e1ea;
      background: #f8fafc;
      border-radius: 6px;
      padding: 10px;
      break-inside: avoid;
    }
    .metric-label { color: #64748b; font-size: 9px; text-transform: uppercase; letter-spacing: .08em; }
    .metric-value { font-weight: 700; font-size: 15px; color: #0f172a; margin-top: 3px; word-break: break-word; }
    ul { margin: 7px 0 0 18px; padding: 0; }
    li { margin: 0 0 5px; }
    table { width: 100%; border-collapse: collapse; margin-top: 10px; break-inside: auto; }
    th, td { border: 1px solid #d8e1ea; padding: 7px 8px; vertical-align: top; text-align: left; }
    th { background: #eff6f5; color: #0f766e; font-size: 10px; text-transform: uppercase; letter-spacing: .06em; }
    .muted { color: #64748b; }
    .pill { display: inline-block; border: 1px solid #cbd5e1; border-radius: 999px; padding: 3px 8px; margin: 0 4px 4px 0; font-size: 10px; background: white; }
    .timeline { border-left: 2px solid #0f766e; margin-left: 7px; padding-left: 14px; }
    .timeline-item { margin: 0 0 12px; break-inside: avoid; }
    .timeline-title { font-weight: 700; color: #0f172a; }
    .status { color: #0f766e; font-weight: 700; text-transform: uppercase; font-size: 9px; }
    .diagram-wrap { height: 230mm; display: flex; align-items: center; justify-content: center; border: 1px solid #d8e1ea; background: #f8fafc; border-radius: 6px; padding: 8mm; }
    .diagram-wrap img { max-width: 100%; max-height: 100%; object-fit: contain; }
    .footer { position: absolute; left: 18mm; right: 18mm; bottom: 8mm; color: #94a3b8; font-size: 9px; display: flex; justify-content: space-between; border-top: 1px solid #e2e8f0; padding-top: 5px; }
    .avoid-break { break-inside: avoid; }
  </style>
</head>
<body>
{% if "cover" in report.sections %}
  <section class="page cover">
    <div class="cover-top">
      {% if report.logo_uri %}<img class="cover-logo" src="{{ report.logo_uri }}" alt="Logo">{% endif %}
      <div class="brand">{{ report.brand or "Architecture Delivery" }}</div>
    </div>
    <div>
      <div class="badge">{{ report.document_type }}</div>
      <h1>{{ report.title }}</h1>
      <p class="subtitle">{{ report.subtitle }}</p>
    </div>
    <div class="cover-footer">
      <span>Prepared for client review</span>
      <span>{{ report.generated_at }}</span>
    </div>
  </section>
{% endif %}

{% if "executive_summary" in report.sections %}
  <section class="page">
    <div class="section-kicker">Executive Summary</div>
    <h2>Architecture Recommendation</h2>
    <div class="metric-grid">
      <div class="metric"><div class="metric-label">Pattern</div><div class="metric-value">{{ report.blueprint.pattern or "TBD" }}</div></div>
      <div class="metric"><div class="metric-label">Provider</div><div class="metric-value">{{ report.analysis.provider_preference or report.brief.provider_preference or "Cloud neutral" }}</div></div>
      <div class="metric"><div class="metric-label">Scale</div><div class="metric-value">{{ report.analysis.scale_level or report.brief.scale_level or "Unspecified" }}</div></div>
      <div class="metric"><div class="metric-label">Security</div><div class="metric-value">{{ report.analysis.security_level or report.brief.security_level or "Standard" }}</div></div>
    </div>
    <div class="card">
      <h3>Key Conclusions</h3>
      <ul>{% for point in report.executive_points %}<li>{{ point }}</li>{% endfor %}</ul>
    </div>
    <div class="grid">
      <div class="card"><h3>Business Value</h3><p>The architecture separates user access, application services, data persistence, and operational concerns so stakeholders can review capability coverage and delivery readiness.</p></div>
      <div class="card"><h3>Technical Value</h3><p>The approved blueprint documents major components, integration paths, technology choices, assumptions, and review outcomes in one traceable package.</p></div>
    </div>
    <div class="footer"><span>{{ report.title }}</span><span>Executive Summary</span></div>
  </section>
{% endif %}

{% if "requirements_analysis" in report.sections %}
  <section class="page">
    <div class="section-kicker">Requirements Analysis</div>
    <h2>Context and Planning Signals</h2>
    <div class="metric-grid">
      <div class="metric"><div class="metric-label">Application Type</div><div class="metric-value">{{ report.analysis.application_type or report.brief.application_type or "Application" }}</div></div>
      <div class="metric"><div class="metric-label">Density</div><div class="metric-value">{{ report.analysis.recommended_density or report.blueprint.density or "standard" }}</div></div>
      <div class="metric"><div class="metric-label">Components</div><div class="metric-value">{{ report.node_count }}</div></div>
      <div class="metric"><div class="metric-label">Connections</div><div class="metric-value">{{ report.edge_count }}</div></div>
    </div>
    <div class="grid">
      <div class="card"><h3>Detected Capabilities</h3>{% for item in report.analysis.detected_capabilities or [] %}<span class="pill">{{ item }}</span>{% else %}<p class="muted">No deterministic capability signals were recorded.</p>{% endfor %}</div>
      <div class="card"><h3>Constraints</h3>{% for item in report.analysis.constraints or [] %}<span class="pill">{{ item }}</span>{% else %}<p class="muted">No explicit constraints were recorded.</p>{% endfor %}</div>
    </div>
    <h3>Functional Requirements</h3>
    <ul>{% for item in report.brief.functional_requirements or [] %}<li>{{ item }}</li>{% else %}<li class="muted">No functional requirements were captured in the brief.</li>{% endfor %}</ul>
    <h3>Non-Functional Requirements</h3>
    <ul>{% for item in report.brief.non_functional_requirements or [] %}<li>{{ item }}</li>{% else %}<li class="muted">No non-functional requirements were captured in the brief.</li>{% endfor %}</ul>
    <div class="footer"><span>{{ report.title }}</span><span>Requirements Analysis</span></div>
  </section>
{% endif %}

{% if "traceability" in report.sections %}
  <section class="page">
    <div class="section-kicker">Traceability</div>
    <h2>Requirement Coverage</h2>
    <table>
      <thead><tr><th>Type</th><th>Requirement</th><th>Mapped Architecture Area</th><th>Status</th></tr></thead>
      <tbody>{% for row in report.traceability %}<tr><td>{{ row.type }}</td><td>{{ row.requirement }}</td><td>{{ row.mapped_to }}</td><td>{{ row.coverage }}</td></tr>{% else %}<tr><td colspan="4" class="muted">No traceability rows available.</td></tr>{% endfor %}</tbody>
    </table>
    <div class="footer"><span>{{ report.title }}</span><span>Traceability</span></div>
  </section>
{% endif %}

{% if "solution" in report.sections %}
  <section class="page">
    <div class="section-kicker">Solution Overview</div>
    <h2>Architecture Approach</h2>
    <p>{{ report.blueprint.pattern_rationale or report.brief.objective or "The solution overview is based on the approved architecture blueprint." }}</p>
    <h3>Primary Flow</h3>
    <table>
      <thead><tr><th>From</th><th>To</th><th>Label</th><th>Protocol</th></tr></thead>
      <tbody>{% for edge in report.blueprint.edges[:12] or [] %}<tr><td>{{ edge["from"] }}</td><td>{{ edge.to }}</td><td>{{ edge.label }}</td><td>{{ edge.protocol }}</td></tr>{% else %}<tr><td colspan="4" class="muted">No blueprint edges were captured.</td></tr>{% endfor %}</tbody>
    </table>
    <h3>Layout and Presentation Constraints</h3>
    <ul>{% for item in report.brief.layout_constraints or [] %}<li>{{ item }}</li>{% else %}<li class="muted">No explicit layout constraints were captured.</li>{% endfor %}</ul>
    <div class="footer"><span>{{ report.title }}</span><span>Solution Overview</span></div>
  </section>
{% endif %}

{% if "techstack" in report.sections %}
  <section class="page">
    <div class="section-kicker">Technology Stack</div>
    <h2>Implementation Rationale</h2>
    <table>
      <thead><tr><th>Layer</th><th>Choice</th><th>Rationale</th><th>Alternatives</th></tr></thead>
      <tbody>{% for item in report.tech_items %}<tr><td>{{ item.layer }}</td><td><strong>{{ item.choice }}</strong></td><td>{{ item.rationale }}</td><td>{{ item.alternatives|join(", ") }}</td></tr>{% else %}<tr><td colspan="4" class="muted">No technology stack was recorded.</td></tr>{% endfor %}</tbody>
    </table>
    <div class="footer"><span>{{ report.title }}</span><span>Technology Stack</span></div>
  </section>
{% endif %}

{% if "architecture_analysis" in report.sections %}
  <section class="page">
    <div class="section-kicker">Architecture Blueprint</div>
    <h2>Components and Decisions</h2>
    <h3>Key Design Decisions</h3>
    <ul>{% for decision in report.blueprint.key_decisions or [] %}<li>{{ decision }}</li>{% else %}<li class="muted">No key decisions were recorded in the blueprint.</li>{% endfor %}</ul>
    <h3>Tiers and Components</h3>
    {% for cluster in report.components_by_cluster %}
      <div class="card avoid-break"><strong>{{ cluster.label }}</strong>{% if cluster.tier %}<span class="muted"> - {{ cluster.tier }}</span>{% endif %}
      <p>{% for node in cluster.nodes %}{{ node.label or node.id }}{% if node.tech %} ({{ node.tech }}){% endif %}{% if not loop.last %}, {% endif %}{% else %}<span class="muted">No components mapped to this tier.</span>{% endfor %}</p></div>
    {% endfor %}
    <div class="footer"><span>{{ report.title }}</span><span>Architecture Blueprint</span></div>
  </section>
{% endif %}

{% if "step_results" in report.sections %}
  <section class="page">
    <div class="section-kicker">Step Results and Quality Gates</div>
    <h2>Workflow Evidence</h2>
    <div class="timeline">
      {% for step in report.evidence_steps %}
        <div class="timeline-item">
          <div class="timeline-title">{{ step.step }} <span class="status">{{ step.status }}</span></div>
          <div class="muted">{{ step.timestamp }}</div>
          <p>{{ step.summary }}</p>
        </div>
      {% else %}
        <p class="muted">No workflow evidence was recorded for this run.</p>
      {% endfor %}
    </div>
    {% if report.tool_summary %}<h3>Tool Summary</h3><pre>{{ report.tool_summary | tojson(indent=2) }}</pre>{% endif %}
    <div class="footer"><span>{{ report.title }}</span><span>Step Results</span></div>
  </section>
{% endif %}

{% if "risks" in report.sections %}
  <section class="page">
    <div class="section-kicker">Risks and Recommendations</div>
    <h2>Assumptions, Concerns, and Next Steps</h2>
    <table>
      <thead><tr><th>Type</th><th>Detail</th><th>Recommendation</th></tr></thead>
      <tbody>{% for risk in report.risks %}<tr><td>{{ risk.type }}</td><td>{{ risk.detail }}</td><td>{{ risk.recommendation }}</td></tr>{% else %}<tr><td colspan="3" class="muted">No risks or assumptions were recorded.</td></tr>{% endfor %}</tbody>
    </table>
    <div class="footer"><span>{{ report.title }}</span><span>Risks and Recommendations</span></div>
  </section>
{% endif %}

{% if "diagram" in report.sections %}
  <section class="page">
    <div class="section-kicker">Architecture Diagram</div>
    <h2>{{ report.blueprint.diagram_title or "Approved Architecture Diagram" }}</h2>
    <div class="diagram-wrap"><img src="{{ report.diagram_uri }}" alt="Architecture diagram"></div>
    <p class="muted">This diagram reflects the approved blueprint and quality review state captured in the preceding sections.</p>
    <div class="footer"><span>{{ report.title }}</span><span>Diagram</span></div>
  </section>
{% endif %}

<section class="page">
  <div class="section-kicker">Appendix</div>
  <h2>Artifact Inventory</h2>
  <table>
    <thead><tr><th>Artifact</th><th>Description</th><th>Size</th></tr></thead>
    <tbody>{% for artifact in report.artifacts %}<tr><td>{{ artifact.name }}</td><td>{{ artifact.label }}</td><td>{{ artifact.bytes }} bytes</td></tr>{% else %}<tr><td colspan="3" class="muted">No artifacts recorded.</td></tr>{% endfor %}</tbody>
  </table>
  <div class="footer"><span>{{ report.title }}</span><span>Appendix</span></div>
</section>
</body>
</html>
"""


def render_report_html(report: dict[str, Any]) -> str:
    env = Environment(autoescape=True)
    template = env.from_string(REPORT_TEMPLATE)
    return template.render(report=report)


def render_pdf_from_html(html: str, pdf_path: Path) -> None:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise ReportRenderError(
            "Playwright is not installed. Install backend dependencies and run "
            "`python -m playwright install chromium` before generating PDF reports."
        ) from exc

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_content(html, wait_until="networkidle")
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
            browser.close()
    except PlaywrightError as exc:
        raise ReportRenderError(
            "Playwright Chromium is not available. Run "
            "`python -m playwright install chromium` locally, or rebuild the backend Docker image."
        ) from exc


def generate_report(
    workspace: Path,
    *,
    title: str = "",
    subtitle: str = "",
    brand: str = "",
    include_sections: list[str] | None = None,
) -> tuple[Path, Path, list[str]]:
    workspace.mkdir(parents=True, exist_ok=True)
    report = assemble_report_data(
        workspace,
        title=title,
        subtitle=subtitle,
        brand=brand,
        include_sections=include_sections,
    )
    html = render_report_html(report)
    html_path = workspace / "out.report.html"
    pdf_path = workspace / "out.pdf"
    html_path.write_text(html, encoding="utf-8")
    render_pdf_from_html(html, pdf_path)
    artifacts = record_artifact_inventory(workspace)
    record_report_step(
        workspace,
        "generate_pdf_report",
        summary=f"Generated client-ready HTML and PDF report with {len(report['sections'])} requested sections.",
        data={"sections": report["sections"], "artifacts": artifacts},
    )
    return html_path, pdf_path, report["sections"]
