"""Identity resolution for a trusted-internal-org deployment (improvement plan §0.6).

This is deliberately NOT full multi-tenant SaaS auth: there is no user database, no
signup/login flow, no session cookie. The assumption (per the improvement plan's
chosen deployment context — "internal / one trusted organization") is that the
service sits behind either:

  - a reverse proxy / SSO gateway (oauth2-proxy, Authelia, Cloudflare Access, nginx
    ``auth_request``, ...) that has already authenticated the caller and forwards a
    verified identity via request headers, or
  - a small set of static bearer tokens issued out-of-band to internal callers.

Before this module, ``/agui``'s ``userEmail``/``userRole`` were read directly from
the client-supplied JSON body (see ``routers/chat.py``) — any caller could claim to
be anyone, including a role permitted to approve HITL gates
(``tools.ROLE_GATE_PERMISSIONS``). ``require_identity`` gives every route a
server-resolved :class:`Identity` instead. ``AUTH_MODE`` selects where that identity
comes from, and — mirroring ``config/cors.py``'s fail-closed pattern — refuses to
start in ``APP_ENV=production`` with a mode that trusts client input.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import HTTPException, Request

_VALID_PRODUCTION_MODES = {"header", "bearer"}


class AuthConfigError(RuntimeError):
    """Raised when auth cannot be configured safely for the current APP_ENV."""


@dataclass(frozen=True)
class Identity:
    """A server-resolved caller identity. ``role`` is one of
    ``tools.ROLE_GATE_PERMISSIONS``'s roles (architect/pm/lead/admin/...) or empty
    (permissive — see ``tools.can_approve``)."""

    email: str
    role: str = ""

    @property
    def subject(self) -> str:
        return self.email or "anonymous"


def resolve_auth_mode(app_env: str, auth_mode_raw: str) -> str:
    """Return the effective auth mode for *app_env* given the raw ``AUTH_MODE`` env
    value. Raises :class:`AuthConfigError` if ``app_env == "production"`` and the
    mode is not one that resolves identity from a source the client cannot forge
    (production must never trust a client-supplied body for identity)."""
    mode = (auth_mode_raw or "none").strip().lower()
    if app_env.strip().lower() == "production" and mode not in _VALID_PRODUCTION_MODES:
        raise AuthConfigError(
            "AUTH_MODE must be 'header' or 'bearer' when APP_ENV=production — a "
            "client-supplied body/role cannot be trusted for HITL gate approval or "
            "thread ownership. Refusing to start with an unauthenticated policy."
        )
    return mode


def parse_bearer_tokens(raw: str) -> dict[str, Identity]:
    """Parse ``AUTH_BEARER_TOKENS="token1:alice@co.com:architect,token2:bob@co.com:pm"``
    (comma-separated, matching this repo's ``ALLOWED_ORIGINS`` convention)."""
    tokens: dict[str, Identity] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":", 2)
        token = parts[0].strip()
        email = parts[1].strip() if len(parts) > 1 else ""
        role = parts[2].strip() if len(parts) > 2 else ""
        if token and email:
            tokens[token] = Identity(email=email, role=role)
    return tokens


_APP_ENV = os.getenv("APP_ENV", "development")
AUTH_MODE = resolve_auth_mode(_APP_ENV, os.getenv("AUTH_MODE", ""))
_HEADER_EMAIL = os.getenv("AUTH_HEADER_EMAIL", "X-Auth-Request-Email")
_HEADER_ROLE = os.getenv("AUTH_HEADER_ROLE", "X-Auth-Request-Role")
_BEARER_TOKENS = parse_bearer_tokens(os.getenv("AUTH_BEARER_TOKENS", ""))


async def _dev_body_identity(request: Request) -> tuple[str, str]:
    """Best-effort read of the legacy client-supplied ``userEmail``/``userRole``
    fields (dev fallback only — never reached in production, see
    :func:`resolve_auth_mode`). Starlette caches the parsed body after the first
    read, so this does not consume the body out from under the route handler's own
    ``await request.json()``."""
    try:
        body = await request.json()
    except Exception:
        return "", ""
    if not isinstance(body, dict):
        return "", ""
    return str(body.get("userEmail") or ""), str(body.get("userRole") or "")


async def require_identity(request: Request) -> Identity:
    """FastAPI dependency: resolve the caller's server-verified identity.

    - ``AUTH_MODE=header``: trusts the ``AUTH_HEADER_EMAIL``/``AUTH_HEADER_ROLE``
      request headers, set by a reverse proxy that already authenticated the
      caller. 401 if the email header is missing.
    - ``AUTH_MODE=bearer``: trusts ``Authorization: Bearer <token>`` matched
      against the static ``AUTH_BEARER_TOKENS`` map. 401 on a missing/unknown
      token.
    - ``AUTH_MODE=none`` (development only): falls back to identity headers if a
      caller supplies them (useful for exercising multiple identities locally via
      curl), else the legacy client-supplied ``userEmail``/``userRole`` body
      fields, else an anonymous dev identity. ``resolve_auth_mode`` refuses this
      mode in production.
    """
    if AUTH_MODE == "header":
        email = request.headers.get(_HEADER_EMAIL, "").strip()
        if not email:
            raise HTTPException(status_code=401, detail=f"Missing {_HEADER_EMAIL} header")
        return Identity(email=email, role=request.headers.get(_HEADER_ROLE, "").strip())

    if AUTH_MODE == "bearer":
        auth_header = request.headers.get("Authorization", "")
        token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
        identity = _BEARER_TOKENS.get(token) if token else None
        if identity is None:
            raise HTTPException(status_code=401, detail="Missing or invalid bearer token")
        return identity

    # AUTH_MODE == "none" — development fallback only (see resolve_auth_mode).
    header_email = request.headers.get(_HEADER_EMAIL, "").strip()
    if header_email:
        return Identity(email=header_email, role=request.headers.get(_HEADER_ROLE, "").strip())
    body_email, body_role = await _dev_body_identity(request)
    return Identity(email=body_email or "dev@local", role=body_role)
