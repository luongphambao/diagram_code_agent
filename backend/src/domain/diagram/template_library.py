"""Render-spec template library for architecture blueprints.

Templates live in ``resources/diagram_templates/*.json`` at the repo root
(repo-tracked, hand-authored) PLUS ``agent_space/outputs/*/template.json``
(gitignored, machine-harvested from approved diagrams — see
``harvest_learned_template`` and ``tools/rendering_tools.py::finalize_diagram``).
They are intentionally render_spec-shaped so the architect can adapt real
topology examples without spending prompt tokens on large few-shot snippets.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_TEMPLATE_DIR = Path(__file__).resolve().parents[4] / "resources" / "diagram_templates"
_LEARNED_TEMPLATE_GLOB = "*/template.json"
# Cap on how many learned templates _load_all() will read, oldest-scored-out
# first (see _load_learned below) — keeps the in-memory catalog and the
# lru_cache bounded even after a long-running deployment harvests many.
_MAX_LEARNED_TEMPLATES = 50


def _norm(text: object) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def _template_text(template: dict[str, Any]) -> str:
    meta = template.get("_meta") or {}
    parts: list[str] = [
        meta.get("name", ""),
        meta.get("provider", ""),
        meta.get("layout_intent", ""),
        meta.get("summary", ""),
        " ".join(meta.get("tags") or []),
        template.get("diagram_title", ""),
        template.get("subtitle", ""),
    ]
    parts.extend(str(c.get("label") or c.get("id") or "") for c in template.get("clusters", []) or [])
    parts.extend(str(n.get("label") or n.get("id") or "") for n in template.get("nodes", []) or [])
    return " ".join(parts)


def _score_entry(template: dict[str, Any], query: str, provider: str = "") -> float:
    q_tokens = set(_norm(query))
    if not q_tokens:
        return 0.0
    meta = template.get("_meta") or {}
    text_tokens = set(_norm(_template_text(template)))
    overlap = len(q_tokens & text_tokens)
    score = float(overlap)
    name = str(meta.get("name") or "").lower()
    tags = " ".join(str(t).lower() for t in meta.get("tags") or [])
    q_lower = query.lower()
    if name and name.replace("_", " ") in q_lower:
        score += 4.0
    for phrase in ("landing zone", "multi az", "multi-az", "medallion", "lakehouse", "caf", "hub spoke"):
        if phrase in q_lower and phrase in tags:
            score += 2.0
    if provider:
        tpl_provider = str(meta.get("provider") or template.get("provider") or "").lower()
        if tpl_provider == provider.lower():
            score += 3.0
        elif tpl_provider:
            score -= 1.0
    return score


def _load_learned() -> list[dict[str, Any]]:
    """Machine-harvested templates from agent_space/outputs/*/template.json —
    written only for diagrams a human actually approved AND that passed the
    production scorecard (see harvest_learned_template / finalize_diagram).
    Capped and ranked by scorecard so a long-running deployment's catalog
    stays bounded and favors its best examples when trimming."""
    try:
        from backends import OUTPUTS_DIR
    except Exception:  # noqa: BLE001 — template library must not hard-fail if backends can't resolve
        return []
    if not OUTPUTS_DIR.exists():
        return []
    found: list[dict[str, Any]] = []
    for path in sorted(OUTPUTS_DIR.glob(_LEARNED_TEMPLATE_GLOB)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        meta = data.setdefault("_meta", {})
        meta.setdefault("name", f"learned_{path.parent.name}")
        meta.setdefault("provider", data.get("provider", ""))
        meta.setdefault("layout_intent", data.get("layout_intent", ""))
        meta.setdefault("tags", [])
        meta.setdefault("summary", "Auto-harvested from an approved, PASS-scoring diagram.")
        found.append(data)
    found.sort(key=lambda d: -float(d.get("scorecard") or 0.0))
    return found[:_MAX_LEARNED_TEMPLATES]


@lru_cache(maxsize=1)
def _load_all() -> tuple[dict[str, Any], ...]:
    templates: list[dict[str, Any]] = []
    if _TEMPLATE_DIR.exists():
        for path in sorted(_TEMPLATE_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            meta = data.setdefault("_meta", {})
            meta.setdefault("name", path.stem)
            meta.setdefault("provider", data.get("provider", ""))
            meta.setdefault("layout_intent", data.get("layout_intent", ""))
            meta.setdefault("tags", [])
            meta.setdefault("summary", "")
            templates.append(data)
    templates.extend(_load_learned())
    return tuple(templates)


def list_templates() -> list[dict[str, Any]]:
    """Return metadata and counts for every available template."""
    out: list[dict[str, Any]] = []
    for template in _load_all():
        meta = dict(template.get("_meta") or {})
        meta["nodes"] = len(template.get("nodes") or [])
        meta["clusters"] = len(template.get("clusters") or [])
        meta["edges"] = len(template.get("edges") or [])
        out.append(meta)
    return out


def load_template(name: str) -> dict[str, Any]:
    """Load one template by _meta.name or file stem."""
    wanted = str(name or "").strip().lower()
    for template in _load_all():
        meta = template.get("_meta") or {}
        if str(meta.get("name") or "").lower() == wanted:
            return copy.deepcopy(template)
    raise KeyError(f"unknown diagram template: {name}")


def find_template(query: str, provider: str = "", limit: int = 3) -> list[dict[str, Any]]:
    """Rank templates by token overlap against name, tags, summary, and labels.

    Ties on token-overlap score break toward the higher production scorecard
    (learned templates only — hand-authored repo templates carry no
    "scorecard" key and sort at 0.0 for this tiebreak, same as before),
    THEN alphabetically by name.
    """
    scored = [(_score_entry(template, query, provider), template) for template in _load_all()]
    scored = [(score, template) for score, template in scored if score > 0]
    scored.sort(
        key=lambda item: (
            -item[0],
            -float(item[1].get("scorecard") or 0.0),
            str((item[1].get("_meta") or {}).get("name") or ""),
        )
    )
    return [copy.deepcopy(template) for score, template in scored[: max(1, limit)]]


def template_skeleton(template: dict[str, Any]) -> dict[str, Any]:
    """Small shape for LLM adaptation: metadata plus topology, not render chrome."""
    meta = dict(template.get("_meta") or {})
    return {
        "_meta": meta,
        "provider": template.get("provider") or meta.get("provider", ""),
        "layout_intent": template.get("layout_intent") or meta.get("layout_intent", ""),
        "style_preset": template.get("style_preset", ""),
        "diagram_title": template.get("diagram_title", ""),
        "clusters": copy.deepcopy(template.get("clusters") or []),
        "nodes": copy.deepcopy(template.get("nodes") or []),
        "edges": copy.deepcopy(template.get("edges") or []),
        "counts": {
            "clusters": len(template.get("clusters") or []),
            "nodes": len(template.get("nodes") or []),
            "edges": len(template.get("edges") or []),
        },
    }


# ---------------------------------------------------------------------------
# Harvesting: approved-diagram -> learned template (§4.3 memory)
#
# Every display label a strip-chặt harvest is allowed to emit MUST come from a
# structural, categorical field (node.type / cluster.tier / edge.flow) — never
# from the free-text label an architect typed for THIS client's real system.
# An unmapped type is a reason to walk away, not a reason to guess: the whole
# diagram is skipped (harvest_learned_template returns None) rather than
# emitting a template with one un-genericized, possibly client-identifying
# label. See tools/rendering_tools.py::finalize_diagram for the (single) call
# site — it only ever calls this AFTER a human has approved the diagram AND
# the production scorecard passed.
# ---------------------------------------------------------------------------

_GENERIC_NODE_LABELS: dict[str, str] = {
    "service": "Service",
    "gateway": "Gateway",
    "api": "API",
    "database": "Database",
    "db": "Database",
    "cache": "Cache",
    "queue": "Queue",
    "topic": "Topic",
    "cdn": "CDN",
    "storage": "Storage",
    "bucket": "Storage",
    "compute": "Compute",
    "function": "Function",
    "lambda": "Function",
    "worker": "Worker",
    "load_balancer": "Load Balancer",
    "lb": "Load Balancer",
    "monitoring": "Monitoring",
    "security": "Security",
    "firewall": "Firewall",
    "waf": "WAF",
    "identity": "Identity Provider",
    "iam": "Identity Provider",
    "network": "Network",
    "vpn": "VPN",
    "dns": "DNS",
    "proxy": "Proxy",
    "client": "Client",
    "mobile": "Mobile Client",
    "browser": "Web Client",
    "external": "External System",
    "actor": "User",
    "user": "User",
    "person": "User",
    "server": "Server",
    "vm": "Virtual Machine",
    "container": "Container",
    "search": "Search Index",
    "analytics": "Analytics",
    "notification": "Notification Service",
    "logging": "Logging",
    "secret": "Secrets Manager",
    "registry": "Registry",
    "gpu": "GPU Compute",
    "ml": "ML Service",
}

_GENERIC_CLUSTER_TIERS: dict[str, str] = {
    "frontend": "Frontend",
    "backend": "Backend",
    "data": "Data",
    "infra": "Infrastructure",
    "edge": "Edge",
    "network": "Network",
    "security": "Security",
    "monitoring": "Observability",
    "integration": "Integration",
}


def _generic_node_label(node_type: str) -> str | None:
    key = (node_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _GENERIC_NODE_LABELS.get(key)


def harvest_learned_template(
    spec: dict[str, Any], plan: dict[str, Any] | None, scorecard_total: float
) -> dict[str, Any] | None:
    """Build a client-name-free, structure-only learned template from an
    approved render_spec. Returns None (do not harvest) if:
      - there are no nodes, or
      - ANY node's `type` doesn't map to a known-safe generic label.

    Keeps: provider, style_preset, layout_intent, the winning layout plan,
    and topology (cluster/node/edge ids + structural fields). Replaces every
    display label: node labels -> generic name from `type` (deduplicated with
    a counter suffix when a spec has more than one of the same type); cluster
    labels -> generic name from `tier`, else a positional "Zone N" (never the
    architect's free-text cluster label, which can itself be client-specific);
    edge labels -> Title-cased `flow` class, else "Flow". Drops diagram_title/
    subtitle/slide_title/source_page entirely (always free text, never needed
    for topology re-adaptation).
    """
    nodes = spec.get("nodes") or []
    if not nodes:
        return None

    type_counts: dict[str, int] = {}
    for n in nodes:
        t = str(n.get("type") or "").strip().lower()
        if _generic_node_label(t) is None:
            return None  # unmappable type -> walk away, don't guess
        type_counts[t] = type_counts.get(t, 0) + 1

    seen: dict[str, int] = {}
    clean_nodes: list[dict[str, Any]] = []
    for n in nodes:
        t = str(n.get("type") or "").strip().lower()
        base = _generic_node_label(t) or "Node"
        seen[t] = seen.get(t, 0) + 1
        label = f"{base} {seen[t]}" if type_counts[t] > 1 else base
        clean_nodes.append(
            {
                "id": n.get("id"),
                "label": label,
                "type": n.get("type"),
                "cluster": n.get("cluster"),
            }
        )

    clean_clusters: list[dict[str, Any]] = []
    for i, c in enumerate(spec.get("clusters") or [], start=1):
        tier = str(c.get("tier") or "").strip().lower()
        label = _GENERIC_CLUSTER_TIERS.get(tier) or f"Zone {i}"
        clean_clusters.append(
            {
                "id": c.get("id"),
                "label": label,
                "tier": c.get("tier"),
                "parent": c.get("parent") or "",
                "accent": c.get("accent"),
                "number": c.get("number"),
            }
        )

    clean_edges = [
        {
            "from": e.get("from"),
            "to": e.get("to"),
            "label": str(e.get("flow") or "flow").replace("_", " ").title(),
            "flow": e.get("flow"),
            "style": e.get("style"),
        }
        for e in (spec.get("edges") or [])
        if e.get("from") and e.get("to")
    ]

    provider = str(spec.get("provider") or "")
    tags = sorted({str(n.get("type") or "") for n in nodes if n.get("type")})
    # Deterministic, content-derived suffix (not a timestamp — this codebase's
    # convention avoids argless datetime.now()/uuid randomness in anything
    # that should stay reproducible) so repeat harvests of similarly-shaped
    # diagrams don't collide under the same _meta.name.
    shape_key = json.dumps([provider, len(clean_nodes), len(clean_edges), tags], sort_keys=True)
    shape_hash = hashlib.sha256(shape_key.encode("utf-8")).hexdigest()[:8]

    return {
        "provider": provider,
        "style_preset": spec.get("style_preset", ""),
        "layout_intent": spec.get("layout_intent", ""),
        "clusters": clean_clusters,
        "nodes": clean_nodes,
        "edges": clean_edges,
        "plan": copy.deepcopy(plan) if plan else None,
        "_meta": {
            "name": f"learned_{provider or 'generic'}_{len(clean_nodes)}n_{shape_hash}",
            "provider": provider,
            "layout_intent": spec.get("layout_intent", ""),
            "tags": tags,
            "summary": "Auto-harvested from an approved, PASS-scoring diagram (client details stripped).",
        },
        "scorecard": scorecard_total,
        "source": "learned",
    }
