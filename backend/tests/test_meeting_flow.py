"""Tests for the Composio Google Calendar/Meet meeting flow.

Covers: (1) the 4 new Google Meet lookup tools are registered as read-only
utility tools (never gated), (2) create_client_meeting persists
last_meeting.json for the frontend result card, and (3) _stage_artifacts
reads it back into agent state — mirroring the pdf_base64/pptx_base64
pattern in test_pdf_report_flow.py.
"""

import contextvars
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import backends
import tools
from agent.middleware.phase_filter import _UTILITY_TOOLS
from context import SessionContext
from session.artifacts import _stage_artifacts

_MEET_TOOL_NAMES = [
    "list_meeting_records",
    "get_meeting_transcript",
    "get_meeting_recordings",
    "list_meeting_participants",
]


def _use_workspace(monkeypatch, tmp_path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        backends, "_current_workspace",
        contextvars.ContextVar("current_workspace", default=tmp_path),
    )


def test_meet_tools_registered_as_ungated_utility_tools():
    main_tool_names = {t.name for t in tools.MAIN_TOOLS}
    for name in _MEET_TOOL_NAMES:
        assert name in main_tool_names, f"{name} missing from MAIN_TOOLS"
        assert name not in tools.GATE_TOOL_NAMES, f"{name} must not be a HITL gate (read-only)"
        assert name not in tools.GATE_DECISIONS
        assert name not in tools.ROLE_GATE_PERMISSIONS
        assert name in _UTILITY_TOOLS, f"{name} must be visible in every workflow phase"


def _fake_composio_client(monkeypatch, module, responses: dict):
    """Patch module._get_composio_client to return a client whose
    .tools.execute(slug, ...) returns responses[slug] (a SimpleNamespace with
    .data / .error), and account-id resolution to a fixed test value.
    """
    client = MagicMock()

    def _execute(slug, arguments=None, connected_account_id=None, version=None):
        return responses[slug]

    client.tools.execute.side_effect = _execute
    monkeypatch.setattr(module, "_get_composio_client", lambda ctx=None: client)
    monkeypatch.setattr(module, "_meet_account_id", lambda ctx=None: "ca_test_meet")
    return client


def test_list_meeting_records_formats_results(monkeypatch):
    import integrations.meet as meet

    _fake_composio_client(monkeypatch, meet, {
        "GOOGLEMEET_LIST_CONFERENCE_RECORDS": SimpleNamespace(
            error=None,
            data={"conference_records": [
                {"name": "conferenceRecords/abc123", "start_time": "2026-07-20T09:00:00Z",
                 "end_time": "2026-07-20T09:45:00Z"},
            ]},
        ),
    })

    result = tools.list_meeting_records.func(runtime=SimpleNamespace(context=SessionContext()))

    assert "conferenceRecords/abc123" in result
    assert "2026-07-20T09:00:00Z" in result


def test_list_meeting_records_empty_result_is_not_an_error(monkeypatch):
    import integrations.meet as meet

    _fake_composio_client(monkeypatch, meet, {
        "GOOGLEMEET_LIST_CONFERENCE_RECORDS": SimpleNamespace(error=None, data={"conference_records": []}),
    })

    result = tools.list_meeting_records.func(runtime=SimpleNamespace(context=SessionContext()))

    assert not result.startswith("ERROR")
    assert "No conference records found" in result


def test_get_meeting_transcript_joins_entries(monkeypatch):
    import integrations.meet as meet

    _fake_composio_client(monkeypatch, meet, {
        "GOOGLEMEET_GET_TRANSCRIPTS_BY_CONFERENCE_RECORD_ID": SimpleNamespace(
            error=None,
            data={"transcripts": [{"name": "conferenceRecords/abc123/transcripts/t1"}]},
        ),
        "GOOGLEMEET_LIST_TRANSCRIPT_ENTRIES": SimpleNamespace(
            error=None,
            data={"transcript_entries": [
                {"participant": "Alice", "text": "Let's review the requirements."},
                {"participant": "Bob", "text": "Sounds good."},
            ]},
        ),
    })

    result = tools.get_meeting_transcript.func(
        conference_record_name="conferenceRecords/abc123",
        runtime=SimpleNamespace(context=SessionContext()),
    )

    assert "Alice: Let's review the requirements." in result
    assert "Bob: Sounds good." in result


def test_get_meeting_transcript_no_transcript_available(monkeypatch):
    import integrations.meet as meet

    _fake_composio_client(monkeypatch, meet, {
        "GOOGLEMEET_GET_TRANSCRIPTS_BY_CONFERENCE_RECORD_ID": SimpleNamespace(
            error=None, data={"transcripts": []},
        ),
    })

    result = tools.get_meeting_transcript.func(
        conference_record_name="conferenceRecords/abc123",
        runtime=SimpleNamespace(context=SessionContext()),
    )

    assert not result.startswith("ERROR")
    assert "No transcript is available" in result


def test_get_meeting_recordings_lists_drive_files(monkeypatch):
    import integrations.meet as meet

    _fake_composio_client(monkeypatch, meet, {
        "GOOGLEMEET_GET_RECORDINGS_BY_CONFERENCE_RECORD_ID": SimpleNamespace(
            error=None,
            data={"recordings": [
                {"drive_destination": {"file": "1a2b3c", "export_uri": "https://drive.google.com/file/d/1a2b3c"}},
            ]},
        ),
    })

    result = tools.get_meeting_recordings.func(
        conference_record_name="conferenceRecords/abc123",
        runtime=SimpleNamespace(context=SessionContext()),
    )

    assert "1a2b3c" in result
    assert "https://drive.google.com/file/d/1a2b3c" in result


def test_list_meeting_participants_reads_display_names(monkeypatch):
    import integrations.meet as meet

    _fake_composio_client(monkeypatch, meet, {
        "GOOGLEMEET_LIST_PARTICIPANTS": SimpleNamespace(
            error=None,
            data={"participants": [
                {"signedin_user": {"display_name": "Alice Nguyen"}},
                {"anonymous_user": {"display_name": "Guest"}},
            ]},
        ),
    })

    result = tools.list_meeting_participants.func(
        conference_record_name="conferenceRecords/abc123",
        runtime=SimpleNamespace(context=SessionContext()),
    )

    assert "Alice Nguyen" in result
    assert "Guest" in result


def test_meet_tool_missing_connected_account_returns_error(monkeypatch):
    import integrations.meet as meet

    monkeypatch.delenv("GOOGLE_MEET_CONNECTED_ACCOUNT_ID", raising=False)
    monkeypatch.setattr(meet, "_get_composio_client", lambda ctx=None: MagicMock())

    result = tools.list_meeting_records.func(runtime=SimpleNamespace(context=SessionContext()))

    assert result.startswith("ERROR")
    assert "GOOGLE_MEET_CONNECTED_ACCOUNT_ID" in result


def test_create_client_meeting_writes_last_meeting_json(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    import integrations.calendar as calendar_mod

    client = MagicMock()
    client.tools.execute.return_value = SimpleNamespace(
        error=None,
        data={
            "htmlLink": "https://calendar.google.com/event?eid=abc",
            "conferenceData": {
                "entryPoints": [
                    {"entryPointType": "video", "uri": "https://meet.google.com/xyz-abcd-efg"},
                ]
            },
        },
    )
    monkeypatch.setattr(calendar_mod, "_get_composio_client", lambda ctx=None: client)
    monkeypatch.setattr(calendar_mod, "_calendar_account_id", lambda ctx=None: "ca_test_calendar")

    result = tools.create_client_meeting.func(
        title="Kickoff with Acme",
        start_datetime="2026-07-22T10:00:00+07:00",
        end_datetime="2026-07-22T11:00:00+07:00",
        attendee_email="client@acme.com",
        runtime=SimpleNamespace(context=SessionContext()),
        attendee_name="Jane Doe",
    )

    assert "Meeting scheduled" in result
    assert "https://meet.google.com/xyz-abcd-efg" in result

    last_meeting_path = tmp_path / "last_meeting.json"
    assert last_meeting_path.exists()
    saved = json.loads(last_meeting_path.read_text(encoding="utf-8"))
    assert saved["title"] == "Kickoff with Acme"
    assert saved["attendee_email"] == "client@acme.com"
    assert saved["meet_link"] == "https://meet.google.com/xyz-abcd-efg"
    assert saved["event_link"] == "https://calendar.google.com/event?eid=abc"

    # _stage_artifacts must surface it for the frontend's agentState.last_meeting.
    artifacts = _stage_artifacts(tmp_path)
    assert artifacts["last_meeting"] == saved


def test_stage_artifacts_omits_last_meeting_when_absent(tmp_path):
    assert "last_meeting" not in _stage_artifacts(tmp_path)
