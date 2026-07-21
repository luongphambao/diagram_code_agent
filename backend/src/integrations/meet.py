"""Composio-based Google Meet tools for reading back past client meetings.

These are read-only lookups against conference records created by Google
Calendar/Meet (e.g. via ``create_client_meeting`` in ``calendar.py``, which
generates the Meet link through ``GOOGLECALENDAR_CREATE_EVENT``). None of
these tools create or modify a meeting, so none are HITL gates — they only
let the agent pull transcript/recording/participant data back into a
proposal or WBS after a call with a client.

Google Meet is a separate Composio toolkit from Google Calendar and needs
its own connected account (``composio add googlemeet``).

Deliberately no ``from __future__ import annotations``: LangChain's
``StructuredTool._injected_args_keys`` (which decides which parameters get the
runtime/state/store injected) inspects ``inspect.signature(fn)`` WITHOUT
resolving stringified annotations. Under postponed evaluation, `runtime:
ToolRuntime[SessionContext]` shows up as the raw string "ToolRuntime[...]"
instead of the real type, so it's never recognized as injected — the LLM's
tool call then crashes with "missing 1 required positional argument:
'runtime'" the moment this tool is actually invoked by a live agent (unit
tests that call `.func()` directly never hit this, since they bypass
StructuredTool entirely).
"""

import os

from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from pydantic import BaseModel

from context import SessionContext

# Pin the toolkit version so a future Composio schema change can't silently
# change these tools' request/response shape underneath us (see send_email's
# GMAIL_SEND_EMAIL pin in email.py). Verified live via
# client.toolkits.get("GOOGLEMEET").meta.version — refresh the same way.
_TOOLKIT_VERSION = "20260615_00"


def _get_composio_client(ctx: SessionContext | None = None):
    try:
        import composio  # type: ignore[import]
    except ImportError:
        raise RuntimeError(
            "composio package is not installed. Run: pip install composio-langchain"
        )
    api_key = (ctx.composio_api_key if ctx else "") or os.environ.get("COMPOSIO_API_KEY", "")
    if not api_key:
        raise RuntimeError("No Composio API key in session context or COMPOSIO_API_KEY env.")
    return composio.Composio(api_key=api_key)


def _meet_account_id(ctx: SessionContext | None = None) -> str:
    acct = (ctx.meet_account_id if ctx else "") or os.environ.get("GOOGLE_MEET_CONNECTED_ACCOUNT_ID", "")
    if not acct:
        raise RuntimeError(
            "GOOGLE_MEET_CONNECTED_ACCOUNT_ID is not set. "
            "Run `composio add googlemeet` to connect Google Meet, "
            "then set this env var to the returned connected account ID."
        )
    return acct


def _composio_error(result) -> str | None:
    if hasattr(result, "error") and result.error:
        return f"ERROR: Composio returned: {result.error}"
    return None


class ListMeetingRecordsArgs(BaseModel):
    meeting_code: str = ""
    space_name: str = ""
    time_min: str = ""
    time_max: str = ""


@tool(args_schema=ListMeetingRecordsArgs)
def list_meeting_records(
    runtime: ToolRuntime[SessionContext],
    meeting_code: str = "",
    space_name: str = "",
    time_min: str = "",
    time_max: str = "",
) -> str:
    """List past Google Meet conference records (finished calls), optionally
    filtered by meeting code, Meet space, or a time range (RFC3339 UTC).

    Use this to find the ``conference_record`` name for a client call before
    fetching its transcript, recording, or participant list.
    """
    try:
        client = _get_composio_client(runtime.context)
        acct_id = _meet_account_id(runtime.context)
    except RuntimeError as exc:
        return f"ERROR: {exc}"

    arguments = {}
    if meeting_code:
        arguments["meeting_code"] = meeting_code
    if space_name:
        arguments["space_name"] = space_name
    if time_min:
        arguments["time_min"] = time_min
    if time_max:
        arguments["time_max"] = time_max

    try:
        result = client.tools.execute(
            "GOOGLEMEET_LIST_CONFERENCE_RECORDS",
            arguments=arguments,
            connected_account_id=acct_id,
            version=_TOOLKIT_VERSION,
        )
    except Exception as exc:
        return f"ERROR: Failed to list Google Meet conference records: {exc}."

    err = _composio_error(result)
    if err:
        return err

    raw = getattr(result, "data", None) or {}
    records = raw.get("conference_records") if isinstance(raw, dict) else None
    records = records or []
    if not records:
        return "No conference records found for that filter."

    lines = ["Conference records:"]
    for rec in records:
        name = rec.get("name", "")
        start = (rec.get("start_time") or "")
        end = (rec.get("end_time") or "")
        lines.append(f"  - {name}  ({start} → {end})")
    return "\n".join(lines)


class GetMeetingTranscriptArgs(BaseModel):
    conference_record_name: str


@tool(args_schema=GetMeetingTranscriptArgs)
def get_meeting_transcript(
    conference_record_name: str,
    runtime: ToolRuntime[SessionContext],
) -> str:
    """Fetch the transcript of a finished Google Meet call by its conference
    record name (from list_meeting_records), joining all transcript entries
    into readable speaker: text lines.

    Transcription must have been enabled for the call and requires a
    Workspace edition that supports it (Business Standard/Plus, Enterprise,
    Education Plus) — returns a clear message if none is available.
    """
    try:
        client = _get_composio_client(runtime.context)
        acct_id = _meet_account_id(runtime.context)
    except RuntimeError as exc:
        return f"ERROR: {exc}"

    try:
        transcripts_result = client.tools.execute(
            "GOOGLEMEET_GET_TRANSCRIPTS_BY_CONFERENCE_RECORD_ID",
            arguments={"conference_record_name": conference_record_name},
            connected_account_id=acct_id,
            version=_TOOLKIT_VERSION,
        )
    except Exception as exc:
        return f"ERROR: Failed to fetch transcripts: {exc}."

    err = _composio_error(transcripts_result)
    if err:
        return err

    raw = getattr(transcripts_result, "data", None) or {}
    transcripts = raw.get("transcripts") if isinstance(raw, dict) else None
    transcripts = transcripts or []
    if not transcripts:
        return (
            "No transcript is available for this meeting. Transcription may not have "
            "been enabled, or the workspace edition doesn't support it."
        )

    lines: list[str] = []
    for transcript in transcripts:
        transcript_name = transcript.get("name", "")
        if not transcript_name:
            continue
        try:
            entries_result = client.tools.execute(
                "GOOGLEMEET_LIST_TRANSCRIPT_ENTRIES",
                arguments={"transcript_name": transcript_name},
                connected_account_id=acct_id,
                version=_TOOLKIT_VERSION,
            )
        except Exception as exc:
            lines.append(f"[ERROR fetching entries for {transcript_name}: {exc}]")
            continue
        entries_raw = getattr(entries_result, "data", None) or {}
        entries = entries_raw.get("transcript_entries") if isinstance(entries_raw, dict) else None
        for entry in entries or []:
            speaker = entry.get("participant") or entry.get("speaker") or "Speaker"
            text = entry.get("text", "")
            if text:
                lines.append(f"{speaker}: {text}")

    if not lines:
        return "Transcript exists but contains no entries yet (it may still be processing)."
    return "\n".join(lines)


class GetMeetingRecordingsArgs(BaseModel):
    conference_record_name: str


@tool(args_schema=GetMeetingRecordingsArgs)
def get_meeting_recordings(
    conference_record_name: str,
    runtime: ToolRuntime[SessionContext],
) -> str:
    """Fetch recording file links (saved to Google Drive) for a finished
    Google Meet call by its conference record name (from list_meeting_records).

    Recording must have been enabled for the call and requires a supporting
    Workspace edition — returns a clear message if none is available. Files
    may take a few minutes to appear after the meeting ends.
    """
    try:
        client = _get_composio_client(runtime.context)
        acct_id = _meet_account_id(runtime.context)
    except RuntimeError as exc:
        return f"ERROR: {exc}"

    try:
        result = client.tools.execute(
            "GOOGLEMEET_GET_RECORDINGS_BY_CONFERENCE_RECORD_ID",
            arguments={"conference_record_name": conference_record_name},
            connected_account_id=acct_id,
            version=_TOOLKIT_VERSION,
        )
    except Exception as exc:
        return f"ERROR: Failed to fetch recordings: {exc}."

    err = _composio_error(result)
    if err:
        return err

    raw = getattr(result, "data", None) or {}
    recordings = raw.get("recordings") if isinstance(raw, dict) else None
    recordings = recordings or []
    if not recordings:
        return (
            "No recording is available for this meeting. Recording may not have been "
            "enabled, the workspace edition doesn't support it, or it's still processing."
        )

    lines = ["Recordings:"]
    for rec in recordings:
        drive = rec.get("drive_destination") or {}
        file_id = drive.get("file") or drive.get("file_id") or ""
        export_uri = drive.get("export_uri", "")
        lines.append(f"  - Drive file: {file_id}" + (f"  {export_uri}" if export_uri else ""))
    return "\n".join(lines)


class ListMeetingParticipantsArgs(BaseModel):
    conference_record_name: str


@tool(args_schema=ListMeetingParticipantsArgs)
def list_meeting_participants(
    conference_record_name: str,
    runtime: ToolRuntime[SessionContext],
) -> str:
    """List participants who joined a finished Google Meet call, given its
    conference record name (from list_meeting_records).

    Useful for confirming who from the client side actually attended before
    summarizing the meeting into a proposal or WBS note.
    """
    try:
        client = _get_composio_client(runtime.context)
        acct_id = _meet_account_id(runtime.context)
    except RuntimeError as exc:
        return f"ERROR: {exc}"

    try:
        result = client.tools.execute(
            "GOOGLEMEET_LIST_PARTICIPANTS",
            arguments={"conference_record_name": conference_record_name},
            connected_account_id=acct_id,
            version=_TOOLKIT_VERSION,
        )
    except Exception as exc:
        return f"ERROR: Failed to list participants: {exc}."

    err = _composio_error(result)
    if err:
        return err

    raw = getattr(result, "data", None) or {}
    participants = raw.get("participants") if isinstance(raw, dict) else None
    participants = participants or []
    if not participants:
        return "No participant records found for this meeting."

    lines = ["Participants:"]
    for p in participants:
        identity = (
            p.get("signedin_user", {}).get("display_name")
            or p.get("anonymous_user", {}).get("display_name")
            or p.get("phone_user", {}).get("display_name")
            or "Unknown"
        )
        lines.append(f"  - {identity}")
    return "\n".join(lines)
