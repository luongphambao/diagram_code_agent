"""ERD / Database Schema Diagram — improvement plan MVP-3 phase 3.

Same reconciled shape as Sequence (phase 2): a validated Pydantic spec is the
canonical artifact; the LLM authors it code-first via `prettygraph/erd_dsl.py`
executed through `render_typed_diagram`, not a giant nested tool-call payload.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import ConfigDict, Field

from .coercion import CoercingModel

Cardinality = Literal["one_to_one", "one_to_many", "many_to_many"]


class ERDColumn(CoercingModel):
    name: str = Field(description="column name")
    data_type: str = Field("text", description="e.g. uuid, text, integer, timestamp")
    primary_key: bool = Field(False)
    foreign_key: bool = Field(False)
    nullable: bool = Field(True)
    unique: bool = Field(False)
    default: str = Field("")
    references: str = Field("", description="'<table_id>.<column_name>' when foreign_key=True")


class ERDEntity(CoercingModel):
    id: str = Field(description="unique snake_case id")
    name: str = Field(description="table name")
    schema_: str = Field("", alias="schema", description="optional PostgreSQL schema name")
    columns: list[ERDColumn] = Field(default_factory=list)
    indexes: list[str] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class ERDRelationship(CoercingModel):
    model_config = ConfigDict(populate_by_name=True)
    from_entity: str = Field(description="id of the table holding the foreign key")
    from_columns: list[str] = Field(default_factory=list)
    to_entity: str = Field(description="id of the referenced table")
    to_columns: list[str] = Field(default_factory=list)
    cardinality: Cardinality = Field("one_to_many")
    on_delete: str = Field("")


class ERDSpec(CoercingModel):
    kind: Literal["erd"] = "erd"
    title: str = Field("", description="diagram title")
    entities: list[ERDEntity] = Field(default_factory=list)
    relationships: list[ERDRelationship] = Field(default_factory=list)


__all__ = ["Cardinality", "ERDColumn", "ERDEntity", "ERDRelationship", "ERDSpec"]
