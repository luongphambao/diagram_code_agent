"""Tests for WS5 Reality Sync (docx §5.2): ingest + drift report."""

from __future__ import annotations

from pathlib import Path

from csm import Component, SolutionModel
from reality_sync import (
    build_current_state_model,
    drift,
    ingest_openapi,
    ingest_terraform,
    run_reality_sync,
)


def test_ingest_terraform():
    tf = '''
    resource "aws_s3_bucket" "data" {}
    resource "aws_lambda_function" "api" {}
    '''
    out = ingest_terraform(tf, "main.tf")
    names = {n for n, _k, _r in out}
    assert names == {"aws_s3_bucket.data", "aws_lambda_function.api"}


def test_ingest_openapi_by_tag():
    spec = '{"tags":[{"name":"orders"},{"name":"users"}],"paths":{"/orders":{}}}'
    out = ingest_openapi(spec, "openapi.json")
    names = {n for n, _k, _r in out}
    assert names == {"api:orders", "api:users"}
    assert all(k == "integration" for _n, k, _r in out)


def test_build_current_state_model_from_dir(tmp_path: Path):
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  web:\n    image: nginx\n  api:\n    image: app\n", encoding="utf-8")
    (tmp_path / "main.tf").write_text('resource "aws_db_instance" "db" {}\n', encoding="utf-8")
    (tmp_path / "openapi.json").write_text('{"paths":{"/health":{}}}', encoding="utf-8")
    model = build_current_state_model(tmp_path)
    names = {c.name for c in model.components}
    assert "web" in names and "api" in names
    assert "aws_db_instance.db" in names
    assert "api:/health" in names


def test_drift_three_buckets():
    desired = SolutionModel(components=[
        Component(id="COMP-web", name="web"),
        Component(id="COMP-api", name="api"),
        Component(id="COMP-cache", name="cache"),   # designed, not built
    ])
    current = SolutionModel(components=[
        Component(id="COMP-web", name="web"),
        Component(id="COMP-api", name="api"),
        Component(id="COMP-worker", name="worker"),  # built, not designed
    ])
    report = drift(desired, current)
    s = report["summary"]
    assert s["matched"] == 2
    assert {e["name"] for e in report["in_design_not_in_reality"]} == {"cache"}
    assert {e["name"] for e in report["in_reality_not_in_design"]} == {"worker"}
    assert any("cache" in r for r in report["remediation"])
    assert any("worker" in r for r in report["remediation"])


def test_no_drift_when_aligned():
    m = SolutionModel(components=[Component(id="COMP-web", name="web")])
    report = drift(m, m)
    assert report["summary"]["in_design_not_in_reality"] == 0
    assert report["summary"]["in_reality_not_in_design"] == 0


def test_run_reality_sync_writes_artifacts(tmp_path: Path):
    # workspace has a desired model with one component not present in the source
    ws = tmp_path / "ws"
    ws.mkdir()
    desired = SolutionModel(components=[Component(id="COMP-payments", name="payments")])
    (ws / "solution_model.json").write_text(desired.to_json(), encoding="utf-8")
    # source has a different service
    src = tmp_path / "src"
    src.mkdir()
    (src / "compose.yaml").write_text("services:\n  billing:\n    image: x\n", encoding="utf-8")

    report = run_reality_sync(src, ws)
    assert (ws / "current_state_model.json").exists()
    assert (ws / "drift_report.json").exists()
    assert {e["name"] for e in report["in_design_not_in_reality"]} == {"payments"}
    assert {e["name"] for e in report["in_reality_not_in_design"]} == {"billing"}
