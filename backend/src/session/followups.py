"""Follow-up message detection: PDF/PPT/WBS re-export phrase matching."""

from __future__ import annotations

import re

from .sse import _text_of


def _last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return _text_of(m.get("content", ""))
    return ""


def _last_tool_msg(messages: list[dict]) -> dict | None:
    """Return the last message only when the client is resolving a HITL gate."""
    if messages and messages[-1].get("role") == "tool":
        return messages[-1]
    return None


def _matches_whole_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    """True if any phrase appears in ``text`` as a whole word/phrase (not a substring).

    Plain substring matching false-positives badly here: "doc" matches "docker",
    "report" matches "reporting" — either turns an unrelated design request into a
    (mis-detected) PDF/PPT follow-up, which skips clear_stage_markers() and silently
    reuses the previous turn's tech_stack.json/blueprint.json instead of a fresh run.
    """
    normalized = " ".join(str(text or "").lower().split())
    return any(re.search(rf"\b{re.escape(phrase)}\b", normalized) for phrase in phrases)


def _is_pdf_followup(text: str) -> bool:
    """Detect a follow-up asking to package the current diagram as a PDF report."""
    return _matches_whole_phrase(text, (
        "pdf",
        "report",
        "document",
        "doc",
        "tạo pdf",
        "tao pdf",
        "xuất pdf",
        "xuat pdf",
        "tạo báo cáo",
        "tao bao cao",
    ))

def _is_ppt_followup(text: str) -> bool:
    """Detect a follow-up asking to package the current diagram as a PowerPoint proposal."""
    return _matches_whole_phrase(text, (
        "ppt",
        "pptx",
        "powerpoint",
        "slide deck",
        "presentation deck",
        "make a proposal",
        "create a proposal",
        "export proposal",
        "generate proposal",
        "tạo ppt",
        "tao ppt",
        "xuất ppt",
        "xuat ppt",
        "tạo proposal",
        "tao proposal",
        "xuất proposal",
        "xuat proposal",
    ))


def _is_wbs_followup(text: str) -> bool:
    """Detect a follow-up asking to (re-)export/send the WBS Excel deliverable."""
    return _matches_whole_phrase(text, (
        "wbs",
        "excel",
        "xlsx",
        "xuất wbs",
        "xuat wbs",
        "xuất lại wbs",
        "xuat lai wbs",
        "gửi wbs",
        "gui wbs",
        "re-export wbs",
        "reexport wbs",
        "export wbs",
    ))
