"""ERD — a small code-first DSL for authoring database schema diagrams.

Staged into the render sandbox as a flat top-level `prettygraph/*.py` module
(see `tools/stage_markers.py::_stage_helpers`), so a generated script does:

    from prettygraph.erd_dsl import ERD

    erd = ERD(title="Session schema")
    erd.table("session", "session")
    erd.column("session", "id", "uuid", pk=True)
    erd.column("session", "owner_id", "uuid")
    erd.column("session", "status", "text")

    erd.table("session_answer", "session_answer")
    erd.column("session_answer", "id", "uuid", pk=True)
    erd.column("session_answer", "session_id", "uuid", fk_to="session.id")
    erd.column("session_answer", "answer_text", "text")

    erd.relationship("session_answer", "session", cardinality="one_to_many")

    erd.render("out")

`fk_to="table.column"` on a column both marks it foreign_key=True/references
AND is convenience for the common 1:N case — `relationship(...)` still needs
calling explicitly so the crow's-foot cardinality is unambiguous.

Deliberately ZERO dependencies beyond the stdlib — same reasoning as
`sequence_dsl.py`: the sandbox only stages this package's flat top-level
files, not `prettygraph/native/` or anything under `domain/`/`tools/`.
`.render()` just writes the accumulated spec as JSON; validation, structural
lint, and the actual native rendering all run server-side afterward — see
`render_typed_diagram` (`tools/rendering_tools.py`).
"""

from __future__ import annotations

import json


class ERD:
    """Accumulates tables/columns/relationships; `.render()` hands the
    result off to the server-side validator+renderer."""

    def __init__(self, title: str = "") -> None:
        self.title = title
        self._entities: dict[str, dict] = {}
        self._entity_order: list[str] = []
        self._relationships: list[dict] = []

    def table(self, id: str, name: str = "", *, schema: str = "") -> "ERD":
        self._entities[id] = {"id": id, "name": name or id, "schema": schema, "columns": [], "indexes": []}
        self._entity_order.append(id)
        return self

    def column(
        self,
        table_id: str,
        name: str,
        data_type: str = "text",
        *,
        pk: bool = False,
        fk_to: str | None = None,
        nullable: bool = True,
        unique: bool = False,
        default: str = "",
    ) -> "ERD":
        col = {
            "name": name,
            "data_type": data_type,
            "primary_key": pk,
            "foreign_key": bool(fk_to),
            "nullable": nullable and not pk,
            "unique": unique,
            "default": default,
            "references": fk_to or "",
        }
        self._entities[table_id]["columns"].append(col)
        return self

    def index(self, table_id: str, name: str) -> "ERD":
        self._entities[table_id]["indexes"].append(name)
        return self

    def relationship(
        self,
        from_table: str,
        to_table: str,
        *,
        from_columns: list[str] | None = None,
        to_columns: list[str] | None = None,
        cardinality: str = "one_to_many",
        on_delete: str = "",
    ) -> "ERD":
        self._relationships.append(
            {
                "from_entity": from_table,
                "from_columns": from_columns or [],
                "to_entity": to_table,
                "to_columns": to_columns or [],
                "cardinality": cardinality,
                "on_delete": on_delete,
            }
        )
        return self

    def render(self, name: str = "out") -> None:
        """Write the accumulated spec as `{name}.typed_spec.json`. Call this
        LAST, once — actual validation/lint/rendering happens server-side
        after this script finishes (see `render_typed_diagram`)."""
        spec = {
            "kind": "erd",
            "title": self.title,
            "entities": [self._entities[eid] for eid in self._entity_order],
            "relationships": self._relationships,
        }
        with open(f"{name}.typed_spec.json", "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2)
        n_cols = sum(len(e["columns"]) for e in spec["entities"])
        print(
            f"ERD spec captured: {len(spec['entities'])} tables, {n_cols} columns, "
            f"{len(self._relationships)} relationships. Validation/lint/render happens "
            "server-side after this script returns."
        )


__all__ = ["ERD"]
