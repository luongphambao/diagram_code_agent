"""Artifact provenance manifest: revision + derived-from tracking per workspace.

Each artifact-writing tool records its output here after a meaningful write
(``record_artifact``). Downstream consumers (the cross-artifact validator,
``phase_filter.py``) call ``is_stale`` to detect "artifact X was written from
artifact Y@revision R, and Y has since changed" -- the concrete gap the Codex
review flagged as H-3 (revision drift): before this module, nothing anywhere
computed per-artifact provenance (``csm_adapter.py``'s revision counter only
tracks the aggregate solution_model.json, not individual source files).

Same "small JSON file in the workspace" convention as ``tools/stage_markers.py``
(``pending_gate.json``, ``render_count.json``, ...) -- no new persistence
mechanism invented. Missing manifest / missing entry always resolves to
"not stale", so a workspace whose artifacts never went through
``record_artifact`` behaves exactly as it did before this module existed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

_MANIFEST_NAME = "artifact_manifest.json"
_APPROVED_BLUEPRINT_INDEX = "approved_blueprint.json"


def _manifest_path(workspace: Path) -> Path:
    return Path(workspace) / _MANIFEST_NAME


def read_manifest(workspace: Path) -> dict:
    """Load artifact_manifest.json; ``{"artifacts": {}}`` if absent/corrupt."""
    try:
        data = json.loads(_manifest_path(workspace).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"artifacts": {}}
    if not isinstance(data, dict) or not isinstance(data.get("artifacts"), dict):
        return {"artifacts": {}}
    return data


def _write_manifest(workspace: Path, manifest: dict) -> None:
    Path(workspace).mkdir(parents=True, exist_ok=True)
    _manifest_path(workspace).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _content_revision(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def record_artifact(
    workspace: Path,
    name: str,
    *,
    derived_from: list[tuple[str, str]] | None = None,
) -> str | None:
    """Hash *name*'s current bytes and record it (+ its upstream revisions) in
    artifact_manifest.json.

    ``derived_from`` is a list of ``(upstream_artifact_name, upstream_revision)``
    pairs -- callers get the upstream revision from this same function's return
    value (or ``current_revision``) when they wrote the upstream artifact.
    Returns the new revision, or ``None`` if *name* doesn't exist on disk (the
    caller's write must have already happened).
    """
    workspace = Path(workspace)
    revision = _content_revision(workspace / name)
    if revision is None:
        return None
    manifest = read_manifest(workspace)
    manifest["artifacts"][name] = {
        "revision": revision,
        "written_at": dt.datetime.now().isoformat(timespec="seconds"),
        "derived_from": [{"artifact": n, "revision": r} for n, r in (derived_from or [])],
    }
    _write_manifest(workspace, manifest)
    return revision


def current_revision(workspace: Path, name: str) -> str | None:
    """The revision the manifest currently has on file for *name* (not a live
    re-hash of the file -- use this to build a later artifact's derived_from)."""
    entry = read_manifest(workspace).get("artifacts", {}).get(name)
    return entry.get("revision") if isinstance(entry, dict) else None


def is_stale(workspace: Path, name: str) -> tuple[bool, list[str]]:
    """True + the upstream artifact name(s) that drifted, if any of *name*'s
    recorded ``derived_from`` revisions no longer match that upstream's
    CURRENT recorded revision in the manifest.

    An upstream never recorded via ``record_artifact`` can't be compared and is
    silently skipped (not treated as drift) -- this only flags drift the
    manifest can actually prove, never a false positive from partial adoption.
    """
    entry = read_manifest(workspace).get("artifacts", {}).get(name)
    if not isinstance(entry, dict):
        return False, []
    drifted: list[str] = []
    for dep in entry.get("derived_from") or []:
        upstream_name = dep.get("artifact")
        recorded_rev = dep.get("revision")
        current = current_revision(workspace, upstream_name)
        if current is not None and current != recorded_rev:
            drifted.append(upstream_name)
    return bool(drifted), drifted


def archive_approved_blueprint(workspace: Path) -> Path | None:
    """Archive the exact proposed blueprint before its gated tool executes.

    Deep Agents interrupts before ``propose_blueprint`` runs, so the approved
    payload lives in ``pending_gate.json`` rather than canonical
    ``blueprint.json`` at decision time. The immutable snapshot becomes the
    semantic source of truth for every downstream preservation check.
    """
    workspace = Path(workspace)
    try:
        pending = json.loads((workspace / "pending_gate.json").read_text(encoding="utf-8"))
        if not isinstance(pending, dict) or pending.get("tool") != "propose_blueprint":
            return None
        args = pending.get("args") or {}
        blueprint = args.get("blueprint", args) if isinstance(args, dict) else {}
        if not isinstance(blueprint, dict) or not blueprint:
            return None
        canonical = json.dumps(blueprint, ensure_ascii=False, indent=2, sort_keys=True)
        revision = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        approved_dir = workspace / "approved"
        approved_dir.mkdir(parents=True, exist_ok=True)
        dest = approved_dir / f"blueprint-{revision}.json"
        if not dest.exists():
            dest.write_text(canonical, encoding="utf-8")
            try:
                import stat

                dest.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
            except OSError:
                pass
        index = {
            "revision": revision,
            "path": str(dest.relative_to(workspace)),
            "gate_id": pending.get("gate_id") or "",
            "gate_revision": pending.get("revision") or 0,
        }
        tmp = workspace / f"{_APPROVED_BLUEPRINT_INDEX}.tmp"
        tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(workspace / _APPROVED_BLUEPRINT_INDEX)
        return dest
    except Exception:  # noqa: BLE001
        return None


def load_approved_blueprint(workspace: Path) -> tuple[dict, dict]:
    """Return ``(blueprint, index)`` or two empty dicts for legacy workspaces."""
    workspace = Path(workspace)
    try:
        index = json.loads((workspace / _APPROVED_BLUEPRINT_INDEX).read_text(encoding="utf-8"))
        if not isinstance(index, dict):
            return {}, {}
        rel = index.get("path")
        rel_path = Path(rel) if isinstance(rel, str) else Path()
        if (
            not rel
            or rel_path.is_absolute()
            or not rel_path.parts
            or rel_path.parts[0] != "approved"
            or ".." in rel_path.parts
        ):
            return {}, {}
        blueprint = json.loads((workspace / rel_path).read_text(encoding="utf-8"))
        return (blueprint, index) if isinstance(blueprint, dict) else ({}, {})
    except Exception:  # noqa: BLE001
        return {}, {}
