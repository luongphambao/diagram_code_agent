"""External service integrations (Composio Gmail + Calendar)."""

from .calendar import create_client_meeting, propose_meeting_slots
from .email import send_architecture_report_email

__all__ = [
    "send_architecture_report_email",
    "propose_meeting_slots",
    "create_client_meeting",
]
