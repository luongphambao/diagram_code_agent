"""Registration canaries for the BRD Agent (docs/plans/2026-07-29-brd-agent.md §E3/E4).

Covers both the S2 surface (the 3 main-agent read/import/validate tools reachable
from every deliverable phase, brd_writer wired in without leaking worker-only
tools into MAIN_TOOLS) and the S3 surface (the 3 HITL gates registered in every
place a gate must be registered — GATE_TOOL_NAMES/GATE_DECISIONS/
ROLE_GATE_PERMISSIONS/_MAIN_TOOL_SELECTOR_ALWAYS_INCLUDE/_PHASE_TOOLS). Mirrors
the registration-test pattern in test_business_case.py.
"""

from __future__ import annotations


def test_brd_main_tools_are_registered():
    from tools import MAIN_TOOLS, import_brd_docx, read_brd_outline, validate_brd

    names = {t.name for t in MAIN_TOOLS}
    assert {"import_brd_docx", "read_brd_outline", "validate_brd"} <= names
    assert import_brd_docx.name == "import_brd_docx"


def test_brd_main_tools_survive_the_phase_tool_filter():
    from agent.middleware.phase_filter import _PHASE_TOOLS

    for phase in ("draw", "wbs", "ppt", "report", "brd"):
        for tool_name in ("import_brd_docx", "read_brd_outline", "validate_brd"):
            assert tool_name in _PHASE_TOOLS[phase], (phase, tool_name)


def test_brd_phase_detected_from_either_draft_or_generated_doc(tmp_path):
    from agent.middleware.phase_filter import _detect_phase

    assert _detect_phase(tmp_path) == "intake"
    (tmp_path / "brd_outline_draft.json").write_text("[]", encoding="utf-8")
    assert _detect_phase(tmp_path) == "brd"

    tmp_path2 = tmp_path / "other"
    tmp_path2.mkdir()
    (tmp_path2 / "out.brd.docx").write_bytes(b"x")
    assert _detect_phase(tmp_path2) == "brd"


def test_brd_phase_outranks_report_phase(tmp_path):
    """'brd' must be checked before 'out.pdf' in _detect_phase — BRD runs after
    the PDF report/WBS in the intended workflow order."""
    from agent.middleware.phase_filter import _detect_phase

    (tmp_path / "out.pdf").write_bytes(b"x")
    (tmp_path / "out.brd.docx").write_bytes(b"x")
    assert _detect_phase(tmp_path) == "brd"


def test_brd_writer_worker_tools_are_not_in_main_tools():
    """load_brd_context/inspect_brd_template/draft_* are brd_writer-only —
    MAIN never drafts BRD content itself, it only imports/reads/validates."""
    from tools import MAIN_TOOLS

    names = {t.name for t in MAIN_TOOLS}
    assert not (
        {"load_brd_context", "inspect_brd_template", "draft_brd_outline", "draft_section_content"} & names
    )


_BRD_GATES = ("propose_brd_outline", "generate_brd_docx", "edit_brd_section")


def test_brd_gates_are_registered_as_gates():
    from tools import GATE_TOOL_NAMES, MAIN_TOOLS, ROLE_GATE_PERMISSIONS, allowed_decisions_for

    main_names = {t.name for t in MAIN_TOOLS}
    for gate in _BRD_GATES:
        assert gate in GATE_TOOL_NAMES, gate
        assert gate in main_names, gate
        assert "approve" in allowed_decisions_for(gate), gate
        assert "reject" in allowed_decisions_for(gate), gate
        assert "ba" in ROLE_GATE_PERMISSIONS[gate], gate


def test_brd_gates_survive_the_tool_selector():
    from agent.constants import _MAIN_TOOL_SELECTOR_ALWAYS_INCLUDE

    for gate in _BRD_GATES:
        assert gate in _MAIN_TOOL_SELECTOR_ALWAYS_INCLUDE, gate


def test_brd_gates_survive_the_phase_tool_filter():
    from agent.middleware.phase_filter import _PHASE_TOOLS

    for phase in ("draw", "wbs", "ppt", "report", "brd"):
        for gate in _BRD_GATES:
            assert gate in _PHASE_TOOLS[phase], (phase, gate)


def test_brd_writer_subagent_is_registered_with_general_purpose_disabled():
    from agent.subagents import build_subagent_specs

    specs = build_subagent_specs(
        workdir="/workspace",
        icons_root="/icons",
        manifest="manifest.json",
        style="pretty",
        drawer_vision_relay=False,
    )
    by_name = {s.name: s for s in specs}
    assert "brd_writer" in by_name
    brd_spec = by_name["brd_writer"]
    tool_names = {t.name for t in brd_spec.tools}
    assert tool_names == {
        "load_brd_context",
        "inspect_brd_template",
        "draft_brd_outline",
        "draft_section_content",
        "read_brd_outline",
        "validate_brd",
    }
    assert brd_spec.model_role == "brd_writer"
    assert brd_spec.permissions and len(brd_spec.permissions) == 1
