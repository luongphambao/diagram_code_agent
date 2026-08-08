"""Build the BnK knowledge graph from the two already-processed corpora and
load it into Postgres.

Inputs (both already exist, neither is re-derived here):
  * ``backend/data/solution_memory.json`` — 116 unified Opportunity entries,
    produced by ``build_solution_memory.py`` (deck narrative + LLM-confirmed
    WBS join).
  * ``DATA/SOLUTION_WBS/*.json``          — 52 raw WBS files, read directly so
    every project surfaces as a node, including the ~21 with no Opportunity
    match.

All entity resolution / vocabulary normalization is in :mod:`kg_vocab`
(role/phase/technology canonicalization) and :mod:`kg_transform` (the corpus →
node/edge mapping) — this script is only the file I/O + orchestration shell,
kept thin on purpose so the actual graph-building logic stays unit-testable
without a corpus or a database (``tests/test_kg_transform.py``,
``tests/test_kg_vocab.py``).

Writes, always:
    backend/data/kg/nodes.jsonl
    backend/data/kg/edges.jsonl
These are the portable canonical export — see [[kg-project-2026-08-08]] for
why storage was deliberately kept swappable (Postgres now, possibly Neo4j
later): both would load from the same two files.

Loads into Postgres when ``DATABASE_URL`` is set (fails loudly if it's set but
unreachable — a silently-skipped load is worse than a crash here, since the
jsonl files would look identical either way).

Run (from backend/, using the project venv):
    ../.venv/Scripts/python.exe scripts/build_knowledge_graph.py [--no-db] [--no-neo4j] [--no-kpi] [--min-tech-count N]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPTS_DIR.parent
_SRC_DIR = _BACKEND_DIR / "src"
for p in (str(_SRC_DIR), str(_SRC_DIR / "domain" / "kg"), str(_SRC_DIR / "rag")):
    if p not in sys.path:
        sys.path.insert(0, p)

import kg_transform  # noqa: E402
import kg_vocab as kv  # noqa: E402

ROOT = _BACKEND_DIR.parent
SOLUTION_MEMORY = _BACKEND_DIR / "data" / "solution_memory.json"
WBS_DIR = ROOT / "DATA" / "SOLUTION_WBS"
OUT_DIR = _BACKEND_DIR / "data" / "kg"
KPI_EXTRACT = OUT_DIR / "kpi_extract.json"


def _load_solution_memory() -> list[dict]:
    if not SOLUTION_MEMORY.exists():
        print(f"WARNING: {SOLUTION_MEMORY} missing — run build_solution_memory.py first", file=sys.stderr)
        return []
    return json.loads(SOLUTION_MEMORY.read_text(encoding="utf-8"))


def _load_wbs_payloads() -> dict[str, dict]:
    if not WBS_DIR.is_dir():
        print(f"WARNING: {WBS_DIR} missing (gitignored — expected on a fresh checkout)", file=sys.stderr)
        return {}
    payloads: dict[str, dict] = {}
    skipped: list[str] = []
    for path in sorted(WBS_DIR.glob("*.json")):
        if path.name == "_tmp_data.json":  # pre-aggregated dashboard feed, not a source WBS
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:  # noqa: BLE001
            skipped.append(f"{path.name}: {exc}")
            continue
        if isinstance(data, dict):
            payloads[path.name] = data
        else:
            skipped.append(f"{path.name}: top-level {type(data).__name__}, not an object")
    if skipped:
        print(f"WARNING: skipped {len(skipped)} unparseable WBS file(s):", file=sys.stderr)
        for s in skipped:
            print(f"  - {s}", file=sys.stderr)
    return payloads


def _load_kpi_extract() -> list[dict]:
    if not KPI_EXTRACT.exists():
        print(
            f"NOTE: {KPI_EXTRACT} missing — run scripts/extract_kpis.py first "
            "to include the Kpi facet (optional; the rest of the graph builds without it).",
            file=sys.stderr,
        )
        return []
    return json.loads(KPI_EXTRACT.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-db", action="store_true", help="skip the Postgres load, jsonl only")
    parser.add_argument(
        "--no-neo4j", action="store_true", help="skip the Neo4j load even if NEO4J_PASSWORD is set"
    )
    parser.add_argument(
        "--no-kpi", action="store_true", help="skip the Kpi facet even if kpi_extract.json exists"
    )
    parser.add_argument(
        "--min-tech-count",
        type=int,
        default=kv.TECH_MIN_PROJECT_COUNT,
        help="minimum distinct projects before a technology becomes a node",
    )
    args = parser.parse_args()

    solution_memory = _load_solution_memory()
    wbs_payloads = _load_wbs_payloads()
    kpi_extract = [] if args.no_kpi else _load_kpi_extract()
    print(
        f"Loaded {len(solution_memory)} opportunity entries, {len(wbs_payloads)} WBS files, "
        f"{sum(len(e.get('kpis') or []) for e in kpi_extract)} KPI facts."
    )

    nodes, edges = kg_transform.build_graph(
        solution_memory,
        wbs_payloads,
        min_tech_project_count=args.min_tech_count,
        kpi_extract=kpi_extract,
    )

    by_type: dict[str, int] = {}
    for n in nodes:
        by_type[n["type"]] = by_type.get(n["type"], 0) + 1
    by_rel: dict[str, int] = {}
    for e in edges:
        by_rel[e["rel"]] = by_rel.get(e["rel"], 0) + 1

    print(f"\nBuilt {len(nodes)} nodes, {len(edges)} edges.")
    print("Nodes by type:")
    for t, c in sorted(by_type.items(), key=lambda kv_: -kv_[1]):
        print(f"  {c:5d}  {t}")
    print("Edges by relation:")
    for r, c in sorted(by_rel.items(), key=lambda kv_: -kv_[1]):
        print(f"  {c:5d}  {r}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "nodes.jsonl").write_text(
        "\n".join(json.dumps(n, ensure_ascii=False, sort_keys=True) for n in nodes) + "\n", encoding="utf-8"
    )
    (OUT_DIR / "edges.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False, sort_keys=True) for e in edges) + "\n", encoding="utf-8"
    )
    print(f"\nWrote {OUT_DIR / 'nodes.jsonl'}")
    print(f"Wrote {OUT_DIR / 'edges.jsonl'}")

    import os

    if args.no_db:
        print("\n--no-db: skipping Postgres load.")
    elif not os.getenv("DATABASE_URL", "").strip():
        print("\nDATABASE_URL not set — skipping Postgres load (pass --no-db to silence this).")
    else:
        import kg_store  # noqa: E402  (imported late: only needed for the DB path)

        stats = kg_store.load_graph(nodes, edges)
        print(f"\nLoaded into Postgres: {stats}")
        print("graph_stats():", kg_store.graph_stats())

    if args.no_neo4j:
        print("\n--no-neo4j: skipping Neo4j load.")
    elif not os.getenv("NEO4J_PASSWORD", "").strip():
        print("\nNEO4J_PASSWORD not set — skipping Neo4j load (pass --no-neo4j to silence this).")
    else:
        import kg_neo4j  # noqa: E402  (imported late: only needed for the DB path)

        stats = kg_neo4j.load_graph(nodes, edges)
        print(f"\nLoaded into Neo4j: {stats}")
        print("graph_stats():", kg_neo4j.graph_stats())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
