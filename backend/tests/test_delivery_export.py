"""Tests for WS4 delivery export (docx §8.6, §10.3): idempotent CSM->tracker sync."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory.stores.csm import SolutionModel, WorkItem
from domain.reporting.delivery_export import (
    DELIVERY_PREVIEW_NAME,
    build_payload,
    plan_sync,
    read_refs,
    sync_work_items,
    work_item_hash,
)


def _model() -> SolutionModel:
    return SolutionModel(work_items=[
        WorkItem(id="WBS-1", name="Set up API gateway", effort_mandays=3,
                 definition_of_done=["routes live", "auth wired"]),
        WorkItem(id="WBS-2", name="Build auth service", effort_mandays=5),
    ])


@pytest.fixture(autouse=True)
def _offline_jira(monkeypatch):
    """Force the offline simulation by default so tests never touch the network even if a
    developer has JIRA_* env vars set. The real-push test overrides this in its body."""
    import jira_adapter
    monkeypatch.setattr(jira_adapter, "jira_credentials", lambda: None)


class _FakeResp:
    def __init__(self, payload=None):
        self._payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_build_payload_shapes():
    wi = _model().work_items[0]
    jira = build_payload("jira", wi)
    assert jira["fields"]["summary"] == "Set up API gateway"
    assert "csm-WBS-1" in jira["fields"]["labels"]
    linear = build_payload("linear", wi)
    assert linear["title"] == "Set up API gateway" and linear["estimate"] == 3
    conf = build_payload("confluence", wi)
    assert conf["metadata"]["csm_id"] == "WBS-1"


def test_dry_run_previews_all_creates_and_mutates_nothing(tmp_path: Path):
    res = sync_work_items(_model(), "jira", dry_run=True, workspace=tmp_path)
    assert res["dry_run"] is True
    assert res["counts"] == {"create": 2, "update": 0, "skip": 0}
    assert (tmp_path / DELIVERY_PREVIEW_NAME).exists()
    # nothing persisted to the sync log
    assert read_refs(tmp_path) == []


def test_real_sync_is_idempotent(tmp_path: Path):
    m = _model()
    # First real sync: both created, refs persisted.
    r1 = sync_work_items(m, "jira", dry_run=False, workspace=tmp_path)
    assert r1["counts"] == {"create": 2, "update": 0, "skip": 0}
    refs = read_refs(tmp_path)
    assert {r.csm_id for r in refs} == {"WBS-1", "WBS-2"}
    assert all(r.external_id for r in refs)
    # Second sync, unchanged: everything skipped (idempotent — no duplicates).
    r2 = sync_work_items(m, "jira", dry_run=False, workspace=tmp_path)
    assert r2["counts"] == {"create": 0, "update": 0, "skip": 2}


def test_changed_work_item_triggers_update(tmp_path: Path):
    m = _model()
    sync_work_items(m, "jira", dry_run=False, workspace=tmp_path)
    # Mutate one work item → its hash changes → update on next sync.
    m.work_items[0].effort_mandays = 8
    r = sync_work_items(m, "jira", dry_run=False, workspace=tmp_path)
    assert r["counts"] == {"create": 0, "update": 1, "skip": 1}
    # external id is stable across the update (same issue, not a new one)
    ref = next(x for x in read_refs(tmp_path) if x.csm_id == "WBS-1")
    assert ref.external_id == "JIRA-WBS-1"


def test_per_system_refs_are_independent(tmp_path: Path):
    m = _model()
    sync_work_items(m, "jira", dry_run=False, workspace=tmp_path)
    # Syncing to a different system creates fresh refs (not skipped).
    r = sync_work_items(m, "linear", dry_run=False, workspace=tmp_path)
    assert r["counts"]["create"] == 2
    systems = {x.system for x in read_refs(tmp_path)}
    assert systems == {"jira", "linear"}


def test_hash_is_stable_for_same_content():
    wi = WorkItem(id="WBS-1", name="x", effort_mandays=2)
    assert work_item_hash(wi) == work_item_hash(WorkItem(id="WBS-1", name="x", effort_mandays=2))


def test_plan_sync_does_not_write(tmp_path: Path):
    plan_sync(_model(), "jira", workspace=tmp_path)
    assert not (tmp_path / "delivery_sync_log.json").exists()


def test_real_jira_sync_with_mock(tmp_path: Path, monkeypatch):
    """With credentials configured, the sync POSTs to Jira and uses the returned issue key
    as the external id; idempotency holds against the real key and edits go via PUT."""
    import jira_adapter
    monkeypatch.setattr(jira_adapter, "jira_credentials", lambda: {
        "base_url": "https://acme.atlassian.net", "email": "e@a.com",
        "token": "t", "project_key": "PROJ", "effort_field": "",
    })
    created: list = []
    puts: list = []

    def fake_post(url, json, auth, timeout):
        n = len(created) + 1
        created.append((url, json))
        return _FakeResp({"key": f"PROJ-{n}"})

    def fake_put(url, json, auth, timeout):
        puts.append((url, json))
        return _FakeResp({})

    monkeypatch.setattr(jira_adapter.httpx, "post", fake_post)
    monkeypatch.setattr(jira_adapter.httpx, "put", fake_put)

    m = _model()
    r1 = sync_work_items(m, "jira", dry_run=False, workspace=tmp_path)
    assert r1["pushed"] is True
    assert r1["counts"] == {"create": 2, "update": 0, "skip": 0}
    assert len(created) == 2
    # project injected on create; effort folded into the description (no effort_field set)
    fields0 = created[0][1]["fields"]
    assert fields0["project"] == {"key": "PROJ"}
    assert "man-days" in fields0["description"]
    assert "customfield_effort_days" not in fields0
    refs = {x.csm_id: x.external_id for x in read_refs(tmp_path)}
    assert refs == {"WBS-1": "PROJ-1", "WBS-2": "PROJ-2"}

    # Re-sync unchanged → all skipped, no further POSTs (idempotent against the real key).
    r2 = sync_work_items(m, "jira", dry_run=False, workspace=tmp_path)
    assert r2["counts"] == {"create": 0, "update": 0, "skip": 2}
    assert len(created) == 2

    # Edit one item → PUT against the stable external id (no new issue created).
    m.work_items[0].effort_mandays = 9
    r3 = sync_work_items(m, "jira", dry_run=False, workspace=tmp_path)
    assert r3["counts"] == {"create": 0, "update": 1, "skip": 1}
    assert puts and puts[0][0].endswith("/rest/api/3/issue/PROJ-1")


def test_no_creds_falls_back_to_simulate(tmp_path: Path, monkeypatch):
    """Without credentials the sync never touches the network and uses simulated ids."""
    import jira_adapter

    def boom(*a, **k):
        raise AssertionError("network must not be called when credentials are absent")

    monkeypatch.setattr(jira_adapter.httpx, "post", boom)
    monkeypatch.setattr(jira_adapter.httpx, "put", boom)
    r = sync_work_items(_model(), "jira", dry_run=False, workspace=tmp_path)
    assert r["pushed"] is False
    assert {x.external_id for x in read_refs(tmp_path)} == {"JIRA-WBS-1", "JIRA-WBS-2"}
