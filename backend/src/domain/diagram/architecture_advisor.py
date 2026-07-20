"""Small deterministic architecture advisor for diagram planning.

This module intentionally stays lightweight: it extracts planning signals that
help the agent choose an architecture pattern and diagram scope. It is not a
cost estimator or a substitute for the user's approved blueprint.
"""

from __future__ import annotations

import re
from typing import Any


_APP_TYPES: dict[str, list[str]] = {
    "e_commerce": ["e-commerce", "ecommerce", "shopping", "checkout", "cart", "marketplace", "payment"],
    "data_analytics": ["analytics", "dashboard", "bi", "reporting", "etl", "data lake", "warehouse"],
    "api_service": ["api", "microservice", "backend", "rest", "graphql", "webhook"],
    "mobile_app": ["mobile", "ios", "android", "push notification"],
    "iot": ["iot", "sensor", "device", "telemetry", "edge"],
    "ml_ai": ["machine learning", "ml", "ai", "llm", "rag", "model inference"],
    "web_application": ["web app", "website", "portal", "frontend", "spa", "static site"],
}

_CAPABILITIES: dict[str, list[str]] = {
    "authentication": ["auth", "login", "signup", "identity", "sso", "iam", "oauth", "oidc"],
    "cdn_static_hosting": ["cdn", "cloudfront", "static", "s3", "object storage", "blob"],
    "container_orchestration": ["eks", "kubernetes", "k8s", "ecs", "container", "docker"],
    "database": ["database", "rds", "aurora", "postgres", "mysql", "sql", "dynamodb", "mongodb"],
    "cache": ["cache", "redis", "elasticache", "memcached"],
    "messaging": ["queue", "event", "kafka", "sns", "sqs", "pubsub", "stream"],
    "ci_cd": ["ci/cd", "cicd", "github actions", "gitlab", "jenkins", "argocd", "argo cd", "pipeline"],
    "monitoring": ["monitoring", "observability", "metrics", "logs", "cloudwatch", "prometheus", "grafana"],
    "security": ["security", "waf", "guardduty", "security hub", "secrets", "kms", "zero trust"],
    "governance": ["governance", "organization", "organizations", "multi-account", "landing zone", "control tower", "audit"],
    "multi_region": ["multi-region", "global", "disaster recovery", "dr", "failover"],
}

_PROVIDERS: dict[str, list[str]] = {
    "aws": ["aws", "amazon web services", "cloudfront", "s3", "eks", "rds", "aurora", "lambda", "guardduty"],
    "azure": ["azure", "app service", "aks", "cosmos", "entra", "blob storage"],
    "gcp": ["gcp", "google cloud", "cloud run", "gke", "cloud sql", "pub/sub"],
    "oci": ["oci", "oracle cloud"],
    "onprem": ["on-prem", "on premises", "self-hosted", "datacenter", "data center"],
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _contains_any(text: str, needles: list[str]) -> bool:
    return any(n in text for n in needles)


def _count_hits(text: str, needles: list[str]) -> int:
    return sum(1 for n in needles if n in text)


def _detect_application_type(text: str) -> str:
    scored = {name: _count_hits(text, keys) for name, keys in _APP_TYPES.items()}
    best = max(scored, key=scored.get)
    return best if scored[best] > 0 else "web_application"


def _detect_scale(text: str) -> str:
    if _contains_any(text, ["enterprise", "millions", "global", "high volume", "large scale"]):
        return "enterprise"
    if _contains_any(text, ["100k", "hundred thousand", "high traffic", "production ready", "commercial"]):
        return "large"
    if _contains_any(text, ["mvp", "prototype", "demo", "small", "internal tool", "poc"]):
        return "small"
    nums = re.findall(r"(\d+)\s*(k|m|thousand|million)?\s+users?", text)
    if nums:
        raw, suffix = nums[0]
        users = int(raw)
        if suffix in {"k", "thousand"}:
            users *= 1_000
        elif suffix in {"m", "million"}:
            users *= 1_000_000
        if users >= 1_000_000:
            return "enterprise"
        if users >= 100_000:
            return "large"
        if users < 1_000:
            return "small"
    return "medium"


def _detect_security(text: str) -> str:
    if _contains_any(text, ["hipaa", "pci", "sox", "zero trust", "critical", "government"]):
        return "critical"
    if _contains_any(text, ["gdpr", "compliance", "audit", "financial", "personal data", "governance"]):
        return "high"
    if _contains_any(text, ["login", "auth", "secure", "encryption", "https", "iam"]):
        return "standard"
    return "basic"


def _detect_provider(text: str, provider_preference: str = "") -> str:
    pref = provider_preference.strip().lower()
    if pref:
        return pref
    scored = {provider: _count_hits(text, keys) for provider, keys in _PROVIDERS.items()}
    best = max(scored, key=scored.get)
    return best if scored[best] > 0 else ""


def _detect_capabilities(text: str) -> list[str]:
    return [name for name, keys in _CAPABILITIES.items() if _contains_any(text, keys)]


def _constraints(text: str) -> list[str]:
    found: list[str] = []
    if _contains_any(text, ["production", "prod", "client-facing", "overview"]):
        found.append("production_focused")
    if _contains_any(text, ["governance", "multi-account", "landing zone", "control tower", "organizations"]):
        found.append("governance_required")
    if _contains_any(text, ["compliance", "audit", "pci", "hipaa", "gdpr", "sox"]):
        found.append("compliance_sensitive")
    if _contains_any(text, ["low cost", "budget", "cost-effective", "cheap"]):
        found.append("budget_sensitive")
    if _contains_any(text, ["multi-region", "disaster recovery", "failover", "high availability", "ha"]):
        found.append("resilience_required")
    return found


def _pattern_score(pattern: str, capabilities: set[str], constraints: set[str], app_type: str, scale: str, security: str, provider: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    def add(points: int, reason: str) -> None:
        nonlocal score
        score += points
        reasons.append(reason)

    if pattern == "aws_multi_account_governance":
        if provider == "aws":
            add(2, "AWS provider detected")
        if "governance" in capabilities or "governance_required" in constraints:
            add(5, "governance or multi-account requirement detected")
        if security in {"high", "critical"}:
            add(2, f"{security} security signal")
        if "production_focused" in constraints:
            add(1, "production-focused overview")
    elif pattern == "containerized_kubernetes":
        if "container_orchestration" in capabilities:
            add(5, "container orchestration detected")
        if "ci_cd" in capabilities:
            add(1, "deployment pipeline detected")
        if scale in {"large", "enterprise"}:
            add(1, f"{scale} scale")
    elif pattern == "serverless":
        if _has_any(capabilities, {"cdn_static_hosting", "messaging"}) and app_type in {"api_service", "web_application"}:
            add(2, "web/API workload with managed services")
        if scale in {"small", "medium"}:
            add(1, "small/medium scale can benefit from managed scaling")
    elif pattern == "three_tier":
        if app_type in {"web_application", "e_commerce"}:
            add(3, f"{app_type} application")
        if "database" in capabilities:
            add(2, "database-backed workload")
    elif pattern == "microservices":
        if app_type == "api_service":
            add(2, "API/service workload")
        if scale in {"large", "enterprise"}:
            add(2, f"{scale} scale")
        if "container_orchestration" in capabilities:
            add(2, "container platform detected")
    elif pattern == "event_driven":
        if "messaging" in capabilities:
            add(4, "queue/stream/event capability detected")
    elif pattern == "data_pipeline":
        if app_type == "data_analytics":
            add(4, "analytics/data application")
        if "messaging" in capabilities:
            add(1, "streaming or event input")
    elif pattern == "static_site_jamstack":
        if "cdn_static_hosting" in capabilities:
            add(3, "static hosting/CDN detected")
        if app_type == "web_application":
            add(1, "web application")

    return score, reasons


def _has_any(values: set[str], targets: set[str]) -> bool:
    return bool(values.intersection(targets))


_PATTERN_COST_META: dict[str, dict[str, Any]] = {
    "aws_multi_account_governance": {
        "relative_cost": "high",
        "cost_drivers": ["AWS Organizations + Control Tower licensing", "per-account CloudTrail/Config costs", "Transit Gateway data transfer"],
    },
    "containerized_kubernetes": {
        "relative_cost": "medium",
        "cost_drivers": ["managed cluster control-plane fee", "node instance costs", "persistent volume storage"],
    },
    "three_tier": {
        "relative_cost": "medium",
        "cost_drivers": ["load balancer hourly fee", "multi-AZ RDS standby instance", "EC2/container instance costs"],
    },
    "serverless": {
        "relative_cost": "low",
        "cost_drivers": ["per-invocation Lambda pricing", "API Gateway request cost", "cold-start mitigation (provisioned concurrency)"],
    },
    "microservices": {
        "relative_cost": "high",
        "cost_drivers": ["per-service container/VM overhead", "service mesh sidecar resources", "inter-service network egress"],
    },
    "event_driven": {
        "relative_cost": "medium",
        "cost_drivers": ["message broker throughput pricing", "consumer instance costs", "dead-letter queue storage"],
    },
    "data_pipeline": {
        "relative_cost": "medium",
        "cost_drivers": ["compute cluster (Spark/Glue) job hours", "data lake storage", "egress between stages"],
    },
    "static_site_jamstack": {
        "relative_cost": "low",
        "cost_drivers": ["CDN request/bandwidth charges", "object storage hosting cost"],
    },
}


def _suggest_patterns(app_type: str, scale: str, security: str, provider: str, capabilities: list[str], constraints: list[str]) -> list[dict[str, Any]]:
    caps = set(capabilities)
    cons = set(constraints)
    names = list(_PATTERN_COST_META.keys())
    out: list[dict[str, Any]] = []
    for name in names:
        score, reasons = _pattern_score(name, caps, cons, app_type, scale, security, provider)
        if score > 0:
            cost_meta = _PATTERN_COST_META.get(name, {})
            out.append({
                "pattern": name,
                "fit": "high" if score >= 6 else "medium" if score >= 3 else "low",
                "score": score,
                "reasons": reasons[:4],
                "relative_cost": cost_meta.get("relative_cost", "medium"),
                "cost_drivers": cost_meta.get("cost_drivers", []),
            })
    out.sort(key=lambda item: item["score"], reverse=True)
    return out[:5]


def _concerns(scale: str, security: str, capabilities: list[str], constraints: list[str]) -> list[str]:
    caps = set(capabilities)
    cons = set(constraints)
    out: list[str] = []
    if security in {"high", "critical"}:
        mandatory = [
            "encryption at rest and in transit for all data stores",
            "IAM boundary with least-privilege roles per service",
            "audit trail (CloudTrail / Activity Log / Cloud Audit Logs)",
            "network isolation (VPC/subnet boundaries, security groups)",
        ]
        if security == "critical":
            mandatory += [
                "WAF + DDoS protection on public ingress",
                "secrets management (Vault / Secrets Manager) — no plaintext credentials",
                "compliance boundary annotation (HIPAA/PCI zone or equivalent)",
            ]
        out.append(
            f"Security level is {security}; the blueprint MUST show: "
            + "; ".join(mandatory)
            + ". Missing any of these is a medium critic finding."
        )
    if "governance_required" in cons:
        out.append("Governance is in scope; show management/security/production boundaries or explain simplification.")
    if scale in {"large", "enterprise"} and "monitoring" not in caps:
        out.append("Large-scale signal detected; include observability as an aggregated side-channel.")
    if "production_focused" in cons:
        out.append("Production-focused overview; collapse dev/staging and secondary accounts unless explicitly requested.")
    if "ci_cd" in caps and "container_orchestration" in caps:
        out.append("CI/CD plus orchestration detected; keep deployment lane separate from runtime request path.")
    return out


def analyze_requirements(requirements: str, provider_preference: str = "") -> dict[str, Any]:
    """Return architecture planning signals from natural-language requirements."""
    text = _norm(requirements)
    app_type = _detect_application_type(text)
    scale = _detect_scale(text)
    security = _detect_security(text)
    provider = _detect_provider(text, provider_preference)
    capabilities = _detect_capabilities(text)
    constraints = _constraints(text)
    patterns = _suggest_patterns(app_type, scale, security, provider, capabilities, constraints)
    concerns = _concerns(scale, security, capabilities, constraints)

    n_capabilities = len(capabilities)
    recommended_density = (
        "poster"
        if (scale in ("enterprise", "large") and n_capabilities >= 5)
        else "standard"
    )

    return {
        "application_type": app_type,
        "scale_level": scale,
        "security_level": security,
        "provider_preference": provider,
        "detected_capabilities": capabilities,
        "constraints": constraints,
        "suggested_patterns": patterns,
        "concerns": concerns,
        "recommended_density": recommended_density,
        "recommended_density_reason": (
            f"scale={scale}, {n_capabilities} detected capabilities → poster grid"
            if recommended_density == "poster"
            else f"scale={scale}, {n_capabilities} capabilities → standard slide"
        ),
    }
