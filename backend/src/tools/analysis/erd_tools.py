"""ERD internals — structural lint + the Pydantic-model-to-render_spec
projection (improvement plan MVP-3 phase 3, typed-diagram foundation).

Library functions, not an LLM-facing tool — the LLM authors an ERD code-first
(see `prettygraph/erd_dsl.py`), executed via
`tools/rendering_tools.py::render_typed_diagram`, which validates the
script's output against `ERDSpec` and then calls `_build_erd_render_spec` +
(via `_render_native_from_spec`'s registry dispatch) `lint_erd` — same
validation/render engine shape as sequence (phase 2), just for tables/FKs.
"""

from __future__ import annotations

from langchain_core.tools import tool

from domain.validation.diagram_lint import LintReport, register_linter
from ..schemas.erd import ERDSpec


def _build_erd_render_spec(spec: ERDSpec) -> dict:
    """Flatten an ERDSpec into the plain-dict render_spec
    `prettygraph.native.erd.build_erd_tree` consumes."""
    return {
        "kind": "erd",
        "title": spec.title,
        "entities": [
            {
                "id": e.id,
                "name": e.name,
                "schema": e.schema_,
                "columns": [
                    {
                        "name": c.name,
                        "data_type": c.data_type,
                        "primary_key": c.primary_key,
                        "foreign_key": c.foreign_key,
                        "nullable": c.nullable,
                        "unique": c.unique,
                        "default": c.default,
                        "references": c.references,
                    }
                    for c in e.columns
                ],
                "indexes": list(e.indexes),
            }
            for e in spec.entities
        ],
        "relationships": [
            {
                "from_entity": r.from_entity,
                "from_columns": list(r.from_columns),
                "to_entity": r.to_entity,
                "to_columns": list(r.to_columns),
                "cardinality": r.cardinality,
                "on_delete": r.on_delete,
            }
            for r in spec.relationships
        ],
    }


def lint_erd(spec: dict) -> LintReport:
    """Structural lint for an ERD render_spec — proposal §4's validation list:
    FK referencing a missing table/column, many-to-many without a junction
    table, table without a primary key, duplicate index, orphan table,
    circular dependency."""
    report = LintReport()
    entities = spec.get("entities", [])
    eid_set = {e.get("id") for e in entities if e.get("id")}
    columns_by_table: dict[str, set[str]] = {
        e.get("id"): {c.get("name") for c in e.get("columns", []) if c.get("name")}
        for e in entities
        if e.get("id")
    }

    for e in entities:
        eid = e.get("id")
        cols = e.get("columns", [])
        if not any(c.get("primary_key") for c in cols):
            report.warning("no_primary_key", f"Table '{eid}' ({e.get('name') or eid}) has no primary key.", eid)
        seen_idx: dict[str, int] = {}
        for idx in e.get("indexes", []):
            seen_idx[idx] = seen_idx.get(idx, 0) + 1
        for idx, count in seen_idx.items():
            if count > 1:
                report.warning("duplicate_index", f"Table '{eid}': index '{idx}' declared {count} times.", eid)

    relationships = spec.get("relationships", [])
    used_tables: set[str] = set()
    for i, r in enumerate(relationships):
        ref = f"relationship[{i}]"
        from_e, to_e = r.get("from_entity"), r.get("to_entity")
        if from_e not in eid_set:
            report.error("unknown_table", f"{ref}: from_entity '{from_e}' is not a declared table.", ref)
        else:
            used_tables.add(from_e)
        if to_e not in eid_set:
            report.error("unknown_table", f"{ref}: to_entity '{to_e}' is not a declared table.", ref)
        else:
            used_tables.add(to_e)
        for col in r.get("from_columns", []):
            if from_e in columns_by_table and col not in columns_by_table[from_e]:
                report.error(
                    "unknown_column", f"{ref}: from_columns references unknown column '{from_e}.{col}'.", ref
                )
        for col in r.get("to_columns", []):
            if to_e in columns_by_table and col not in columns_by_table[to_e]:
                report.error(
                    "unknown_column", f"{ref}: to_columns references unknown column '{to_e}.{col}'.", ref
                )
        if r.get("cardinality") == "many_to_many":
            # A real M:N needs a junction table — heuristic: some OTHER table
            # must hold FK relationships into BOTH sides of this pair.
            junction_exists = any(
                other is not r
                and {other.get("from_entity")} <= {from_e, to_e}
                and any(rr.get("to_entity") in (from_e, to_e) for rr in relationships if rr.get("from_entity") == other.get("from_entity"))
                for other in relationships
            )
            if not junction_exists:
                report.warning(
                    "many_to_many_without_junction",
                    f"{ref}: many_to_many between '{from_e}' and '{to_e}' has no apparent junction table.",
                    ref,
                )

    for eid in eid_set:
        if eid not in used_tables:
            report.info("orphan_table", f"Table '{eid}' has no foreign-key relationship to or from it.", eid)

    # Circular dependency: any cycle in the from_entity -> to_entity graph.
    graph: dict[str, set[str]] = {eid: set() for eid in eid_set}
    for r in relationships:
        if r.get("from_entity") in graph and r.get("to_entity") in graph:
            graph[r["from_entity"]].add(r["to_entity"])
    visiting, visited = set(), set()

    def _has_cycle(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for nxt in graph.get(node, ()):
            if _has_cycle(nxt):
                return True
        visiting.discard(node)
        visited.add(node)
        return False

    if any(_has_cycle(n) for n in graph):
        report.warning("circular_dependency", "Circular foreign-key dependency detected among tables.")

    return report


register_linter("erd", lint_erd)


@tool(parse_docstring=True)
def sql_to_erd_script(sql: str) -> str:
    """Parse PostgreSQL `CREATE TABLE` DDL into ready-to-run ERD DSL Python
    code — deterministic extraction (via sqlglot), never LLM-guessed
    structure, matching how tech-stack costs are computed deterministically
    rather than trusted from a model.

    Returns a complete script using `prettygraph.erd_dsl.ERD` (tables,
    columns with PK/FK/nullable/unique/default, and relationships inferred
    from inline REFERENCES / table-level FOREIGN KEY constraints). Review and
    adjust it if needed, then pass it to render_typed_diagram(kind="erd",
    code=...).

    When to use: the user pasted or uploaded SQL DDL and wants an ERD from it,
    instead of hand-writing ERD DSL calls from scratch.

    Args:
        sql: one or more CREATE TABLE statements (PostgreSQL dialect).
    """
    from codevis.sql_schema import erd_spec_to_dsl_code, parse_postgres_ddl

    try:
        spec = parse_postgres_ddl(sql)
    except Exception as exc:  # noqa: BLE001
        return f"Could not parse the DDL: {exc}"
    if not spec["entities"]:
        return "No CREATE TABLE statements found in the given SQL."
    return erd_spec_to_dsl_code(spec)


__all__ = ["lint_erd", "_build_erd_render_spec", "sql_to_erd_script"]
