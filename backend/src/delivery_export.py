"""Delivery export (docx §8.6, §10.3) — push CSM work items to Jira/Linear/Confluence.

A solution's WBS is structured work, not a free-text task dump, so it can be synced to a
delivery tracker *idempotently with trace ids*: each `WorkItem` maps to one external
issue, keyed by its stable CSM id. A re-sync creates new items, updates changed ones and
skips unchanged ones (the work item's content hash gates the decision), so running it
twice never duplicates issues.

Safety (docx §5.4, §12.3 "explicit send gates"): the default is **dry-run** — a preview
payload is written and nothing leaves the process. A real push happens only when
`dry_run=False`; with no credentials configured the push is *simulated* with a
deterministic external id so the idempotent sync can be exercised offline/in CI.

The id↔external mapping lives ONLY in `delivery_sync_log.json` (persisted across runs),
NOT on the CSM `WorkItem`, to keep the model's content hash stable (§12.3 "schema scope
explodes"). Imports only `csm` (cycle-free).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Literal, Optional

from pydantic import BaseModel, Field

from csm import SolutionModel, WorkItem

DELIVERY_SYNC_LOG_NAME = "delivery_sync_log.json"
DELIVERY_PREVIEW_NAME = "delivery_export_preview.json"

System = Literal["jira", "linear", "confluence"]
SyncAction = Literal["create", "update", "skip"]


class ExternalRef(BaseModel):
    """A stable mapping from a CSM entity to an external tracker issue."""

    csm_id: str
    system: System
    external_id: str = ""
    last_synced_hash: str = ""


# --- work-item hashing (drives create/update/skip) ---------------------------

def work_item_hash(wi: WorkItem) -> str:
    """Content hash of the fields we sync; a change here means 'needs update'."""
    payload = {
        "name": wi.name,
        "effort": wi.effort_mandays,
        "parent": wi.parent,
        "owner": wi.owner or "",
        "dod": list(wi.definition_of_done),
        "sprint": wi.assigned_sprint,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# --- adapters: CSM WorkItem -> external payload ------------------------------

def build_payload(system: System, wi: WorkItem) -> dict:
    """Map a WorkItem to the create/update payload shape of the target system.

    These are the field mappings a real adapter would POST; in dry-run they are written
    to the preview file so a human can review exactly what would be pushed.
    """
    desc_parts = []
    if wi.definition_of_done:
        desc_parts.append("Definition of Done:\n" + "\n".join(f"- {d}" for d in wi.definition_of_done))
    desc_parts.append(f"CSM trace id: {wi.id}")
    description = "\n\n".join(desc_parts)

    if system == "jira":
        return {
            "fields": {
                "summary": wi.name,
                "description": description,
                "issuetype": {"name": "Task"},
                "labels": [f"csm-{wi.id}"],
                "customfield_effort_days": wi.effort_mandays,
            }
        }
    if system == "linear":
        return {
            "title": wi.name,
            "description": description,
            "estimate": wi.effort_mandays,
            "labelIds": [f"csm-{wi.id}"],
        }
    # confluence: a row/section in a delivery page
    return {
        "title": wi.name,
        "body": description,
        "metadata": {"csm_id": wi.id, "effort_days": wi.effort_mandays},
    }


# --- store -------------------------------------------------------------------

def _log_path(workspace: Optional[Path]) -> Path:
    if workspace is None:
        from backends import WORKSPACE
        workspace = WORKSPACE
    return Path(workspace) / DELIVERY_SYNC_LOG_NAME


def read_refs(workspace: Optional[Path] = None) -> list[ExternalRef]:
    """Load the persisted id↔external mapping; [] when absent/unreadable."""
    path = _log_path(workspace)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    items = raw.get("refs", []) if isinstance(raw, dict) else raw
    out: list[ExternalRef] = []
    for d in items or []:
        try:
            out.append(ExternalRef.model_validate(d))
        except Exception:  # noqa: BLE001
            continue
    return out


def _write_refs(refs: Iterable[ExternalRef], workspace: Optional[Path]) -> None:
    path = _log_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"refs": [r.model_dump() for r in refs]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _ref_key(csm_id: str, system: str) -> tuple[str, str]:
    return (csm_id, system)


# --- the sync ----------------------------------------------------------------

def _simulate_external_id(system: System, csm_id: str) -> str:
    """Deterministic stand-in id for an offline/credential-less push."""
    return f"{system.upper()}-{csm_id}"


def plan_sync(model: SolutionModel, system: System,
              workspace: Optional[Path] = None) -> list[dict]:
    """Compute the create/update/skip plan for ``system`` without mutating anything."""
    refs = {(_ref_key(r.csm_id, r.system)): r for r in read_refs(workspace)}
    plan: list[dict] = []
    for wi in model.work_items:
        h = work_item_hash(wi)
        existing = refs.get(_ref_key(wi.id, system))
        if existing is None:
            action: SyncAction = "create"
        elif existing.last_synced_hash == h:
            action = "skip"
        else:
            action = "update"
        plan.append({
            "csm_id": wi.id,
            "action": action,
            "external_id": existing.external_id if existing else "",
            "hash": h,
            "payload": build_payload(system, wi),
        })
    return plan


def sync_work_items(
    model: SolutionModel,
    system: System,
    *,
    dry_run: bool = True,
    workspace: Optional[Path] = None,
) -> dict:
    """Sync the model's work items to ``system`` and return a result summary.

    dry_run=True (default): write the plan to `delivery_export_preview.json`, mutate
    nothing. dry_run=False: apply the plan — create/update issues (simulated id when no
    credentials), then persist the refs so the NEXT sync skips unchanged items.
    """
    plan = plan_sync(model, system, workspace)
    counts = {"create": 0, "update": 0, "skip": 0}
    for row in plan:
        counts[row["action"]] += 1

    if dry_run:
        preview_path = (_log_path(workspace).parent / DELIVERY_PREVIEW_NAME)
        preview_path.write_text(
            json.dumps({"system": system, "dry_run": True, "plan": plan},
                       indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return {"system": system, "dry_run": True, "counts": counts, "plan": plan,
                "preview": str(preview_path)}

    # Real sync: apply create/update, persist refs (skip leaves the ref untouched).
    refs = {(_ref_key(r.csm_id, r.system)): r for r in read_refs(workspace)}
    for row in plan:
        if row["action"] == "skip":
            continue
        key = _ref_key(row["csm_id"], system)
        existing = refs.get(key)
        external_id = (existing.external_id if existing and existing.external_id
                       else _simulate_external_id(system, row["csm_id"]))
        refs[key] = ExternalRef(csm_id=row["csm_id"], system=system,
                                external_id=external_id, last_synced_hash=row["hash"])
        row["external_id"] = external_id
    _write_refs(refs.values(), workspace)
    return {"system": system, "dry_run": False, "counts": counts, "plan": plan}
