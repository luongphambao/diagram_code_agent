from __future__ import annotations

import json

from domain.validation.solution_validator import _semantic_chain_findings, validate_solution
from session.artifact_manifest import archive_approved_blueprint, load_approved_blueprint


def _write_approved_blueprint(workspace):
    blueprint = {
        "nodes": [{"id": "client"}, {"id": "api"}],
        "edges": [{"from": "client", "to": "api"}],
    }
    (workspace / "pending_gate.json").write_text(
        json.dumps(
            {
                "tool": "propose_blueprint",
                "args": {"blueprint": blueprint},
                "gate_id": "gate-1",
                "revision": 1,
            }
        ),
        encoding="utf-8",
    )
    assert archive_approved_blueprint(workspace) is not None
    return blueprint


def _drawio(*, include_api: bool = True, include_edge: bool = True) -> str:
    api = (
        '<mxCell id="api" vertex="1" parent="1"><mxGeometry width="80" height="40" as="geometry"/></mxCell>'
        if include_api
        else ""
    )
    edge = (
        '<mxCell id="e1" edge="1" source="client" target="api" parent="1"><mxGeometry relative="1" as="geometry"/></mxCell>'
        if include_edge
        else ""
    )
    return (
        '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
        '<mxCell id="client" vertex="1" parent="1"><mxGeometry width="80" height="40" as="geometry"/></mxCell>'
        f"{api}{edge}</root></mxGraphModel>"
    )


def test_archives_exact_approved_blueprint(tmp_path):
    blueprint = _write_approved_blueprint(tmp_path)
    archived, index = load_approved_blueprint(tmp_path)
    assert archived == blueprint
    assert index["gate_id"] == "gate-1"


def test_semantic_chain_passes_when_both_hops_preserve_ids(tmp_path):
    blueprint = _write_approved_blueprint(tmp_path)
    (tmp_path / "render_spec.json").write_text(json.dumps(blueprint), encoding="utf-8")
    (tmp_path / "out.drawio").write_text(_drawio(), encoding="utf-8")
    assert _semantic_chain_findings(tmp_path) == []


def test_semantic_chain_blocks_render_spec_loss(tmp_path):
    _write_approved_blueprint(tmp_path)
    (tmp_path / "render_spec.json").write_text(
        json.dumps({"nodes": [{"id": "client"}], "edges": []}), encoding="utf-8"
    )
    (tmp_path / "out.drawio").write_text(_drawio(include_api=False, include_edge=False), encoding="utf-8")

    findings = _semantic_chain_findings(tmp_path)
    assert len(findings) == 1
    assert all(f.severity == "high" for f in findings)
    assert any("render specification" in f.title.lower() for f in findings)

    _all, summary = validate_solution(tmp_path, block=True)
    assert summary.startswith("VALIDATION: BLOCK")


def test_semantic_chain_blocks_drawio_loss_from_complete_render_spec(tmp_path):
    blueprint = _write_approved_blueprint(tmp_path)
    (tmp_path / "render_spec.json").write_text(json.dumps(blueprint), encoding="utf-8")
    (tmp_path / "out.drawio").write_text(_drawio(include_api=False, include_edge=False), encoding="utf-8")

    findings = _semantic_chain_findings(tmp_path)
    assert len(findings) == 1
    assert findings[0].severity == "high"
    assert "draw.io" in findings[0].title.lower()


def test_semantic_chain_fails_closed_when_approved_snapshot_is_corrupt(tmp_path):
    (tmp_path / "approved_blueprint.json").write_text("not json", encoding="utf-8")

    findings = _semantic_chain_findings(tmp_path)
    assert len(findings) == 1
    assert findings[0].severity == "high"
    assert "unavailable" in findings[0].title.lower()
