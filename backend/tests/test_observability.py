"""Tests for observability.py (improvement plan §1.4)."""

from __future__ import annotations

import logging

from observability import (
    ContextFilter,
    bind_context,
    current_context,
    new_id,
    reset_context,
    set_context,
)


def test_current_context_empty_by_default():
    assert current_context() == {}


def test_bind_context_sets_and_restores():
    with bind_context(thread_id="t1", run_id="r1"):
        assert current_context() == {"thread_id": "t1", "run_id": "r1"}
    assert current_context() == {}


def test_bind_context_nesting_extends_not_replaces():
    with bind_context(thread_id="t1"):
        with bind_context(run_id="r1"):
            assert current_context() == {"thread_id": "t1", "run_id": "r1"}
        # Inner block's addition is gone, outer binding remains.
        assert current_context() == {"thread_id": "t1"}
    assert current_context() == {}


def test_bind_context_drops_empty_values():
    with bind_context(thread_id="t1", run_id="", request_id=None):
        assert current_context() == {"thread_id": "t1"}


def test_bind_context_does_not_overwrite_with_blank():
    with bind_context(thread_id="t1"):
        with bind_context(thread_id=""):
            # Empty string must not erase the outer binding.
            assert current_context() == {"thread_id": "t1"}


def test_set_context_and_reset_context_manual_pair():
    token = set_context(thread_id="t2")
    try:
        assert current_context() == {"thread_id": "t2"}
    finally:
        reset_context(token)
    assert current_context() == {}


def test_new_id_is_short_and_unique():
    a, b = new_id(), new_id()
    assert a != b
    assert len(a) == 12


def test_context_filter_injects_defaults_when_unbound():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    assert ContextFilter().filter(record) is True
    assert record.thread_id == "-"
    assert record.run_id == "-"
    assert record.request_id == "-"


def test_context_filter_injects_bound_values():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    with bind_context(thread_id="t3", run_id="r3"):
        ContextFilter().filter(record)
    assert record.thread_id == "t3"
    assert record.run_id == "r3"
    assert record.render_job_id == "-"
