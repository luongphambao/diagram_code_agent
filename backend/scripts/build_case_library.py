"""Build a case-study library from the digested past-project decks.

Parses every ``DATA/SLIDE_IMAGES/*/analysis.md`` (the human-readable analyses already
produced for BnK's ~60 reference decks) into a compact JSON library that
``deck_resolver.pick_case_study`` matches against the current CSM to fill the
``SUCCESS STORY`` slide from a relevant past project.

Two analysis.md formats exist and both are handled:
  * NEW: a header line ``**Client:** … | **Tech:** … | **Type:** …``.
  * OLD (e.g. Ex Umbra): a ``## File Info`` table with ``| Client | … |`` rows and a
    ``### Tech Stack`` table.

Run once (re-run to refresh):
    python backend/scripts/build_case_library.py
Writes: backend/data/case_library.json

Deterministic; stdlib only; read-only over DATA/ (only writes the output JSON).
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

# repo root = parents[2] of this file (backend/scripts/build_case_library.py)
ROOT = Path(__file__).resolve().parents[2]
SLIDE_IMAGES = ROOT / "DATA" / "SLIDE_IMAGES"
OUT_PATH = ROOT / "backend" / "data" / "case_library.json"

# Only include decks that can serve as a success story / reference case.
_KEEP_TYPES = ("case study", "proposal", "solution")
_SKIP_NAME_HINTS = ("manual", "introduction", "kick-off", "kickoff", "power query")

# domain tag -> keyword triggers (matched case-insensitively over the whole analysis).
_DOMAIN_KEYWORDS = {
    "banking": ["bank", "l/c", "letter of credit", "swift", "trade finance", "payment", "finance", "kyc", "aml"],
    "insurance": ["insurance", "ageas", "life", "policy", "underwriting"],
    "agriculture": ["agricult", "farm", "soil", "yield", "crop", "boom sprayer"],
    "manufacturing": ["factory", "manufactur", "oee", "smart factory", "cnc", "plc", "production"],
    "logistics": ["logistic", "warehouse", "dispatch", "fleet", "shipping", "maritime", "crew"],
    "healthcare": ["clinic", "patient", "health", "care", "medical", "long-term care"],
    "retail": ["retail", "ecommerce", "e-commerce", "pos", "customer data platform", "cdp"],
    "document-ai": ["idp", "ocr", "document understanding", "textract", "discrepancy", "document processing"],
    "data-platform": ["data platform", "analytics", "etl", "data pipeline", "power bi", "tableau", "warehouse"],
    "ai-ml": ["ai", "machine learning", "ml", "llm", "gpt", "computer vision", "nlp", "sentiment"],
}


def _norm(text: str) -> str:
    """Lowercased, accent-stripped for keyword matching."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.lower()


def _section(md: str, *header_res: str) -> str:
    """Return the body of the first H2 section whose header matches any regex, else ''."""
    for hre in header_res:
        m = re.search(rf"^##\s*{hre}.*$", md, re.MULTILINE | re.IGNORECASE)
        if not m:
            continue
        start = m.end()
        nxt = re.search(r"^##\s", md[start:], re.MULTILINE)
        body = md[start: start + nxt.start()] if nxt else md[start:]
        return body.strip()
    return ""


def _first(md: str, pattern: str) -> str:
    m = re.search(pattern, md, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _demark(text: str) -> str:
    """Strip markdown noise (headers, bold, bullets, table pipes) to plain prose."""
    lines = []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln or set(ln) <= {"|", "-", ":", " "}:   # separators / table rules
            continue
        ln = re.sub(r"^#{1,6}\s*", "", ln)              # ### headers
        ln = re.sub(r"^\s*[-*]\s+", "", ln)             # bullet markers
        ln = ln.replace("|", " ").replace("**", "").replace("`", "")
        lines.append(ln.strip())
    return " ".join(lines)


def _clip(text: str, limit: int) -> str:
    text = " ".join(_demark(text).split())
    return text[:limit].rstrip() + ("…" if len(text) > limit else "")


def _slug(name: str) -> str:
    s = _norm(name)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60]


def _parse_client(md: str) -> str:
    return (
        _first(md, r"\*\*Client:\*\*\s*([^|\n]+)")
        or _first(md, r"^\|\s*Client\s*\|\s*([^|]+)\|")     # File Info table
        or _first(md, r"^\|\s*Vendor.*?\|\s*([^|]+)\|")
    )


def _parse_tech(md: str) -> list[str]:
    raw = _first(md, r"\*\*Tech:\*\*\s*([^\n]+)")
    if not raw:
        # OLD format: a "### Tech Stack" table -> pull the Technology column cells.
        block = _section(md, r"Ki[eế]n tr[uú]c.*Tech Stack", r"Tech Stack", r"Architecture")
        cells = re.findall(r"^\|[^|\n]*\|\s*([^|\n]+?)\s*\|", block, re.MULTILINE)
        raw = ", ".join(c for c in cells if c and not re.match(r"^-+$", c) and "Technology" not in c)
    parts = re.split(r"[,/|]", raw)
    seen, out = set(), []
    for p in parts:
        t = p.strip().strip("`*").strip()
        if 1 < len(t) <= 40 and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:20]


def _parse_type(md: str) -> str:
    return (
        _first(md, r"\*\*(?:Type|Document type)[:\*\s]*\s*([^|\n]+)")
        or _first(md, r"^\|\s*Document type\s*\|\s*([^|]+)\|")
    )


def _parse_title(md: str, folder: str) -> str:
    h1 = _first(md, r"^#\s+(.+)$")
    h1 = re.sub(r"^(Ph[aâ]n t[ií]ch|Analysis)\s*[:：-]\s*", "", h1, flags=re.IGNORECASE).strip()
    return h1 or folder.replace("_", " ").strip()


def _infer_domains(blob: str) -> list[str]:
    n = _norm(blob)
    return [tag for tag, kws in _DOMAIN_KEYWORDS.items() if any(_norm(k) in n for k in kws)]


def _image_ref(folder_dir: Path) -> str | None:
    # A mid-deck slide tends to be a real content/success-story slide, not the cover.
    for cand in ("slide_007.png", "slide_005.png", "slide_003.png", "slide_001.png"):
        if (folder_dir / cand).exists():
            return str((folder_dir / cand).relative_to(ROOT)).replace("\\", "/")
    return None


def build() -> list[dict]:
    if not SLIDE_IMAGES.is_dir():
        print(f"ERROR: {SLIDE_IMAGES} not found", file=sys.stderr)
        return []

    library: list[dict] = []
    skipped: list[str] = []
    for analysis in sorted(SLIDE_IMAGES.glob("*/analysis.md")):
        folder = analysis.parent.name
        md = analysis.read_text(encoding="utf-8")

        dtype = _parse_type(md)
        name_l = folder.lower()
        if any(h in name_l for h in _SKIP_NAME_HINTS):
            skipped.append(f"{folder} (name hint)")
            continue
        if dtype and not any(k in dtype.lower() for k in _KEEP_TYPES):
            skipped.append(f"{folder} (type={dtype!r})")
            continue

        client = _parse_client(md)
        tech = _parse_tech(md)
        problem = _section(md, r"B[aà]i to[aá]n", r"Problem", r"Bài toán")
        solution = _section(md, r"Gi[aả]i ph[aá]p", r"Proposed Solution", r"Solution")
        outcome = _section(md, r"KPIs?", r"Expected", r"Nh[aậ]n x[eé]t", r"Kết quả", r"Results")

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
        }
        library.append(entry)

    print(f"Parsed {len(library)} case(s); skipped {len(skipped)}.")
    for s in skipped:
        print(f"  - skip: {s}")
    return library


def main() -> int:
    library = build()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(library)} entries -> {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
