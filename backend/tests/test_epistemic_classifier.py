"""Tests for the epistemic confidence-tier classifier in csm_adapter."""

import pytest

from csm import Assumption, SolutionModel
from csm_adapter import _classify_assumption_tier, from_artifacts


# --- unit tests for the classifier -------------------------------------------

@pytest.mark.parametrize("statement,expected_tier", [
    # must_confirm: financial
    ("Budget is $50,000 USD per month", "must_confirm"),
    ("Total cost must not exceed EUR 200,000", "must_confirm"),
    # must_confirm: deadline
    ("Go-live deadline is Q3 2025", "must_confirm"),
    ("Project must launch by December 2025", "must_confirm"),  # no direct keyword match — should be should_confirm
    ("Go live by March 2026", "must_confirm"),
    # must_confirm: compliance
    ("HIPAA compliance is required before launch", "must_confirm"),
    ("PCI-DSS level 1 certification needed", "must_confirm"),
    ("GDPR must be satisfied for EU data", "must_confirm"),
    # must_confirm: SLA
    ("API SLA: 99.99% uptime", "must_confirm"),
    ("Response time must be under 200ms (P99)", "must_confirm"),
    # nice_to_confirm: best practice
    ("We typically follow microservices best practices", "nice_to_confirm"),
    ("By default, we prefer trunk-based development", "nice_to_confirm"),
    ("Standard approach for authentication is OAuth", "nice_to_confirm"),
    # should_confirm: everything else
    ("The client uses Azure as their cloud provider", "should_confirm"),
    ("Team size is 4 engineers", "should_confirm"),
    ("Integration with Salesforce is assumed", "should_confirm"),
])
def test_classify_assumption_tier(statement, expected_tier):
    assert _classify_assumption_tier(statement) == expected_tier


def test_assumptions_get_tier_from_adapter():
    brief = {
        "assumptions": [
            "Budget is $10,000/month",
            "GDPR compliance is required",
            "We will typically use best practices",
            "AWS is the cloud provider",
        ]
    }
    model = from_artifacts(brief, {}, {})
    tiers = {a.statement: a.confidence_tier for a in model.assumptions}
    assert tiers["Budget is $10,000/month"] == "must_confirm"
    assert tiers["GDPR compliance is required"] == "must_confirm"
    assert tiers["We will typically use best practices"] == "nice_to_confirm"
    assert tiers["AWS is the cloud provider"] == "should_confirm"


def test_epistemic_summary_includes_tier():
    model = SolutionModel(assumptions=[
        Assumption(id="ASM-1", statement="x", confidence_tier="must_confirm", status="pending"),
        Assumption(id="ASM-2", statement="y", confidence_tier="should_confirm", status="pending"),
    ])
    summ = model.epistemic_summary()
    tiers = {a["id"]: a["tier"] for a in summ["assumptions_needing_confirmation"]}
    assert tiers["ASM-1"] == "must_confirm"
    assert tiers["ASM-2"] == "should_confirm"
    by_tier = summ["assumptions_by_tier"]
    assert by_tier["must_confirm"] == 1
    assert by_tier["should_confirm"] == 1
    assert by_tier["nice_to_confirm"] == 0


def test_confirmed_assumptions_excluded_from_pending():
    model = SolutionModel(assumptions=[
        Assumption(id="ASM-1", statement="x", confidence_tier="must_confirm", status="confirmed"),
        Assumption(id="ASM-2", statement="y", confidence_tier="should_confirm", status="pending"),
    ])
    summ = model.epistemic_summary()
    ids = [a["id"] for a in summ["assumptions_needing_confirmation"]]
    assert "ASM-1" not in ids
    assert "ASM-2" in ids
    assert summ["assumptions_by_tier"]["must_confirm"] == 0
