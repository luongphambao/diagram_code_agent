"""Canonical Pydantic schema for BnK WBS JSON files.

53 historical WBS files use ~40 top-level schema variants and ~60 role label
variants. This module normalises them into one ``WbsProject`` shape suitable
for embedding and retrieval.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Role alias table — maps the ~60 raw labels found in the corpus to 5
# canonical role keys that mirror the BnK WBS template's Master Data sheet.
# ---------------------------------------------------------------------------
ROLE_ALIASES: dict[str, str] = {
    # BE / backend / server-side
    "BE Coding": "be_coding",
    "BE_Coding": "be_coding",
    "BE/AI_Coding": "be_coding",
    "Coding_Dev": "be_coding",
    "SE": "be_coding",
    "AI Coding": "be_coding",
    "AI": "be_coding",
    "Dev (Backend/AI/Workflow Dev)": "be_coding",
    "Coding (BE+FE+AI)": "be_coding",
    "DEV_BE_IoT_DevOps": "be_coding",
    "Fix bugs": "be_coding",
    "Golive/Deployment": "be_coding",
    # FE / mobile / frontend
    "FE/Mobile Coding": "fe_mobile_coding",
    "FE_Coding": "fe_mobile_coding",
    "FE_Mobile_Coding": "fe_mobile_coding",
    "DEV_FE": "fe_mobile_coding",
    "DEV_Mobile": "fe_mobile_coding",
    # BA / requirements
    "Requirement Analysis (BA)": "requirement_analysis",
    "Requirement_Analysis": "requirement_analysis",
    "Requirement_Analysis_BA": "requirement_analysis",
    "BA (Business Analysis / BRD)": "requirement_analysis",
    "BA_Tester": "requirement_analysis",
    # QA / testing
    "Testing": "testing",
    "Testing (QA)": "testing",
    "Testing (QC)": "testing",
    "Testing_QA": "testing",
    "Testing_QC": "testing",
    "QA/Testing": "testing",
    "UAT (MBAL)": "testing",
    # PM
    "Project Management (PM)": "project_management",
    "Project_Management": "project_management",
    "Project_Management_PM": "project_management",
}


def _resolve_role(raw: str) -> str:
    """Map a raw role label to a canonical key; unknown labels → be_coding."""
    return ROLE_ALIASES.get(raw, ROLE_ALIASES.get(raw.strip(), "be_coding"))


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
                # e.g. {"category": "Backend", "items": ["FastAPI", ...]}
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
        canonical: dict[str, float] = {
            "be_coding": 0.0,
            "fe_mobile_coding": 0.0,
            "requirement_analysis": 0.0,
            "testing": 0.0,
            "project_management": 0.0,
        }
        for label, value in raw.items():
            try:
                v = float(value or 0)
            except (TypeError, ValueError):
                continue
            key = _resolve_role(label)
            canonical[key] = canonical.get(key, 0.0) + v
        return cls(**canonical)


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
    risks: list[str] = Field(default_factory=list)
    raw_summary: str | None = None

    # Source filename (not serialised to JSON by default)
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
                    # risks_constraints is often a list of dicts
                    text = item.get("risk") or item.get("description") or item.get("constraint") or ""
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

        # objectives may be a list of strings or a dict {goal: ..., key_outcomes: [...]}
        raw_obj = data.get("objectives") or []
        if isinstance(raw_obj, dict):
            raw_obj = list(raw_obj.values())

        return cls(
            project_code=pi.get("project_code") or "",
            name=pi.get("name") or data.get("name") or "",
            client=pi.get("client"),
            business_domain=pi.get("business_domain") or "",
            solution_type=pi.get("solution_type") or "",
            description=pi.get("description"),
            objectives=raw_obj,
            technology_stack=data.get("technology_stack"),
            total_mandays=total_md,
            modules=modules,
            risks=data.get("risks_constraints"),
            raw_summary=data.get("raw_summary"),
            source_file=source_file,
        )
