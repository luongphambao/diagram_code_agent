"""apply_wbs_reestimate — the commit step for a code-interpreter-transformed
WBS (improvement plan §C, S1 flagship). Covers the exact real-world ask this
was built for: "re-estimate, remove FE/Mobile, drop a module, scale AI" —
without add_wbs_items's LLM-retypes-every-leaf path."""

import contextvars
import json

import backends
from wbs_effort import rollup
from wbs_tools import (
    WBS_PLANNER_TOOLS,
    add_wbs_items,
    apply_wbs_reestimate,
    draft_wbs_skeleton,
    finalize_wbs,
    LeafIn,
    PhaseMeta,
    ModuleMeta,
    ProjectInfo,
)


def _bind(monkeypatch, ws):
    ws.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        backends,
        "_current_workspace",
        contextvars.ContextVar("current_workspace", default=ws),
    )


def _build_wbs_with_two_modules():
    draft_wbs_skeleton.func(
        project_info=ProjectInfo(name="Demo", project_code="DMO"),
        phases=[
            PhaseMeta(
                code="II",
                name="DEVELOPMENT",
                modules=[
                    ModuleMeta(code="II.A", name="Web Portal"),
                    ModuleMeta(code="II.B", name="Solution Design"),
                ],
            )
        ],
    )
    add_wbs_items.func(
        items=[
            LeafIn(phase_code="II", module_code="II.A", name="Login", be=2, fe=3, mobile=1, ai=0),
            LeafIn(phase_code="II", module_code="II.A", name="Dashboard", be=3, fe=2, mobile=0, ai=4),
            LeafIn(
                phase_code="II",
                module_code="II.B",
                name="Architecture spec",
                phase_type="requirement",
                be=0,
                fe=0,
                mobile=0,
                ai=0,
                ba=5,
            ),
        ]
    )


def test_apply_wbs_reestimate_recomputes_qc_pm_total_from_scratch(tmp_path, monkeypatch):
    """The exact bug this tool exists to prevent: dropping fe/mobile on an
    item must NOT leave its old (now-stale) qc/pm/total in place — rollup()
    sums whatever is stored, it does not re-derive."""
    _bind(monkeypatch, tmp_path / "ws")
    _build_wbs_with_two_modules()

    wbs = json.loads((tmp_path / "ws" / "wbs.json").read_text(encoding="utf-8"))
    stale_item = next(it for it in wbs["items"] if it["name"] == "Login")
    stale_total = stale_item["total"]
    assert stale_item["fe"] == 3 and stale_item["mobile"] == 1

    # Simulate what run_python would produce: fe/mobile zeroed, but qc/pm/total
    # left as whatever the interpreter script happened to write (garbage —
    # this is exactly what a careless code-authored edit could leave behind).
    transformed = {
        "items": [
            {**stale_item, "fe": 0, "mobile": 0, "qc": 999, "pm": 999, "total": 999},
        ]
    }
    (tmp_path / "ws" / "reestimated.json").write_text(json.dumps(transformed), encoding="utf-8")

    out = apply_wbs_reestimate.func(source_file="reestimated.json")
    assert "Committed 1 re-estimated item" in out
    for label in ("[rollup]", "[timeline]", "[team]", "[milestones]", "[validation]"):
        assert label in out, out

    wbs2 = json.loads((tmp_path / "ws" / "wbs.json").read_text(encoding="utf-8"))
    committed = wbs2["items"][0]
    assert committed["fe"] == 0
    assert committed["mobile"] == 0
    # qc/pm/total must be RE-DERIVED from be=2/fe=0/mobile=0/ai=0, NOT the
    # garbage 999 the fake interpreter output tried to assert.
    assert committed["total"] != 999
    assert committed["total"] < stale_total
    assert committed["qc"] != 999
    assert committed["pm"] != 999


def test_apply_wbs_reestimate_drops_a_module_and_rolls_up_correctly(tmp_path, monkeypatch):
    """The other half of the real ask: 'drop Solution Design' — filtering out
    an entire module's items and re-rolling up. Independent oracle: the new
    total must equal rollup() over ONLY the two surviving items' original
    (pre-reestimate) derived numbers — computed here from the raw wbs.json
    that existed before apply_wbs_reestimate ever ran, not re-derived by the
    tool under test, so this isn't circular."""
    _bind(monkeypatch, tmp_path / "ws")
    _build_wbs_with_two_modules()

    wbs = json.loads((tmp_path / "ws" / "wbs.json").read_text(encoding="utf-8"))
    kept = [it for it in wbs["items"] if it["module_code"] != "II.B"]
    dropped = [it for it in wbs["items"] if it["module_code"] == "II.B"]
    assert len(kept) == 2 and len(dropped) == 1  # dropped the II.B (Solution Design) item
    independent_oracle = rollup(kept)  # computed BEFORE apply_wbs_reestimate touches anything

    (tmp_path / "ws" / "reestimated.json").write_text(json.dumps({"items": kept}), encoding="utf-8")
    apply_wbs_reestimate.func(source_file="reestimated.json")

    wbs2 = json.loads((tmp_path / "ws" / "wbs.json").read_text(encoding="utf-8"))
    assert len(wbs2["items"]) == 2
    assert all(it["module_code"] == "II.A" for it in wbs2["items"])
    assert wbs2["effort_totals"]["total_mandays"] == independent_oracle["total_mandays"]
    assert wbs2["effort_totals"]["effort_by_role"] == independent_oracle["effort_by_role"]
    # Sanity: the dropped item actually carried nonzero effort, so this isn't
    # a vacuous "0 == 0" check. Compare against rollup() over the ORIGINAL 3
    # items (not wbs["effort_totals"] — no finalize_wbs/rollup call happened
    # yet in _build_wbs_with_two_modules, so that key doesn't exist pre-reestimate).
    assert dropped[0]["total"] > 0
    assert wbs2["effort_totals"]["total_mandays"] < rollup(wbs["items"])["total_mandays"]


def test_apply_wbs_reestimate_scales_effort(tmp_path, monkeypatch):
    """'scale AI effort x0.7' — a precise numeric transform an LLM retyping
    numbers would round differently every time."""
    _bind(monkeypatch, tmp_path / "ws")
    _build_wbs_with_two_modules()

    wbs = json.loads((tmp_path / "ws" / "wbs.json").read_text(encoding="utf-8"))
    scaled = []
    for it in wbs["items"]:
        it = dict(it)
        it["ai"] = round(it["ai"] * 0.7, 4)
        scaled.append(it)
    (tmp_path / "ws" / "reestimated.json").write_text(json.dumps({"items": scaled}), encoding="utf-8")
    apply_wbs_reestimate.func(source_file="reestimated.json")

    wbs2 = json.loads((tmp_path / "ws" / "wbs.json").read_text(encoding="utf-8"))
    dashboard = next(it for it in wbs2["items"] if it["name"] == "Dashboard")
    assert dashboard["ai"] == 2.8  # 4 * 0.7


def test_apply_wbs_reestimate_rejects_unknown_module_code(tmp_path, monkeypatch):
    _bind(monkeypatch, tmp_path / "ws")
    _build_wbs_with_two_modules()
    (tmp_path / "ws" / "reestimated.json").write_text(
        json.dumps({"items": [{"module_code": "ZZ.NOPE", "name": "Ghost", "be": 1}]}),
        encoding="utf-8",
    )
    out = apply_wbs_reestimate.func(source_file="reestimated.json")
    assert "nothing committed" in out
    assert "ZZ.NOPE" in out
    # wbs.json must be untouched.
    wbs = json.loads((tmp_path / "ws" / "wbs.json").read_text(encoding="utf-8"))
    assert len(wbs["items"]) == 3


def test_apply_wbs_reestimate_skips_malformed_items_with_warning(tmp_path, monkeypatch):
    _bind(monkeypatch, tmp_path / "ws")
    _build_wbs_with_two_modules()
    (tmp_path / "ws" / "reestimated.json").write_text(
        json.dumps(
            {
                "items": [
                    {"module_code": "II.A", "name": "Kept", "be": 1},
                    {"module_code": "II.A", "name": ""},  # missing name -> skipped
                    "not even a dict",  # malformed -> skipped
                ]
            }
        ),
        encoding="utf-8",
    )
    out = apply_wbs_reestimate.func(source_file="reestimated.json")
    assert "Committed 1 re-estimated item" in out
    assert "skipped 2 malformed item(s)" in out


def test_apply_wbs_reestimate_missing_source_file(tmp_path, monkeypatch):
    _bind(monkeypatch, tmp_path / "ws")
    _build_wbs_with_two_modules()
    out = apply_wbs_reestimate.func(source_file="does_not_exist.json")
    assert "does not exist" in out


def test_apply_wbs_reestimate_malformed_json(tmp_path, monkeypatch):
    _bind(monkeypatch, tmp_path / "ws")
    _build_wbs_with_two_modules()
    (tmp_path / "ws" / "bad.json").write_text("{not valid json", encoding="utf-8")
    out = apply_wbs_reestimate.func(source_file="bad.json")
    assert "not valid JSON" in out


def test_apply_wbs_reestimate_requires_items_list(tmp_path, monkeypatch):
    _bind(monkeypatch, tmp_path / "ws")
    _build_wbs_with_two_modules()
    (tmp_path / "ws" / "no_items.json").write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
    out = apply_wbs_reestimate.func(source_file="no_items.json")
    assert "'items' list" in out


def test_apply_wbs_reestimate_before_any_wbs_exists(tmp_path, monkeypatch):
    _bind(monkeypatch, tmp_path / "ws_empty")
    out = apply_wbs_reestimate.func(source_file="whatever.json")
    assert "draft the skeleton" in out


def test_apply_wbs_reestimate_registered_in_wbs_planner_tools():
    assert "apply_wbs_reestimate" in [t.name for t in WBS_PLANNER_TOOLS]
