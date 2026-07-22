"""Comment store (docx §8.6) — review comments anchored to CSM entity IDs.

Collaboration needs comments tied to *what* they are about — a requirement, a
component, a slide — not just free chat. A `CommentRecord` anchors a note to a stable
entity id (or an artifact region) plus its author/role, so a review thread survives a
requirement rename and can be exported with the proposal package.

This mirrors the append-only store pattern of `evidence.py`/`decisions.py`. Like
`finding_store`, comments are an audit trail and are NOT projected into the CSM (that
would balloon the schema/hash); they persist across runs like the decision log. The
module imports nothing from the pipeline so it stays cycle-free; timestamps are
injected by the caller.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

COMMENT_LOG_NAME = "comment_log.json"


class CommentRecord(BaseModel):
    """One review comment anchored to a CSM entity id (or artifact region)."""

    id: str
    anchor_entity_id: str = ""  # e.g. "REQ-3", "COMP-api_gw", "SLIDE-7"; "" = general
    author: str = ""
    role: str = ""  # architect / pm / reviewer / client / ...
    body: str = ""
    timestamp: str = ""  # ISO 8601; injected by the caller
    resolved: bool = False
    resolved_by: str = ""
    resolved_at: str = ""


def new_comment_record(
    body: str,
    *,
    seq: int,
    anchor_entity_id: str = "",
    author: str = "",
    role: str = "",
    timestamp: str = "",
) -> CommentRecord:
    """Mint a comment with a stable id (`CMT-1`, `CMT-2`, ...) from the log size."""
    return CommentRecord(
        id=f"CMT-{seq}",
        anchor_entity_id=anchor_entity_id,
        author=author,
        role=role,
        body=body,
        timestamp=timestamp,
    )


# --- store -------------------------------------------------------------------


def _log_path(workspace: Optional[Path]) -> Path:
    if workspace is None:
        from backends import current_workspace

        workspace = current_workspace()
    return Path(workspace) / COMMENT_LOG_NAME


def read_comments(workspace: Optional[Path] = None) -> list[CommentRecord]:
    """Load the append-only comment log; returns [] when absent or unreadable."""
    path = _log_path(workspace)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    items = raw.get("comments", []) if isinstance(raw, dict) else raw
    out: list[CommentRecord] = []
    for d in items or []:
        try:
            out.append(CommentRecord.model_validate(d))
        except Exception:  # noqa: BLE001 — never let one bad row kill the log
            continue
    return out


def _write_comments(records: list[CommentRecord], workspace: Optional[Path]) -> None:
    path = _log_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"comments": [r.model_dump() for r in records]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def append_comment(record: CommentRecord, workspace: Optional[Path] = None) -> CommentRecord:
    """Append one comment to `comment_log.json` (creating it if needed)."""
    existing = read_comments(workspace)
    existing.append(record)
    _write_comments(existing, workspace)
    return record


def resolve_comment(
    comment_id: str,
    *,
    resolved_by: str = "",
    resolved_at: str = "",
    workspace: Optional[Path] = None,
) -> Optional[CommentRecord]:
    """Mark a comment resolved. Returns the updated record, or None if id not found."""
    records = read_comments(workspace)
    hit: Optional[CommentRecord] = None
    for r in records:
        if r.id == comment_id:
            r.resolved = True
            r.resolved_by = resolved_by
            r.resolved_at = resolved_at
            hit = r
            break
    if hit is not None:
        _write_comments(records, workspace)
    return hit


def next_seq(workspace: Optional[Path] = None) -> int:
    """1-based sequence for the next comment id, derived from the current log size."""
    return len(read_comments(workspace)) + 1


def comments_for(entity_id: str, workspace: Optional[Path] = None) -> list[CommentRecord]:
    """All comments anchored to a given entity id."""
    return [c for c in read_comments(workspace) if c.anchor_entity_id == entity_id]
