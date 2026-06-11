import base64

from diagram_mcp import server
from diagram_mcp import tools
from diagram_mcp.tools import GATE_TOOL_NAMES


def _use_workspace(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    monkeypatch.setattr(tools, "_ARCH_ANALYSIS_FILE", tmp_path / "architecture_analysis.json")
    monkeypatch.setattr(tools, "_BRIEF_FILE", tmp_path / "diagram_brief.json")
    monkeypatch.setattr(tools, "_TECHSTACK_FILE", tmp_path / "tech_stack.json")
    monkeypatch.setattr(tools, "_BLUEPRINT_FILE", tmp_path / "blueprint.json")
    monkeypatch.setattr(tools, "_TOOL_SUMMARY_FILE", tmp_path / "tool_budget_summary.json")


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
    Image.new("RGB", (120, 80), "white").save(tmp_path / "out.png")

    result = tools.generate_pdf_report.func(include_sections=["diagram"])

    assert "Wrote" in result
    assert (tmp_path / "out.pdf").exists()
    assert (tmp_path / "out.pdf").read_bytes().startswith(b"%PDF")
