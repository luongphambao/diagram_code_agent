import base64
import json

from diagram_mcp import server
from diagram_mcp import tools
from diagram_mcp import reporting
from diagram_mcp.tools import GATE_TOOL_NAMES


def _use_workspace(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    monkeypatch.setattr(tools, "_ARCH_ANALYSIS_FILE", tmp_path / "architecture_analysis.json")
    monkeypatch.setattr(tools, "_BRIEF_FILE", tmp_path / "diagram_brief.json")
    monkeypatch.setattr(tools, "_TECHSTACK_FILE", tmp_path / "tech_stack.json")
    monkeypatch.setattr(tools, "_BLUEPRINT_FILE", tmp_path / "blueprint.json")
    monkeypatch.setattr(tools, "_CRITIQUE_FILE", tmp_path / "critique.json")
    monkeypatch.setattr(tools, "_TOOL_SUMMARY_FILE", tmp_path / "tool_budget_summary.json")


def _fake_pdf_renderer(html: str, pdf_path) -> None:
    pdf_path.write_bytes(b"%PDF-1.4\n%fake report\n")


def _write_report_inputs(tmp_path) -> None:
    (tmp_path / "architecture_analysis.json").write_text(json.dumps({
        "application_type": "web_application",
        "scale_level": "large",
        "security_level": "high",
        "provider_preference": "aws",
        "detected_capabilities": ["database", "security"],
        "constraints": ["production_focused"],
        "concerns": ["Include observability and security boundaries."],
    }), encoding="utf-8")
    (tmp_path / "diagram_brief.json").write_text(json.dumps({
        "objective": "Deliver a customer-facing architecture for the platform.",
        "functional_requirements": ["Users access the portal", "Application reads relational data"],
        "non_functional_requirements": ["High availability", "Audit-ready security"],
        "layout_constraints": ["Keep runtime and operations concerns separate"],
        "assumptions": ["Traffic volume will be validated during detailed design"],
    }), encoding="utf-8")
    (tmp_path / "tech_stack.json").write_text(json.dumps({
        "frontend": {"choice": "React", "rationale": "Fits SPA delivery", "alternatives": ["Vue"]},
        "database": {"choice": "PostgreSQL", "rationale": "Relational consistency", "alternatives": ["MySQL"]},
    }), encoding="utf-8")
    (tmp_path / "blueprint.json").write_text(json.dumps({
        "slide_title": "Customer Platform Architecture",
        "brand": "Acme",
        "pattern": "three_tier",
        "pattern_rationale": "A three-tier pattern separates access, application, and data layers.",
        "key_decisions": ["Use managed database for operational resilience."],
        "clusters": [{"id": "app", "label": "Application Layer", "tier": "backend"}],
        "nodes": [{"id": "api", "label": "API Service", "tech": "FastAPI", "cluster": "app"}],
        "edges": [{"from": "portal", "to": "api", "label": "HTTPS", "protocol": "HTTP"}],
    }), encoding="utf-8")
    reporting.record_report_step(tmp_path, "test_step", summary="Evidence captured.")


def test_artifacts_includes_pdf_base64(monkeypatch, tmp_path):
    pdf_bytes = b"%PDF-1.4\n%test\n"
    (tmp_path / "out.pdf").write_bytes(pdf_bytes)

    monkeypatch.setattr(server, "WORKSPACE", tmp_path)

    artifacts = server._artifacts()

    assert artifacts["pdf_base64"] == base64.b64encode(pdf_bytes).decode("ascii")


def test_generate_pdf_report_maps_to_hitl_card():
    card, step, delta = server._card_for(
        {
            "action_requests": [
                {
                    "name": "generate_pdf_report",
                    "args": {
                        "title": "Architecture Blueprint",
                        "subtitle": "Solution Report",
                        "brand": "Acme",
                        "include_sections": ["cover", "diagram"],
                    },
                }
            ]
        },
        summary="",
    )

    assert "generate_pdf_report" in GATE_TOOL_NAMES
    assert step == "awaiting_pdf_report"
    assert delta == {}
    assert card == {
        "type": "pdf_report_approval",
        "question": "Generate the PDF report with these settings?",
        "title": "Architecture Blueprint",
        "subtitle": "Solution Report",
        "brand": "Acme",
        "include_sections": ["cover", "diagram"],
    }


def test_last_tool_msg_only_when_latest_message_is_tool():
    history_then_user = [
        {"role": "user", "content": "make a diagram"},
        {"role": "tool", "content": '{"approved": true}'},
        {"role": "user", "content": "i want to generate pdf document"},
    ]
    resume = [
        {"role": "user", "content": "make a diagram"},
        {"role": "tool", "content": '{"approved": true}'},
    ]

    assert server._last_tool_msg(history_then_user) is None
    assert server._last_tool_msg(resume) == resume[-1]


def test_pdf_followup_detection():
    assert server._is_pdf_followup("i want to generate pdf document")
    assert server._is_pdf_followup("tạo báo cáo PDF giúp tôi")
    assert not server._is_pdf_followup("please add redis to the diagram")


def test_generate_pdf_report_writes_pdf(monkeypatch, tmp_path):
    from PIL import Image

    _use_workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(reporting, "render_pdf_from_html", _fake_pdf_renderer)
    _write_report_inputs(tmp_path)
    Image.new("RGB", (120, 80), "white").save(tmp_path / "out.png")

    result = tools.generate_pdf_report.func(include_sections=["diagram"])

    assert "Wrote" in result
    assert (tmp_path / "out.report.html").exists()
    assert (tmp_path / "out.pdf").exists()
    assert (tmp_path / "out.pdf").read_bytes().startswith(b"%PDF")


def test_report_data_uses_step_results_and_section_aliases(tmp_path):
    from PIL import Image

    _write_report_inputs(tmp_path)
    Image.new("RGB", (120, 80), "white").save(tmp_path / "out.png")

    data = reporting.assemble_report_data(tmp_path, include_sections=["cover", "blueprint", "diagram"])

    assert data["sections"] == ["cover", "architecture_analysis", "diagram"]
    assert data["title"] == "Customer Platform Architecture"
    assert data["analysis"]["security_level"] == "high"
    assert data["evidence_steps"][0]["step"] == "test_step"
    assert data["traceability"]


def test_report_template_escapes_user_text(tmp_path):
    from PIL import Image

    _write_report_inputs(tmp_path)
    brief = json.loads((tmp_path / "diagram_brief.json").read_text(encoding="utf-8"))
    brief["objective"] = "<script>alert('x')</script>"
    (tmp_path / "diagram_brief.json").write_text(json.dumps(brief), encoding="utf-8")
    Image.new("RGB", (120, 80), "white").save(tmp_path / "out.png")

    html = reporting.render_report_html(reporting.assemble_report_data(tmp_path))

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Executive Summary" in html
    assert "Step Results and Quality Gates" in html


def test_generate_pdf_report_missing_playwright_is_actionable(monkeypatch, tmp_path):
    from PIL import Image

    _use_workspace(monkeypatch, tmp_path)
    _write_report_inputs(tmp_path)
    Image.new("RGB", (120, 80), "white").save(tmp_path / "out.png")

    def fail_renderer(html: str, pdf_path) -> None:
        raise reporting.ReportRenderError("Playwright Chromium is not available.")

    monkeypatch.setattr(reporting, "render_pdf_from_html", fail_renderer)

    result = tools.generate_pdf_report.func(include_sections=["diagram"])

    assert "PDF report generation failed" in result
    assert "Playwright Chromium" in result
