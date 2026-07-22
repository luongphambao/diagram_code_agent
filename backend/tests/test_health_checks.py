"""Tests for health_checks.py (improvement plan §1.5)."""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from health_checks import (
    check_model_config,
    check_modal,
    check_postgres,
    run_readiness_checks,
    version_info,
)


def _run(coro):
    return asyncio.run(coro)


class _FakeConn:
    def __init__(self, fail: bool = False):
        self._fail = fail

    async def execute(self, sql):
        if self._fail:
            raise RuntimeError("connection refused")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, fail: bool = False):
        self._fail = fail

    def connection(self):
        return _FakeConn(self._fail)


# --- check_postgres -----------------------------------------------------------


def test_check_postgres_ok_when_pool_none():
    result = _run(check_postgres(None))
    assert result["ok"] is True
    assert "note" in result


def test_check_postgres_ok_when_query_succeeds():
    result = _run(check_postgres(_FakePool(fail=False)))
    assert result == {"ok": True}


def test_check_postgres_fails_on_error():
    result = _run(check_postgres(_FakePool(fail=True)))
    assert result["ok"] is False
    assert "connection refused" in result["error"]


# --- check_modal ---------------------------------------------------------------


def test_check_modal_skipped_for_local_provider(monkeypatch):
    monkeypatch.setenv("SANDBOX_PROVIDER", "local")
    result = _run(check_modal())
    assert result["ok"] is True
    assert "local" in result["note"]


def test_check_modal_ok_when_lookup_succeeds(monkeypatch):
    monkeypatch.setenv("SANDBOX_PROVIDER", "modal")
    fake_modal = types.SimpleNamespace(
        App=types.SimpleNamespace(lookup=lambda name, create_if_missing=True: object())
    )
    monkeypatch.setitem(sys.modules, "modal", fake_modal)
    result = _run(check_modal())
    assert result == {"ok": True}


def test_check_modal_fails_when_lookup_raises(monkeypatch):
    monkeypatch.setenv("SANDBOX_PROVIDER", "modal")

    def _raise(name, create_if_missing=True):
        raise RuntimeError("invalid token")

    fake_modal = types.SimpleNamespace(App=types.SimpleNamespace(lookup=_raise))
    monkeypatch.setitem(sys.modules, "modal", fake_modal)
    result = _run(check_modal())
    assert result["ok"] is False
    assert "invalid token" in result["error"]


# --- check_model_config ---------------------------------------------------------


def test_check_model_config_ok_with_openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert check_model_config() == {"ok": True}


def test_check_model_config_ok_with_anthropic_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert check_model_config() == {"ok": True}


def test_check_model_config_fails_with_no_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = check_model_config()
    assert result["ok"] is False


# --- run_readiness_checks -------------------------------------------------------


def test_run_readiness_checks_all_ok(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SANDBOX_PROVIDER", "local")
    ok, checks = _run(run_readiness_checks(None))
    assert ok is True
    assert checks["postgres"]["ok"] is True
    assert checks["modal"]["ok"] is True
    assert checks["model_config"]["ok"] is True


def test_run_readiness_checks_false_if_any_check_fails(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("SANDBOX_PROVIDER", "local")
    ok, checks = _run(run_readiness_checks(None))
    assert ok is False
    assert checks["model_config"]["ok"] is False


# --- version_info ----------------------------------------------------------------


def test_version_info_defaults(monkeypatch):
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("BUILD_TIME", raising=False)
    monkeypatch.setenv("SANDBOX_PROVIDER", "modal")
    info = version_info(app_version="3.0.0", auth_mode="header")
    assert info["version"] == "3.0.0"
    assert info["git_sha"] == "unknown"
    assert info["build_time"] == "unknown"
    assert info["auth_mode"] == "header"
    assert info["sandbox_provider"] == "modal"
    assert info["api_schema_version"]
    assert info["solution_schema_version"]


def test_version_info_reads_build_env(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc1234")
    monkeypatch.setenv("BUILD_TIME", "2026-07-22T00:00:00Z")
    info = version_info(app_version="3.0.0", auth_mode="bearer")
    assert info["git_sha"] == "abc1234"
    assert info["build_time"] == "2026-07-22T00:00:00Z"
