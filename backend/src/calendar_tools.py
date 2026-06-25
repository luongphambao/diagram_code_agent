# Superseded by integrations/calendar.py — this shim preserves backward compatibility.
from integrations.calendar import (  # noqa: F401
    CreateMeetingArgs,
    ProposeMeetingSlotsArgs,
    _calendar_account_id,
    _fmt_slot,
    _get_composio_client,
    create_client_meeting,
    propose_meeting_slots,
)
