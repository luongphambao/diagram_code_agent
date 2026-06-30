"""Tests for the epistemic-summary surfacing (step 1.4) over a CSM."""

from csm import Assumption, Constraint, Decision, Requirement, SolutionModel
from tools.analysis_tools import _epistemic_note


def _model() -> SolutionModel:
    return SolutionModel(
        requirements=[Requirement(id="REQ-1", statement="Confirmed need", status="confirmed")],
        assumptions=[Assumption(id="ASM-1", statement="Assume 500 rps", status="pending")],
        decisions=[Decision(id="DEC-1", title="Pick managed k8s", status="proposed")],
        constraints=[Constraint(id="CON-1", statement="EU region only", kind="region")],
    )


def test_epistemic_note_renders_each_section():
    note = _epistemic_note(_model())
    # HITL v2: the header now points the user to the gate actions, and each line is
    # prefixed with its stable CSM id so approve_with_assumptions can reference it.
    assert "EPISTEMIC SUMMARY" in note and "approve_with_assumptions" in note
    assert "Known facts" in note and "REQ-1: Confirmed need" in note
    assert "should confirm" in note and "ASM-1: Assume 500 rps" in note
    assert "Open decisions" in note and "DEC-1: Pick managed k8s" in note
    assert "Constraints" in note and "CON-1: EU region only [region]" in note


def test_epistemic_note_omits_empty_sections_and_empty_model():
    # a model with no pending/confirmed/proposed entities yields no note
    assert _epistemic_note(SolutionModel()) == ""
    # only a constraint -> the other three sections are omitted
    note = _epistemic_note(SolutionModel(constraints=[Constraint(id="CON-1", statement="x")]))
    assert "Constraints" in note
    assert "Known facts" not in note and "Open decisions" not in note
