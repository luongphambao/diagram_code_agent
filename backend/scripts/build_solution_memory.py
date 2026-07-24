"""Build the unified "solution memory" — case-study narrative + real WBS estimate/tech —
by merging two so-far-disconnected corpora:

  * ``DATA/SLIDE_IMAGES/*/analysis.md``  — 84 human-readable deck analyses (client/problem/
    solution/tech/domain). Already parsed by ``build_case_library.py``; this script REUSES
    those same regex parsers for the deterministic fields (client/type/domain/tech/problem/
    solution/outcome/image_ref) rather than duplicating them.
  * ``DATA/SOLUTION_WBS/*.json``        — 53 structured WBS files (real total_mandays,
    per-module MD, technology_stack, team_composition) normalised by
    ``domain.wbs.wbs_normalizer.load_all_projects``.

Why an LLM pass for the estimate/pricing/team fields (NOT plain regex)
-----------------------------------------------------------------------
Sampled across all 4 authoring batches (2026-07-24): phrasing for effort/timeline/pricing
is highly heterogeneous — free prose, buried inside critique paragraphs, sometimes a
rate-card table, sometimes a day-rate instead of a total, sometimes completely absent
("no billing model" noted by the analysis itself). A hand-written regex would silently
mis-extract (e.g. grab a module's sub-effort instead of the deck total) far more often than
it would cleanly fail — worse than the "not found" it's supposed to prevent, since a wrong
number becomes a bad benchmarking prior downstream. So those fields go through ONE-TIME
structured LLM extraction (``config.make_llm``, the ``main`` role model) per deck, with an
explicit "null if not stated, never invent a number" instruction and the deck's own
Team&Timeline / Chi phí sections as the only input. Cached in solution_memory.json by
source-mtime, so re-runs only re-extract decks that changed — this stays cheap and mostly
deterministic in practice (temperature=0, same prompt) even though it isn't pure regex.

The two corpora are joined narrative<->WBS by fuzzy client/name token overlap (best-effort;
unmatched decks/projects still appear, tagged by ``source``).

Run (from backend/, using the project venv which has langchain_openai + the domain package):
    ../.venv/Scripts/python.exe scripts/build_solution_memory.py [--no-llm] [--limit N]
Writes: backend/data/solution_memory.json

``--no-llm`` skips the LLM extraction pass entirely (fields come back null) — useful for a
fast structural dry-run of the join/dedup logic without spending any tokens.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Optional

# --- path setup: import build_case_library.py's parsers (same dir) + the domain package --
_SCRIPTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPTS_DIR.parent
_SRC_DIR = _BACKEND_DIR / "src"
for p in (str(_SCRIPTS_DIR), str(_SRC_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from build_case_library import (  # noqa: E402
    ROOT,
    SLIDE_IMAGES,
    _clip,
    _first,
    _image_ref,
    _infer_domains,
    _norm,
    _parse_client,
    _parse_tech,
    _parse_title,
    _parse_type,
    _section,
    _slug,
)

OUT_PATH = _BACKEND_DIR / "data" / "solution_memory.json"
_LLM_MODEL_ROLE = "main"  # config.yaml role to use for extraction (gpt-5.6-luna as of writing)

_TECH_ALIASES: dict[str, str] = {
    # kept in sync with backend/src/tools/icon_tools.py's _TECH_ALIASES — duplicated (not
    # imported) so this script stays free of that module's app-runtime dependencies
    # (backends.current_workspace / stage_markers), which assume a live session context.
    "kubernetes": "k8s",
    "postgres": "postgresql",
    "mongo": "mongodb",
    "js": "javascript",
    "ts": "typescript",
    "node": "nodejs",
}


def _squish_tech(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _canonical_tech(tech: list[str]) -> list[str]:
    """Dedupe tech names that differ only by alias/case/punctuation; keep first-seen display form."""
    seen: dict[str, str] = {}
    for t in tech:
        squished = _squish_tech(t)
        key = _squish_tech(_TECH_ALIASES.get(squished, squished))
        seen.setdefault(key, t.strip())
    return list(seen.values())


# --- structured LLM extraction of the fields regex can't reliably get ---------------------


class _DeckEstimate:
    """Plain container (not pydantic — avoids importing pydantic at module scope for the
    --no-llm fast path); built from the LLM's tool-call args or left all-None."""

    __slots__ = (
        "effort_md",
        "timeline_months",
        "timeline_text",
        "team_bnk_roles",
        "team_client_roles",
        "capex_usd",
        "capex_note",
        "opex_annual_usd",
        "pricing_model",
    )

    def __init__(self, **kw: Any) -> None:
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


def _extraction_schema() -> dict:
    """JSON schema for the LLM structured-output call (pydantic-free; passed straight to
    with_structured_output which accepts a raw JSON schema dict)."""
    return {
        "title": "DeckEstimate",
        "description": "Estimate/pricing/team facts stated in this deck analysis. Use null "
        "for anything not explicitly stated — never infer or invent a number.",
        "type": "object",
        "properties": {
            "effort_md": {
                "type": ["number", "null"],
                "description": "Total project effort in man-days (MD), if a single total figure is stated.",
            },
            "timeline_months": {
                "type": ["number", "null"],
                "description": "Total delivery timeline in months, if stated (convert weeks to months if needed).",
            },
            "timeline_text": {
                "type": ["string", "null"],
                "description": "Short verbatim-ish timeline summary, e.g. '0.5mo req + 1.5mo dev + 1mo UAT + 1mo support'.",
            },
            "team_bnk_roles": {
                "type": "array",
                "items": {"type": "string"},
                "description": "BnK-side roles mentioned (e.g. Project Manager, Tech Lead, Developer, BA/Tester). Empty list if none stated.",
            },
            "team_client_roles": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Client-side roles mentioned. Empty list if none stated.",
            },
            "capex_usd": {
                "type": ["number", "null"],
                "description": "Total one-off development cost (CAPEX) in USD, if an actual number is stated (not a placeholder like 'XXX USD').",
            },
            "capex_note": {
                "type": ["string", "null"],
                "description": "Short note on CAPEX, e.g. 'template placeholder, not filled' or 'license only, excludes implementation'.",
            },
            "opex_annual_usd": {
                "type": ["number", "null"],
                "description": "Annual recurring infra/license cost (OPEX) in USD, if stated (convert monthly*12 if needed).",
            },
            "pricing_model": {
                "type": ["string", "null"],
                "description": "Short label for the commercial model, e.g. 'Milestone 30/30/30/10', 'T&M staff augmentation', 'License-only (no service fee)'.",
            },
        },
        "required": [
            "effort_md",
            "timeline_months",
            "timeline_text",
            "team_bnk_roles",
            "team_client_roles",
            "capex_usd",
            "capex_note",
            "opex_annual_usd",
            "pricing_model",
        ],
    }


def _extraction_input(md: str) -> str:
    """The subset of the analysis.md most likely to carry estimate/pricing/team facts —
    keeps the LLM call cheap and focused instead of sending the whole (often 150-220 line) file."""
    parts = []
    for header_res in (
        (r"Team & Timeline",),
        (r"Chi ph[ií] & Billing Model", r"Pricing"),
    ):
        body = _section(md, *header_res)
        if body:
            parts.append(body)
    # Header line (Type/Client/Tech) gives useful context even if the two sections above are thin.
    header = "\n".join(md.splitlines()[:4])
    return header + "\n\n" + "\n\n".join(parts) if parts else header


_llm_cache: Any = None


def _get_llm():
    global _llm_cache
    if _llm_cache is not None:
        return _llm_cache
    from dotenv import load_dotenv

    load_dotenv(_BACKEND_DIR / ".env")

    import yaml

    cfg = yaml.safe_load((_BACKEND_DIR / "config.yaml").read_text(encoding="utf-8"))
    model_name = cfg.get("models", {}).get(_LLM_MODEL_ROLE, "gpt-5-mini")

    from config import make_llm

    llm = make_llm(model_name)
    _llm_cache = llm.with_structured_output(_extraction_schema())
    return _llm_cache


def _extract_estimate_llm(md: str, folder: str) -> _DeckEstimate:
    llm = _get_llm()
    text = _extraction_input(md)
    try:
        result = llm.invoke(
            "Extract estimate/pricing/team facts from this BnK proposal-deck analysis. "
            "Only report numbers explicitly present in the text; use null for anything not "
            "stated (do NOT estimate or infer). Text:\n\n" + text
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  WARN: LLM extraction failed for {folder!r}: {exc}", file=sys.stderr)
        return _DeckEstimate()
    if isinstance(result, dict):
        return _DeckEstimate(**result)
    # Some LangChain versions return a pydantic-like object for JSON-schema structured output.
    return _DeckEstimate(**dict(result))


# --- WBS-side corpus (structured, real numbers) --------------------------------------------


def _load_wbs_projects() -> list[dict]:
    """Normalised WBS projects as plain dicts (avoids a hard dependency on the domain
    package's pydantic models leaking into this script's output shape)."""
    from domain.wbs.wbs_normalizer import load_all_projects

    projects, errors = load_all_projects()
    for e in errors:
        print(f"  WARN: WBS load error: {e}", file=sys.stderr)
    out = []
    for p in projects:
        out.append(
            {
                "source_file": p.source_file or "",
                "project_code": p.project_code,
                "name": p.name,
                "client": p.client or "",
                "business_domain": p.business_domain,
                "solution_type": p.solution_type,
                "technology_stack": p.technology_stack,
                "total_mandays": p.total_mandays,
                "modules": [
                    {"code": m.code, "name": m.name, "total_md": m.total_md} for m in p.modules
                ],
            }
        )
    return out


# --- fuzzy join: narrative deck <-> WBS project by client/name token overlap --------------

_STOPWORDS = {
    "bnk",
    "solution",
    "proposal",
    "project",
    "system",
    "platform",
    "phase",
    "update",
    "updated",
    "ver",
    "version",
    "v1",
    "v2",
    "v3",
    "the",
    "a",
    "for",
    "and",
    "of",
    "plan",
    "wbs",
    "final",
    "draft",
    "co",
    "ltd",
    "inc",
    "case",
    "study",
}


def _tokens(*texts: str) -> set[str]:
    hay = " ".join(t for t in texts if t)
    hay = _norm(hay)
    toks = set(re.findall(r"[a-z0-9]+", hay))
    return {t for t in toks if t not in _STOPWORDS and len(t) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _match_wbs(deck_folder: str, deck_client: str, wbs_projects: list[dict]) -> tuple[Optional[dict], float]:
    """Best WBS project match for one narrative deck, by client+name token Jaccard overlap."""
    deck_toks = _tokens(deck_folder, deck_client)
    best, best_score = None, 0.0
    for wp in wbs_projects:
        wp_toks = _tokens(wp["name"], wp["client"])
        # weight client-name overlap higher than generic name overlap when both present
        score = _jaccard(deck_toks, wp_toks)
        if score > best_score:
            best, best_score = wp, score
    return (best, best_score) if best_score >= 0.34 else (None, best_score)


# --- main build -----------------------------------------------------------------------------


def build(*, use_llm: bool = True, limit: Optional[int] = None) -> list[dict]:
    if not SLIDE_IMAGES.is_dir():
        print(f"ERROR: {SLIDE_IMAGES} not found", file=sys.stderr)
        return []

    wbs_projects = _load_wbs_projects()
    print(f"Loaded {len(wbs_projects)} WBS projects from DATA/SOLUTION_WBS", file=sys.stderr)

    # load prior output for LLM-result caching (skip re-extraction for unchanged files)
    prior_by_folder: dict[str, dict] = {}
    if OUT_PATH.exists():
        try:
            for e in json.loads(OUT_PATH.read_text(encoding="utf-8")):
                if e.get("folder"):
                    prior_by_folder[e["folder"]] = e
        except Exception:  # noqa: BLE001
            pass

    analyses = sorted(SLIDE_IMAGES.glob("*/analysis.md"))
    if limit:
        analyses = analyses[:limit]

    used_wbs_source_files: set[str] = set()
    library: list[dict] = []
    skipped: list[str] = []

    for i, analysis in enumerate(analyses, 1):
        folder = analysis.parent.name
        md = analysis.read_text(encoding="utf-8")
        mtime = analysis.stat().st_mtime

        dtype = _parse_type(md)
        name_l = folder.lower()
        _SKIP_NAME_HINTS = ("manual", "introduction", "kick-off", "kickoff", "power query")
        _KEEP_TYPES = ("case study", "proposal", "solution")
        if any(h in name_l for h in _SKIP_NAME_HINTS):
            skipped.append(f"{folder} (name hint)")
            continue
        if dtype and not any(k in dtype.lower() for k in _KEEP_TYPES):
            skipped.append(f"{folder} (type={dtype!r})")
            continue

        client = _parse_client(md)
        tech = _canonical_tech(_parse_tech(md))
        problem = _section(md, r"B[aà]i to[aá]n", r"Problem", r"Bài toán")
        solution = _section(md, r"Gi[aả]i ph[aá]p", r"Proposed Solution", r"Solution")
        outcome = _section(md, r"KPIs?", r"Expected", r"Nh[aậ]n x[eé]t", r"Kết quả", r"Results")

        wbs_match, match_score = _match_wbs(folder, client, wbs_projects)
        if wbs_match:
            used_wbs_source_files.add(wbs_match["source_file"])

        # LLM estimate/pricing/team extraction — cached by mtime.
        prior = prior_by_folder.get(folder)
        if not use_llm:
            est = _DeckEstimate()
        elif prior and prior.get("_source_mtime") == mtime and prior.get("estimate"):
            est = _DeckEstimate(**prior["estimate"])
        else:
            print(f"[{i}/{len(analyses)}] extracting estimate: {folder}", file=sys.stderr)
            est = _extract_estimate_llm(md, folder)

        entry = {
            "slug": _slug(folder),
            "folder": folder,
            "title": _parse_title(md, folder),
            "client": client,
            "type": dtype,
            "domain": _infer_domains(f"{folder} {client} {' '.join(tech)} {problem[:400]}"),
            "tech": tech,
            "problem": _clip(problem, 400),
            "solution": _clip(solution, 400),
            "outcome": _clip(outcome, 300),
            "image_ref": _image_ref(analysis.parent),
            "estimate": est.as_dict(),
            "wbs_match": (
                {
                    "source_file": wbs_match["source_file"],
                    "match_score": round(match_score, 2),
                    "project_name": wbs_match["name"],
                    "project_client": wbs_match["client"],
                    "business_domain": wbs_match["business_domain"],
                    "solution_type": wbs_match["solution_type"],
                    "total_mandays": wbs_match["total_mandays"],
                    "technology_stack": wbs_match["technology_stack"],
                    "modules": wbs_match["modules"],
                }
                if wbs_match
                else None
            ),
            "source": "narrative+wbs" if wbs_match else "narrative",
            "_source_mtime": mtime,
        }
        library.append(entry)

    # WBS projects with no narrative match still carry real numbers worth keeping.
    wbs_only = 0
    for wp in wbs_projects:
        if wp["source_file"] in used_wbs_source_files:
            continue
        library.append(
            {
                "slug": _slug(wp["name"] or wp["source_file"]),
                "folder": None,
                "title": wp["name"],
                "client": wp["client"],
                "type": wp["solution_type"],
                "domain": _infer_domains(f"{wp['name']} {wp['client']} {' '.join(wp['technology_stack'])}"),
                "tech": _canonical_tech(wp["technology_stack"]),
                "problem": "",
                "solution": "",
                "outcome": "",
                "image_ref": None,
                "estimate": {
                    "effort_md": wp["total_mandays"],
                    "timeline_months": None,
                    "timeline_text": None,
                    "team_bnk_roles": [],
                    "team_client_roles": [],
                    "capex_usd": None,
                    "capex_note": None,
                    "opex_annual_usd": None,
                    "pricing_model": None,
                },
                "wbs_match": {
                    "source_file": wp["source_file"],
                    "match_score": None,
                    "project_name": wp["name"],
                    "project_client": wp["client"],
                    "business_domain": wp["business_domain"],
                    "solution_type": wp["solution_type"],
                    "total_mandays": wp["total_mandays"],
                    "technology_stack": wp["technology_stack"],
                    "modules": wp["modules"],
                },
                "source": "wbs_only",
                "_source_mtime": None,
            }
        )
        wbs_only += 1

    print(f"Parsed {len(analyses) - len(skipped)} narrative deck(s); skipped {len(skipped)}.", file=sys.stderr)
    for s in skipped:
        print(f"  - skip: {s}", file=sys.stderr)
    matched = sum(1 for e in library if e["source"] == "narrative+wbs")
    print(f"WBS-join matched: {matched} | WBS-only (no narrative): {wbs_only}", file=sys.stderr)
    return library


def main() -> int:
    use_llm = "--no-llm" not in sys.argv
    limit = None
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        limit = int(sys.argv[idx + 1])

    library = build(use_llm=use_llm, limit=limit)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(library)} entries -> {OUT_PATH.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
