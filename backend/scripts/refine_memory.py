"""Offline learning-loop analyzer: mine gate outcomes → update AGENTS.md.

Synthesizes reject outcomes (with notes) from the conversations table into
structured style guidance written into ``agent_space/memories/AGENTS.md``.

Usage:
    cd backend
    uv run python scripts/refine_memory.py              # continual: new outcomes only
    uv run python scripts/refine_memory.py --bootstrap  # process full history
    uv run python scripts/refine_memory.py --dry-run    # preview, do not write

Requires:
    DATABASE_URL   — Postgres connection string (same as server).
    OPENAI_API_KEY — for the synthesis LLM call.
    DIAGRAM_AGENT_MODEL (optional) — defaults to gpt-4.1-mini.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_BACKEND = Path(__file__).resolve().parent.parent
_AGENTS_MD = _BACKEND / "agent_space" / "memories" / "AGENTS.md"

# Section headers (must match AGENTS.md exactly)
_SECTIONS = ["## Do Not Do", "## Style Preferences", "## Learned Icon & Tech Notes"]

# Hidden machine marker inside an HTML comment (deepagents strips comments before
# inject, so this never leaks into the model context but survives on disk).
_TIMESTAMP_PATTERN = re.compile(r"<!-- last_analyzed: ([^>]+) -->")


# ---------------------------------------------------------------------------
# AGENTS.md read / write helpers
# ---------------------------------------------------------------------------

def _read_agents_md() -> str:
    if _AGENTS_MD.exists():
        return _AGENTS_MD.read_text(encoding="utf-8")
    return ""


def _last_analyzed(text: str) -> datetime | None:
    m = _TIMESTAMP_PATTERN.search(text)
    if m:
        try:
            return datetime.fromisoformat(m.group(1).rstrip("Z")).replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _replace_section(text: str, header: str, new_body: str) -> str:
    """Replace the content between ``header`` and the next ``##`` section."""
    start = text.find(header)
    if start == -1:
        # Section missing — append it.
        return text.rstrip() + f"\n\n{header}\n{new_body}\n"
    after = start + len(header)
    # Find next section header (or end of file).
    next_sec = len(text)
    for h in _SECTIONS:
        if h == header:
            continue
        idx = text.find(h, after)
        if idx != -1 and idx < next_sec:
            next_sec = idx
    return text[:after] + "\n" + new_body + "\n" + text[next_sec:]


def _set_timestamp(text: str) -> str:
    ts = datetime.now(timezone.utc).isoformat()
    marker = f"<!-- last_analyzed: {ts} -->"
    if _TIMESTAMP_PATTERN.search(text):
        return _TIMESTAMP_PATTERN.sub(marker, text)
    # Insert after the first HTML comment block (the managed-by comment).
    first_comment_end = text.find("-->")
    if first_comment_end != -1:
        ins = first_comment_end + len("-->")
        return text[:ins] + f"\n{marker}" + text[ins:]
    return marker + "\n" + text


# ---------------------------------------------------------------------------
# Postgres helpers
# ---------------------------------------------------------------------------

def _fetch_outcomes(since: datetime | None) -> list[dict]:
    """Return all gate outcomes, optionally filtered to those after ``since``."""
    try:
        import psycopg
    except ImportError:
        print("psycopg not installed. Run: pip install 'psycopg[binary]'", file=sys.stderr)
        sys.exit(1)

    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        print("DATABASE_URL not set.", file=sys.stderr)
        sys.exit(1)

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT thread_id, outcomes_json FROM conversations")
            rows = cur.fetchall()

    results: list[dict] = []
    for thread_id, outcomes_json in rows:
        try:
            outcomes = json.loads(outcomes_json or "[]")
        except Exception:
            continue
        for o in outcomes:
            if not isinstance(o, dict):
                continue
            decision = o.get("decision", "")
            note = (o.get("note") or "").strip()
            # Only reject outcomes with a note carry learning signal.
            if decision != "reject" or not note:
                continue
            ts_str = o.get("timestamp", "")
            if since and ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.rstrip("Z")).replace(tzinfo=timezone.utc)
                    if ts <= since:
                        continue
                except ValueError:
                    pass
            results.append({
                "thread_id": thread_id,
                "gate": o.get("gate", "unknown"),
                "note": note,
                "timestamp": ts_str,
            })
    return results


# ---------------------------------------------------------------------------
# LLM synthesis
# ---------------------------------------------------------------------------

_SYNTHESIS_PROMPT = """\
You are updating the style-guidance memory for a diagram-generation AI agent.
Below are user rejection notes collected from gate decisions.  Each note
explains WHY the user rejected a tech-stack, blueprint, or final-diagram
proposal.

Your task: synthesise these notes into a concise, de-duplicated, actionable
bullet list for the "{section}" section of the agent's AGENTS.md file.

Rules:
- Output ONLY the bullet lines (Markdown "- …"), no headings, no preamble.
- One bullet per distinct pattern. Merge similar items.
- Each bullet must be concrete and directly actionable.
- Format for "Do Not Do":  `- [gate] <pattern> — <brief reason>`
  (gate is one of: propose_tech_stack, propose_blueprint, finalize_diagram)
- Format for "Style Preferences": `- <what users prefer>`
- Format for "Learned Icon & Tech Notes": `- <service>: <path or import>`
- Do NOT include items already covered by generic library docs.
- Maximum 15 bullets. If nothing actionable, output a single line:
  `- (nothing learned yet)`

Rejection notes:
{notes}
"""


def _synthesize(section: str, outcomes: list[dict], model: str) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        print("openai not installed. Run: pip install openai", file=sys.stderr)
        sys.exit(1)

    notes_text = "\n".join(
        f"[{o['gate']}] {o['note']}" for o in outcomes
    )
    prompt = _SYNTHESIS_PROMPT.format(section=section.lstrip("# "), notes=notes_text)
    client = OpenAI()
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=800,
    )
    return resp.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Section routing: which outcomes belong to which section
# ---------------------------------------------------------------------------

def _route(outcomes: list[dict]) -> dict[str, list[dict]]:
    """Split outcomes into per-section buckets."""
    buckets: dict[str, list[dict]] = {s: [] for s in _SECTIONS}
    for o in outcomes:
        gate = o.get("gate", "")
        note = o.get("note", "").lower()
        if gate in ("propose_tech_stack", "propose_blueprint", "finalize_diagram"):
            buckets["## Do Not Do"].append(o)
        # Style notes often mention layout, color, style words.
        if any(w in note for w in ("style", "color", "layout", "direction", "align", "font", "cluster")):
            buckets["## Style Preferences"].append(o)
        # Icon / import notes.
        if any(w in note for w in ("icon", "import", "path", "logo", "class")):
            buckets["## Learned Icon & Tech Notes"].append(o)
    return buckets


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Refine AGENTS.md from gate outcomes.")
    parser.add_argument("--bootstrap", action="store_true",
                        help="Process full history (ignore last_analyzed timestamp).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the updated AGENTS.md to stdout, do not write.")
    args = parser.parse_args()

    model = os.getenv("DIAGRAM_AGENT_MODEL", "gpt-4.1-mini")
    print(f"[refine_memory] model={model}  bootstrap={args.bootstrap}  dry_run={args.dry_run}")

    current_text = _read_agents_md()
    since = None if args.bootstrap else _last_analyzed(current_text)
    if since:
        print(f"[refine_memory] processing outcomes after {since.isoformat()}")
    else:
        print("[refine_memory] processing full history")

    outcomes = _fetch_outcomes(since)
    print(f"[refine_memory] found {len(outcomes)} reject outcomes with notes")

    if not outcomes:
        print("[refine_memory] nothing to learn — AGENTS.md unchanged")
        return

    buckets = _route(outcomes)
    updated = current_text
    for section, section_outcomes in buckets.items():
        if not section_outcomes:
            continue
        print(f"[refine_memory] synthesizing {len(section_outcomes)} items → {section!r}")
        new_body = _synthesize(section, section_outcomes, model)
        updated = _replace_section(updated, section, new_body)

    updated = _set_timestamp(updated)

    if args.dry_run:
        print("\n--- AGENTS.md preview ---")
        print(updated)
        print("--- end preview ---")
    else:
        _AGENTS_MD.parent.mkdir(parents=True, exist_ok=True)
        _AGENTS_MD.write_text(updated, encoding="utf-8")
        print(f"[refine_memory] wrote {_AGENTS_MD}")


if __name__ == "__main__":
    main()
