"""Icon search relevance: _search_icon_hits (bundled pack) and aiicons.search
(AI-brand CDN) must rank/reject weak coincidental substring matches rather than
return a confidently-wrong icon (e.g. "engine" matching "volcengine.png", "ai"
matching "rails.png", "database" matching "blob-storage.png" via its category).
"""
from __future__ import annotations

from tools.icon_tools import _search_icon_hits
from domain.diagram.aiicons import search_ai_brands


def _stem(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def test_generic_category_query_prefers_name_match_over_category_only():
    """A bare "database" query must not return an icon that only matches via its
    category folder (e.g. blob-storage.png filed under azure/database/) — the
    real regression: "Relational Database" got Azure Blob Storage's icon."""
    hits = _search_icon_hits("database", "azure", limit=5)
    assert hits, "expected at least one real database icon"
    assert all("blob-storage" not in _stem(h) for h in hits[:1])


def test_short_token_does_not_match_via_bare_substring():
    """A 2-char query like "ai" must not match "rails.png" just because "ai" is
    a literal substring of "rails" — short tokens need a real word match."""
    hits = _search_icon_hits("ai", "programming", limit=5)
    assert all("rails" not in _stem(h) for h in hits)


def test_legit_bundled_searches_still_rank_the_canonical_icon_first():
    hits = _search_icon_hits("redis", None, limit=5)
    assert hits and _stem(hits[0]) == "redis.png"
    hits = _search_icon_hits("react", None, limit=5)
    assert hits and _stem(hits[0]) == "react.png"


def test_ai_brand_search_rejects_generic_engine_collision():
    """Generic architecture-role labels ("OCR Engine", "GNN Engine",
    "Recommendation Engine") must NOT match the "Volcano Engine" brand logo just
    because "engine" is a literal substring of "volcengine" — real bug found in
    a delivered diagram where 3 unrelated nodes all got the same wrong logo."""
    for label in ("OCR Engine", "GNN Engine", "Recommendation Engine"):
        assert search_ai_brands(label, limit=3) == [], label


def test_ai_brand_search_still_finds_real_brands():
    for q in ("redis", "openai", "claude"):
        results = search_ai_brands(q, limit=3)
        assert results, f"expected a match for real brand {q!r}"
        assert results[0]["brand"] == q
