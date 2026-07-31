"""Tier D1: artifact provenance manifest (closes H-3, revision drift).

Before this module, nothing anywhere computed "artifact X was derived from
artifact Y@revision R, and Y has since changed" — csm_adapter.py's revision
counter only tracked the aggregate solution_model.json, not per-artifact
provenance. These tests lock the manifest's write/read/staleness contract and
its two consumers: the cross-artifact validator (a medium, non-blocking
finding) and the phase filter (reinstating a stale artifact's producer tool).
"""

from __future__ import annotations

from session.artifact_manifest import current_revision, is_stale, read_manifest, record_artifact


def test_record_artifact_round_trip(tmp_path):
    (tmp_path / "blueprint.json").write_text("{}", encoding="utf-8")
    rev = record_artifact(tmp_path, "blueprint.json")
    assert rev
    manifest = read_manifest(tmp_path)
    assert manifest["artifacts"]["blueprint.json"]["revision"] == rev
    assert current_revision(tmp_path, "blueprint.json") == rev


def test_record_artifact_missing_file_returns_none(tmp_path):
    assert record_artifact(tmp_path, "nope.json") is None
    assert read_manifest(tmp_path) == {"artifacts": {}}


def test_read_manifest_missing_or_corrupt_is_empty(tmp_path):
    assert read_manifest(tmp_path) == {"artifacts": {}}
    (tmp_path / "artifact_manifest.json").write_text("not json", encoding="utf-8")
    assert read_manifest(tmp_path) == {"artifacts": {}}


def test_is_stale_false_when_no_manifest_entry(tmp_path):
    # Backward compat: an artifact that never went through record_artifact
    # behaves exactly as if this module didn't exist.
    (tmp_path / "out.drawio").write_text("<mxfile/>", encoding="utf-8")
    stale, drifted = is_stale(tmp_path, "out.drawio")
    assert stale is False
    assert drifted == []


def test_is_stale_false_when_upstream_unchanged(tmp_path):
    (tmp_path / "blueprint.json").write_text('{"nodes": []}', encoding="utf-8")
    bp_rev = record_artifact(tmp_path, "blueprint.json")
    (tmp_path / "out.drawio").write_text("<mxfile/>", encoding="utf-8")
    record_artifact(tmp_path, "out.drawio", derived_from=[("blueprint.json", bp_rev)])

    stale, drifted = is_stale(tmp_path, "out.drawio")
    assert stale is False
    assert drifted == []


def test_is_stale_true_after_upstream_changes(tmp_path):
    (tmp_path / "blueprint.json").write_text('{"nodes": []}', encoding="utf-8")
    bp_rev = record_artifact(tmp_path, "blueprint.json")
    (tmp_path / "out.drawio").write_text("<mxfile/>", encoding="utf-8")
    record_artifact(tmp_path, "out.drawio", derived_from=[("blueprint.json", bp_rev)])

    # Simulate an out-of-band edit to blueprint.json (e.g. via edit_file) that
    # never goes through propose_blueprint / record_artifact again.
    (tmp_path / "blueprint.json").write_text('{"nodes": [{"id": "a"}]}', encoding="utf-8")
    record_artifact(tmp_path, "blueprint.json")

    stale, drifted = is_stale(tmp_path, "out.drawio")
    assert stale is True
    assert drifted == ["blueprint.json"]


def test_is_stale_skips_upstream_never_recorded(tmp_path):
    # derived_from references an artifact that was never itself recorded — is_stale
    # must not treat "can't compare" as drift (would be a false positive on partial
    # adoption of record_artifact across write sites).
    (tmp_path / "deck_plan.json").write_text("{}", encoding="utf-8")
    record_artifact(tmp_path, "deck_plan.json", derived_from=[("tech_stack.json", "somerev")])

    stale, drifted = is_stale(tmp_path, "deck_plan.json")
    assert stale is False
    assert drifted == []
