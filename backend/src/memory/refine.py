"""Offline learning-loop consolidator: mine gate outcomes -> update global memory.

Synthesizes reject outcomes (with notes) from the `conversations` table into
structured style guidance written into `agent_space/memories/AGENTS.md` (the
file every agent gets in its system prompt every turn — see
docs/agent-design.md §6 and ADR 0001). The data going IN is already written by
code on every gate decision (`conversations.record_gate_outcome`, called from
`routers/chat.py`), so this script is the missing CONSUMER, not a new
producer — it was previously `backend/scripts/refine_memory.py`, which could
not run in the container (`.dockerignore` excludes `scripts/`) and had never
been executed against this repo's AGENTS.md (no `<!-- last_analyzed -->`
watermark on disk).

Usage (from `backend/`):
    uv run python -m memory.refine                # continual: new outcomes only
    uv run python -m memory.refine --bootstrap     # process full history
    uv run python -m memory.refine --dry-run       # preview, do not write

Requires:
    DATABASE_URL           — Postgres connection string (same as server).
    <provider API key>     — for the synthesis LLM call, via config.make_llm.
    DIAGRAM_AGENT_MODEL (optional) — defaults to mimo-v2.5-pro.

Deliberately NOT wired to a cron/scheduler in this change — it calls an LLM
and rewrites a file that lands in every agent's prompt every turn, so a human
should see the diff (--dry-run) before it's applied, same as every other gate
in this product.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

from backends import MEMORIES_DIR

_AGENTS_MD = MEMORIES_DIR / "AGENTS.md"

# Section headers this script knows how to synthesize INTO (see _route below).
# NOTE: "## Learned WBS Norms" is a fourth, hand-maintained section in the live
# file that this script never writes to — it's listed here only so it's
# visible as a real section name; _replace_section (below) no longer depends
# on this list to find section BOUNDARIES (that was the bug — see its
# docstring), so an unlisted section is safe either way.
_SECTIONS = [
    "## Do Not Do",
    "## Style Preferences",
    "## Learned Icon & Tech Notes",
    "## Learned WBS Norms",
]

# Hidden machine marker inside an HTML comment (deepagents strips comments before
# inject, so this never leaks into the model context but survives on disk).
_TIMESTAMP_PATTERN = re.compile(r"<!-- last_analyzed: ([^>]+) -->")
_H2_HEADER_RE = re.compile(r"^## .+$", re.MULTILINE)


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
    """Replace the content between ``header`` and the next ``## `` header.

    BUG FIX vs. the old scripts/refine_memory.py: the previous version found
    the "next section" boundary by searching only the headers enumerated in
    _SECTIONS. AGENTS.md has a FOURTH section ("## Learned WBS Norms", added
    by hand) that was never added to that list — so synthesizing into
    "## Learned Icon & Tech Notes" (the last-listed section) found no
    "next" boundary before end-of-file and silently deleted everything after
    it, including "## Learned WBS Norms". Scanning for ANY real "## " header
    in the text (this version) is correct regardless of what's enumerated in
    _SECTIONS, including sections nobody remembered to list.
    """
    start = text.find(header)
    if start == -1:
        # Section missing — append it.
        return text.rstrip() + f"\n\n{header}\n{new_body}\n"
    after = start + len(header)
    m = _H2_HEADER_RE.search(text, after)
    next_sec = m.start() if m else len(text)
    return text[:after] + "\n" + new_body + "\n" + text[next_sec:]


def _set_timestamp(text: str) -> str:
    ts = datetime.now(timezone.utc).isoformat()
    marker = f"<!-- last_analyzed: {ts} -->"
    if _TIMESTAMP_PATTERN.search(text):
        return _TIMESTAMP_PATTERN.sub(marker, text)
    # Insert after the title line (or at the very top if the file is empty).
    first_line_end = text.find("\n")
    if first_line_end != -1:
        return text[: first_line_end + 1] + f"\n{marker}\n" + text[first_line_end + 1 :]
    return marker + "\n" + text


# ---------------------------------------------------------------------------
# Postgres helpers
# ---------------------------------------------------------------------------


def _fetch_outcomes(since: datetime | None) -> list[dict]:
    """Return all gate outcomes, optionally filtered to those after ``since``."""
    try:
        import psycopg
    except ImportError:
        print("psycopg not installed. Run: uv add psycopg[binary] (or use the backend env).", file=sys.stderr)
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
        except Exception:  # noqa: BLE001 — a malformed row shouldn't abort the whole run
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
            results.append(
                {
                    "thread_id": thread_id,
                    "gate": o.get("gate", "unknown"),
                    "note": note,
                    "timestamp": ts_str,
                }
            )
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
    from config import make_llm
    from langchain_core.messages import HumanMessage

    notes_text = "\n".join(f"[{o['gate']}] {o['note']}" for o in outcomes)
    prompt = _SYNTHESIS_PROMPT.format(section=section.lstrip("# "), notes=notes_text)
    llm = make_llm(model).bind(temperature=0, max_tokens=800)
    resp = llm.invoke([HumanMessage(content=prompt)])
    return (resp.content or "").strip()


# ---------------------------------------------------------------------------
# Section routing: which outcomes belong to which section
# ---------------------------------------------------------------------------

# Only sections this script actually SYNTHESIZES into — "## Learned WBS Norms"
# is intentionally excluded (hand-maintained, no routing rule for it yet).
_SYNTHESIS_TARGETS = ["## Do Not Do", "## Style Preferences", "## Learned Icon & Tech Notes"]


def _route(outcomes: list[dict]) -> dict[str, list[dict]]:
    """Split outcomes into per-section buckets."""
    buckets: dict[str, list[dict]] = {s: [] for s in _SYNTHESIS_TARGETS}
    for o in outcomes:
        gate = o.get("gate", "")
        note = o.get("note", "").lower()
        if gate in ("propose_tech_stack", "propose_blueprint", "finalize_diagram"):
            buckets["## Do Not Do"].append(o)
        # Style notes often mention layout, color, style words.
        if any(
            w in note for w in ("style", "color", "layout", "direction", "align", "font", "cluster", "zone")
        ):
            buckets["## Style Preferences"].append(o)
        # Icon / import notes.
        if any(w in note for w in ("icon", "import", "path", "logo", "class")):
            buckets["## Learned Icon & Tech Notes"].append(o)
    return buckets


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Refine agent_space/memories/AGENTS.md from gate outcomes.")
    parser.add_argument(
        "--bootstrap", action="store_true", help="Process full history (ignore last_analyzed timestamp)."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the updated AGENTS.md to stdout, do not write."
    )
    args = parser.parse_args()

    model = os.getenv("DIAGRAM_AGENT_MODEL", "mimo-v2.5-pro")
    print(f"[memory.refine] model={model}  bootstrap={args.bootstrap}  dry_run={args.dry_run}")

    current_text = _read_agents_md()
    since = None if args.bootstrap else _last_analyzed(current_text)
    if since:
        print(f"[memory.refine] processing outcomes after {since.isoformat()}")
    else:
        print("[memory.refine] processing full history")

    outcomes = _fetch_outcomes(since)
    print(f"[memory.refine] found {len(outcomes)} reject outcomes with notes")

    if not outcomes:
        print("[memory.refine] nothing to learn — AGENTS.md unchanged")
        return

    buckets = _route(outcomes)
    updated = current_text
    for section, section_outcomes in buckets.items():
        if not section_outcomes:
            continue
        print(f"[memory.refine] synthesizing {len(section_outcomes)} items -> {section!r}")
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
        print(f"[memory.refine] wrote {_AGENTS_MD}")


if __name__ == "__main__":
    main()
