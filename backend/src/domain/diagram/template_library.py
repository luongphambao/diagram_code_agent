"""Render-spec template library for architecture blueprints.

Templates live in ``resources/diagram_templates/*.json`` at the repo root. They
are intentionally render_spec-shaped so the architect can adapt real topology
examples without spending prompt tokens on large few-shot snippets.
"""

from __future__ import annotations

import copy
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_TEMPLATE_DIR = Path(__file__).resolve().parents[4] / "resources" / "diagram_templates"


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


@lru_cache(maxsize=1)
def _load_all() -> tuple[dict[str, Any], ...]:
    templates: list[dict[str, Any]] = []
    if not _TEMPLATE_DIR.exists():
        return ()
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
    """Rank templates by token overlap against name, tags, summary, and labels."""
    scored = [(_score_entry(template, query, provider), template) for template in _load_all()]
    scored = [(score, template) for score, template in scored if score > 0]
    scored.sort(key=lambda item: (-item[0], str((item[1].get("_meta") or {}).get("name") or "")))
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
