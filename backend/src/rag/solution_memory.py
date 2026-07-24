"""Load ``backend/data/solution_memory.json`` (built by
``backend/scripts/build_solution_memory.py``) and convert entries into LangChain-style
document dicts for the ``bnk_solutions`` Qdrant collection.

This is the unified corpus — each entry already merges the narrative case-study fields
(client/problem/solution/outcome/tech/domain, from ``DATA/SLIDE_IMAGES/*/analysis.md``) with
real WBS numbers where a same-project join was confirmed (effort MD, tech stack, module
skeleton, from ``DATA/SOLUTION_WBS/*.json``), plus LLM-extracted estimate/pricing/team facts.
One hit here answers both "case study" and "estimate + tech stack" — see the module
docstring of ``build_solution_memory.py`` for why the join/extraction is LLM-confirmed
rather than pure regex/token-overlap.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# backend/src/rag/solution_memory.py -> backend/ (2 levels up)
_DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "solution_memory.json"


def load_solution_memory(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load the unified solution-memory entries (empty list if the file doesn't exist yet —
    run ``build_solution_memory.py`` first)."""
    p = Path(path) if path else _DEFAULT_PATH
    if not p.exists():
        logger.warning(
            "solution_memory.json not found at %s — run "
            "`python backend/scripts/build_solution_memory.py` first.",
            p,
        )
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to parse solution_memory.json: %s", exc)
        return []


def entry_to_document(entry: dict[str, Any]) -> dict[str, Any]:
    """One solution-memory entry -> one embeddable document (project-granularity).

    ``page_content`` is what gets embedded (semantic match target); ``metadata`` carries
    the structured facts a caller actually wants back (estimate/tech/pricing/provenance) —
    kept flat and JSON-scalar-typed since Qdrant payload filtering wants simple values.
    """
    est = entry.get("estimate") or {}
    wbs = entry.get("wbs_match") or {}
    tech = entry.get("tech") or []
    domain = entry.get("domain") or []

    parts = [
        entry.get("title") or entry.get("folder") or "",
        entry.get("client") or "",
        entry.get("type") or "",
    ]
    if domain:
        parts.append("Domain: " + ", ".join(domain))
    if tech:
        parts.append("Tech: " + ", ".join(tech[:20]))
    if entry.get("problem"):
        parts.append("Problem: " + entry["problem"])
    if entry.get("solution"):
        parts.append("Solution: " + entry["solution"])
    if entry.get("outcome"):
        parts.append("Outcome: " + entry["outcome"])
    if est.get("pricing_model"):
        parts.append("Pricing: " + est["pricing_model"])
    if est.get("timeline_text"):
        parts.append("Timeline: " + est["timeline_text"])

    effort_md = est.get("effort_md") or wbs.get("total_mandays")

    metadata = {
        "granularity": "solution",
        "slug": entry.get("slug") or "",
        "folder": entry.get("folder") or "",
        "title": entry.get("title") or "",
        "client": entry.get("client") or "",
        "type": entry.get("type") or "",
        "domain": ", ".join(domain),
        "tech_keywords": ", ".join(tech[:20]),
        "business_domain": (domain[0] if domain else ""),
        "solution_type": entry.get("type") or "",
        "total_mandays": effort_md or 0,
        "capex_usd": est.get("capex_usd") or 0,
        "opex_annual_usd": est.get("opex_annual_usd") or 0,
        "pricing_model": est.get("pricing_model") or "",
        "timeline_months": est.get("timeline_months") or 0,
        "image_ref": entry.get("image_ref") or "",
        "source": entry.get("source") or "",
        "wbs_source_file": wbs.get("source_file") or "",
    }

    return {"page_content": "\n".join(p for p in parts if p), "metadata": metadata}


def solution_memory_to_documents(path: str | Path | None = None) -> list[dict[str, Any]]:
    """All solution-memory entries as embeddable documents."""
    entries = load_solution_memory(path)
    return [entry_to_document(e) for e in entries]
