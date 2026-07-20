"""Change-impact diff for the Canonical Solution Model (docx §13.1).

Pure functions, NO I/O — given two :class:`~csm.SolutionModel` snapshots (the
previous revision and the current one) it reports what was added, removed and
changed, per entity type and over the trace links. The agent surfaces this via the
``query_change_impact`` tool after the user revises a requirement, so the impact of
the change is visible instead of silently re-rolling the whole solution.

The diff is keyed by the CSM's stable IDs (``REQ-1``, ``WBS-3``, ...), so a renamed
node is a *change*, not an add+remove. CSM entities carry no timestamps, so a plain
``model_dump()`` equality is already stable across re-runs (the volatile
``created_at``/``revision`` live on the model, not the entities).
"""

from __future__ import annotations

from typing import Iterable

from .csm import SolutionModel, TraceLink, _Entity

# Entity collections compared, in report order. Each is a (label, attribute) pair.
_ENTITY_TYPES = [
    ("requirements", "requirements"),
    ("constraints", "constraints"),
    ("assumptions", "assumptions"),
    ("decisions", "decisions"),
    ("components", "components"),
    ("risks", "risks"),
    ("work_items", "work_items"),
]


def diff_entities(old_list: Iterable[_Entity], new_list: Iterable[_Entity]) -> dict:
    """Compare two entity lists keyed by ``.id``.

    Returns ``{"added": [dump...], "removed": [dump...], "changed": [{id, old, new}...]}``
    where each dump is ``entity.model_dump()``. An id present in both whose content
    differs is reported in ``changed`` (never as add+remove).
    """
    old_by_id = {e.id: e for e in old_list}
    new_by_id = {e.id: e for e in new_list}
    added = [new_by_id[i].model_dump() for i in new_by_id if i not in old_by_id]
    removed = [old_by_id[i].model_dump() for i in old_by_id if i not in new_by_id]
    changed = []
    for i in old_by_id:
        if i in new_by_id:
            old_d = old_by_id[i].model_dump()
            new_d = new_by_id[i].model_dump()
            if old_d != new_d:
                changed.append({"id": i, "old": old_d, "new": new_d})
    return {"added": added, "removed": removed, "changed": changed}


def _link_key(link: TraceLink) -> tuple[str, str, str]:
    return (link.from_id, link.relation, link.to_id)


def diff_trace_links(old_links: Iterable[TraceLink], new_links: Iterable[TraceLink]) -> dict:
    """Diff trace links by the ``(from_id, relation, to_id)`` triple.

    Returns ``{"added": [dump...], "removed": [dump...]}``. A link is identified by
    its endpoints+relation, so confidence/provenance changes on the same edge are
    not reported (they are not change-impact relevant).
    """
    old_by_key = {_link_key(l): l for l in old_links}
    new_by_key = {_link_key(l): l for l in new_links}
    added = [new_by_key[k].model_dump() for k in new_by_key if k not in old_by_key]
    removed = [old_by_key[k].model_dump() for k in old_by_key if k not in new_by_key]
    return {"added": added, "removed": removed}


def diff_solution_models(old: SolutionModel, new: SolutionModel) -> dict:
    """Top-level diff: per entity-type deltas + trace-link deltas + a summary.

    Returns a dict with one key per entity type (each a :func:`diff_entities` result),
    a ``trace_links`` key (:func:`diff_trace_links`), a ``revision`` ``{from, to}``
    block and a ``summary`` of total added/removed/changed counts.
    """
    out: dict = {"revision": {"from": old.revision, "to": new.revision}}
    n_added = n_removed = n_changed = 0
    for label, attr in _ENTITY_TYPES:
        d = diff_entities(getattr(old, attr), getattr(new, attr))
        out[label] = d
        n_added += len(d["added"])
        n_removed += len(d["removed"])
        n_changed += len(d["changed"])
    links = diff_trace_links(old.trace_links, new.trace_links)
    out["trace_links"] = links
    out["summary"] = {
        "entities_added": n_added,
        "entities_removed": n_removed,
        "entities_changed": n_changed,
        "links_added": len(links["added"]),
        "links_removed": len(links["removed"]),
    }
    return out
