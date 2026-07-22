"""Tests for security.auth (improvement plan §0.6).

Pure unit tests against security/auth.py directly (not through server.py, whose
module-level imports pull in the full agent/LangChain stack — same rationale as
test_cors_config.py). require_identity only touches `request.headers` and
`request.json()`, so a minimal duck-typed fake stands in for a real
starlette.Request.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from security.auth import (
    AuthConfigError,
    Identity,
    parse_bearer_tokens,
    require_identity,
    resolve_auth_mode,
)


class _FakeRequest:
    def __init__(self, headers: dict | None = None, body=None):
        self.headers = headers or {}
        self._body = body

    async def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


def _run(coro):
    return asyncio.run(coro)


# --- resolve_auth_mode (fail-closed, mirrors config/cors.py) ----------------


def test_production_requires_header_or_bearer():
    with pytest.raises(AuthConfigError):
        resolve_auth_mode("production", "")
    with pytest.raises(AuthConfigError):
        resolve_auth_mode("production", "none")


def test_production_accepts_header_or_bearer():
    assert resolve_auth_mode("production", "header") == "header"
    assert resolve_auth_mode("production", "bearer") == "bearer"


def test_development_defaults_to_none():
    assert resolve_auth_mode("development", "") == "none"


def test_app_env_and_mode_are_case_insensitive():
    assert resolve_auth_mode("Production", "HEADER") == "header"


# --- parse_bearer_tokens -----------------------------------------------------


def test_parse_bearer_tokens_basic():
    tokens = parse_bearer_tokens("tok1:alice@co.com:architect,tok2:bob@co.com:pm")
    assert tokens["tok1"] == Identity(email="alice@co.com", role="architect")
    assert tokens["tok2"] == Identity(email="bob@co.com", role="pm")


def test_parse_bearer_tokens_role_optional():
    tokens = parse_bearer_tokens("tok1:alice@co.com")
    assert tokens["tok1"] == Identity(email="alice@co.com", role="")


def test_parse_bearer_tokens_ignores_malformed_entries():
    tokens = parse_bearer_tokens("garbage,,tok1:alice@co.com")
    assert "garbage" not in tokens
    assert tokens["tok1"].email == "alice@co.com"


def test_parse_bearer_tokens_empty_string():
    assert parse_bearer_tokens("") == {}


# --- require_identity: header mode ------------------------------------------


def test_header_mode_reads_identity(monkeypatch):
    monkeypatch.setattr("security.auth.AUTH_MODE", "header")
    monkeypatch.setattr("security.auth._HEADER_EMAIL", "X-Auth-Request-Email")
    monkeypatch.setattr("security.auth._HEADER_ROLE", "X-Auth-Request-Role")
    req = _FakeRequest(headers={
        "X-Auth-Request-Email": "alice@co.com",
        "X-Auth-Request-Role": "architect",
    })
    identity = _run(require_identity(req))
    assert identity == Identity(email="alice@co.com", role="architect")


def test_header_mode_missing_email_is_401(monkeypatch):
    monkeypatch.setattr("security.auth.AUTH_MODE", "header")
    monkeypatch.setattr("security.auth._HEADER_EMAIL", "X-Auth-Request-Email")
    req = _FakeRequest(headers={})
    with pytest.raises(HTTPException) as exc_info:
        _run(require_identity(req))
    assert exc_info.value.status_code == 401


# --- require_identity: bearer mode ------------------------------------------


def test_bearer_mode_matches_known_token(monkeypatch):
    monkeypatch.setattr("security.auth.AUTH_MODE", "bearer")
    monkeypatch.setattr(
        "security.auth._BEARER_TOKENS",
        {"secret-tok": Identity(email="svc@co.com", role="admin")},
    )
    req = _FakeRequest(headers={"Authorization": "Bearer secret-tok"})
    identity = _run(require_identity(req))
    assert identity == Identity(email="svc@co.com", role="admin")


def test_bearer_mode_unknown_token_is_401(monkeypatch):
    monkeypatch.setattr("security.auth.AUTH_MODE", "bearer")
    monkeypatch.setattr("security.auth._BEARER_TOKENS", {})
    req = _FakeRequest(headers={"Authorization": "Bearer nope"})
    with pytest.raises(HTTPException) as exc_info:
        _run(require_identity(req))
    assert exc_info.value.status_code == 401


def test_bearer_mode_missing_header_is_401(monkeypatch):
    monkeypatch.setattr("security.auth.AUTH_MODE", "bearer")
    monkeypatch.setattr("security.auth._BEARER_TOKENS", {"tok": Identity(email="a@b.com")})
    req = _FakeRequest(headers={})
    with pytest.raises(HTTPException):
        _run(require_identity(req))


# --- require_identity: none (dev fallback) ----------------------------------


def test_none_mode_prefers_header_if_present(monkeypatch):
    monkeypatch.setattr("security.auth.AUTH_MODE", "none")
    monkeypatch.setattr("security.auth._HEADER_EMAIL", "X-Auth-Request-Email")
    monkeypatch.setattr("security.auth._HEADER_ROLE", "X-Auth-Request-Role")
    req = _FakeRequest(headers={"X-Auth-Request-Email": "alice@co.com"})
    identity = _run(require_identity(req))
    assert identity.email == "alice@co.com"


def test_none_mode_falls_back_to_body_userEmail(monkeypatch):
    monkeypatch.setattr("security.auth.AUTH_MODE", "none")
    monkeypatch.setattr("security.auth._HEADER_EMAIL", "X-Auth-Request-Email")
    req = _FakeRequest(headers={}, body={"userEmail": "bob@co.com", "userRole": "pm"})
    identity = _run(require_identity(req))
    assert identity == Identity(email="bob@co.com", role="pm")


def test_none_mode_anonymous_when_nothing_supplied(monkeypatch):
    monkeypatch.setattr("security.auth.AUTH_MODE", "none")
    monkeypatch.setattr("security.auth._HEADER_EMAIL", "X-Auth-Request-Email")
    req = _FakeRequest(headers={}, body=None)  # .json() raises -> caught
    identity = _run(require_identity(req))
    assert identity.email == "dev@local"


def test_none_mode_ignores_non_dict_body(monkeypatch):
    monkeypatch.setattr("security.auth.AUTH_MODE", "none")
    monkeypatch.setattr("security.auth._HEADER_EMAIL", "X-Auth-Request-Email")
    req = _FakeRequest(headers={}, body=["not", "a", "dict"])
    identity = _run(require_identity(req))
    assert identity.email == "dev@local"


def test_identity_subject_defaults_to_email_or_anonymous():
    assert Identity(email="a@b.com").subject == "a@b.com"
    assert Identity(email="").subject == "anonymous"
