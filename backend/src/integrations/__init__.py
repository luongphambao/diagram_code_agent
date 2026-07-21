"""External service integrations (Composio Gmail + Calendar + Meet)."""

from .calendar import create_client_meeting, propose_meeting_slots
from .email import send_email
from .meet import (
    get_meeting_recordings,
    get_meeting_transcript,
    list_meeting_participants,
    list_meeting_records,
)

__all__ = [
    "send_email",
    "propose_meeting_slots",
    "create_client_meeting",
    "list_meeting_records",
    "get_meeting_transcript",
    "get_meeting_recordings",
    "list_meeting_participants",
]
