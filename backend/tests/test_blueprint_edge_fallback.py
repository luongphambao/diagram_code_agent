from tools.analysis.blueprint_tools import _build_render_spec
from tools.schemas.blueprint import Blueprint


def test_blueprint_without_edges_infers_visible_architecture_flow():
    bp = Blueprint(
        pattern="serverless",
        slide_title="Aila",
        clusters=[
            {"id": "users", "label": "End Users", "number": 1},
            {"id": "edge", "label": "Edge & CDN", "number": 2},
            {"id": "compute", "label": "Compute & API", "number": 3},
            {"id": "data", "label": "Data & Storage", "number": 4},
            {"id": "external", "label": "External Integrations", "number": 5},
        ],
        nodes=[
            {"id": "line_users", "label": "LINE Users", "cluster": "users", "type": "external"},
            {"id": "line_messaging", "label": "LINE Messaging API", "cluster": "external", "type": "external"},
            {"id": "route53", "label": "Amazon Route 53", "cluster": "edge", "type": "external"},
            {"id": "cloudfront", "label": "Amazon CloudFront", "cluster": "edge", "type": "cdn"},
            {"id": "waf", "label": "AWS WAF", "cluster": "edge", "type": "external"},
            {"id": "api_gateway", "label": "Amazon API Gateway", "cluster": "compute", "type": "gateway"},
            {"id": "lambda_aila_core", "label": "AWS Lambda - Aila Core", "cluster": "compute", "type": "service"},
            {"id": "rds_postgres", "label": "Amazon RDS PostgreSQL", "cluster": "data", "type": "database"},
            {"id": "openai_api", "label": "OpenAI API", "cluster": "external", "type": "external"},
        ],
        edges=[],
    )

    spec = _build_render_spec(bp, "aws")

    assert spec["_inferred_edges"]["count"] == len(spec["edges"])
    pairs = {(e["from"], e["to"]) for e in spec["edges"]}
    assert ("line_users", "line_messaging") in pairs
    assert ("api_gateway", "lambda_aila_core") in pairs
    assert ("lambda_aila_core", "rds_postgres") in pairs


def test_inferred_edges_render_with_arrowheads():
    bp = Blueprint(
        pattern="serverless",
        clusters=[
            {"id": "users", "label": "Users", "number": 1},
            {"id": "compute", "label": "Compute", "number": 2},
            {"id": "data", "label": "Data", "number": 3},
        ],
        nodes=[
            {"id": "users", "label": "Users", "cluster": "users", "type": "external"},
            {"id": "api", "label": "API Gateway", "cluster": "compute", "type": "gateway"},
            {"id": "lambda_core", "label": "AWS Lambda Core", "cluster": "compute", "type": "service"},
            {"id": "db", "label": "Amazon RDS", "cluster": "data", "type": "database"},
        ],
        edges=[],
    )
    spec = _build_render_spec(bp, "aws")

    from prettygraph.native.topology import build_drawio_from_spec

    xml, stats = build_drawio_from_spec(spec, "Fallback")
    assert stats["edges"] >= 2
    assert 'edge="1"' in xml
    assert "source=\"api\"" in xml or "source=\"lambda_core\"" in xml
