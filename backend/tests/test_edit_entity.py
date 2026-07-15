"""Tests for the edit_entity tool (analysis_tools.py).

Covers: happy path field update (Decision.title) + revision bump + .prev.json written;
patching Requirement.status; unknown entity id error; disallowed field guard;
missing solution_model.json error.
"""

import contextvars
import json

import backends
from memory.stores.csm import Decision, Requirement, SolutionModel
from memory.stores.csm_adapter import SOLUTION_MODEL_NAME, SOLUTION_MODEL_PREV_NAME
from tools import edit_entity


def _write_model(tmp_path, model: SolutionModel) -> None:
    (tmp_path / SOLUTION_MODEL_NAME).write_text(
        json.dumps(model.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _use_workspace(monkeypatch, tmp_path):
    # §4.10: bind tmp_path as the current-thread workspace (auto-restored by monkeypatch).
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        backends, "_current_workspace",
        contextvars.ContextVar("current_workspace", default=tmp_path),
    )


# ---------------------------------------------------------------------------

def test_edit_entity_updates_decision_title_bumps_revision(monkeypatch, tmp_path):
    model = SolutionModel(revision=3, decisions=[Decision(id="DEC-1", title="Old title")])
    _write_model(tmp_path, model)
    _use_workspace(monkeypatch, tmp_path)

    result = edit_entity.invoke({"entity_id": "DEC-1", "field": "title", "new_value": "New title"})

    assert "DEC-1.title updated" in result
    assert "revision bumped to 4" in result
    assert "query_change_impact" in result

    updated = json.loads((tmp_path / SOLUTION_MODEL_NAME).read_text(encoding="utf-8"))
    assert updated["revision"] == 4
    assert updated["decisions"][0]["title"] == "New title"

    # Prev snapshot holds the old value and old revision
    prev = json.loads((tmp_path / SOLUTION_MODEL_PREV_NAME).read_text(encoding="utf-8"))
    assert prev["revision"] == 3
    assert prev["decisions"][0]["title"] == "Old title"


def test_edit_entity_updates_requirement_status(monkeypatch, tmp_path):
    model = SolutionModel(requirements=[Requirement(id="REQ-1", statement="Must support SSO")])
    _write_model(tmp_path, model)
    _use_workspace(monkeypatch, tmp_path)

    result = edit_entity.invoke({"entity_id": "REQ-1", "field": "status", "new_value": "confirmed"})

    assert "REQ-1.status updated" in result
    updated = json.loads((tmp_path / SOLUTION_MODEL_NAME).read_text(encoding="utf-8"))
    assert updated["requirements"][0]["status"] == "confirmed"


def test_edit_entity_unknown_id_returns_error(monkeypatch, tmp_path):
    model = SolutionModel(decisions=[Decision(id="DEC-1", title="x")])
    _write_model(tmp_path, model)
    _use_workspace(monkeypatch, tmp_path)

    result = edit_entity.invoke({"entity_id": "DEC-99", "field": "title", "new_value": "y"})
    assert "ERROR" in result
    assert "DEC-99" in result


def test_edit_entity_disallowed_field_returns_error(monkeypatch, tmp_path):
    model = SolutionModel(decisions=[Decision(id="DEC-1", title="x")])
    _write_model(tmp_path, model)
    _use_workspace(monkeypatch, tmp_path)

    result = edit_entity.invoke({"entity_id": "DEC-1", "field": "id", "new_value": "DEC-99"})
    assert "ERROR" in result
    assert "not patchable" in result
    # File must not have changed
    unchanged = json.loads((tmp_path / SOLUTION_MODEL_NAME).read_text(encoding="utf-8"))
    assert unchanged["decisions"][0]["id"] == "DEC-1"


def test_edit_entity_no_model_returns_error(monkeypatch, tmp_path):
    _use_workspace(monkeypatch, tmp_path)
    result = edit_entity.invoke({"entity_id": "DEC-1", "field": "title", "new_value": "x"})
    assert "ERROR" in result
    assert "no solution_model.json" in result
