"""Extract KPI/outcome facts from every ``DATA/SLIDE_IMAGES/*/analysis.md``,
WITH explicit per-KPI client attribution — the facet deliberately left out of
the first knowledge-graph build (see [[kg-project-2026-08-08]]).

Why this needs an LLM pass, not regex
--------------------------------------
The corpus itself repeatedly warns that KPI numbers in a proposal often belong
to a DIFFERENT client's case study, cited as evidence of capability rather
than as a commitment for the deck's own subject. The BnK - CMC RPA Proposal
deck is the clearest example: its own analysis says outright "Các con số này
là kết quả từ dự án khác, không phải cam kết KPI riêng cho CMC Telecom" — every
KPI in that section belongs to Eximbank/BIDV/Sacombank. A regex over "KPI"
keywords cannot tell those apart; only reading the surrounding sentence can.

Validated on that exact adversarial case (2026-08-08, ad-hoc smoke test) using
``cx/gpt-5.6-luna`` via the ``bnk_router`` provider: 0 misattributed KPIs
across 36 extracted facts, with ``is_commitment_for_subject_client`` correctly
false for every one of the 27 case-study rows. The one issue found — the
model also captured hardware counts and BnK's own team-capacity stats as
"KPIs" — is fixed here by narrowing the prompt's definition and giving
explicit include/exclude examples, not by changing the attribution approach.

Why plain prompting, not ``.with_structured_output()``
--------------------------------------------------------
``config.yaml`` documents ``bnk_router`` as ``supports_structured_output:
false`` — LangChain's structured-output tool-call schema isn't honoured by
the gateway and raises a ChatMessage validation error. This prompts for JSON
directly and parses the response text instead.

Run (from backend/, using the project venv):
    ../.venv/Scripts/python.exe scripts/extract_kpis.py [--limit N] [--model cx/gpt-5.6-luna]
Writes: backend/data/kg/kpi_extract.json

Cached by source-mtime like build_solution_memory.py — re-runs only
re-extract decks whose analysis.md changed since the last run.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPTS_DIR.parent
_SRC_DIR = _BACKEND_DIR / "src"
for p in (str(_SCRIPTS_DIR), str(_SRC_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from build_case_library import ROOT, SLIDE_IMAGES  # noqa: E402

OUT_PATH = _BACKEND_DIR / "data" / "kg" / "kpi_extract.json"
DEFAULT_MODEL = "cx/gpt-5.6-luna"

PROMPT = """You are extracting BUSINESS OUTCOME METRICS (KPIs) from a BnK \
sales-proposal analysis (Vietnamese), with careful client attribution.

INCLUDE only metrics that describe a business RESULT or EXPECTED OUTCOME of \
the automation/solution — accuracy rate, % automated, time/cost reduction, \
uptime, error reduction, throughput, ROI, SLA response time, and similar.

EXCLUDE (do NOT list these as KPIs):
  - Infrastructure/hardware counts (number of servers, gateways, licenses)
  - BnK's own company/team capacity stats (headcount, number of past projects,
    years as a partner) — these describe BnK, not a solution outcome
  - Project scope counts (number of processes/modules in THIS project's scope)
    unless explicitly framed as an achieved or targeted result
  - Timeline/duration figures (those belong to a separate timeline facet)

For each KPI you keep, identify which client the number is ACTUALLY about —
read the surrounding sentence carefully. The deck's main subject client and
the client a case-study KPI is illustrating are often DIFFERENT. If the text
says the figures are "not a commitment for [subject client]" or similar,
reflect that explicitly.

Return ONLY a JSON object, no markdown fences, no commentary:
{{
  "deck_subject_client": "<the client this deck's own proposal is FOR, or empty string if none>",
  "kpis": [
    {{
      "metric": "<short metric name>",
      "value": "<the stated number/percentage>",
      "attributed_client": "<which client this number is actually about>",
      "is_commitment_for_subject_client": <true|false>,
      "slide_evidence": "<slide number(s) cited near this KPI, or empty string>"
    }}
  ]
}}

Analysis text:
{text}
"""

_llm_cache: Any = None
_model_name = DEFAULT_MODEL


def _get_llm():
    global _llm_cache
    if _llm_cache is not None:
        return _llm_cache
    from dotenv import load_dotenv

    load_dotenv(_BACKEND_DIR / ".env")
    from config import make_llm

    _llm_cache = make_llm(_model_name)
    return _llm_cache


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    return json.loads(raw)


def extract_one(md: str, folder: str) -> dict:
    llm = _get_llm()
    try:
        resp = llm.invoke(PROMPT.format(text=md))
        raw = resp.content if hasattr(resp, "content") else str(resp)
        data = _extract_json(raw)
    except Exception as exc:  # noqa: BLE001
        print(f"  WARN: KPI extraction failed for {folder!r}: {exc}", file=sys.stderr)
        return {"deck_subject_client": "", "kpis": []}
    if not isinstance(data, dict) or not isinstance(data.get("kpis"), list):
        print(f"  WARN: malformed KPI extraction shape for {folder!r}: {data!r}", file=sys.stderr)
        return {"deck_subject_client": "", "kpis": []}
    return data


def build(*, limit: int | None = None, model: str = DEFAULT_MODEL) -> list[dict]:
    global _model_name
    _model_name = model

    if not SLIDE_IMAGES.is_dir():
        print(f"ERROR: {SLIDE_IMAGES} not found", file=sys.stderr)
        return []

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

    out: list[dict] = []
    for i, path in enumerate(analyses, 1):
        folder = path.parent.name
        mtime = path.stat().st_mtime
        prior = prior_by_folder.get(folder)
        if prior and prior.get("_source_mtime") == mtime and prior.get("_model") == model:
            out.append(prior)
            continue

        md = path.read_text(encoding="utf-8", errors="replace")
        print(f"[{i}/{len(analyses)}] extracting {folder!r}...", file=sys.stderr)
        result = extract_one(md, folder)
        out.append(
            {
                "folder": folder,
                "deck_subject_client": result.get("deck_subject_client", ""),
                "kpis": result.get("kpis", []),
                "_source_mtime": mtime,
                "_model": model,
            }
        )

    return out


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    entries = build(limit=args.limit, model=args.model)
    n_kpis = sum(len(e.get("kpis") or []) for e in entries)
    print(f"Extracted {n_kpis} KPI(s) across {len(entries)} deck(s).", file=sys.stderr)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {n_kpis} KPI(s) -> {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
