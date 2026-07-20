"""Traceability sidecar — emit typed trace links between artifacts.

Generalizes `reporting._traceability` (which produced report *rows*) into a small
set of typed relationship edges (docx §6.2) written to `trace_links.json`:

    REQ  --satisfies-->  COMP        (requirement addressed by a component/cluster)
    WBS  --implements--> COMP/REQ    (work item builds a component / fulfils a req)

It does NOT introduce a central model — it derives links from the artifact files
that already exist, using the SAME soft-match semantics as the validator and the
report, so all three agree on what "covered" means. The sidecar is what later
powers change-impact ("which tasks/slides touch REQ-3?") without a big refactor.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from domain.validation.solution_validator import _as_list, _read_json, _soft_match


def _requirements(brief: dict[str, Any]) -> list[dict[str, str]]:
    """Stable-id requirement list. Honors an explicit `id` if present, else REQ-#."""
    out: list[dict[str, str]] = []
    n = 0
    for kind, key in (("functional", "functional_requirements"),
                      ("non-functional", "non_functional_requirements")):
        for item in _as_list(brief.get(key)):
            n += 1
            rid = ""
            text = item
            if isinstance(item, dict):
                rid = str(item.get("id") or "")
                text = item.get("statement") or item.get("text") or item.get("name") or ""
            out.append({"id": rid or f"REQ-{n}", "kind": kind, "text": str(text)})
    return out


def build_trace_links(
    brief: dict[str, Any],
    blueprint: dict[str, Any],
    wbs: dict[str, Any],
) -> dict[str, Any]:
    """Derive typed trace edges + a coverage summary from the three artifacts."""
    reqs = _requirements(brief)
    nodes = [n for n in _as_list(blueprint.get("nodes")) if isinstance(n, dict)]
    clusters = [c for c in _as_list(blueprint.get("clusters")) if isinstance(c, dict)]

    # name -> stable component id, for turning a soft-match hit back into an id.
    comp_by_name: dict[str, str] = {}
    for n in nodes:
        comp_by_name[str(n.get("label") or n.get("id") or "")] = f"COMP-{n.get('id') or n.get('label')}"
    for c in clusters:
        comp_by_name[str(c.get("label") or c.get("id") or "")] = f"CLUSTER-{c.get('id') or c.get('label')}"
    comp_names = list(comp_by_name.keys())

    links: list[dict[str, str]] = []

    # REQ --satisfies--> COMP/CLUSTER
    for r in reqs:
        for hit in _soft_match(r["text"], comp_names):
            links.append({"from": r["id"], "to": comp_by_name[hit],
                          "relation": "satisfies", "provenance": "deterministic"})

    # WBS --implements--> COMP or REQ
    req_by_text = {r["text"]: r["id"] for r in reqs}
    for it in _as_list(wbs.get("items")):
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or it.get("deliverable") or "")
        wid = f"WBS-{it.get('id') or it.get('ref_code') or it.get('code') or name[:24]}"
        for hit in _soft_match(name, comp_names):
            links.append({"from": wid, "to": comp_by_name[hit],
                          "relation": "implements", "provenance": "deterministic"})
        for hit in _soft_match(name, list(req_by_text.keys())):
            links.append({"from": wid, "to": req_by_text[hit],
                          "relation": "implements", "provenance": "deterministic"})

    covered_reqs = {l["from"] for l in links if l["relation"] == "satisfies"}
    total = len(reqs)
    return {
        "requirements": reqs,
        "links": links,
        "coverage": {
            "requirements_total": total,
            "requirements_covered": len(covered_reqs),
            "ratio": round(len(covered_reqs) / total, 3) if total else 1.0,
        },
    }


def _graph_from_model(model: Any) -> dict[str, Any]:
    """Project a `SolutionModel` into the same {requirements, links, coverage} shape
    `build_trace_links` returns — but using the CSM's STABLE ids, so `trace_links.json`
    and `solution_model.json` agree on every id (the whole point of step 1.3)."""
    reqs = [{"id": r.id, "kind": r.kind, "text": r.statement} for r in model.requirements]
    links = [
        {"from": l.from_id, "to": l.to_id, "relation": l.relation, "provenance": l.provenance}
        for l in model.trace_links
    ]
    covered = {l["from"] for l in links if l["relation"] == "satisfies"}
    total = len(reqs)
    return {
        "requirements": reqs,
        "links": links,
        "coverage": {
            "requirements_total": total,
            "requirements_covered": len(covered),
            "ratio": round(len(covered) / total, 3) if total else 1.0,
        },
    }


def write_trace_links(workspace: Optional[Path] = None) -> dict[str, Any]:
    """Read the workspace artifacts, build trace links, write `trace_links.json`.

    Projects from the CSM (`solution_model.json`) so ids match the canonical model;
    falls back to the legacy artifact-derived graph if the CSM can't be built.
    """
    if workspace is None:
        from backends import current_workspace
        workspace = current_workspace()
    workspace = Path(workspace)

    try:
        from csm_adapter import build_solution_model
        graph = _graph_from_model(build_solution_model(workspace))
    except Exception:
        graph = build_trace_links(
            _read_json(workspace / "diagram_brief.json", {}) or {},
            _read_json(workspace / "blueprint.json", {}) or {},
            _read_json(workspace / "wbs.json", {}) or {},
        )

    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "trace_links.json").write_text(
        json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return graph
