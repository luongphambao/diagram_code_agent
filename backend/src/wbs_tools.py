"""WBS planner tools — generate a BnK-format Work Breakdown Structure from the
results of the earlier pipeline steps (diagram_brief / tech_stack / blueprint).

Mirrors the structure of ``email_tools.py``: a self-contained tool module that the
agent wires in. Only the steps that need model REASONING are model-facing tools;
the deterministic tail (rollup → timeline → team → milestones → validate) runs
inside one code-driven ``finalize_wbs`` call — the model never "presses buttons"
through five separate tool calls (each one used to cost a full ~30K-token model
turn):

    load_solution_context (incl. effort-norms digest) → draft_wbs_skeleton
      → [HITL] propose_wbs_skeleton
      → add_wbs_items (×N) → finalize_wbs
      → [HITL] propose_wbs → [HITL] export_wbs_excel

Effort follows the verified BnK ratio model (see :mod:`wbs_effort`): the planner
only sizes dev (BE/FE/Mobile/AI) per leaf; BA/QC/PM are derived. The Excel export
clones the template and keeps the formulas live (see :mod:`wbs_excel`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field, model_validator

from backends import WORKSPACE, WorkspaceFile, current_workspace
import wbs_excel
from wbs_effort import (
    RATIOS, Ratios, derive_leaf_effort, rollup, make_ref_code, delivery_grid,
    critical_path, MANDAYS_PER_MONTH, pert_percentile, assign_sprints, MANDAYS_PER_WEEK,
    level_resources,
)

# ── state files (registered in tools.clear_stage_markers) ────────────────────
# Resolved lazily per request (per-thread isolation, §4.10) via WorkspaceFile.
_BRIEF_FILE = WorkspaceFile("diagram_brief.json")
_TECHSTACK_FILE = WorkspaceFile("tech_stack.json")
_BLUEPRINT_FILE = WorkspaceFile("blueprint.json")
_SKELETON_FILE = WorkspaceFile("wbs_skeleton.json")
_WBS_FILE = WorkspaceFile("wbs.json")
_WBS_XLSX = WorkspaceFile("wbs_filled.xlsx")


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data) -> None:
    current_workspace().mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── mimo-safe base: shared coercion (str→json, numeric-dict→list, None→[]) ───
class _CoercingModel(BaseModel):
    """Normalise mimo's malformed payloads before validation.

    Delegates to tool_coercion.coerce_model_values — the shared helper that also
    backs ToolArgCoercionMiddleware — so the str→json.loads branch (the one this
    class used to lack, which let draft_wbs_skeleton(ratios='{...}') fail) lives
    in one place.
    """

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, values):
        from tool_coercion import coerce_model_values
        return coerce_model_values(cls, values)


# ════════════════════════════════════════════════════════════════════════════
# 1. load_solution_context
# ════════════════════════════════════════════════════════════════════════════
@tool(parse_docstring=True)
def load_solution_context() -> str:
    """Load the approved upstream artifacts to ground the WBS decomposition.

    Reads diagram_brief.json, tech_stack.json and blueprint.json from the
    workspace and returns a compact digest (objective, functional requirements,
    application type, tech layers, blueprint clusters/nodes). Call this FIRST so
    the modules and features you break down trace back to the approved solution.
    """
    brief = _read_json(_BRIEF_FILE, {}) or {}
    tech = _read_json(_TECHSTACK_FILE, {}) or {}
    bp = _read_json(_BLUEPRINT_FILE, {}) or {}
    if not (brief or bp):
        return ("No upstream artifacts found. Get the diagram brief / blueprint "
                "approved first (propose_diagram_brief, propose_blueprint).")

    digest: dict[str, Any] = {
        "objective": brief.get("objective"),
        "application_type": brief.get("application_type"),
        "functional_requirements": brief.get("functional_requirements", [])[:40],
        "non_functional_requirements": brief.get("non_functional_requirements", [])[:20],
        "stakeholders": brief.get("stakeholders", []),
        "tech_layers": {k: (v or {}).get("choice") for k, v in (tech.get("layers", {}) or {}).items()},
        "blueprint_clusters": [c.get("label") for c in bp.get("clusters", [])],
        "blueprint_nodes": [n.get("label") for n in bp.get("nodes", [])][:60],
        "pattern": bp.get("pattern"),
    }
    return json.dumps(digest, ensure_ascii=False, indent=2)


# ════════════════════════════════════════════════════════════════════════════
# 2. get_effort_norms — deterministic benchmark table (distilled from samples)
# ════════════════════════════════════════════════════════════════════════════
# dev man-days (BE, FE/Mobile) per feature type; total ≈ 1.54×dev under 10/30/10.
EFFORT_NORMS: dict[str, dict] = {
    "login_auth_web": {"be": [0.5, 2], "fe": [0.5, 2], "note": "login/logout, forgot pw, OTP"},
    "login_auth_mobile": {"be": [0, 0.5], "fe": [1, 2]},
    "registration_onboarding": {"be": [3, 4], "fe": [4, 5]},
    "dashboard": {"be": [1.5, 2], "fe": [1.5, 3]},
    "crud_list": {"be": [0.75, 1.5], "fe": [0.75, 3], "note": "sort/filter/export"},
    "crud_detail": {"be": [2, 3.5], "fe": [2, 3]},
    "rbac_roles": {"be": [2, 4], "fe": [0, 2]},
    "kyc": {"be": [3, 3], "fe": [5, 5]},
    "file_upload": {"be": [3, 4], "fe": [1, 1]},
    "notification_framework": {"be": [2, 2], "fe": [0, 0]},
    "notification_channel": {"be": [1, 1], "fe": [0, 0], "note": "per channel email/sms/in-app"},
    "chat_realtime": {"be": [1, 1], "fe": [3, 3]},
    "report_export": {"be": [5, 11], "fe": [0, 8]},
    "payment_integration": {"be": [1, 5], "fe": [0, 1]},
    "third_party_integration": {"be": [1, 14], "fe": [0, 2], "note": "SSO/gateway/public API"},
    "admin_user_mgmt": {"be": [2.5, 2.5], "fe": [3, 3]},
    "search_filter_builder": {"be": [4, 6], "fe": [1, 4]},
    "workflow_approval": {"be": [6, 6], "fe": [4, 4]},
    "rule_calc_engine": {"be": [3, 9], "fe": [1, 3], "note": "per rule"},
    "audit_trail": {"be": [3, 3.5], "fe": [1, 2]},
    # design / setup (phase_type=design): BE-only, no BA/QC
    "database_design": {"be": [1, 6], "fe": [0, 0], "phase_type": "design"},
    "system_architecture_design": {"be": [5, 5], "fe": [0, 0], "phase_type": "design"},
    "uiux_design": {"be": [0, 0], "fe": [5, 20], "phase_type": "uiux"},
    "code_base_setup": {"be": [2, 2], "fe": [0, 2], "phase_type": "design"},
    "deployment_setup": {"be": [3, 5], "fe": [0, 0], "phase_type": "design"},
    "monitoring_setup": {"be": [2, 2], "fe": [0, 0], "phase_type": "design", "note": "per monitor"},
    "prod_deploy_migration": {"be": [1, 1], "fe": [0, 0], "phase_type": "deployment", "note": "PM=0"},
    # requirement (phase_type=requirement): BA-only
    "requirement_workshop_brd": {"ba": [3, 14], "phase_type": "requirement"},
    # AI (counts as dev)
    "ai_dataset_prep": {"be": [15, 15], "fe": [0, 0], "note": "AI MD; ~17 total"},
    "ai_finetune_sft": {"be": [15, 15], "fe": [0, 0]},
    "ai_model_serving": {"be": [5, 6], "fe": [0, 0]},
}


@tool(parse_docstring=True)
def get_effort_norms(feature_types: Optional[list[str]] = None) -> str:
    """Return benchmark dev man-day ranges per feature type to anchor estimates.

    These ranges are distilled from ~50 real BnK WBS files. Use them to size each
    leaf's BE / FE-Mobile man-days consistently (BA/QC/PM are derived from dev by
    the ratio model — do NOT estimate them yourself). Some entries carry a
    ``phase_type`` (design/uiux/deployment/requirement) that gates which roles apply.

    Args:
        feature_types: optional subset of norm keys to return; omit for the full table.
    """
    if feature_types:
        sub = {k: EFFORT_NORMS[k] for k in feature_types if k in EFFORT_NORMS}
        if not sub:
            return ("No matching norm keys. Available: " + ", ".join(sorted(EFFORT_NORMS)))
        return json.dumps(sub, ensure_ascii=False, indent=2)
    return json.dumps(EFFORT_NORMS, ensure_ascii=False, indent=2)


# ════════════════════════════════════════════════════════════════════════════
# 3. draft_wbs_skeleton
# ════════════════════════════════════════════════════════════════════════════
class ModuleMeta(BaseModel):
    code: str = Field(description="dotted module code, e.g. 'II.A'")
    name: str = Field(description="module name, e.g. 'Web Portal'")


class PhaseMeta(BaseModel):
    code: str = Field(description="roman phase code: I / II / III")
    name: str = Field(description="phase name, e.g. 'DEVELOPMENT'")
    modules: list[ModuleMeta] = Field(default_factory=list)


class ProjectInfo(BaseModel):
    name: str
    project_code: str = Field("BNK", description="Ref.Code prefix, e.g. 'CL', 'DLP'")
    client: str = ""
    solution_type: str = ""
    business_domain: str = ""


class DraftSkeletonArgs(_CoercingModel):
    project_info: ProjectInfo
    phases: list[PhaseMeta]
    ratios: Optional[dict] = Field(
        None, description="override {ba_on_dev,qc_on_dev,pm_on_total}; default 0.10/0.30/0.10")


@tool(args_schema=DraftSkeletonArgs)
def draft_wbs_skeleton(project_info: ProjectInfo, phases: list[PhaseMeta],
                       ratios: Optional[dict] = None) -> str:
    """Define the WBS phase/module skeleton BEFORE estimating any effort.

    Use the BnK 3-phase spine — I SET UP & INSTALLATION (Solution Design, System
    Operation), II DEVELOPMENT (one module per product surface / architecture tier),
    III TESTING & DEPLOYMENT SUPPORT (Solution Qualification, Deployment &
    Maintenance). Writes wbs_skeleton.json. Follow with propose_wbs_skeleton for the
    user to approve the structure, then add_wbs_items.
    """
    if not phases:
        return "Provide at least one phase with modules."
    r = {**RATIOS.__dict__, **(ratios or {})}
    skeleton = {
        "project_info": project_info.model_dump(),
        "ratios": r,
        "phases": [p.model_dump() for p in phases],
    }
    _write_json(_SKELETON_FILE, skeleton)
    # seed wbs.json with empty item list + skeleton
    _write_json(_WBS_FILE, {**skeleton, "items": []})
    n_mod = sum(len(p.modules) for p in phases)
    lines = [f"WBS skeleton drafted: {len(phases)} phase(s), {n_mod} module(s)."]
    for p in phases:
        lines.append(f"  {p.code} {p.name}: " + ", ".join(f"{m.code} {m.name}" for m in p.modules))
    lines.append("Next: call propose_wbs_skeleton to get the structure approved.")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════
# 4. add_wbs_items
# ════════════════════════════════════════════════════════════════════════════
class DependencyEdge(BaseModel):
    """A rich DAG edge with optional lag and relationship type."""
    predecessor_ref: str
    lag_days: float = 0.0
    relationship: Literal["FS", "SS", "FF"] = "FS"


class LeafIn(BaseModel):
    phase_code: str = Field(description="which phase this leaf belongs to, e.g. 'II'")
    module_code: str = Field(description="which module, e.g. 'II.A'")
    name: str = Field(description="feature name (goes in the Features column)")
    description: str = ""
    group: str = Field("", description="optional sub-module group label, e.g. 'Common Module'")
    phase_type: str = Field("development",
                            description="development | design | uiux | deployment | requirement | support")
    be: float = Field(0, description="Backend dev man-days (hand estimate)")
    fe: float = Field(0, description="Frontend/web dev man-days")
    mobile: float = Field(0, description="Mobile dev man-days")
    ai: float = Field(0, description="AI/ML dev man-days")
    ba: float = Field(0, description="ONLY for phase_type=requirement: the analysis man-days")
    optimistic: float = Field(0, description="PERT optimistic man-days (O); scheduling only")
    likely: float = Field(0, description="PERT most-likely man-days (M); >0 enables 3-point scheduling")
    pessimistic: float = Field(0, description="PERT pessimistic man-days (P); scheduling only")
    predecessors: list[str] = Field(
        default_factory=list,
        description="ref_code(s) that must finish before this task starts, e.g. ['BNK-3']")
    remark: str = ""
    owner: Optional[str] = None
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="Definition-of-Done checklist, e.g. ['Unit tests pass', 'PR reviewed']")
    dependencies: list[DependencyEdge] = Field(
        default_factory=list,
        description="Rich DAG edges with lag and type (FS/SS/FF); supersedes predecessors when set")


class AddItemsArgs(_CoercingModel):
    items: list[LeafIn]


@tool(args_schema=AddItemsArgs)
def add_wbs_items(items: list[LeafIn]) -> str:
    """Append leaf features (with hand-estimated dev man-days) to the WBS.

    Estimate ONLY the dev columns (be/fe/mobile/ai); BA/QC/PM and Total are derived
    deterministically by the ratio model and phase-gating. Call repeatedly, one
    module at a time, after the skeleton is approved. Each item must name its
    phase_code + module_code (must exist in the skeleton). Use get_effort_norms to
    size features consistently.
    """
    wbs = _read_json(_WBS_FILE)
    if not wbs:
        return "Draft the skeleton first (draft_wbs_skeleton)."
    valid_modules = {m["code"] for p in wbs["phases"] for m in p["modules"]}
    pc = wbs.get("project_info", {}).get("project_code", "BNK")
    r = Ratios(**{k: wbs["ratios"][k] for k in ("ba_on_dev", "qc_on_dev", "pm_on_total")})
    existing = wbs.setdefault("items", [])
    seq = len(existing)
    added, bad = 0, []
    for it in items:
        if it.module_code not in valid_modules:
            bad.append(it.module_code)
            continue
        seq += 1
        eff = derive_leaf_effort(be=it.be, fe=it.fe, mobile=it.mobile, ai=it.ai,
                                 ba=it.ba, phase_type=it.phase_type, ratios=r)
        # PERT is for scheduling only — it does NOT feed the BnK effort/ratio model.
        pert = round((it.optimistic + 4 * it.likely + it.pessimistic) / 6, 4) if it.likely > 0 else 0.0
        pert_p50 = pert_percentile(it.optimistic, it.likely, it.pessimistic, 0.0) if it.likely > 0 else 0.0
        pert_p80 = pert_percentile(it.optimistic, it.likely, it.pessimistic, 0.842) if it.likely > 0 else 0.0
        existing.append({
            "seq": seq, "ref_code": make_ref_code(pc, seq),
            "phase_code": it.phase_code, "module_code": it.module_code,
            "group": it.group or None, "name": it.name, "description": it.description,
            "phase_type": it.phase_type, "remark": it.remark or None,
            "be": eff["be"], "fe": eff["fe"], "mobile": eff["mobile"], "ai": eff["ai"],
            "fe_mobile": round(eff["fe"] + eff["mobile"] + eff["ai"], 4),
            "ba": eff["ba"], "qc": eff["qc"], "pm": eff["pm"], "total": eff["total"],
            "optimistic": it.optimistic, "likely": it.likely, "pessimistic": it.pessimistic,
            "pert_expected_md": pert, "pert_p50_md": pert_p50, "pert_p80_md": pert_p80,
            "predecessors": [str(p).strip() for p in (it.predecessors or [])],
            "dependencies": [d.model_dump() for d in it.dependencies],
            "owner": it.owner or None,
            "acceptance_criteria": list(it.acceptance_criteria),
        })
        added += 1
    _write_json(_WBS_FILE, wbs)
    msg = f"Added {added} item(s); {len(existing)} total. Running dev+overhead = " \
          f"{round(sum(i['total'] for i in existing), 2)} MD."
    if bad:
        msg += f"\nWARNING: unknown module_code(s) skipped: {sorted(set(bad))}. " \
               f"Valid: {sorted(valid_modules)}."
    return msg


# ════════════════════════════════════════════════════════════════════════════
# 5. compute_wbs_rollup — assemble nested tree + totals for export
# ════════════════════════════════════════════════════════════════════════════
def _assemble_nested(wbs: dict) -> dict:
    """Group the flat items into the nested phases/modules/groups the builder needs."""
    items = wbs.get("items", [])
    by_mod: dict[str, list] = {}
    for it in items:
        by_mod.setdefault(it["module_code"], []).append(it)
    phases_out = []
    for p in wbs["phases"]:
        modules_out = []
        for m in p["modules"]:
            mits = by_mod.get(m["code"], [])
            # preserve first-seen group order
            groups: dict = {}
            order: list = []
            for it in mits:
                g = it.get("group") or None
                if g not in groups:
                    groups[g] = []
                    order.append(g)
                groups[g].append({
                    "name": it["name"], "description": it.get("description", ""),
                    "remark": it.get("remark"), "phase_type": it.get("phase_type", "development"),
                    "be": it["be"], "fe": it["fe"], "mobile": it["mobile"], "ai": it["ai"],
                    "fe_mobile": it.get("fe_mobile", round(it["fe"] + it["mobile"] + it["ai"], 4)),
                    "ba": it["ba"], "qc": it["qc"], "pm": it["pm"], "total": it["total"],
                    # WBS v2 scheduling fields (passed through to Excel builder)
                    "optimistic": it.get("optimistic", 0), "likely": it.get("likely", 0),
                    "pessimistic": it.get("pessimistic", 0),
                    "pert_p50_md": it.get("pert_p50_md", 0),
                    "pert_p80_md": it.get("pert_p80_md", 0),
                    "acceptance_criteria": it.get("acceptance_criteria", []),
                    "owner": it.get("owner"),
                    "assigned_sprint": it.get("assigned_sprint"),
                    "dependencies": it.get("dependencies", []),
                })
            modules_out.append({"code": m["code"], "name": m["name"],
                                "groups": [{"name": g, "items": groups[g]} for g in order]})
        phases_out.append({"code": p["code"], "name": p["name"], "modules": modules_out})
    return phases_out


@tool(parse_docstring=True)
def compute_wbs_rollup() -> str:
    """Roll up all leaf items into module/phase/role totals and assemble the tree.

    Reads the flat items, groups them under their modules, computes effort_by_module,
    effort_totals (man-days, man-months, by-role split) and writes the nested
    ``phases`` structure that the Excel export consumes. Call after add_wbs_items.
    """
    wbs = _read_json(_WBS_FILE)
    if not wbs or not wbs.get("items"):
        return "No WBS items yet — call add_wbs_items first."
    nested = _assemble_nested(wbs)
    # effort_by_module
    by_mod = []
    for p in nested:
        for m in p["modules"]:
            leaves = [it for g in m["groups"] for it in g["items"]]
            roll = rollup(leaves)
            by_mod.append({"code": m["code"], "name": m["name"],
                           "total_md": roll["total_mandays"], "breakdown": roll["effort_by_role"]})
    totals = rollup(wbs["items"])
    wbs["phases_nested"] = nested
    wbs["effort_by_module"] = by_mod
    wbs["effort_totals"] = totals
    # Critical path (only when the agent supplied dependencies or 3-point estimates).
    cp_msg = ""
    if any(it.get("predecessors") or it.get("dependencies") or it.get("pert_expected_md")
           for it in wbs["items"]):
        cp = critical_path(wbs["items"])
        sched = {s["ref_code"]: s for s in cp["items"]}
        sched_keys = ("early_start", "early_finish", "late_start", "late_finish",
                      "float_md", "critical")
        for it in wbs["items"]:
            s = sched.get(it["ref_code"])
            if s:
                it.update({k: s[k] for k in sched_keys})
        wbs["critical_path"] = {"project_duration_md": cp["project_duration_md"],
                                "ref_codes": cp["critical_path_ref_codes"]}
        cp_msg = (f" Critical path: {len(cp['critical_path_ref_codes'])} tasks, "
                  f"{cp['project_duration_md']} MD.")
    # the builder reads wbs["phases"] as the nested tree → swap it in for export,
    # but keep the skeleton meta under phases_meta so add_wbs_items stays valid.
    wbs["phases_meta"] = wbs["phases"]
    wbs["phases"] = nested
    _write_json(_WBS_FILE, wbs)
    br = totals["effort_by_role"]
    return (f"Roll-up complete: {totals['total_mandays']} MD "
            f"(~{totals['total_manmonths']} man-months) across {len(by_mod)} modules. "
            f"By role — BE {br['BE']}, FE/Mobile {br['FE_Mobile']}, BA {br['BA']}, "
            f"QC {br['QC']}, PM {br['PM']}." + cp_msg)


# ════════════════════════════════════════════════════════════════════════════
# 6. plan_timeline_and_sprints
# ════════════════════════════════════════════════════════════════════════════
class TimelineArgs(_CoercingModel):
    duration_weeks: Optional[int] = Field(
        None, description="explicit project duration in weeks; omit to auto-derive from effort")
    peak_dev_fte: float = Field(
        3.0, description="peak parallel developers used to auto-derive duration")


@tool(args_schema=TimelineArgs)
def plan_timeline_and_sprints(duration_weeks: Optional[int] = None,
                              peak_dev_fte: float = 3.0) -> str:
    """Compute the delivery calendar: duration, 2-week sprints, months, Gantt grid.

    1 sprint = 2 weeks, 1 month = 4 weeks. If duration_weeks is omitted it is derived
    from total man-days and peak_dev_fte (duration_months ≈ mandays/(22·peak)). Emits
    an explicit per-module active week-range so the Delivery Plan always has ENOUGH
    months and no module overflows the calendar. Call after compute_wbs_rollup.
    """
    wbs = _read_json(_WBS_FILE)
    if not wbs or not wbs.get("effort_totals"):
        return "Roll up the WBS first (compute_wbs_rollup)."
    total_md = wbs["effort_totals"]["total_mandays"]
    if not duration_weeks:
        months = max(1, round(total_md / (MANDAYS_PER_MONTH * max(0.5, peak_dev_fte))))
        duration_weeks = months * 4
    grid = delivery_grid(duration_weeks)
    wbs["timeline"] = {
        "weeks": grid["weeks"], "sprints": grid["sprints"], "months": grid["months"],
        "weeks_per_sprint": 2, "weeks_per_month": 4,
        "project_start_date": "TBD", "project_end_date": "TBD",
    }
    # Sprint assignment: if CPM Early Start exists (from compute_wbs_rollup), assign sprints now.
    if any(it.get("early_start") is not None for it in wbs.get("items", [])):
        assign_sprints(wbs["items"], peak_dev_fte, weeks_per_sprint=2)
    _write_json(_WBS_FILE, wbs)
    return (f"Timeline: {grid['weeks']} weeks = {grid['months']} months / "
            f"{grid['sprints']} sprints (2-week sprints). Delivery Plan will render "
            f"{grid['months']} month columns.")


# ════════════════════════════════════════════════════════════════════════════
# 7. plan_team_and_resources
# ════════════════════════════════════════════════════════════════════════════
class RoleFTEArgs(_CoercingModel):
    dev_fte: Optional[float] = Field(None, description="peak parallel dev FTE (BE+FE+Mobile); derived from effort if omitted")
    ba_fte: Optional[float] = Field(None, description="BA FTE assumption; derived if omitted")
    qc_fte: Optional[float] = Field(None, description="QC FTE assumption; derived if omitted")
    pm_fte: Optional[float] = Field(None, description="PM FTE assumption; derived if omitted")


@tool(args_schema=RoleFTEArgs)
def plan_team_and_resources(dev_fte: Optional[float] = None, ba_fte: Optional[float] = None,
                             qc_fte: Optional[float] = None, pm_fte: Optional[float] = None) -> str:
    """Derive a team composition reconciled to the role effort totals.

    Maps the rolled-up BE/FE/BA/QC/PM man-days to a default BnK team (PM, Technical
    Lead, Developer(s), Business Analyst, Quality Controller, Designer, DevOps) and
    estimates headcount from man-days over the timeline. Runs resource leveling to
    flag sprint overloads against team capacity. Call after plan_timeline_and_sprints.
    """
    import math
    wbs = _read_json(_WBS_FILE)
    if not wbs or not wbs.get("effort_totals"):
        return "Roll up the WBS first (compute_wbs_rollup)."
    br = wbs["effort_totals"]["effort_by_role"]
    weeks = (wbs.get("timeline") or {}).get("weeks", 16)
    workdays = max(1, weeks * 5)
    team = [
        {"role": "Project Manager", "total_md": br.get("PM", 0)},
        {"role": "Technical Lead", "total_md": None},
        {"role": "Developer", "total_md": round(br.get("BE", 0) + br.get("FE_Mobile", 0), 2)},
        {"role": "Business Analyst", "total_md": br.get("BA", 0)},
        {"role": "Quality Controller", "total_md": br.get("QC", 0)},
        {"role": "Designer", "total_md": None},
        {"role": "DevOps", "total_md": None},
    ]
    for m in team:
        md = m["total_md"]
        m["est_headcount"] = round(md / workdays, 2) if md else None
    wbs["team_composition"] = team

    # Derive FTE assumptions from effort totals when not explicitly provided.
    # min 1 when a role has any effort; the ceil ensures the timeline is technically achievable.
    def _derive(total_md: float) -> float:
        if total_md and total_md > 0:
            return float(max(1, math.ceil(total_md / max(1, weeks * MANDAYS_PER_WEEK))))
        return 1.0

    role_fte: dict[str, float] = {
        "dev": dev_fte if dev_fte is not None else _derive(br.get("BE", 0) + br.get("FE_Mobile", 0)),
        "ba": ba_fte if ba_fte is not None else _derive(br.get("BA", 0)),
        "qc": qc_fte if qc_fte is not None else _derive(br.get("QC", 0)),
        "pm": pm_fte if pm_fte is not None else _derive(br.get("PM", 0)),
    }
    rl = level_resources(wbs.get("items") or [], role_fte=role_fte, weeks_per_sprint=2)
    wbs["resource_leveling"] = rl

    _write_json(_WBS_FILE, wbs)
    devs = next(t for t in team if t["role"] == "Developer")
    n_over = len(rl.get("overloads") or [])
    msg = (f"Team: PM {br.get('PM',0)} MD, Developer {devs['total_md']} MD "
           f"(~{devs['est_headcount']} FTE over {weeks} weeks), BA {br.get('BA',0)}, "
           f"QC {br.get('QC',0)} MD + TL/Designer/DevOps as needed. "
           f"Assumed FTE: dev={role_fte['dev']}, ba={role_fte['ba']}, "
           f"qc={role_fte['qc']}, pm={role_fte['pm']}.")
    if n_over:
        msg += f" WARNING: {n_over} sprint(s) overloaded — check resource_leveling in wbs.json."
    return msg


# ════════════════════════════════════════════════════════════════════════════
# 8. define_milestones
# ════════════════════════════════════════════════════════════════════════════
_BNK_MILESTONES = [
    {"name": "Contract Signoff", "deliverables": ["Signed contract"]},
    {"name": "Requirement Confirmation/Signoff", "deliverables": ["BRD"]},
    {"name": "Development Completion and UAT Initiation",
     "deliverables": ["System ready in UAT", "Test Cases", "Test Report"]},
    {"name": "Completion of UAT",
     "deliverables": ["Source Code", "User Guide", "Technical Specification"]},
    {"name": "Completion of Post-Launch Support", "deliverables": ["Maintenance log"]},
]


class MilestoneIn(BaseModel):
    name: str
    deliverables: list[str] = Field(default_factory=list)
    start: str = "TBD"
    end: str = "TBD"


class MilestonesArgs(_CoercingModel):
    milestones: Optional[list[MilestoneIn]] = Field(
        None, description="override the default BnK 5-milestone spine")


@tool(args_schema=MilestonesArgs)
def define_milestones(milestones: Optional[list[MilestoneIn]] = None) -> str:
    """Set the delivery milestones (defaults to the BnK 5-milestone spine).

    Default: Contract Signoff → Requirement Signoff → Dev Completion & UAT Init →
    UAT Completion → Post-Launch Support. Override only if the engagement differs.
    Call after plan_team_and_resources.
    """
    wbs = _read_json(_WBS_FILE)
    if not wbs:
        return "Draft the skeleton first (draft_wbs_skeleton)."
    ms = [m.model_dump() for m in milestones] if milestones else _BNK_MILESTONES
    wbs["milestones"] = ms
    _write_json(_WBS_FILE, wbs)
    return "Milestones set: " + " → ".join(m["name"] for m in ms)


# ════════════════════════════════════════════════════════════════════════════
# 9. validate_wbs — non-blocking warnings
# ════════════════════════════════════════════════════════════════════════════
@tool(parse_docstring=True)
def validate_wbs() -> str:
    """Run deterministic quality checks on the WBS (warnings only, never blocks).

    Checks: every dev leaf has effort > 0, ref codes unique/sequential, module
    roll-ups reconcile to the grand total, functional-requirement coverage vs the
    brief, and that the Delivery-Plan calendar covers every module's schedule. Call
    before propose_wbs.
    """
    wbs = _read_json(_WBS_FILE)
    if not wbs or not wbs.get("items"):
        return "No WBS to validate — build it first."
    warns: list[str] = []
    items = wbs["items"]

    zero = [it["ref_code"] for it in items if it.get("total", 0) <= 0]
    if zero:
        warns.append(f"{len(zero)} item(s) have zero effort: {zero[:6]}")

    seqs = [it["seq"] for it in items]
    if len(set(seqs)) != len(seqs):
        warns.append("Duplicate sequence numbers found — ref codes are not unique.")

    # coverage vs brief functional requirements (loose keyword match)
    brief = _read_json(_BRIEF_FILE, {}) or {}
    reqs = brief.get("functional_requirements", []) or []
    if reqs:
        names = " ".join(it["name"].lower() for it in items)
        uncovered = [r for r in reqs if not any(w in names for w in str(r).lower().split()[:3])]
        if uncovered:
            warns.append(f"{len(uncovered)}/{len(reqs)} functional requirement(s) may be "
                         f"uncovered by any feature: {uncovered[:4]}")

    # delivery-plan coverage
    tl = wbs.get("timeline") or {}
    if tl.get("weeks"):
        sched = wbs_excel._module_schedule(wbs, tl["weeks"])
        over = [m["code"] for m in sched if m["end_week"] > tl["weeks"]]
        if over:
            warns.append(f"Delivery plan: module(s) overflow the calendar: {over}")
        if tl.get("months", 0) < 1:
            warns.append("Delivery plan has < 1 month — check the timeline.")

    # resource leveling overloads (non-blocking warning — solution gate is the hard block).
    rl_overloads = (wbs.get("resource_leveling") or {}).get("overloads") or []
    if rl_overloads:
        worst = max(rl_overloads, key=lambda o: float(o.get("overflow_md") or 0))
        warns.append(
            f"Resource leveling: {len(rl_overloads)} sprint(s) overloaded "
            f"(worst: sprint {worst['sprint']} {worst['role']} "
            f"+{float(worst['overflow_md']):.1f} MD over capacity). "
            f"Increase FTE, reduce sprint scope, or extend the timeline."
        )

    if not warns:
        return "Validation passed: no issues found."
    return "Validation warnings (non-blocking):\n- " + "\n- ".join(warns)


# ════════════════════════════════════════════════════════════════════════════
# HITL GATE TOOLS (interrupt_on in agent.py)
# ════════════════════════════════════════════════════════════════════════════
# Pydantic arg schemas — the LLM passes display data when calling each gate
# so the frontend can render a rich approval card from activeTcArgs.

class _WbsModuleArg(_CoercingModel):
    code: str = ""
    name: str = ""

class _WbsPhaseArg(_CoercingModel):
    code: str = ""
    name: str = ""
    modules: list[_WbsModuleArg] = Field(default_factory=list)

class _SkeletonGateArgs(_CoercingModel):
    question: str = "Review the WBS structure and approve to begin effort estimation."
    project_name: str = ""
    project_code: str = ""
    phases: list[_WbsPhaseArg] = Field(default_factory=list)

class _ModuleEffortArg(_CoercingModel):
    code: str = ""
    name: str = ""
    total_md: float = 0.0

class _PlanGateArgs(_CoercingModel):
    question: str = "Review the WBS plan and approve to export to Excel."
    total_mandays: float = 0.0
    total_manmonths: float = 0.0
    timeline_weeks: int = 0
    timeline_months: int = 0
    effort_by_role: dict = Field(default_factory=dict)
    effort_by_module: list[_ModuleEffortArg] = Field(default_factory=list)

class _ExcelGateArgs(_CoercingModel):
    question: str = "Ready to generate the BnK-format WBS Excel file."
    total_mandays: float = 0.0
    timeline_months: int = 0


def _tree_summary(wbs: dict) -> str:
    lines = []
    for p in wbs.get("phases", wbs.get("phases_meta", [])):
        lines.append(f"{p['code']} {p['name']}")
        for m in p.get("modules", []):
            lines.append(f"   {m['code']} {m['name']}")
    return "\n".join(lines)


@tool(args_schema=_SkeletonGateArgs)
def propose_wbs_skeleton(
    question: str,
    project_name: str = "",
    project_code: str = "",
    phases: list = None,
) -> str:
    """Present the WBS phase/module structure for the user to approve.

    PAUSES for human approval of the STRUCTURE before any effort is estimated.
    Pass the full phase/module tree in `phases` so the frontend can render it.
    If rejected you get a note — revise the skeleton (draft_wbs_skeleton) and re-propose.
    Call after draft_wbs_skeleton.

    Args:
        question: Approval question shown to the user.
        project_name: Project name from project_info.
        project_code: Project code from project_info.
        phases: Phase/module tree from wbs_skeleton.json
            [{code, name, modules: [{code, name}]}].
    """
    sk = _read_json(_SKELETON_FILE)
    if not sk:
        return "No skeleton yet — call draft_wbs_skeleton first."
    pi = sk.get("project_info", {})
    return (
        f"✓ WBS skeleton APPROVED for {pi.get('name')} (code {pi.get('project_code')}):\n"
        + _tree_summary(sk)
        + "\n\nSkeleton is approved. IMMEDIATELY proceed to STEP 2 — do NOT wait for "
        "user input: call task(subagent_type='wbs_planner', description='Estimate dev "
        "effort: add_wbs_items for every module, compute_wbs_rollup, "
        "plan_timeline_and_sprints, plan_team_and_resources, define_milestones, "
        "validate_wbs. Write wbs.json.') → then call propose_wbs() → then "
        "export_wbs_excel()."
    )


@tool(args_schema=_PlanGateArgs)
def propose_wbs(
    question: str,
    total_mandays: float = 0.0,
    total_manmonths: float = 0.0,
    timeline_weeks: int = 0,
    timeline_months: int = 0,
    effort_by_role: dict = None,
    effort_by_module: list = None,
) -> str:
    """Present the full estimated WBS plan for the user to review and approve.

    PAUSES for human approval. Pass the effort summary so the frontend renders a
    rich review card. Call after validate_wbs. On approval, export_wbs_excel produces
    the .xlsx deliverable.

    Args:
        question: Approval question shown to the user.
        total_mandays: Grand total man-days from effort_totals.
        total_manmonths: Grand total man-months from effort_totals.
        timeline_weeks: Project duration in weeks from timeline.
        timeline_months: Project duration in months from timeline.
        effort_by_role: {BE, FE_Mobile, BA, QC, PM} man-day split.
        effort_by_module: [{code, name, total_md}] per-module breakdown.
    """
    wbs = _read_json(_WBS_FILE)
    if not wbs or not wbs.get("effort_totals"):
        return "Roll up and plan the WBS first (compute_wbs_rollup ... validate_wbs)."
    et = wbs["effort_totals"]; br = et["effort_by_role"]
    tl = wbs.get("timeline", {})
    lines = [
        f"WBS PLAN — {wbs.get('project_info', {}).get('name')}",
        f"Total effort: {et['total_mandays']} MD (~{et['total_manmonths']} man-months)",
        f"By role: BE {br['BE']} | FE/Mobile {br['FE_Mobile']} | BA {br['BA']} | "
        f"QC {br['QC']} | PM {br['PM']}",
        f"Timeline: {tl.get('weeks','?')} weeks / {tl.get('months','?')} months / "
        f"{tl.get('sprints','?')} sprints",
        "Effort by module:",
    ]
    for m in wbs.get("effort_by_module", []):
        lines.append(f"  {m['code']} {m['name']}: {m['total_md']} MD")
    if wbs.get("milestones"):
        lines.append("Milestones: " + " → ".join(m["name"] for m in wbs["milestones"]))
    lines.append("\n✓ WBS plan APPROVED. IMMEDIATELY call export_wbs_excel(question='Generate the BnK-format WBS Excel file?', total_mandays={:.1f}, timeline_months={}) — do NOT wait for user input.".format(
        et["total_mandays"], tl.get("months", 0)))
    summary = lines[1]
    try:
        from reporting import record_report_step
        record_report_step(current_workspace(), "propose_wbs", summary=summary, data=et)
    except Exception:
        pass
    return "\n".join(lines)


@tool(args_schema=_ExcelGateArgs)
def export_wbs_excel(
    question: str = "Ready to generate the BnK-format WBS Excel file.",
    total_mandays: float = 0.0,
    timeline_months: int = 0,
) -> str:
    """Generate the BnK-format WBS .xlsx deliverable from the approved plan.

    PAUSES for human approval. Clones the BnK template and fills the WBS, Effort and
    Delivery-Plan sheets with LIVE formulas (Excel recomputes BA/QC/PM/totals on open)
    and a dynamic month-by-month delivery grid. Writes wbs_filled.xlsx. Call only
    after propose_wbs is approved.

    Args:
        question: Confirmation prompt shown to the user.
        total_mandays: Total man-days for display (from effort_totals).
        timeline_months: Project duration in months for display.
    """
    wbs = _read_json(_WBS_FILE)
    if not wbs or not wbs.get("phases"):
        return "No approved WBS to export — run the planning pipeline first."
    try:
        layout = wbs_excel.build_wbs_workbook(wbs, _WBS_XLSX)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR building WBS workbook: {exc}"
    dly = layout.get("delivery", {})
    et = wbs.get("effort_totals", {})
    msg = (f"WBS exported to {_WBS_XLSX.name} "
           f"({_WBS_XLSX.stat().st_size:,} bytes). "
           f"{len(wbs.get('items', []))} work items, {et.get('total_mandays','?')} MD, "
           f"Delivery Plan spans {dly.get('months','?')} months / {dly.get('weeks','?')} weeks. "
           f"All effort columns are live formulas linked to the Master Data ratios.")
    # Per-stage cross-artifact check (refresh CSM + trace links + flag drift, advisory).
    # Persists findings to findings_log.json (stable id + waive/resolve lifecycle) and
    # drops settled ones, mirroring analysis_tools._solution_gate_note (docx §4.3, §7.1).
    try:
        from csm_adapter import build_solution_model
        from solution_validator import format_validation, validate_solution
        from traceability import write_trace_links
        model = build_solution_model(current_workspace())   # the WBS is now in scope — refresh the CSM
        write_trace_links(current_workspace())
        findings, _ = validate_solution(current_workspace(), block=False)
        try:
            from finding_store import active_findings, upsert_findings
            upsert_findings(findings, revision=model.revision)
            findings = active_findings(findings)
        except Exception:
            pass
        msg += (
            f"\n\nSOLUTION MODEL — revision {model.revision}: "
            f"{len(model.work_items)} task linked via {len(model.trace_links)} trace link(s) "
            "(solution_model.json)."
        )
        if findings:
            msg += "\n\nCROSS-ARTIFACT CHECK [wbs] — " + format_validation(findings, block=False)
    except Exception:
        pass
    return msg


# ── tool collections (imported by tools.py) ──────────────────────────────────
WBS_PLANNER_TOOLS = [
    load_solution_context,
    get_effort_norms,
    draft_wbs_skeleton,
    add_wbs_items,
    compute_wbs_rollup,
    plan_timeline_and_sprints,
    plan_team_and_resources,
    define_milestones,
    validate_wbs,
]

WBS_GATE_TOOLS = [propose_wbs_skeleton, propose_wbs, export_wbs_excel]
WBS_GATE_TOOL_NAMES = ["propose_wbs_skeleton", "propose_wbs", "export_wbs_excel"]
