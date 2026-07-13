"""Tests for diagram quality §4.7: findings_from_validation + _diagram_gate_note.

Verifies that the linter output maps to the correct SolutionFinding dimensions,
repair_strategies, severities, and stable finding_ids — the repair contract
required by docx §4.3 / §7.1.
"""

from __future__ import annotations

import textwrap

import pytest

import domain.validation.validate_drawio as vd
from domain.validation.solution_validator import AUTO_REPAIR_STRATEGIES


# --------------------------------------------------------------------------- #
# Minimal XML helpers
# --------------------------------------------------------------------------- #

_WRAP = "<mxfile><diagram name=\"P\"><mxGraphModel><root>{}</root></mxGraphModel></diagram></mxfile>"
_CELLS = '<mxCell id="0"/><mxCell id="1" parent="0"/>'
_NODE = '<mxCell id="{id}" value="{label}" vertex="1" parent="1"><mxGeometry x="{x}" y="{y}" width="100" height="50" as="geometry"/></mxCell>'


def _xml(*body_parts: str) -> str:
    return _WRAP.format(_CELLS + "".join(body_parts))


def _validate(xml: str) -> dict:
    import os
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".drawio", delete=False, mode="w", encoding="utf-8") as f:
        f.write(xml)
        tmp = f.name
    try:
        return vd.validate_file(tmp)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# findings_from_validation — mapping tests
# --------------------------------------------------------------------------- #

def test_findings_from_clean_xml_is_empty():
    xml = _xml(
        _NODE.format(id="n1", label="A", x=10, y=10),
        _NODE.format(id="n2", label="B", x=200, y=10),
    )
    result = _validate(xml)
    findings = vd.findings_from_validation(result)
    assert findings == [], "clean diagram must produce no findings"


def test_findings_from_validation_errors_map_to_structural():
    """Dangling edge → diagram_structural, patch_blueprint, severity=high."""
    xml = _xml(
        _NODE.format(id="n1", label="A", x=10, y=10),
        '<mxCell id="bad-edge" edge="1" source="n1" target="ghost-99" parent="1">'
        '<mxGeometry relative="1" as="geometry"/></mxCell>',
    )
    result = _validate(xml)
    findings = vd.findings_from_validation(result)
    structural = [f for f in findings if f.dimension == "diagram_structural"]
    assert structural, "dangling edge must produce a diagram_structural finding"
    f = structural[0]
    assert f.repair_strategy == "patch_blueprint"
    assert f.severity == "high"


def test_findings_from_validation_warnings_map_to_layout():
    """Overlapping sibling vertices → diagram_layout, auto_repair, severity=medium."""
    xml = _xml(
        # Both nodes at overlapping positions — same parent (id="1")
        '<mxCell id="na" value="A" vertex="1" parent="1"><mxGeometry x="10" y="10" width="120" height="60" as="geometry"/></mxCell>',
        '<mxCell id="nb" value="B" vertex="1" parent="1"><mxGeometry x="60" y="30" width="120" height="60" as="geometry"/></mxCell>',
    )
    result = _validate(xml)
    findings = vd.findings_from_validation(result)
    layout = [f for f in findings if f.dimension == "diagram_layout"]
    assert layout, "overlapping vertices must produce a diagram_layout finding"
    f = layout[0]
    assert f.repair_strategy == "auto_repair"
    assert f.severity == "medium"


def test_findings_from_validation_advice_map_to_style():
    """5 distinct font sizes → diagram_style, repair_strategy=none, severity=low."""
    xml = _xml(
        '<mxCell id="n1" value="A" vertex="1" parent="1" style="fontSize=8;"><mxGeometry x="10" y="10" width="80" height="40" as="geometry"/></mxCell>',
        '<mxCell id="n2" value="B" vertex="1" parent="1" style="fontSize=10;"><mxGeometry x="110" y="10" width="80" height="40" as="geometry"/></mxCell>',
        '<mxCell id="n3" value="C" vertex="1" parent="1" style="fontSize=12;"><mxGeometry x="210" y="10" width="80" height="40" as="geometry"/></mxCell>',
        '<mxCell id="n4" value="D" vertex="1" parent="1" style="fontSize=14;"><mxGeometry x="10" y="70" width="80" height="40" as="geometry"/></mxCell>',
        '<mxCell id="n5" value="E" vertex="1" parent="1" style="fontSize=18;"><mxGeometry x="110" y="70" width="80" height="40" as="geometry"/></mxCell>',
    )
    result = _validate(xml)
    findings = vd.findings_from_validation(result)
    style = [f for f in findings if f.dimension == "diagram_style"
             and f.severity == "low"]
    assert style, "5 distinct font sizes must produce a diagram_style finding"
    f = style[0]
    assert f.repair_strategy == "none"
    # fontSize=8 also trips the production-polish gate (medium, auto_repair).
    polish = [f for f in findings if f.dimension == "diagram_style"
              and f.severity == "medium"]
    assert polish and polish[0].repair_strategy == "auto_repair"


def test_stable_finding_id_consistent_across_runs():
    """Same defect in same XML → same SF-<hash> id on every call."""
    xml = _xml(
        _NODE.format(id="n1", label="X", x=10, y=10),
        '<mxCell id="e" edge="1" source="n1" target="missing-42" parent="1">'
        '<mxGeometry relative="1" as="geometry"/></mxCell>',
    )
    result = _validate(xml)
    ids_run1 = {f.finding_id for f in vd.findings_from_validation(result)}
    ids_run2 = {f.finding_id for f in vd.findings_from_validation(result)}
    assert ids_run1 == ids_run2, "finding ids must be stable across runs"
    assert all(fid.startswith("SF-") for fid in ids_run1)


def test_repair_contract_valid_for_all_findings():
    """All findings must have SF- id, valid repair_strategy, and consistent severity."""
    _VALID_REPAIR = AUTO_REPAIR_STRATEGIES | {"request_evidence", "human_decision", "none"}
    # Mix errors + warnings + advice
    xml = _xml(
        '<mxCell id="na" value="A" vertex="1" parent="1"><mxGeometry x="10" y="10" width="120" height="60" as="geometry"/></mxCell>',
        '<mxCell id="nb" value="B" vertex="1" parent="1"><mxGeometry x="60" y="30" width="120" height="60" as="geometry"/></mxCell>',
        '<mxCell id="ec" edge="1" source="na" target="ghost" parent="1"><mxGeometry relative="1" as="geometry"/></mxCell>',
    )
    result = _validate(xml)
    findings = vd.findings_from_validation(result)
    assert findings, "expected at least one finding from mixed defects"
    for f in findings:
        assert f.finding_id.startswith("SF-"), f"bad id: {f.finding_id}"
        assert f.repair_strategy in _VALID_REPAIR, f"invalid repair_strategy: {f.repair_strategy}"
        assert f.severity in {"low", "medium", "high", "critical"}, f"invalid severity: {f.severity}"
