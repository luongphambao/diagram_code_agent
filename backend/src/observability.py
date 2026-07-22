"""Structured logging context (improvement plan §1.4).

Threads request_id/thread_id/run_id/render_job_id/sandbox_id through every log
line for the duration of a request, using the same contextvars pattern already
established for per-thread workspace binding (see runtime/backends.py's
``_current_workspace``). Without this, correlating log lines for one
problematic run means grepping unstructured prose and hoping the thread_id
happens to appear in the message text.

Deliberately excludes user identity from the default bound context — the
improvement plan explicitly says default logs must not include full uploaded
documents, generated code, or secrets; an email isn't a secret, but binding
every caller's identity into every log line by default is more PII exposure
than this pass needs. Callers that specifically need it can pass it as a
normal ``logger.info("...", extra={"user": email})`` call instead.

contextvars propagate automatically across ``await`` and ``asyncio.create_task``,
but NOT into a separate OS thread spawned via ``loop.run_in_executor`` unless
explicitly copied — most of this codebase's logging happens on the async path,
so plain ``with bind_context(...):`` covers it.
"""

from __future__ import annotations

import contextvars
import logging
import uuid
from contextlib import contextmanager

_CONTEXT: contextvars.ContextVar[dict] = contextvars.ContextVar("log_context", default={})

# Keep in sync with health_checks.version_info's field names where they overlap
# (app_version) so a log line and a /version response describe the same build.
FIELDS = ("request_id", "thread_id", "run_id", "render_job_id", "sandbox_id")


class ContextFilter(logging.Filter):
    """Injects the current bound context as record attributes, so a format
    string referencing e.g. ``%(thread_id)s`` never KeyErrors — unset fields
    render as ``"-"``."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _CONTEXT.get()
        for field in FIELDS:
            setattr(record, field, ctx.get(field, "-"))
        return True


def set_context(**fields: str) -> contextvars.Token:
    """Manual set/reset pair for call sites that can't use a ``with`` block —
    e.g. an async generator whose body already manages another contextvar
    (``current_workspace()``, see runtime/backends.py) via a token stashed
    across many ``yield`` statements and reset in one shared ``finally:``.
    Prefer :func:`bind_context` (the context-manager form) everywhere else.
    """
    current = _CONTEXT.get()
    updates = {k: v for k, v in fields.items() if v}
    return _CONTEXT.set({**current, **updates})


def reset_context(token: contextvars.Token) -> None:
    _CONTEXT.reset(token)


@contextmanager
def bind_context(**fields: str):
    """Bind request-scoped fields for the duration of the ``with`` block.

    Nested calls extend (not replace) the current context — e.g. binding
    ``render_job_id`` inside a block that already bound ``thread_id``/``run_id``
    keeps all three for any logging inside the nested block, and the outer
    binding is restored on exit regardless of which fields changed.

    ``None``/empty values are dropped rather than overwriting an existing
    binding with a blank, so an optional field a caller doesn't have yet
    doesn't erase one already set higher up the call stack.
    """
    current = _CONTEXT.get()
    updates = {k: v for k, v in fields.items() if v}
    token = _CONTEXT.set({**current, **updates})
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def new_id() -> str:
    """A short, log-friendly correlation id (not a security token — don't use
    this for anything that needs to be unguessable)."""
    return uuid.uuid4().hex[:12]


def current_context() -> dict:
    """A snapshot of the currently bound fields (for tests / debugging)."""
    return dict(_CONTEXT.get())


LOG_FORMAT = "%(asctime)s  [req=%(request_id)s thread=%(thread_id)s run=%(run_id)s]  %(message)s"
