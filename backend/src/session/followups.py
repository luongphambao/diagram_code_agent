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
    return _matches_whole_phrase(
        text,
        (
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
        ),
    )


def _is_ppt_followup(text: str) -> bool:
    """Detect a follow-up asking to package the current diagram as a PowerPoint proposal."""
    return _matches_whole_phrase(
        text,
        (
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
        ),
    )


# A client-delivery framing that unambiguously means "email it" in this app — send_email
# is the only "send to someone" capability the agent has, so these don't need the word
# "email" alongside them to be unambiguous.
_EMAIL_CLIENT_DELIVERY_PHRASES: tuple[str, ...] = (
    "send to client",
    "send to the client",
    "send the deliverable",
    "send deliverables",
    "send it to",
    "send this to",
    "gửi cho khách",
    "gui cho khach",
    "gửi khách hàng",
    "gui khach hang",
)
# Verbs that mean "transmit" (not "add"/"build"/etc.) — deliberately excludes
# "email"/"mail" as verbs since those double as the channel nouns below, and
# requiring a *separate* verb word is what keeps "add email verification" safe.
_SEND_VERBS: tuple[str, ...] = ("send", "gửi", "gui", "forward", "resend", "re-send")
# The email channel itself — only a signal when paired with a send verb above.
_EMAIL_CHANNELS: tuple[str, ...] = ("email", "e-mail", "mail", "gmail")


def _is_email_followup(text: str) -> bool:
    """Detect a request to SEND an already-generated deliverable via email.

    This must win over the pdf/ppt/wbs detectors below: "gửi file WBS qua email"
    or "send the report by email" contain "wbs"/"report" and would otherwise be
    mis-classified as a re-export/regenerate request, causing chat.py to inject
    a "call export_wbs_excel()/generate_pdf_report() now" instruction that
    discards the user's actual intent (send what already exists) and wastefully
    regenerates the deliverable instead of just emailing it.

    Deliberately does NOT match on a bare "email"/"mail"/"gmail" mention alone —
    those are common nouns in ordinary design requests ("add email verification",
    "email field on the login form", "integrate with gmail api") that have
    nothing to do with sending mail. Instead this requires EITHER an unambiguous
    client-delivery phrase, OR a send verb ("send"/"gửi"/...) co-occurring
    ANYWHERE in the message with an email-channel word — the two need not be
    adjacent, so natural phrasing like "send the report by email" or "gửi báo
    cáo qua email" (verb and channel separated by the object) still matches,
    while "add a mail queue service" (channel word, no send verb) does not.
    """
    if _matches_whole_phrase(text, _EMAIL_CLIENT_DELIVERY_PHRASES):
        return True
    return _matches_whole_phrase(text, _SEND_VERBS) and _matches_whole_phrase(text, _EMAIL_CHANNELS)


def _is_wbs_followup(text: str) -> bool:
    """Detect a WBS request — either first-time creation OR re-export of the deliverable.

    A WBS request is always a downstream step from an already-approved solution, never a
    fresh project, so chat.py preserves the upstream artifacts (brief/tech_stack/blueprint)
    instead of wiping them via clear_stage_markers(). This must therefore match BOTH the
    re-export phrasing ("xuất lại wbs") AND first-time asks ("tạo WBS", "ước lượng effort",
    "estimate the work breakdown") — a miss here means the very artifacts the WBS planner
    reads get deleted before it runs.
    """
    return _matches_whole_phrase(
        text,
        (
            # re-export / send the existing deliverable
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
            # first-time WBS creation / effort estimation (EN)
            "work breakdown",
            "work breakdown structure",
            "estimate effort",
            "effort estimate",
            "effort estimation",
            "man-day",
            "manday",
            "create wbs",
            "build wbs",
            "generate wbs",
            # first-time WBS creation / effort estimation (VI, with + without diacritics)
            "tạo wbs",
            "tao wbs",
            "lập wbs",
            "lap wbs",
            "ước lượng",
            "uoc luong",
            "phân rã công việc",
            "phan ra cong viec",
            "bóc tách công việc",
            "boc tach cong viec",
            "kế hoạch công việc",
            "ke hoach cong viec",
        ),
    )


def _wbs_preserve(text: str, *, solution_exists: bool, wbs_exists: bool, attached: bool) -> tuple[bool, bool]:
    """Decide whether a WBS request should preserve on-disk artifacts (vs. a fresh wipe).

    Returns ``(preserve, already_planned)``:

    - ``preserve`` is True when the message is a WBS request AND an upstream solution
      already exists on disk (blueprint/tech_stack/rendered diagram) AND no new document
      was attached (a fresh attachment is new-project intake, not a WBS follow-up). When
      True, chat.py skips ``clear_stage_markers()`` so the WBS planner still has its
      ``diagram_brief.json`` / ``tech_stack.json`` / ``blueprint.json`` inputs to read.
    - ``already_planned`` is True only when a full ``wbs.json`` already exists — the
      re-export case, where chat.py tells the agent to call ``export_wbs_excel()``
      directly instead of re-delegating to ``wbs_planner``. On a FIRST WBS request it is
      False, so the normal skeleton → estimate delegation runs on the preserved artifacts.

    Pure/side-effect-free so the preserve decision is unit-testable without the endpoint.
    """
    preserve = _is_wbs_followup(text) and solution_exists and not attached
    return preserve, (preserve and wbs_exists)
