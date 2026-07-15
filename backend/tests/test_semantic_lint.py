"""Tests for semantic lint rules (§4.7): Rules 7/8/9 in solution_validator.

One positive (rule fires) + one negative (mechanism present → rule silent) per rule.
Uses evaluate_solution() directly — pure function, no I/O.
"""

from domain.validation.solution_validator import evaluate_solution, is_blocking


# --- minimal helpers ---------------------------------------------------------

def _simple_wbs():
    return {
        "items": [{"id": "1.1", "name": "Setup", "be": 5, "total": 5}],
        "effort_totals": {"total_mandays": 5},
    }


def _blueprint_with_public_node_and_edge(decisions=None):
    return {
        "nodes": [
            {"id": "client", "label": "Client", "cluster": "ext"},
            {"id": "api_svc", "label": "API Service", "cluster": "app"},
        ],
        "clusters": [{"id": "ext", "label": "External"}, {"id": "app", "label": "App"}],
        "edges": [{"from": "client", "to": "api_svc"}],
        "key_decisions": decisions if decisions is not None else ["REST API for core features"],
        "nfr_mapping": [],
    }


# ─── Rule 7: Public-flow auth ─────────────────────────────────────────────────

def test_rule7_fires_when_public_flow_no_auth():
    brief = {
        "functional_requirements": ["Handle user requests"],
        "non_functional_requirements": ["security: all endpoints require authentication"],
    }
    findings = evaluate_solution(brief, _blueprint_with_public_node_and_edge(), _simple_wbs())
    sec = [f for f in findings if f.dimension == "security"]
    assert sec, "Rule 7 should fire — public node with edge + security NFR + no auth in corpus"
    assert any("auth" in f.title.lower() or "auth" in f.detail.lower() for f in sec)
    assert all(f.requires_human_decision for f in sec)
    assert all(f.repair_strategy == "human_decision" for f in sec)
    # medium severity → NOT blocking by default
    assert not any(is_blocking(f) for f in sec)


def test_rule7_silent_when_auth_mechanism_in_decisions():
    brief = {
        "functional_requirements": ["Handle user requests"],
        "non_functional_requirements": ["security: all endpoints require authentication"],
    }
    blueprint = _blueprint_with_public_node_and_edge(
        decisions=["JWT authentication and OAuth2 on all public endpoints"]
    )
    findings = evaluate_solution(brief, blueprint, _simple_wbs())
    assert not any(f.dimension == "security" and "auth" in f.title.lower() for f in findings)


def test_rule7_silent_when_no_security_nfr():
    brief = {
        "functional_requirements": ["Handle user requests"],
        "non_functional_requirements": ["99.9% uptime SLA"],
    }
    findings = evaluate_solution(brief, _blueprint_with_public_node_and_edge(), _simple_wbs())
    assert not any(f.dimension == "security" for f in findings)


def test_rule7_silent_when_no_edge_from_public():
    brief = {
        "functional_requirements": ["Internal API"],
        "non_functional_requirements": ["security: internal auth required"],
    }
    blueprint = {
        "nodes": [
            {"id": "client", "label": "Client", "cluster": "ext"},
            {"id": "api_svc", "label": "API Service", "cluster": "app"},
        ],
        "clusters": [{"id": "ext", "label": "External"}, {"id": "app", "label": "App"}],
        "edges": [],  # no edges → no outbound flow from public node
        "key_decisions": ["Internal service mesh"],
        "nfr_mapping": [],
    }
    findings = evaluate_solution(brief, blueprint, _simple_wbs())
    assert not any(f.dimension == "security" for f in findings)


# ─── Rule 8: PII protection ──────────────────────────────────────────────────

def _pii_blueprint(decisions=None):
    return {
        "nodes": [{"id": "db", "label": "Customer DB", "cluster": "data"}],
        "clusters": [{"id": "data", "label": "Data"}],
        "edges": [],
        "key_decisions": decisions if decisions is not None else ["PostgreSQL for storage"],
        "nfr_mapping": [],
    }


def test_rule8_fires_when_pii_no_protection():
    brief = {
        "functional_requirements": ["Store customer profiles"],
        "non_functional_requirements": ["GDPR compliance required"],
    }
    findings = evaluate_solution(brief, _pii_blueprint(), _simple_wbs())
    sec = [f for f in findings if f.dimension == "security"]
    assert sec, "Rule 8 should fire — PII NFR + no protection in corpus"


def test_rule8_high_severity_with_compliance_constraint():
    brief = {
        "functional_requirements": ["Store customer data"],
        "non_functional_requirements": ["data protection required"],
        "constraints": ["GDPR residency: EU data must remain in EU region"],
    }
    findings = evaluate_solution(brief, _pii_blueprint(), _simple_wbs())
    sec = [f for f in findings if f.dimension == "security"]
    assert sec
    assert sec[0].severity == "high"
    assert is_blocking(sec[0])


def test_rule8_silent_when_encryption_documented():
    brief = {
        "functional_requirements": ["Store customer profiles"],
        "non_functional_requirements": ["GDPR compliance required"],
    }
    blueprint = _pii_blueprint(
        decisions=["AES-256 encrypt at rest via KMS; TLS 1.3 in transit for all PII fields"]
    )
    findings = evaluate_solution(brief, blueprint, _simple_wbs())
    assert not any(f.dimension == "security" for f in findings)


def test_rule8_silent_when_no_pii_nfr():
    brief = {
        "functional_requirements": ["Store product catalogue"],
        "non_functional_requirements": ["fast read latency < 50ms"],
    }
    findings = evaluate_solution(brief, _pii_blueprint(), _simple_wbs())
    assert not any(f.dimension == "security" for f in findings)


# ─── Rule 9: Async resilience ─────────────────────────────────────────────────

def _async_blueprint(decisions=None):
    return {
        "nodes": [
            {"id": "api", "label": "Order API", "cluster": "app"},
            {"id": "sqs_q", "label": "SQS Queue", "cluster": "msg"},
            {"id": "worker", "label": "Order Worker", "cluster": "app"},
        ],
        "clusters": [{"id": "app", "label": "App"}, {"id": "msg", "label": "Messaging"}],
        "edges": [{"from": "api", "to": "sqs_q"}, {"from": "sqs_q", "to": "worker"}],
        "key_decisions": decisions if decisions is not None else ["SQS for async processing"],
        "nfr_mapping": [],
    }


def test_rule9_fires_when_async_no_resilience():
    brief = {"functional_requirements": ["Process orders asynchronously"]}
    findings = evaluate_solution(brief, _async_blueprint(), _simple_wbs())
    rel = [f for f in findings if f.dimension == "reliability"]
    assert rel, "Rule 9 should fire — async node + no retry/DLQ in corpus"
    assert all(f.requires_human_decision for f in rel)
    assert all(f.repair_strategy == "human_decision" for f in rel)
    # medium → not blocking
    assert not any(is_blocking(f) for f in rel)


def test_rule9_silent_when_dlq_in_decisions():
    brief = {"functional_requirements": ["Process orders asynchronously"]}
    blueprint = _async_blueprint(
        decisions=["SQS with DLQ (dead letter queue) and exponential backoff retry; idempotency keys on consumers"]
    )
    findings = evaluate_solution(brief, blueprint, _simple_wbs())
    assert not any(f.dimension == "reliability" for f in findings)


def test_rule9_fires_on_amqp_edge_even_without_async_node_label():
    brief = {"functional_requirements": ["Event-driven pipeline"]}
    blueprint = {
        "nodes": [
            {"id": "producer", "label": "Producer Service", "cluster": "app"},
            {"id": "consumer", "label": "Consumer Service", "cluster": "app"},
        ],
        "clusters": [{"id": "app", "label": "App"}],
        "edges": [{"from": "producer", "to": "consumer", "protocol": "AMQP"}],
        "key_decisions": ["RabbitMQ for event streaming"],
        "nfr_mapping": [],
    }
    findings = evaluate_solution(brief, blueprint, _simple_wbs())
    assert any(f.dimension == "reliability" for f in findings)


# ─── Regression: clean workspace still passes ─────────────────────────────────

def test_clean_workspace_no_new_false_positives():
    """case_01_clean equivalent: no new semantic findings on a well-described system."""
    brief = {"functional_requirements": ["API Gateway routes requests"]}
    blueprint = {
        "nodes": [{"id": "api_gw", "label": "API Gateway", "cluster": "edge"}],
        "clusters": [{"id": "edge", "label": "Edge"}],
        "edges": [],
        "key_decisions": ["Use a managed API gateway for routing and auth."],
        "nfr_mapping": [],
    }
    wbs = {"items": [{"id": "1.1", "name": "API Gateway setup"}],
           "effort_totals": {"total_mandays": 12}}
    findings = evaluate_solution(brief, blueprint, wbs)
    assert findings == []
