"""ERD / Database Schema Diagram — improvement plan MVP-3 phase 3.

Covers: the ERDSpec schema, the native table/crow's-foot renderer
(prettygraph.native.erd), its registration into prettygraph.native.registry +
dispatch through topology.build_tree, the ERD structural linter, the
code-first `ERD` DSL (prettygraph.erd_dsl), the sqlglot DDL parser
(codevis.sql_schema), and render_typed_diagram end to end — same code-first
shape as Sequence (phase 2, see that phase's "Pivot" note).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import backends
from codevis.sql_schema import erd_spec_to_dsl_code, parse_postgres_ddl
from prettygraph.native.erd import build_erd_tree, erd_semantic_ids
from prettygraph.native.registry import RENDERERS
from prettygraph.native.topology import build_drawio_from_spec, build_tree
from prettygraph.erd_dsl import ERD
from tools.analysis.erd_tools import _build_erd_render_spec, lint_erd
from tools.rendering_tools import render_typed_diagram
from tools.schemas.erd import ERDSpec


def _session_schema_dict() -> dict:
    """The proposal §4 session/session_answer example as a render_spec dict."""
    return {
        "kind": "erd",
        "title": "Session schema",
        "entities": [
            {
                "id": "session",
                "name": "session",
                "columns": [
                    {"name": "id", "data_type": "uuid", "primary_key": True, "nullable": False},
                    {"name": "owner_id", "data_type": "uuid", "nullable": False},
                    {"name": "status", "data_type": "text", "nullable": False},
                ],
                "indexes": [],
            },
            {
                "id": "session_answer",
                "name": "session_answer",
                "columns": [
                    {"name": "id", "data_type": "uuid", "primary_key": True, "nullable": False},
                    {
                        "name": "session_id",
                        "data_type": "uuid",
                        "foreign_key": True,
                        "references": "session.id",
                    },
                    {"name": "answer_text", "data_type": "text"},
                ],
                "indexes": [],
            },
        ],
        "relationships": [
            {
                "from_entity": "session_answer",
                "from_columns": ["session_id"],
                "to_entity": "session",
                "to_columns": ["id"],
                "cardinality": "one_to_many",
            }
        ],
    }


# --------------------------------------------------------------------------- #
# schema
# --------------------------------------------------------------------------- #


def test_schema_defaults_and_alias():
    spec = ERDSpec(
        entities=[{"id": "t", "name": "t", "schema": "public", "columns": [{"name": "id", "pk": True}]}]
    )
    assert spec.kind == "erd"
    assert spec.entities[0].schema_ == "public"


def test_render_spec_projection_shape():
    spec = ERDSpec(**_session_schema_dict())
    render_spec = _build_erd_render_spec(spec)
    assert render_spec["kind"] == "erd"
    assert render_spec["entities"][0]["id"] == "session"
    assert render_spec["relationships"][0]["cardinality"] == "one_to_many"


# --------------------------------------------------------------------------- #
# registry dispatch
# --------------------------------------------------------------------------- #


def test_erd_registered_as_native_renderer():
    entry = RENDERERS.get("erd")
    assert entry is not None
    assert entry.backend == "native"
    assert entry.tree_builder is build_erd_tree
    assert entry.lint_kind == "erd"


def test_build_tree_dispatches_to_erd_for_registered_kind():
    d, root = build_tree(_session_schema_dict())
    assert root["kind"] == "erd"
    assert set(root["entities"]) == {"session", "session_answer"}


# --------------------------------------------------------------------------- #
# renderer geometry
# --------------------------------------------------------------------------- #


def test_renders_native_crows_foot_shapes_and_valid_xml():
    xml, stats = build_drawio_from_spec(_session_schema_dict(), "Session schema")
    assert stats["style_preset"] == "erd"
    assert "ERone" in xml or "ERmany" in xml
    root = ET.fromstring(xml)
    assert root.tag == "mxfile"


def test_tables_layer_by_fk_dependency():
    """session (referenced) must sit in an earlier layer (smaller x) than
    session_answer (the table holding the FK)."""
    d, _ = build_erd_tree(_session_schema_dict())
    assert d.R["session"]["x"] < d.R["session_answer"]["x"]


def test_relationship_edge_targets_the_correct_row():
    """The FK column's row and the referenced PK's row must produce matching
    exitY/entryY fractions — the crow's-foot connector should point at the
    exact declared column, not just table centers."""
    xml, _ = build_drawio_from_spec(_session_schema_dict(), "Session schema")
    root = ET.fromstring(xml)
    rel = next(c for c in root.iter("mxCell") if (c.get("id") or "").startswith("rel_"))
    style = rel.get("style") or ""
    styles = dict(kv.split("=", 1) for kv in style.split(";") if "=" in kv)
    assert "exitY" in styles and "entryY" in styles


def test_pk_less_table_still_renders():
    spec = _session_schema_dict()
    for col in spec["entities"][0]["columns"]:
        col["primary_key"] = False
    d, _ = build_erd_tree(spec)
    assert "session" in d.R


# --------------------------------------------------------------------------- #
# anchor-geometry regression (same class of bug the Sequence actor fix caught)
# --------------------------------------------------------------------------- #


def test_table_registered_geometry_matches_emitted_xml_geometry():
    d, _ = build_erd_tree(_session_schema_dict())
    xml = d.mxfile("Session schema")
    root = ET.fromstring(xml)

    def _geometry(cell_id):
        cell = next(c for c in root.iter("mxCell") if c.get("id") == cell_id)
        geom = cell.find("mxGeometry")
        return {k: float(geom.get(k)) for k in ("x", "y", "width", "height")}

    for tid in ("session", "session_answer"):
        r = d.R[tid]
        g = _geometry(tid)
        assert g["height"] == r["h"]
        assert g["y"] == r["y"]


def test_semantic_ids_cover_tables_and_relationship_pairs():
    ids, edges = erd_semantic_ids(_session_schema_dict())
    assert set(ids) == {"session", "session_answer"}
    assert ("session_answer", "session") in edges


# --------------------------------------------------------------------------- #
# structural lint (proposal §4's validation list)
# --------------------------------------------------------------------------- #


def test_lint_clean_spec_has_no_errors():
    report = lint_erd(_session_schema_dict())
    assert not report.has_errors


def test_lint_catches_fk_to_missing_table():
    spec = _session_schema_dict()
    spec["relationships"][0]["to_entity"] = "does_not_exist"
    report = lint_erd(spec)
    assert any(f.code == "unknown_table" for f in report.errors)


def test_lint_catches_fk_to_missing_column():
    spec = _session_schema_dict()
    spec["relationships"][0]["to_columns"] = ["nonexistent_col"]
    report = lint_erd(spec)
    assert any(f.code == "unknown_column" for f in report.errors)


def test_lint_catches_table_without_primary_key():
    spec = _session_schema_dict()
    for col in spec["entities"][0]["columns"]:
        col["primary_key"] = False
    report = lint_erd(spec)
    assert any(f.code == "no_primary_key" and f.ref == "session" for f in report.findings)


def test_lint_catches_duplicate_index():
    spec = _session_schema_dict()
    spec["entities"][0]["indexes"] = ["idx_owner", "idx_owner"]
    report = lint_erd(spec)
    assert any(f.code == "duplicate_index" for f in report.findings)


def test_lint_catches_orphan_table():
    spec = _session_schema_dict()
    spec["entities"].append({"id": "unused", "name": "unused", "columns": [{"name": "id", "primary_key": True}]})
    report = lint_erd(spec)
    assert any(f.code == "orphan_table" and f.ref == "unused" for f in report.findings)


def test_lint_catches_circular_dependency():
    spec = _session_schema_dict()
    spec["relationships"].append(
        {"from_entity": "session", "from_columns": ["id"], "to_entity": "session_answer", "to_columns": ["id"], "cardinality": "one_to_one"}
    )
    report = lint_erd(spec)
    assert any(f.code == "circular_dependency" for f in report.findings)


def test_lint_catches_many_to_many_without_junction():
    spec = {
        "kind": "erd",
        "entities": [
            {"id": "a", "name": "a", "columns": [{"name": "id", "primary_key": True}]},
            {"id": "b", "name": "b", "columns": [{"name": "id", "primary_key": True}]},
        ],
        "relationships": [
            {"from_entity": "a", "to_entity": "b", "cardinality": "many_to_many", "from_columns": ["id"], "to_columns": ["id"]},
        ],
    }
    report = lint_erd(spec)
    assert any(f.code == "many_to_many_without_junction" for f in report.findings)


# --------------------------------------------------------------------------- #
# ERD() DSL — code-first authoring surface (no sandbox)
# --------------------------------------------------------------------------- #


def test_dsl_writes_spec_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    erd = ERD(title="Session schema")
    erd.table("session", "session")
    erd.column("session", "id", "uuid", pk=True)
    erd.column("session", "owner_id", "uuid")
    erd.table("session_answer", "session_answer")
    erd.column("session_answer", "id", "uuid", pk=True)
    erd.column("session_answer", "session_id", "uuid", fk_to="session.id")
    erd.relationship("session_answer", "session", from_columns=["session_id"], to_columns=["id"])
    erd.render("out")

    spec = json.loads((tmp_path / "out.typed_spec.json").read_text())
    assert spec["kind"] == "erd"
    assert [e["id"] for e in spec["entities"]] == ["session", "session_answer"]
    fk_col = spec["entities"][1]["columns"][1]
    assert fk_col["foreign_key"] is True
    assert fk_col["references"] == "session.id"


def test_dsl_spec_round_trips_through_validation_and_lint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    erd = ERD()
    erd.table("t", "t")
    erd.column("t", "id", "uuid", pk=True)
    erd.render("out")

    raw = json.loads((tmp_path / "out.typed_spec.json").read_text())
    validated = ERDSpec(**raw)
    render_spec = _build_erd_render_spec(validated)
    report = lint_erd(render_spec)
    assert not report.has_errors


# --------------------------------------------------------------------------- #
# sqlglot DDL parser (proposal §4's DDL sample)
# --------------------------------------------------------------------------- #

_SESSION_DDL = """
CREATE TABLE session (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    status text NOT NULL
);

CREATE TABLE session_answer (
    id uuid PRIMARY KEY,
    session_id uuid REFERENCES session(id),
    answer_text text
);
"""


def test_parse_postgres_ddl_extracts_tables_and_fk():
    spec = parse_postgres_ddl(_SESSION_DDL)
    assert [e["id"] for e in spec["entities"]] == ["session", "session_answer"]
    session_id_col = spec["entities"][1]["columns"][1]
    assert session_id_col["foreign_key"] is True
    assert session_id_col["references"] == "session.id"
    assert spec["relationships"][0] == {
        "from_entity": "session_answer",
        "from_columns": ["session_id"],
        "to_entity": "session",
        "to_columns": ["id"],
        "cardinality": "one_to_many",
        "on_delete": "",
    }


def test_parse_postgres_ddl_marks_primary_keys():
    spec = parse_postgres_ddl(_SESSION_DDL)
    assert spec["entities"][0]["columns"][0]["primary_key"] is True


def test_parse_postgres_ddl_table_level_constraints():
    ddl = """
    CREATE TABLE order_item (
        order_id uuid,
        product_id uuid,
        PRIMARY KEY (order_id, product_id),
        FOREIGN KEY (order_id) REFERENCES orders(id),
        FOREIGN KEY (product_id) REFERENCES products(id)
    );
    """
    spec = parse_postgres_ddl(ddl)
    cols = {c["name"]: c for c in spec["entities"][0]["columns"]}
    assert cols["order_id"]["primary_key"] is True
    assert cols["product_id"]["primary_key"] is True
    assert cols["order_id"]["foreign_key"] is True
    assert len(spec["relationships"]) == 2


def test_generated_dsl_code_round_trips_through_validation():
    """The generated script text must itself be valid ERD() DSL calls that
    reproduce the same spec after validation."""
    spec = parse_postgres_ddl(_SESSION_DDL)
    code = erd_spec_to_dsl_code(spec)
    assert "from prettygraph.erd_dsl import ERD" in code
    ns: dict = {}
    import sys

    sys.path.insert(0, "src")
    try:
        exec(compile(code.replace('erd.render("out")', ""), "<generated>", "exec"), ns)
    finally:
        sys.path.pop(0)
    erd_obj = ns["erd"]
    assert [e["id"] for e in erd_obj._entities.values()] == ["session", "session_answer"]


# --------------------------------------------------------------------------- #
# render_typed_diagram tool, end to end (real sandbox subprocess)
# --------------------------------------------------------------------------- #

_SESSION_SCRIPT = """
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

erd.relationship("session_answer", "session", from_columns=["session_id"], to_columns=["id"], cardinality="one_to_many")

erd.render("out")
"""


def test_render_typed_diagram_erd_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_PROVIDER", "local")
    monkeypatch.setenv("APP_ENV", "development")
    token = backends.set_current_workspace(tmp_path)
    try:
        (tmp_path / "diagram_brief.json").write_text("{}", encoding="utf-8")
        result = render_typed_diagram.func(kind="erd", code=_SESSION_SCRIPT)
        assert "Rendered erd diagram" in result, result
        assert (tmp_path / "out.drawio").exists()
        stats = json.loads((tmp_path / "out.native_stats.json").read_text())
        assert stats["style_preset"] == "erd"
        assert stats["semantic"]["node_recall"] == 1.0
        assert stats["semantic"]["edge_recall"] == 1.0
        assert stats["lint"]["errors"] == []
    finally:
        backends.reset_current_workspace(token)


def test_render_typed_diagram_erd_surfaces_lint_findings_without_blocking(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBOX_PROVIDER", "local")
    monkeypatch.setenv("APP_ENV", "development")
    token = backends.set_current_workspace(tmp_path)
    try:
        (tmp_path / "diagram_brief.json").write_text("{}", encoding="utf-8")
        script = (
            "from prettygraph.erd_dsl import ERD\n"
            "erd = ERD()\n"
            "erd.table('a', 'a')\n"
            "erd.column('a', 'id', 'uuid', pk=True)\n"
            "erd.relationship('a', 'missing')\n"
            "erd.render('out')\n"
        )
        result = render_typed_diagram.func(kind="erd", code=script)
        assert "Rendered erd diagram" in result, result
        assert "unknown_table" in result or "not a declared table" in result
        assert (tmp_path / "out.drawio").exists()
    finally:
        backends.reset_current_workspace(token)
