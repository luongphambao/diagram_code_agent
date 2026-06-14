"""Composio-based Google Calendar tools for scheduling client meetings.

Flow:
  1. propose_meeting_slots  — fetches free slots, then interrupt()s to let the
     user visually pick one on the frontend.  Uses mid-execution interrupt()
     so Composio runs BEFORE the gate, not after.
  2. create_client_meeting  — interrupt_on gate; shows the confirmed slot for
     final approval, then creates the Calendar event + optional Google Meet link.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from langchain_core.tools import tool
from langgraph.types import interrupt
from pydantic import BaseModel


_DEFAULT_TZ = "Asia/Ho_Chi_Minh"


def _get_composio_client():
    try:
        import composio  # type: ignore[import]
    except ImportError:
        raise RuntimeError(
            "composio package is not installed. Run: pip install composio-langchain"
        )
    api_key = os.environ.get("COMPOSIO_API_KEY", "")
    if not api_key:
        raise RuntimeError("COMPOSIO_API_KEY environment variable is not set.")
    return composio.Composio(api_key=api_key)


def _calendar_account_id() -> str:
    acct = os.environ.get("GOOGLE_CALENDAR_CONNECTED_ACCOUNT_ID", "")
    if not acct:
        raise RuntimeError(
            "GOOGLE_CALENDAR_CONNECTED_ACCOUNT_ID is not set. "
            "Run `composio add googlecalendar` to connect your Google Calendar, "
            "then set this env var to the returned connected account ID."
        )
    return acct


def _fmt_slot(start_dt: datetime, end_dt: datetime) -> dict:
    return {
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "display_day": start_dt.strftime("%A, %d %b %Y"),
        "display_time": f"{start_dt.strftime('%H:%M')} – {end_dt.strftime('%H:%M')}",
    }


# ---------------------------------------------------------------------------
# Tool 1: propose_meeting_slots — mid-execution interrupt(), user picks a slot
# ---------------------------------------------------------------------------

class ProposeMeetingSlotsArgs(BaseModel):
    date_range_days: int = 5
    duration_minutes: int = 60
    timezone: str = _DEFAULT_TZ
    working_hours_start: str = "09:00"
    working_hours_end: str = "17:00"
    calendar_id: str = "primary"
    context: str = ""   # optional: reason for the meeting, shown in slot picker


@tool(args_schema=ProposeMeetingSlotsArgs)
def propose_meeting_slots(
    date_range_days: int = 5,
    duration_minutes: int = 60,
    timezone: str = _DEFAULT_TZ,
    working_hours_start: str = "09:00",
    working_hours_end: str = "17:00",
    calendar_id: str = "primary",
    context: str = "",
) -> str:
    """Check Google Calendar for free time and let the user pick a meeting slot.

    First queries Google Calendar via Composio to find available windows
    within working hours over the next N days.  Then PAUSES (interrupt) so
    the frontend can show the slots as selectable cards — the user clicks one.
    On resume the tool returns the chosen start/end datetimes so the agent
    can call create_client_meeting with those values.

    Use this whenever the user asks to schedule, check availability, or pick
    a meeting time.  Call create_client_meeting afterward to confirm + book.
    """
    try:
        client = _get_composio_client()
        acct_id = _calendar_account_id()
    except RuntimeError as exc:
        return f"ERROR: {exc}"

    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    wh_start_h, wh_start_m = int(working_hours_start.split(":")[0]), int(working_hours_start.split(":")[1])
    wh_end_h, wh_end_m = int(working_hours_end.split(":")[0]), int(working_hours_end.split(":")[1])

    search_from = (now + timedelta(days=1)).replace(
        hour=wh_start_h, minute=wh_start_m, second=0, microsecond=0
    )
    search_to = search_from + timedelta(days=date_range_days)

    # --- 1. Fetch free slots from Composio ---
    try:
        result = client.tools.execute(
            "GOOGLECALENDAR_FIND_FREE_SLOTS",
            arguments={
                "time_min": search_from.isoformat(),
                "time_max": search_to.isoformat(),
                "duration": duration_minutes,
                "timezone": timezone,
                "calendar_id": calendar_id,
            },
            connected_account_id=acct_id,
        )
    except Exception as exc:
        return (
            f"ERROR: Failed to query Google Calendar free/busy: {exc}. "
            "Check that Google Calendar is connected via Composio."
        )

    if hasattr(result, "error") and result.error:
        return f"ERROR: Composio returned: {result.error}"

    raw = getattr(result, "data", None) or {}
    raw_slots: list = []
    if isinstance(raw, dict):
        raw_slots = raw.get("free_slots") or raw.get("available_slots") or []
    elif isinstance(raw, list):
        raw_slots = raw

    # Build a clean, normalised list of slots filtered to working hours
    slots: list[dict] = []
    for s in raw_slots:
        start_str = s.get("start") or s.get("start_time") or ""
        end_str = s.get("end") or s.get("end_time") or ""
        if not start_str:
            continue
        try:
            sd = datetime.fromisoformat(start_str).astimezone(tz)
            ed = (
                datetime.fromisoformat(end_str).astimezone(tz)
                if end_str
                else sd + timedelta(minutes=duration_minutes)
            )
        except ValueError:
            continue
        # keep only slots that start within working hours
        if (sd.hour, sd.minute) >= (wh_start_h, wh_start_m) and \
           (sd.hour, sd.minute) < (wh_end_h, wh_end_m):
            slots.append(_fmt_slot(sd, ed))
        if len(slots) >= 8:
            break

    if not slots:
        # Fallback: synthesise suggestions at standard working-hour blocks
        fallback_hours = [9, 10, 11, 14, 15, 16]
        for day_offset in range(1, date_range_days + 1):
            for hour in fallback_hours:
                if len(slots) >= 6:
                    break
                sd = (now + timedelta(days=day_offset)).replace(
                    hour=hour, minute=0, second=0, microsecond=0
                )
                if sd.weekday() < 5:  # Mon–Fri only
                    slots.append(_fmt_slot(sd, sd + timedelta(minutes=duration_minutes)))
            if len(slots) >= 6:
                break

    # --- 2. Interrupt — frontend shows slot picker, user picks one ---
    response = interrupt({
        "type": "slot_picker",
        "slots": slots,
        "duration_minutes": duration_minutes,
        "timezone": timezone,
        "context": context,
    })

    # --- 3. Resume — unpack user's decision ---
    decisions = response.get("decisions", [{}]) if isinstance(response, dict) else [{}]
    d = decisions[0] if decisions else {}

    if d.get("type") != "approve":
        return "User cancelled slot selection. Ask if they'd like to try different dates or times."

    selected = d.get("selected_slot") or {}
    start_iso = selected.get("start", "")
    end_iso = selected.get("end", "")
    display = selected.get("display_day", "") + " " + selected.get("display_time", "")

    if not start_iso:
        return "No slot was returned. Ask the user to pick again."

    return (
        f"User selected: {display.strip()}\n"
        f"  start_datetime: {start_iso}\n"
        f"  end_datetime:   {end_iso}\n"
        f"  timezone:       {timezone}\n\n"
        "Now call create_client_meeting with these start_datetime / end_datetime values "
        "along with the client's email and meeting title."
    )


# ---------------------------------------------------------------------------
# Tool 2: create_client_meeting — interrupt_on gate, final booking confirmation
# ---------------------------------------------------------------------------

class CreateMeetingArgs(BaseModel):
    title: str
    start_datetime: str   # ISO 8601 with tz offset, e.g. "2026-06-16T10:00:00+07:00"
    end_datetime: str
    attendee_email: str
    attendee_name: str = "Client"
    description: str = ""
    add_google_meet: bool = True
    timezone: str = _DEFAULT_TZ


@tool(args_schema=CreateMeetingArgs)
def create_client_meeting(
    title: str,
    start_datetime: str,
    end_datetime: str,
    attendee_email: str,
    attendee_name: str = "Client",
    description: str = "",
    add_google_meet: bool = True,
    timezone: str = _DEFAULT_TZ,
) -> str:
    """Create a Google Calendar event for a confirmed client meeting slot.

    Adds the event to the connected Google Calendar, emails a calendar invite
    to the client, and optionally generates a Google Meet video link.

    Always call propose_meeting_slots first so the user has already picked the
    time before this tool is called.  This tool PAUSES for final approval
    (interrupt_on gate) before creating the event.
    """
    try:
        client = _get_composio_client()
        acct_id = _calendar_account_id()
    except RuntimeError as exc:
        return f"ERROR: {exc}"

    try:
        tz = ZoneInfo(timezone)
        start_dt = datetime.fromisoformat(start_datetime).astimezone(tz)
        end_dt = datetime.fromisoformat(end_datetime).astimezone(tz)
        duration_min = int((end_dt - start_dt).total_seconds() / 60)
    except Exception as exc:
        return f"ERROR: Invalid datetime format: {exc}. Use ISO 8601, e.g. 2026-06-16T10:00:00+07:00"

    meet_desc = description
    if add_google_meet:
        suffix = "\n\nA Google Meet video link will be included in the calendar invite."
        meet_desc = (description + suffix) if description else suffix.strip()

    try:
        result = client.tools.execute(
            "GOOGLECALENDAR_CREATE_EVENT",
            arguments={
                "calendar_id": "primary",
                "summary": title,
                "description": meet_desc,
                "start_datetime": start_datetime,
                "end_datetime": end_datetime,
                "timezone": timezone,
                "attendees": [attendee_email],
                "create_meeting_room": add_google_meet,
            },
            connected_account_id=acct_id,
        )
    except Exception as exc:
        return (
            f"ERROR: Failed to create calendar event via Composio: {exc}. "
            "Check that Google Calendar is connected."
        )

    if hasattr(result, "error") and result.error:
        return f"ERROR: Composio returned: {result.error}"

    raw = getattr(result, "data", None) or {}
    event_link = ""
    meet_link = ""
    if isinstance(raw, dict):
        event_link = raw.get("htmlLink") or raw.get("event_link") or raw.get("link") or ""
        conf = raw.get("conferenceData") or {}
        for ep in (conf.get("entryPoints") or []):
            if ep.get("entryPointType") == "video":
                meet_link = ep.get("uri", "")
                break

    parts = [
        f"Meeting scheduled: \"{title}\"",
        f"  Date: {start_dt.strftime('%A, %d %b %Y')}",
        f"  Time: {start_dt.strftime('%H:%M')} – {end_dt.strftime('%H:%M')} ({timezone})",
        f"  Duration: {duration_min} min",
        f"  Attendee: {attendee_name} <{attendee_email}>",
    ]
    if event_link:
        parts.append(f"  Calendar link: {event_link}")
    if meet_link:
        parts.append(f"  Google Meet: {meet_link}")
    return "\n".join(parts)
