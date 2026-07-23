"""Deterministic SQL DDL -> ERD parser (improvement plan MVP-3 phase 3).

PostgreSQL `CREATE TABLE` first (proposal §4). Uses `sqlglot` to parse DDL
into an AST and walks it deterministically — no LLM involved in extracting
structure, matching the repo's "deterministic extraction, never LLM-guessed
structure" rule (the same reasoning that made tech-stack cost totals
deterministic instead of trusted from the model).

Two entry points:
- `parse_postgres_ddl(sql) -> dict`: an erd render_spec-shaped dict
  (entities/relationships), the same shape `tools.analysis.erd_tools.
  _build_erd_render_spec` produces from a validated `ERDSpec`.
- `erd_spec_to_dsl_code(spec) -> str`: renders that dict back out as
  `prettygraph.erd_dsl.ERD(...)` Python source — since the LLM authors
  diagrams code-first (`render_typed_diagram`), a SQL-to-diagram tool hands
  back a script to review/adjust, not a JSON blob to re-encode by hand.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp


def _column_type(col: exp.ColumnDef) -> str:
    kind = col.kind
    if kind is None:
        return "text"
    try:
        return kind.sql(dialect="postgres").lower()
    except Exception:  # noqa: BLE001
        return str(kind).lower()


def parse_postgres_ddl(sql: str) -> dict:
    """Parse one or more `CREATE TABLE` statements into an erd render_spec dict."""
    entities: list[dict] = []
    relationships: list[dict] = []

    for stmt in sqlglot.parse(sql, dialect="postgres"):
        if not isinstance(stmt, exp.Create) or stmt.args.get("kind") != "TABLE":
            continue
        schema = stmt.this
        table = schema.this
        table_id = table.name
        columns: list[dict] = []
        indexes: list[str] = []
        table_pk_cols: set[str] = set()
        col_by_name: dict[str, dict] = {}

        for item in schema.expressions:
            if isinstance(item, exp.ColumnDef):
                name = item.name
                col = {
                    "name": name,
                    "data_type": _column_type(item),
                    "primary_key": False,
                    "foreign_key": False,
                    "nullable": True,
                    "unique": False,
                    "default": "",
                    "references": "",
                }
                for constraint in item.constraints or []:
                    ckind = constraint.kind
                    if isinstance(ckind, exp.PrimaryKeyColumnConstraint):
                        col["primary_key"] = True
                        col["nullable"] = False
                    elif isinstance(ckind, exp.NotNullColumnConstraint):
                        col["nullable"] = False
                    elif isinstance(ckind, exp.UniqueColumnConstraint):
                        col["unique"] = True
                    elif isinstance(ckind, exp.DefaultColumnConstraint):
                        col["default"] = ckind.this.sql(dialect="postgres") if ckind.this else ""
                    elif isinstance(ckind, exp.Reference):
                        ref_schema = ckind.this
                        ref_table = ref_schema.this.name
                        ref_cols = [i.name for i in ref_schema.expressions] or ["id"]
                        col["foreign_key"] = True
                        col["references"] = f"{ref_table}.{ref_cols[0]}"
                        relationships.append(
                            {
                                "from_entity": table_id,
                                "from_columns": [name],
                                "to_entity": ref_table,
                                "to_columns": ref_cols,
                                "cardinality": "one_to_many",
                                "on_delete": "",
                            }
                        )
                columns.append(col)
                col_by_name[name] = col
            elif isinstance(item, exp.PrimaryKey):
                table_pk_cols.update(i.name for i in item.expressions)
            elif isinstance(item, exp.ForeignKey):
                local_cols = [i.name for i in item.expressions]
                ref = item.args.get("reference")
                if ref is not None:
                    ref_schema = ref.this
                    ref_table = ref_schema.this.name
                    ref_cols = [i.name for i in ref_schema.expressions] or ["id"]
                    for lc in local_cols:
                        if lc in col_by_name:
                            col_by_name[lc]["foreign_key"] = True
                            col_by_name[lc]["references"] = f"{ref_table}.{ref_cols[0]}"
                    relationships.append(
                        {
                            "from_entity": table_id,
                            "from_columns": local_cols,
                            "to_entity": ref_table,
                            "to_columns": ref_cols,
                            "cardinality": "one_to_many",
                            "on_delete": "",
                        }
                    )
            elif isinstance(item, exp.UniqueColumnConstraint):
                cols = [i.name for i in (item.this.expressions if item.this else [])]
                if cols:
                    indexes.append(f"unique({','.join(cols)})")

        for name in table_pk_cols:
            if name in col_by_name:
                col_by_name[name]["primary_key"] = True
                col_by_name[name]["nullable"] = False

        entities.append({"id": table_id, "name": table_id, "schema": "", "columns": columns, "indexes": indexes})

    return {"kind": "erd", "title": "", "entities": entities, "relationships": relationships}


def _py_literal(value) -> str:
    return repr(value)


def erd_spec_to_dsl_code(spec: dict) -> str:
    """Render an erd render_spec dict as `prettygraph.erd_dsl.ERD(...)` source."""
    lines = ["from prettygraph.erd_dsl import ERD", "", f"erd = ERD(title={_py_literal(spec.get('title') or '')})"]
    for e in spec.get("entities", []):
        lines.append(f"erd.table({_py_literal(e['id'])}, {_py_literal(e.get('name') or e['id'])})")
        for c in e.get("columns", []):
            kwargs = [f"pk={c.get('primary_key', False)}"]
            if c.get("foreign_key") and c.get("references"):
                kwargs.append(f"fk_to={_py_literal(c['references'])}")
            kwargs.append(f"nullable={c.get('nullable', True)}")
            if c.get("unique"):
                kwargs.append("unique=True")
            if c.get("default"):
                kwargs.append(f"default={_py_literal(c['default'])}")
            lines.append(
                f"erd.column({_py_literal(e['id'])}, {_py_literal(c['name'])}, "
                f"{_py_literal(c.get('data_type') or 'text')}, {', '.join(kwargs)})"
            )
    for r in spec.get("relationships", []):
        lines.append(
            f"erd.relationship({_py_literal(r['from_entity'])}, {_py_literal(r['to_entity'])}, "
            f"from_columns={r.get('from_columns') or []!r}, to_columns={r.get('to_columns') or []!r}, "
            f"cardinality={_py_literal(r.get('cardinality') or 'one_to_many')})"
        )
    lines.append('erd.render("out")')
    return "\n".join(lines)


__all__ = ["parse_postgres_ddl", "erd_spec_to_dsl_code"]
