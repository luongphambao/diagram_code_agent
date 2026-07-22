"""Tests for config.cors.resolve_allowed_origins (improvement plan §0.5).

Kept separate from server.py (which pulls in the full agent/LangChain
import chain at module scope) so the fail-closed CORS behavior is testable
in isolation.
"""

from __future__ import annotations

import pytest

from config.cors import CorsConfigError, resolve_allowed_origins


def test_production_without_origins_fails_closed():
    with pytest.raises(CorsConfigError, match="production"):
        resolve_allowed_origins("production", "")


def test_production_with_origins_returns_them():
    origins = resolve_allowed_origins("production", "https://app.example.com, https://admin.example.com")
    assert origins == ["https://app.example.com", "https://admin.example.com"]


def test_production_rejects_whitespace_only_origins():
    with pytest.raises(CorsConfigError):
        resolve_allowed_origins("production", "   ,  ")


def test_development_without_origins_uses_local_dev_default():
    origins = resolve_allowed_origins("development", "")
    assert origins  # non-empty
    assert "*" not in origins  # never a wildcard, even by default
    assert all(o.startswith("http://localhost") or o.startswith("http://127.0.0.1") for o in origins)


def test_development_with_origins_uses_them_not_the_default():
    origins = resolve_allowed_origins("development", "https://staging.example.com")
    assert origins == ["https://staging.example.com"]


def test_app_env_is_case_insensitive():
    with pytest.raises(CorsConfigError):
        resolve_allowed_origins("PRODUCTION", "")
