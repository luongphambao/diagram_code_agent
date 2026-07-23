"""Sequence diagram internals — structural lint + the Pydantic-model-to-
render_spec projection (improvement plan MVP-3 phase 2, typed-diagram
foundation).

These are library functions, not an LLM-facing tool: the LLM authors a
sequence diagram code-first (see `prettygraph/sequence_dsl.py`), executed via
`tools/rendering_tools.py::render_typed_diagram`, which calls
`_build_sequence_render_spec` + (via `_render_native_from_spec`'s registry
dispatch) `lint_sequence` after validating the script's output against
`SequenceSpec` — same validation/render engine as the original structured
tool-call design, just called from a different entry point.
"""

from __future__ import annotations

from domain.validation.diagram_lint import LintReport, register_linter
from ..schemas.sequence import SequenceSpec


def _build_sequence_render_spec(spec: SequenceSpec) -> dict:
    """Flatten a SequenceSpec into the plain-dict render_spec
    `prettygraph.native.sequence.build_sequence_tree` consumes — the same
    Pydantic-model -> plain-dict projection role `_build_render_spec` plays
    for `Blueprint`."""
    return {
        "kind": "sequence",
        "title": spec.title,
        "participants": [{"id": p.id, "label": p.label, "kind": p.kind} for p in spec.participants],
        "messages": [
            {"order": m.order, "from": m.from_, "to": m.to, "label": m.label, "kind": m.kind}
            for m in spec.messages
        ],
        "fragments": [
            {"kind": f.kind, "condition": f.condition, "start_order": f.start_order, "end_order": f.end_order}
            for f in spec.fragments
        ],
        "activations": [
            {"participant": a.participant, "start_order": a.start_order, "end_order": a.end_order}
            for a in spec.activations
        ],
    }


def lint_sequence(spec: dict) -> LintReport:
    """Structural lint for a sequence render_spec — proposal §3's validation
    list: dangling participant refs, duplicate order, malformed/empty
    fragments, activations that end before they start, unpaired returns,
    orphan participants, and a diagram-width warning."""
    report = LintReport()
    participants = spec.get("participants", [])
    pids = [p.get("id") for p in participants if p.get("id")]
    pid_set = set(pids)
    for dup in sorted({p for p in pids if pids.count(p) > 1}):
        report.error("duplicate_participant", f"Participant id '{dup}' declared more than once.", dup)

    messages = spec.get("messages", [])
    order_counts: dict[int, int] = {}
    used_participants: set[str] = set()
    for m in messages:
        order = m.get("order")
        src, tgt = m.get("from"), m.get("to")
        ref = f"order={order}"
        if src not in pid_set:
            report.error(
                "unknown_participant", f"Message order={order}: from '{src}' is not a declared participant.", ref
            )
        else:
            used_participants.add(src)
        if tgt not in pid_set:
            report.error(
                "unknown_participant", f"Message order={order}: to '{tgt}' is not a declared participant.", ref
            )
        else:
            used_participants.add(tgt)
        if order is not None:
            order_counts[order] = order_counts.get(order, 0) + 1
    for order, count in order_counts.items():
        if count > 1:
            report.error(
                "duplicate_order", f"{count} messages share order={order} — each order must be unique.", f"order={order}"
            )

    for p in participants:
        pid = p.get("id")
        if pid and pid not in used_participants:
            report.warning(
                "orphan_participant", f"Participant '{pid}' ({p.get('label') or pid}) appears in no message.", pid
            )

    if len(pid_set) > 8:
        report.info("many_participants", f"{len(pid_set)} participants — diagram may render very wide.")

    order_set = set(order_counts)
    for frag in spec.get("fragments", []):
        lo, hi, kind = frag.get("start_order"), frag.get("end_order"), frag.get("kind")
        ref = f"{kind} [{lo}-{hi}]"
        if lo is None or hi is None or lo > hi:
            report.error("invalid_fragment_range", f"Fragment {ref}: start_order must be <= end_order.", ref)
            continue
        if not any(lo <= o <= hi for o in order_set):
            report.warning("empty_fragment", f"Fragment {ref} encloses no declared message.", ref)

    for act in spec.get("activations", []):
        lo, hi, pid = act.get("start_order"), act.get("end_order"), act.get("participant")
        ref = f"{pid} [{lo}-{hi}]"
        if pid not in pid_set:
            report.error("unknown_participant", f"Activation on unknown participant '{pid}'.", ref)
        if lo is None or hi is None or lo > hi:
            report.error(
                "invalid_activation_range", f"Activation {ref}: ends before it starts (start_order must be <= end_order).", ref
            )

    ordered = sorted(messages, key=lambda m: m.get("order") or 0)
    for m in ordered:
        if m.get("kind") != "return":
            continue
        src, tgt, order = m.get("from"), m.get("to"), m.get("order")
        has_request = any(
            (om.get("order") or 0) < (order or 0)
            and om.get("kind") in ("sync", "async")
            and om.get("from") == tgt
            and om.get("to") == src
            for om in ordered
        )
        if not has_request:
            report.warning(
                "unpaired_return",
                f"Return message order={order} ({src}->{tgt}) has no earlier request {tgt}->{src} to return from.",
                f"order={order}",
            )

    return report


register_linter("sequence", lint_sequence)


__all__ = ["lint_sequence", "_build_sequence_render_spec"]
