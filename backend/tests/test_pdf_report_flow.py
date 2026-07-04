import base64
import contextvars
import json

import backends
import session_state as server
import tools
import tools.analysis_tools as analysis_tools
import reporting
from tools import GATE_TOOL_NAMES


def _use_workspace(monkeypatch, tmp_path) -> None:
    """Bind ``tmp_path`` as the current-thread workspace (§4.10).

    Stage files resolve lazily against backends.current_workspace(), so swapping the
    ContextVar isolates the whole suite; monkeypatch auto-restores it after the test.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        backends, "_current_workspace",
        contextvars.ContextVar("current_workspace", default=tmp_path),
    )


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

    artifacts = server._artifacts(tmp_path)

    assert artifacts["pdf_base64"] == base64.b64encode(pdf_bytes).decode("ascii")

def test_artifacts_includes_pptx_base64(monkeypatch, tmp_path):
    pptx_bytes = b"PK\x03\x04fake pptx"
    (tmp_path / "out.pptx").write_bytes(pptx_bytes)

    artifacts = server._artifacts(tmp_path)

    assert artifacts["pptx_base64"] == base64.b64encode(pptx_bytes).decode("ascii")


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
        "missing_sections": [
            "executive_summary",
            "requirements_analysis",
            "traceability",
            "solution",
            "techstack",
            "architecture_analysis",
            "well_architected",
            "step_results",
            "risks",
        ],
    }

def test_generate_ppt_proposal_maps_to_hitl_card():
    card, step, delta = server._card_for(
        {
            "action_requests": [
                {
                    "name": "generate_ppt_proposal",
                    "args": {
                        "title": "Architecture Proposal",
                        "subtitle": "Solution Deck",
                        "brand": "Acme",
                        "include_sections": ["cover", "architecture_diagram"],
                    },
                }
            ]
        },
        summary="",
    )

    assert "generate_ppt_proposal" in GATE_TOOL_NAMES
    assert step == "awaiting_ppt_proposal"
    assert delta == {}
    assert card["type"] == "ppt_proposal_approval"
    assert card["title"] == "Architecture Proposal"
    assert card["include_sections"] == ["cover", "architecture_diagram"]
    assert "technical_stack" in card["missing_sections"]


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

def test_pdf_followup_does_not_false_positive_on_substrings():
    """Regression test: naive substring matching used to match "doc" inside
    "docker" and "report" inside "reporting", wrongly treating an unrelated
    design request as a PDF follow-up and preserving stale stage artifacts."""
    assert not server._is_pdf_followup("dùng Docker và Kubernetes cho kiến trúc")
    assert not server._is_pdf_followup("add a docker container for the backend")
    assert not server._is_pdf_followup("thêm reporting service vào kiến trúc")

def test_ppt_followup_detection():
    assert server._is_ppt_followup("tạo PPT proposal theo template BnK")
    assert server._is_ppt_followup("make a PowerPoint slide deck")
    assert not server._is_ppt_followup("please add redis to the diagram")


def test_wbs_followup_detection():
    """Regression test: re-export/re-send asks like "xuất lại file WBS" must be
    recognized as a WBS follow-up so chat.py's preserve_artifacts logic skips
    clear_stage_markers() instead of wiping the already-approved wbs.json."""
    assert server._is_wbs_followup("xuất lại file WBS")
    assert server._is_wbs_followup("re-export the WBS excel file")
    assert server._is_wbs_followup("gửi WBS cho khách")
    assert not server._is_wbs_followup("please add redis to the diagram")


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

def test_generate_ppt_proposal_writes_openable_pptx(monkeypatch, tmp_path):
    from PIL import Image
    from pptx import Presentation

    _use_workspace(monkeypatch, tmp_path)
    _write_report_inputs(tmp_path)
    Image.new("RGB", (1280, 720), "white").save(tmp_path / "out.png")

    result = tools.generate_ppt_proposal.func(include_sections=["cover", "architecture_diagram"])

    assert "Wrote" in result
    pptx_path = tmp_path / "out.pptx"
    assert pptx_path.exists()
    prs = Presentation(str(pptx_path))
    assert len(prs.slides) >= 2


def test_generate_ppt_proposal_renders_brand_tables(monkeypatch, tmp_path):
    """The fallback path (no LLM) must emit native, brand-styled tables, not just bullets."""
    from PIL import Image
    from pptx import Presentation

    _use_workspace(monkeypatch, tmp_path)
    _write_report_inputs(tmp_path)
    Image.new("RGB", (1280, 720), "white").save(tmp_path / "out.png")

    result = tools.generate_ppt_proposal.func(
        include_sections=["cover", "technical_stack", "scope", "pricing"]
    )

    assert "Wrote" in result
    prs = Presentation(str(tmp_path / "out.pptx"))
    # At least one slide must contain a real table (graphic frame), proving table builders ran.
    tables = [
        shape
        for slide in prs.slides
        for shape in slide.shapes
        if shape.has_table
    ]
    assert tables, "expected at least one native table in the proposal"


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
