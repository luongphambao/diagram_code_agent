"""Per-run session context injected into tools via ``ToolRuntime``.

This is the deepagents "runtime context" mechanism: values here are passed at
invocation time (``AGENT.astream(..., context=SessionContext(...))``) and are
NOT placed in the model prompt. Tools read them through an injected
``runtime: ToolRuntime[SessionContext]`` parameter instead of reading the process
environment directly, which keeps secrets/account ids out of the prompt and lets
each session carry its own credentials. Runtime context propagates to subagents
automatically.

Every field defaults to empty so tools fall back to the process environment when
no context is supplied — behaviour is unchanged for callers that don't pass one.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SessionContext:
    """Session-scoped configuration available to tools via ``runtime.context``.

    Attributes:
        user_email: The requesting user's email; used as a default email recipient.
        composio_api_key: Composio API key override (falls back to ``COMPOSIO_API_KEY``).
        gmail_account_id: Composio connected Gmail account id for sending reports.
        calendar_account_id: Composio connected Google Calendar account id.
    """

    user_email: str = ""
    composio_api_key: str = ""
    gmail_account_id: str = ""
    calendar_account_id: str = ""
