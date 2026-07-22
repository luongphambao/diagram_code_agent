"""Canonical Pydantic schema for BnK WBS JSON files.

53 historical WBS files use ~40 top-level schema variants and ~60 role label
variants. This module normalises them into one ``WbsProject`` shape suitable
for embedding and retrieval.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Role alias table — maps raw labels from both effort_by_module AND wbs_items
# fields to 5 canonical role keys (BnK Master Data sheet standard).
# ---------------------------------------------------------------------------
ROLE_ALIASES: dict[str, str] = {
    # ---- BE / backend / server-side ----
    "BE Coding": "be_coding",
    "BE_Coding": "be_coding",
    "BE/AI_Coding": "be_coding",
    "BE_AI_md": "be_coding",
    "BE_AI": "be_coding",
    "be_coding_md": "be_coding",
    "be_md": "be_coding",
    "be_dev_md": "be_coding",
    "BE": "be_coding",
    "Coding_Dev": "be_coding",
    "coding_md": "be_coding",
    "SE": "be_coding",
    "AI Coding": "be_coding",
    "AI": "be_coding",
    "Dev (Backend/AI/Workflow Dev)": "be_coding",
    "Coding (BE+FE+AI)": "be_coding",
    "DEV_BE_IoT_DevOps": "be_coding",
    "Fix bugs": "be_coding",
    "Golive/Deployment": "be_coding",
    "DEV_md": "be_coding",  # WBS_EUP sheet
    "DEV": "be_coding",
    # ---- FE / mobile / frontend ----
    "FE/Mobile Coding": "fe_mobile_coding",
    "FE_Coding": "fe_mobile_coding",
    "FE_Mobile_Coding": "fe_mobile_coding",
    "fe_mobile_coding_md": "fe_mobile_coding",
    "fe_mobile_md": "fe_mobile_coding",
    "fe_md": "fe_mobile_coding",
    "mobile_md": "fe_mobile_coding",
    "mobile_coding_md": "fe_mobile_coding",
    "FE": "fe_mobile_coding",
    "FE_md": "fe_mobile_coding",
    "DEV_FE": "fe_mobile_coding",
    "DEV_Mobile": "fe_mobile_coding",
    # ---- BA / requirement analysis ----
    "Requirement Analysis (BA)": "requirement_analysis",
    "Requirement_Analysis": "requirement_analysis",
    "Requirement_Analysis_BA": "requirement_analysis",
    "requirement_analysis_md": "requirement_analysis",
    "req_analysis": "requirement_analysis",
    "ra_md": "requirement_analysis",
    "ba_md": "requirement_analysis",
    "BA (Business Analysis / BRD)": "requirement_analysis",
    "BA_Tester": "requirement_analysis",
    "BA": "requirement_analysis",
    "BA_md": "requirement_analysis",
    "JBA": "requirement_analysis",  # arm1 sheet
    # ---- QA / testing ----
    "Testing": "testing",
    "Testing (QA)": "testing",
    "Testing (QC)": "testing",
    "Testing_QA": "testing",
    "Testing_QC": "testing",
    "testing_md": "testing",
    "QA/Testing": "testing",
    "UAT (MBAL)": "testing",
    "QA": "testing",
    "QC": "testing",
    "qc_md": "testing",
    "QC_md": "testing",
    "Test": "testing",
    # ---- PM ----
    "Project Management (PM)": "project_management",
    "Project_Management": "project_management",
    "Project_Management_PM": "project_management",
    "project_management_md": "project_management",
    "pm_md": "project_management",
    "PM": "project_management",
    "PM_md": "project_management",
    "Python": "be_coding",  # arm1 treats Python as dev role
}

_CANONICAL_ROLES = frozenset(
    {"be_coding", "fe_mobile_coding", "requirement_analysis", "testing", "project_management"}
)


def _resolve_role(raw: str) -> str:
    """Map a raw role label to a canonical key; unmapped labels → be_coding."""
    return ROLE_ALIASES.get(raw, ROLE_ALIASES.get(raw.strip(), "be_coding"))


def _safe_float(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _flatten_tech_stack(value: Any) -> list[str]:
    """Normalise technology_stack — may be list[str] or dict[str, list]."""
    if value is None:
        return []
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                for v in item.values():
                    if isinstance(v, str):
                        result.append(v)
                    elif isinstance(v, list):
                        result.extend(str(i) for i in v if i)
        return [s for s in result if s]
    if isinstance(value, dict):
        result = []
        for v in value.values():
            if isinstance(v, str):
                result.append(v)
            elif isinstance(v, list):
                result.extend(str(i) for i in v if i)
        return [s for s in result if s]
    return []


# ---------------------------------------------------------------------------
# EffortByRole
# ---------------------------------------------------------------------------


class EffortByRole(BaseModel):
    """Effort breakdown by the 5 canonical BnK roles (in mandays)."""

    be_coding: float = 0.0
    fe_mobile_coding: float = 0.0
    requirement_analysis: float = 0.0
    testing: float = 0.0
    project_management: float = 0.0

    @property
    def dev_md(self) -> float:
        return self.be_coding + self.fe_mobile_coding

    @property
    def total(self) -> float:
        return (
            self.be_coding
            + self.fe_mobile_coding
            + self.requirement_analysis
            + self.testing
            + self.project_management
        )

    @classmethod
    def from_raw_dict(cls, raw: dict[str, Any]) -> "EffortByRole":
        canonical: dict[str, float] = {k: 0.0 for k in _CANONICAL_ROLES}
        for label, value in raw.items():
            key = _resolve_role(label)
            canonical[key] = canonical.get(key, 0.0) + _safe_float(value)
        return cls(**canonical)

    @classmethod
    def from_wbs_item_dict(cls, item: dict[str, Any]) -> "EffortByRole":
        """Extract effort from a wbs_item row (fields like ba_md, BE, fe_md, etc.)."""
        canonical: dict[str, float] = {k: 0.0 for k in _CANONICAL_ROLES}

        # 1. Flat role keys directly on the item
        for key, value in item.items():
            if key in ROLE_ALIASES:
                role = ROLE_ALIASES[key]
                canonical[role] = canonical.get(role, 0.0) + _safe_float(value)

        # 2. breakdown / role_breakdown dict
        for bkey in ("breakdown", "role_breakdown"):
            bd = item.get(bkey) or {}
            if isinstance(bd, dict):
                for label, value in bd.items():
                    role = _resolve_role(label)
                    canonical[role] = canonical.get(role, 0.0) + _safe_float(value)

        # 3. role_breakdowns list of dicts: [{role: ..., md: ...}, ...]
        rbl = item.get("role_breakdowns") or []
        if isinstance(rbl, list):
            for rb in rbl:
                if isinstance(rb, dict):
                    raw_role = rb.get("role") or rb.get("name") or ""
                    md_val = rb.get("md") or rb.get("mandays") or rb.get("effort_md") or 0
                    if raw_role:
                        role = _resolve_role(raw_role)
                        canonical[role] = canonical.get(role, 0.0) + _safe_float(md_val)

        return cls(**canonical)


# ---------------------------------------------------------------------------
# WbsItem — one task / line in the WBS
# ---------------------------------------------------------------------------


class WbsItem(BaseModel):
    """Normalised WBS task row."""

    id: str = ""
    code: str = ""
    name: str = ""
    description: str = ""
    module: str = ""  # module or phase grouping
    phase: str = ""
    total_md: float = 0.0
    effort: EffortByRole = Field(default_factory=EffortByRole)
    remark: str = ""

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "WbsItem":
        effort = EffortByRole.from_wbs_item_dict(raw)

        # total_md: prefer explicit key, else sum roles
        raw_total = raw.get("total_md") or raw.get("days") or raw.get("weeks")
        total_md = _safe_float(raw_total)
        if total_md == 0.0:
            total_md = effort.total

        remark_val = raw.get("remark") or raw.get("remarks") or raw.get("note") or ""

        return cls(
            id=str(raw.get("id") or raw.get("ref_code") or ""),
            code=str(raw.get("code") or raw.get("ref_code") or ""),
            name=str(raw.get("name") or raw.get("deliverable") or ""),
            description=str(raw.get("description") or ""),
            module=str(raw.get("module") or raw.get("section") or raw.get("feature_category") or ""),
            phase=str(raw.get("phase") or ""),
            total_md=total_md,
            effort=effort,
            remark=str(remark_val),
        )


# ---------------------------------------------------------------------------
# WbsModule — one row from effort_by_module (summary level)
# ---------------------------------------------------------------------------


class WbsModule(BaseModel):
    """One module/phase row from effort_by_module."""

    code: str = ""
    name: str = ""
    total_md: float = 0.0
    effort: EffortByRole = Field(default_factory=EffortByRole)

    @model_validator(mode="before")
    @classmethod
    def _parse_raw(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        breakdown = data.get("breakdown_by_role") or {}
        if isinstance(breakdown, dict):
            data = dict(data)
            data["effort"] = EffortByRole.from_raw_dict(breakdown).model_dump()
        return data


# ---------------------------------------------------------------------------
# WbsProject — top-level canonical shape
# ---------------------------------------------------------------------------


class WbsProject(BaseModel):
    """Canonical representation of one BnK WBS project."""

    project_code: str = ""
    name: str = ""
    client: str | None = None
    business_domain: str = ""
    solution_type: str = ""
    description: str | None = None
    objectives: list[str] = Field(default_factory=list)
    technology_stack: list[str] = Field(default_factory=list)
    total_mandays: float | None = None
    modules: list[WbsModule] = Field(default_factory=list)
    wbs_items: list[WbsItem] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    raw_summary: str | None = None

    source_file: str | None = Field(default=None, exclude=True)

    @field_validator("technology_stack", mode="before")
    @classmethod
    def _norm_tech_stack(cls, v: Any) -> list[str]:
        return _flatten_tech_stack(v)

    @field_validator("objectives", "risks", mode="before")
    @classmethod
    def _ensure_list_of_str(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v else []
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, str):
                    result.append(item)
                elif isinstance(item, dict):
                    text = (
                        item.get("risk")
                        or item.get("description")
                        or item.get("constraint")
                        or item.get("assumption")
                        or ""
                    )
                    if text:
                        result.append(str(text))
            return result
        return []

    @classmethod
    def from_raw(cls, data: dict[str, Any], *, source_file: str = "") -> "WbsProject":
        """Build a WbsProject from the raw JSON dict of a WBS file."""
        pi = data.get("project_info") or {}
        et = data.get("effort_totals") or {}

        total_md = None
        raw_tm = et.get("total_mandays")
        try:
            total_md = float(raw_tm) if raw_tm is not None else None
        except (TypeError, ValueError):
            pass

        modules_raw = data.get("effort_by_module") or []
        modules = []
        for m in modules_raw:
            if isinstance(m, dict):
                try:
                    modules.append(WbsModule.model_validate(m))
                except Exception:  # noqa: BLE001
                    pass

        # Normalise wbs_items — handle flat list, dict-of-lists, and nested tasks
        wbs_items = _extract_wbs_items(data)

        raw_obj = data.get("objectives") or []
        if isinstance(raw_obj, dict):
            raw_obj = list(raw_obj.values())

        return cls(
            project_code=pi.get("project_code") or "",
            name=pi.get("name") or data.get("name") or "",
            client=pi.get("client") or pi.get("client_customer") or pi.get("customer"),
            business_domain=pi.get("business_domain") or "",
            solution_type=pi.get("solution_type") or "",
            description=pi.get("description"),
            objectives=raw_obj,
            technology_stack=data.get("technology_stack"),
            total_mandays=total_md,
            modules=modules,
            wbs_items=wbs_items,
            risks=data.get("risks_constraints") or data.get("risks") or data.get("risks_and_constraints"),
            raw_summary=data.get("raw_summary"),
            source_file=source_file,
        )


# ---------------------------------------------------------------------------
# Helper: extract and flatten wbs_items from the many source shapes
# ---------------------------------------------------------------------------


def _extract_wbs_items(data: dict[str, Any]) -> list[WbsItem]:
    """Convert the highly-variable wbs_items field to list[WbsItem]."""
    raw_wi = data.get("wbs_items")
    if not raw_wi:
        return []

    rows: list[dict[str, Any]] = []

    if isinstance(raw_wi, list):
        for item in raw_wi:
            if isinstance(item, dict):
                # MBAL format: each top-level item has a 'tasks' list of sub-items
                subtasks = item.get("tasks")
                if isinstance(subtasks, list):
                    for task in subtasks:
                        if isinstance(task, dict):
                            merged = {**task, "module": item.get("name", ""), "id": item.get("id", "")}
                            rows.append(merged)
                else:
                    rows.append(item)
            # IDP format: may have nested sub_items
            # Already covered if sub_items key is present in the dict above

    elif isinstance(raw_wi, dict):
        # Some files have {phase_name: [list of items], ...}
        for key, val in raw_wi.items():
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        rows.append({**item, "module": key})
            elif isinstance(val, dict):
                rows.append({**val, "module": key})

    # Also check sub_items field on each row
    expanded: list[dict[str, Any]] = []
    for row in rows:
        sub = row.get("sub_items")
        if isinstance(sub, list) and sub:
            for s in sub:
                if isinstance(s, dict):
                    expanded.append({**s, "module": row.get("name", row.get("module", ""))})
        else:
            expanded.append(row)

    result = []
    for row in expanded:
        try:
            result.append(WbsItem.from_raw(row))
        except Exception:  # noqa: BLE001
            pass
    return result
