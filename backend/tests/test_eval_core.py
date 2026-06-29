"""Tests for the shared eval core (evals/_core.py), focused on the regression gate.

The deterministic-matcher re-exports and the baseline comparison are what every
suite relies on, so they get unit coverage independent of any LLM/agent run.
"""

import json
import sys
from pathlib import Path

# evals/ lives under backend/, not src/ — put the backend root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals._core import (  # noqa: E402
    aggregate,
    compare_to_baseline,
    soft_match,
    write_baseline,
)


def test_soft_match_reexport_works():
    tp, fp, fn = soft_match(["API Gateway", "Lambda"], ["api gateway"])
    assert tp == 1 and fn == 0


def test_aggregate_means_skip_missing():
    results = [{"scores": {"f1": 1.0}}, {"scores": {"f1": 0.0}}, {"scores": {}}]
    agg = aggregate(results, ["scores.f1"])
    assert agg["scores.f1"] == 0.5


def test_compare_to_baseline_no_file_passes(tmp_path):
    passed, regr = compare_to_baseline(
        [{"scores": {"f1": 0.5}}], tmp_path / "baseline.json", ["scores.f1"])
    assert passed and regr == []


def test_compare_to_baseline_flags_regression(tmp_path):
    base = tmp_path / "baseline.json"
    write_baseline(base, [{"scores": {"f1": 0.90}}], ["scores.f1"])
    # Current run drops well below baseline - tolerance.
    passed, regr = compare_to_baseline(
        [{"scores": {"f1": 0.70}}], base, ["scores.f1"], tolerance=0.02)
    assert not passed
    assert regr[0]["metric"] == "scores.f1" and regr[0]["drop"] == 0.2


def test_compare_to_baseline_within_tolerance_passes(tmp_path):
    base = tmp_path / "baseline.json"
    write_baseline(base, [{"scores": {"f1": 0.90}}], ["scores.f1"])
    passed, regr = compare_to_baseline(
        [{"scores": {"f1": 0.89}}], base, ["scores.f1"], tolerance=0.02)
    assert passed and regr == []


def test_write_baseline_shape(tmp_path):
    base = tmp_path / "baseline.json"
    write_baseline(base, [{"scores": {"f1": 1.0}}, {"scores": {"f1": 0.0}}], ["scores.f1"])
    raw = json.loads(base.read_text(encoding="utf-8"))
    assert raw["n_cases"] == 2 and raw["metrics"]["scores.f1"] == 0.5
