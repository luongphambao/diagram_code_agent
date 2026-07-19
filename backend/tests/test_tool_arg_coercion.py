"""Regression tests for the generic tool-arg coercion middleware.

Reproduces the exact malformed tool calls observed in LangSmith traces
(2026-07-04, project diagram-agent): mimo-v2.5 passing list/dict args as
JSON-encoded strings — search_diagrams_nodes(queries='["vpn",...]'),
fit_labels(edge_labels='[...]'), draft_wbs_skeleton(ratios='{...}') — and the
deepagents builtin `ls` called with no `path`. Each one triggered a Pydantic
ValidationError whose ToolMessage echoed the full kwargs blob, producing
call/token retry storms.
"""

from typing import Optional

import pytest
from langchain_core.messages import ToolMessage
from pydantic import BaseModel

from tool_coercion import (
    ToolArgCoercionMiddleware,
    coerce_args,
    coerce_model_values,
    compact_invocation_error,
)
from tools import ICON_RESOLVER_TOOLS


# ── schema fixtures ──────────────────────────────────────────────────────────

class _Item(BaseModel):
    label: str
    sublabel: str = ""


class _Args(BaseModel):
    nodes: list[_Item] = []
    edge_labels: Optional[list[str]] = None
    ratios: Optional[dict] = None
    note: str = ""
    count: int = 0


class _FakeTool:
    def __init__(self, args_schema):
        self.args_schema = args_schema


class _FakeRequest:
    """Duck-typed stand-in for langgraph's ToolCallRequest."""

    def __init__(self, tool_call, tool=None):
        self.tool_call = tool_call
        self.tool = tool

    def override(self, **kw):
        return _FakeRequest(kw.get("tool_call", self.tool_call), self.tool)


def _run_middleware(tool_call, tool=None):
    """Run wrap_tool_call and capture the args the handler actually received."""
    mw = ToolArgCoercionMiddleware()
    seen = {}

    def handler(request):
        seen.update(request.tool_call.get("args") or {})
        return ToolMessage(content="ok", tool_call_id=tool_call.get("id", "t1"),
                           name=tool_call.get("name", "tool"))

    mw.wrap_tool_call(_FakeRequest(tool_call, tool), handler)
    return seen


# ── coerce_args: the exact LangSmith failures ────────────────────────────────

def test_list_of_str_passed_as_json_string():
    # fit_labels(edge_labels='["HTTPS", "OAuth 2.0"]')
    out = coerce_args({"edge_labels": '["HTTPS", "OAuth 2.0"]'}, _Args)
    assert out["edge_labels"] == ["HTTPS", "OAuth 2.0"]


def test_free_dict_passed_as_json_string():
    # draft_wbs_skeleton(ratios='{"ba_on_dev": 0.1, "qc_on_dev": 0.3}')
    out = coerce_args({"ratios": '{"ba_on_dev": 0.1, "qc_on_dev": 0.3}'}, _Args)
    assert out["ratios"] == {"ba_on_dev": 0.1, "qc_on_dev": 0.3}


def test_nested_model_list_as_json_string_and_numeric_dict():
    out = coerce_args({"nodes": '[{"label": "API"}, {"label": "DB"}]'}, _Args)
    assert [n["label"] for n in out["nodes"]] == ["API", "DB"]

    out = coerce_args({"nodes": {"0": {"label": "API"}, "1": {"label": "DB"}}}, _Args)
    assert [n["label"] for n in out["nodes"]] == ["API", "DB"]


def test_search_diagrams_nodes_real_schema():
    # search_diagrams_nodes(queries='["vpn", "azure", "teams"]') — real tool schema.
    tool = next(t for t in ICON_RESOLVER_TOOLS
                if getattr(t, "name", "") == "search_diagrams_nodes")
    out = coerce_args({"queries": '["vpn", "azure", "teams"]'}, tool.args_schema)
    assert out["queries"] == ["vpn", "azure", "teams"]
    tool.args_schema.model_validate(out)  # must now pass validation


def test_plain_str_field_never_json_parsed():
    prose = '{"looks": "like json"}'
    out = coerce_args({"note": prose}, _Args)
    assert out["note"] == prose


def test_well_formed_args_are_a_noop():
    args = {"nodes": [{"label": "API"}], "edge_labels": ["a"], "count": 3}
    assert coerce_args(dict(args), _Args) == args


def test_none_for_bare_list_becomes_empty():
    class Bare(BaseModel):
        items: list[str] = []
    assert coerce_args({"items": None}, Bare)["items"] == []


def test_coerce_model_values_usable_as_validator_body():
    values = coerce_model_values(_Args, {"edge_labels": '["x"]'})
    assert values["edge_labels"] == ["x"]
    assert _Args.model_validate(values).edge_labels == ["x"]

def test_tech_stack_cost_range_accepts_min_max_aliases():
    from tools.schemas.tech_stack import ProposeTechStackArgs

    args = ProposeTechStackArgs.model_validate({
        "tech_stack": [{
            "layer": "compute",
            "choice": "4x A100",
            "estimated_monthly_cost_usd": {"min": 7000, "max": 13000},
            "alternatives": [],
        }],
        "estimated_total_monthly_cost_usd": {"min": 7000, "max": 13000},
    })

    assert args.tech_stack[0].estimated_monthly_cost_usd.min_usd == 7000
    assert args.tech_stack[0].estimated_monthly_cost_usd.max_usd == 13000
    assert args.estimated_total_monthly_cost_usd.min_usd == 7000

def test_tech_stack_accepts_scalar_compliance_and_total_cost():
    from tools.schemas.tech_stack import ProposeTechStackArgs

    args = ProposeTechStackArgs.model_validate({
        "tech_stack": [{"layer": "compute", "choice": "EKS"}],
        "assumptions": {"compliance": "data_sovereignty, iso27001"},
        "estimated_total_monthly_cost_usd": "$7k-$13k/mo",
    })

    assert args.assumptions.compliance == ["data_sovereignty", "iso27001"]
    assert args.estimated_total_monthly_cost_usd.min_usd == 7000
    assert args.estimated_total_monthly_cost_usd.max_usd == 13000

def test_tech_stack_accepts_wrapped_layers_and_numeric_total_cost():
    from tools.schemas.tech_stack import ProposeTechStackArgs

    args = ProposeTechStackArgs.model_validate({
        "tech_stack": {"layers": {"compute": {"choice": "EKS"}}},
        "estimated_total_monthly_cost_usd": 1200,
    })

    assert args.tech_stack[0].layer == "compute"
    assert args.tech_stack[0].choice == "EKS"
    assert args.estimated_total_monthly_cost_usd.min_usd == 1200

def test_tech_stack_accepts_provider_shorthand_shapes():
    from tools.schemas.tech_stack import ProposeTechStackArgs

    args = ProposeTechStackArgs.model_validate({
        "tech_stack": [{
            "layer": "Compute & Orchestration",
            "choice": "GKE Autopilot",
            "decision_criteria": [
                {"criterion": "Cost efficiency", "score": 3},
                {"criterion": "Operational simplicity", "score": 4},
                {"criterion": "Scalability", "score": 5},
            ],
            "alternatives": [
                {"why_rejected": "Too much operational overhead"},
                "Cloud Run",
            ],
            "risks": [
                "GPU availability in asia-southeast1",
                {"title": "Cold start latency", "mitigation": "Keep minimum replicas"},
            ],
        }],
        "assumptions": {
            "users": "~200 concurrent operators",
            "peak_rps": "~100 inference requests/sec",
            "data_volume": "~500GB/month",
            "team_size": "8-15 AI/platform engineers",
            "compliance": ["ISO 9001", "ISO 27001"],
        },
    })

    layer = args.tech_stack[0]
    assert layer.decision_criteria.cost == 3
    assert layer.decision_criteria.ops_complexity == 4
    assert layer.decision_criteria.scalability == 5
    assert [a.name for a in layer.alternatives] == ["Alternative", "Cloud Run"]
    assert layer.risks[0].risk == "GPU availability in asia-southeast1"
    assert layer.risks[1].risk == "Cold start latency"
    assert args.assumptions.users.peak_concurrent == 200
    assert args.assumptions.users.peak_rps == 100
    assert args.assumptions.data.initial_gb == 500
    assert args.assumptions.team.size == 8

def test_blueprint_key_decision_objects_become_strings():
    from tools.schemas.blueprint import Blueprint

    bp = Blueprint.model_validate({
        "pattern": "hybrid",
        "key_decisions": [{
            "decision": "Use SGLang for model serving",
            "rationale": "It supports continuous batching.",
            "tradeoffs": ["Operational ownership", "Version pinning required"],
        }],
    })

    assert bp.key_decisions == [
        "Use SGLang for model serving — It supports continuous batching. — "
        "Trade-offs: Operational ownership; Version pinning required"
    ]


# ── middleware behavior ──────────────────────────────────────────────────────

def test_middleware_coerces_before_handler():
    seen = _run_middleware(
        {"name": "fit_labels", "id": "t1", "args": {"edge_labels": '["HTTPS"]'}},
        tool=_FakeTool(_Args),
    )
    assert seen["edge_labels"] == ["HTTPS"]


def test_middleware_ls_default_path():
    # ls called with no args at all (RC6: "path Field required").
    seen = _run_middleware({"name": "ls", "id": "t1", "args": {}})
    assert seen["path"] == "/"


def test_middleware_whole_args_as_json_string():
    seen = _run_middleware(
        {"name": "fit_labels", "id": "t1", "args": '{"edge_labels": ["a"]}'},
        tool=_FakeTool(_Args),
    )
    assert seen["edge_labels"] == ["a"]


def test_middleware_compacts_invocation_error():
    mw = ToolArgCoercionMiddleware()
    blob = "x" * 9000
    raw = (
        f"Error invoking tool 'fit_labels' with kwargs {{'edge_labels': '{blob}'}} "
        "with error:\n 1 validation error for fit_labels\nedge_labels\n"
        "  Input should be a valid list\n Please fix the error and try again."
    )

    def handler(request):
        return ToolMessage(content=raw, tool_call_id="t1", name="fit_labels",
                           status="error")

    result = mw.wrap_tool_call(
        _FakeRequest({"name": "fit_labels", "id": "t1", "args": {}}), handler)
    assert "edge_labels" in result.content
    assert blob not in result.content            # kwargs echo gone
    assert len(result.content) < 1200
    assert "never as quoted strings" in result.content


def test_middleware_leaves_normal_errors_alone():
    mw = ToolArgCoercionMiddleware()

    def handler(request):
        return ToolMessage(content="BUDGET_EXHAUSTED", tool_call_id="t1",
                           name="web_research", status="error")

    result = mw.wrap_tool_call(
        _FakeRequest({"name": "web_research", "id": "t1", "args": {}}), handler)
    assert result.content == "BUDGET_EXHAUSTED"


@pytest.mark.anyio
async def test_middleware_async_path():
    mw = ToolArgCoercionMiddleware()
    seen = {}

    async def handler(request):
        seen.update(request.tool_call.get("args") or {})
        return ToolMessage(content="ok", tool_call_id="t1", name="fit_labels")

    await mw.awrap_tool_call(
        _FakeRequest({"name": "fit_labels", "id": "t1",
                      "args": {"edge_labels": '["a", "b"]'}},
                     _FakeTool(_Args)),
        handler,
    )
    assert seen["edge_labels"] == ["a", "b"]


# ── critic lenient enum coercion (findings.py) ──────────────────────────────

def test_diagram_finding_lenient_enums():
    from domain.diagram.findings import DiagramFinding
    f = DiagramFinding.model_validate({
        "severity": "major",          # off-enum → medium
        "confidence": "certain",      # off-enum → medium
        "category": "visual",         # off-enum → style (aesthetic, never blocks)
        "title": "x", "detail": "y",
    })
    assert f.severity == "medium"
    assert f.confidence == "medium"
    assert f.category == "style"

    ok = DiagramFinding.model_validate({
        "severity": "CRITICAL",       # case-normalised, still valid
        "confidence": "high",
        "category": "completeness",
        "title": "x", "detail": "y",
    })
    assert ok.severity == "critical"
    assert ok.category == "completeness"


def test_blueprint_accepts_common_provider_aliases():
    from tools.schemas.blueprint import Blueprint

    bp = Blueprint.model_validate({
        "pattern": "hybrid",
        "nodes": [
            {"id": "users", "title": "Users"},
            {"id": "api", "name": "API Gateway"},
        ],
        "clusters": [{"id": "edge", "title": "Edge"}],
        "edges": [{"source": "users", "target": "api", "label": "HTTPS"}],
        "pillar_coverage": {
            "security": {"addressed_by": "waf, iam"},
            "reliability": "multi az",
            "performance_efficiency": ["cdn", "cache"],
        },
    })

    assert [node.label for node in bp.nodes] == ["Users", "API Gateway"]
    assert bp.clusters[0].label == "Edge"
    assert bp.edges[0].from_ == "users"
    assert bp.edges[0].to == "api"
    assert bp.pillar_coverage is not None
    assert bp.pillar_coverage.security.addressed_by == ["waf", "iam"]
    assert bp.pillar_coverage.reliability.addressed_by == ["multi az"]
    assert bp.pillar_coverage.performance_efficiency.addressed_by == ["cdn", "cache"]
