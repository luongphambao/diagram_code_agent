"""Renderer registry — the single place a new diagram family (sequence, erd,
state_machine, c4, ...) registers into the render pipeline (improvement plan:
typed-diagram foundation).

Design goal: additive, zero regression risk. `build_tree` (topology.py) and
`_render_native_from_spec` (tools/rendering_tools.py) keep their existing
inline dispatch for "architecture" / "bpmn" / exotic-topology / "refined"
UNCHANGED — those code paths never read `spec["kind"]` and nothing here alters
their behavior. This registry is consulted ONLY when a spec carries an
explicit `spec["kind"]` that resolves to a registered entry — which happens
for NEW diagram families the new per-kind gate tools write, never for
existing Blueprint/ProcessBlueprint-derived specs.

Two renderer backends:
- "native": a `tree_builder(spec, flat, plan) -> (Diagram, root)` function,
  following the exact `build_tree` return contract (BPMN's `_build_bpmn_tree`
  is the model). Registered by the kind's own `prettygraph/native/<kind>.py`
  module.
- "codegen": no `tree_builder` — the kind is rendered by generating a
  `diagrams` (mingrammer) Python program executed through the existing
  `render_diagram` sandbox path instead of the native engine (e.g. C4, which
  has a ready-made `diagrams.c4` node set). `tools/rendering_tools.py` checks
  `backend == "codegen"` to skip the native pre-render entirely for these kinds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

# Callable contract: (spec: dict, *, flat: bool, plan: dict | None) -> tuple[Diagram, dict]
TreeBuilder = Callable[..., tuple[object, dict]]
# Callable contract: (spec: dict) -> tuple[list[str], list[tuple[str, str]]]
# Returns (expected_ids, expected_edge_pairs) fed to validate_drawio.check_semantic_preservation.
SemanticIdsFn = Callable[[dict], tuple[list, list]]


@dataclass(frozen=True)
class RendererEntry:
    """One diagram kind's renderer registration."""

    kind: str
    backend: str  # "native" | "codegen"
    tree_builder: Optional[TreeBuilder] = None
    # production_scorecard/stats label — set so score bars that don't apply to
    # this kind (icon coverage, zone nesting, ...) are skipped, mirroring how
    # the BPMN branch sets stats["style_preset"] = "bpmn" today.
    style_preset_label: str = ""
    semantic_ids_fn: Optional[SemanticIdsFn] = None
    # domain/validation/diagram_lint.py linter key for this kind, if any.
    lint_kind: str = ""


RENDERERS: dict[str, RendererEntry] = {}


def register(entry: RendererEntry) -> None:
    """Register (or replace) a renderer entry for `entry.kind`."""
    RENDERERS[entry.kind] = entry


def get(kind: str) -> Optional[RendererEntry]:
    """Look up a registered renderer entry by kind, or None if unregistered."""
    if not kind:
        return None
    return RENDERERS.get(str(kind).lower())


def resolve_native_kind(spec: dict) -> Optional[str]:
    """Return the explicit `spec["kind"]` IFF it names a registered NATIVE
    renderer with a `tree_builder` — the only case where callers should divert
    from the legacy inline dispatch in `build_tree`/`_render_native_from_spec`.

    Returns None for every spec that doesn't opt in this way (including all
    specs from the existing architecture/BPMN flows, which never set
    `spec["kind"]`), so existing behavior is untouched.
    """
    kind = str(spec.get("kind") or "").lower()
    if not kind:
        return None
    entry = RENDERERS.get(kind)
    if entry is not None and entry.backend == "native" and entry.tree_builder is not None:
        return kind
    return None


__all__ = ["RendererEntry", "RENDERERS", "register", "get", "resolve_native_kind"]
