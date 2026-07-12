"""Locks the load-bearing middleware + context-edit ORDER produced by
``agent._middleware()``.

These invariants are documented in ``_middleware()`` (and, after the Stage-2
refactor, in ``agent/middleware/``). They are load-bearing:

  * ``KeepLatestImagesEdit`` MUST precede ``InjectVisionAsUserEdit`` — it reduces
    the ToolMessage history to a single live image before the relay edit scans.
  * ``ToolArgCoercionMiddleware`` MUST precede ``DrawerReviseGateMiddleware`` —
    the gate assumes well-formed ``task`` args.
  * ``ModelCallLimitMiddleware`` uses ``exit_behavior="end"``; the ``task``
    ``ToolCallLimitMiddleware`` uses ``"continue"`` ("end" raises
    NotImplementedError with pending parallel calls).

This test is intentionally introspective (asserts the *type sequence* of the
assembled list) so that moving these classes into ``agent/middleware/`` during
the refactor cannot silently reorder or drop a layer.

Imports go through the top-level ``agent`` module, which stays a valid import
surface (real module now, re-export shim after Stage 2).
"""

from __future__ import annotations

import agent


def _names(mws):
    return [type(m).__name__ for m in mws]


def _edit_names(context_editing_mw):
    return [type(e).__name__ for e in context_editing_mw.edits]


# ---------------------------------------------------------------------------
# Middleware layer order
# ---------------------------------------------------------------------------

def test_default_middleware_order():
    """Base layers, no optional flags, no FALLBACK_MODEL env."""
    layers = agent._middleware()
    assert _names(layers) == [
        "ContextEditingMiddleware",
        "UsageLoggingMiddleware",
        "ModelCallLimitMiddleware",
        "ToolArgCoercionMiddleware",
    ]


def test_full_middleware_order():
    """All env-independent optional flags on → exact type sequence."""
    layers = agent._middleware(
        use_vision_relay=True,
        task_call_limit=3,
        use_drawer_revise_gate=True,
        use_phase_filter=True,
    )
    assert _names(layers) == [
        "ContextEditingMiddleware",
        "UsageLoggingMiddleware",
        "ModelCallLimitMiddleware",
        "ToolArgCoercionMiddleware",
        "VisionErrorFallbackMiddleware",
        "ToolCallLimitMiddleware",
        "DrawerReviseGateMiddleware",
        "PhaseToolFilterMiddleware",
        "PhasePromptFilterMiddleware",
    ]


def test_tool_arg_coercion_precedes_drawer_revise_gate():
    names = _names(agent._middleware(use_drawer_revise_gate=True))
    assert names.index("ToolArgCoercionMiddleware") < names.index("DrawerReviseGateMiddleware")


def test_exit_behaviors():
    layers = agent._middleware(task_call_limit=3)
    by_type = {type(m).__name__: m for m in layers}
    assert by_type["ModelCallLimitMiddleware"].exit_behavior == "end"
    assert by_type["ToolCallLimitMiddleware"].exit_behavior == "continue"


# ---------------------------------------------------------------------------
# Context-edit order (inside ContextEditingMiddleware)
# ---------------------------------------------------------------------------

def test_default_edit_order():
    ce = agent._middleware()[0]
    assert _edit_names(ce) == [
        "KeepLatestImagesEdit",
        "SanitizeToolTextBlocksEdit",
        "OffloadGateArgsEdit",
        "ClearToolUsesEdit",
    ]


def test_vision_relay_edit_order():
    ce = agent._middleware(use_vision_relay=True)[0]
    assert _edit_names(ce) == [
        "KeepLatestImagesEdit",
        "InjectVisionAsUserEdit",
        "SanitizeToolTextBlocksEdit",
        "OffloadGateArgsEdit",
        "ClearToolUsesEdit",
    ]


def test_keep_latest_images_precedes_inject_vision():
    ce = agent._middleware(use_vision_relay=True)[0]
    names = _edit_names(ce)
    assert names.index("KeepLatestImagesEdit") < names.index("InjectVisionAsUserEdit")
