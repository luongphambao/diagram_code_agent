"""Canonical vocabularies for the BnK knowledge graph.

Every mapping here was derived from a full scan of ``DATA/SOLUTION_WBS`` (52 WBS
files, 3050 task nodes) and ``DATA/SLIDE_IMAGES`` (84 ``analysis.md``), not from
guesswork. The counts in the comments are the observed occurrences at the time of
extraction — they are there so a future reader can tell a long tail from a typo.

Why this module exists: the same concept is spelled up to six ways across the
corpus (``testing_md`` / ``Testing_md`` / ``Testing_MD`` / ``qc_md`` / ``QC_md`` /
``QA_md``). Loading that into a graph without collapsing it first produces six
nodes for one role, and every downstream aggregate — effort benchmarks above all —
comes out wrong while still looking plausible.

Three traps this module is specifically built to avoid:

1. **Estimator confusion.** ``oi_md`` / ``oi_estimated_md`` (1046 MD across the
   corpus) is *the partner's own estimate*, not a BnK role. One source file says
   it outright: "Oi's own estimated effort, separate from BnK estimate of 249.16
   MD". Summing it into role effort inflates every benchmark it touches.
2. **Total-vs-leaf double counting.** ``total_md`` appears on parents *and*
   children; naively summing the 2801 occurrences yields 74,063 MD, several times
   the real figure. Callers must respect hierarchy — see :data:`ROLLUP_FIELDS`.
3. **People in role columns.** 93 occurrences of personal names (``Bao`` 37,
   ``Tien`` 21, ``Dat Nguyen`` 9 …) sit in role fields. They are PII, they are not
   roles, and they must not become graph nodes.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

# ════════════════════════════════════════════════════════════════════════════
# 1. Roles — the closed vocabulary
# ════════════════════════════════════════════════════════════════════════════
# Modelled on the MSPDI ``Assignment`` element (Task × Resource × Work), which is
# the only published schema that represents effort per role per task. Kept
# deliberately small: a role earns a slot only if BnK prices it separately.

Role = Literal["PM", "BA", "BE", "FE", "MOBILE", "QC", "AI", "DATA", "RPA", "DEVOPS", "TL", "UX", "SE"]

ROLES: tuple[Role, ...] = (
    "PM",
    "BA",
    "BE",
    "FE",
    "MOBILE",
    "QC",
    "AI",
    "DATA",
    "RPA",
    "DEVOPS",
    "TL",
    "UX",
    "SE",
)

ROLE_LABELS: dict[Role, str] = {
    "PM": "Project Management",
    "BA": "Business Analysis / Requirement",
    "BE": "Backend Engineering",
    "FE": "Frontend Engineering",
    "MOBILE": "Mobile Engineering",
    "QC": "Quality Control / Testing",
    "AI": "AI / ML Engineering",
    "DATA": "Data Science / Engineering",
    "RPA": "RPA Engineering",
    "DEVOPS": "DevOps / Infrastructure",
    "TL": "Technical Lead / Solution Architect",
    "UX": "UI/UX Design",
    "SE": "Support / Service Engineering",
}

# Free-text role strings observed in `role_breakdown`, `pic`, `team_composition`
# and `effort_by_role`. Keys are normalised by :func:`_key` before lookup, so
# casing, accents, punctuation and spacing do not need entries of their own.
ROLE_ALIASES: dict[str, tuple[Role, ...]] = {
    # -- single roles ------------------------------------------------------
    "pm": ("PM",),
    "projectmanager": ("PM",),
    "projectmanagement": ("PM",),
    "projectmanagementpm": ("PM",),
    "pmprojectmanager": ("PM",),
    "ba": ("BA",),
    "businessanalyst": ("BA",),
    "requirementanalysis": ("BA",),
    "requirementanalysisba": ("BA",),
    "babusinessanalyst": ("BA",),
    "ra": ("BA",),
    "be": ("BE",),
    "becoding": ("BE",),
    "bedeveloper": ("BE",),
    "backenddeveloper": ("BE",),
    "backend": ("BE",),
    "becodingbackenddeveloper": ("BE",),
    "becodingdeveloper": ("BE",),
    "developerbe": ("BE",),
    "fe": ("FE",),
    "fecoding": ("FE",),
    "frontenddeveloper": ("FE",),
    "frontendengineer": ("FE",),
    "frontend": ("FE",),
    "mobile": ("MOBILE",),
    "mobilecoding": ("MOBILE",),
    "mobiledeveloper": ("MOBILE",),
    "mobilecodingmobiledeveloper": ("MOBILE",),
    "developermobile": ("MOBILE",),
    "qc": ("QC",),
    "qa": ("QC",),
    "testing": ("QC",),
    "tester": ("QC",),
    "testingqa": ("QC",),
    "testingqc": ("QC",),
    "qualitycontroller": ("QC",),
    "qualitycontrollertester": ("QC",),
    "qualitycontrollerqcqa": ("QC",),
    "qualitycontrollerqctester": ("QC",),
    "qualitycontrollerqa": ("QC",),
    "qatester": ("QC",),
    "ai": ("AI",),
    "aicoding": ("AI",),
    "aiengineer": ("AI",),
    "aimlengineer": ("AI",),
    "ds": ("DATA",),
    "datascientist": ("DATA",),
    "dataengineer": ("DATA",),
    "rpa": ("RPA",),
    "rpacoding": ("RPA",),
    "rpadeveloper": ("RPA",),
    "devops": ("DEVOPS",),
    "devopsengineer": ("DEVOPS",),
    "tl": ("TL",),
    "technicallead": ("TL",),
    "techlead": ("TL",),
    "sa": ("TL",),
    "solutionarchitect": ("TL",),
    "designer": ("UX",),
    "designeruiux": ("UX",),
    "uiux": ("UX",),
    "uxdesigner": ("UX",),
    "se": ("SE",),
    "supportengineer": ("SE",),
    "serviceengineer": ("SE",),
    # -- composite columns: one Excel column priced across several roles ----
    # Kept as tuples so the loader can split effort explicitly rather than
    # silently attributing it to whichever role happens to sort first.
    "femobile": ("FE", "MOBILE"),
    "femobilecoding": ("FE", "MOBILE"),
    "femobilecoder": ("FE", "MOBILE"),
    "femobiledeveloper": ("FE", "MOBILE"),
    "batester": ("BA", "QC"),
    "baqa": ("BA", "QC"),
    "baqacombined": ("BA", "QC"),
    "businessanalystqualitycontroller": ("BA", "QC"),
    "dsba": ("BA", "DATA"),
    "bads": ("BA", "DATA"),
    "designerdocumentation": ("UX", "BA"),
    "developerbefe": ("BE", "FE"),
    "developerbeai": ("BE", "AI"),
    "developerbemobile": ("BE", "MOBILE"),
    "developerbefemobile": ("BE", "FE", "MOBILE"),
    "developerbeaife": ("BE", "AI", "FE"),
    "developeraibefe": ("BE", "AI", "FE"),
    "aimlengineerbackend": ("AI", "BE"),
    "backenddeveloperaiengineer": ("BE", "AI"),
    "technicalleadaicoding": ("TL", "AI"),
    "developerbefecodingrpa": ("BE", "FE", "RPA"),
    "developer": ("BE", "FE"),  # unqualified "Developer" — generic dev pool
}

# Personal names found sitting in role/PIC columns. Not roles, and PII: the
# loader drops them rather than minting a node. Matched on the normalised key,
# including the observed "Bao & Tien" / "Dat Nguyen/Thu" pairings.
PERSON_NAME_KEYS: frozenset[str] = frozenset(
    {
        "bao",
        "tien",
        "lich",
        "thuy",
        "trang",
        "quyen",
        "duy",
        "datnguyen",
        "thutran",
        "thuynguyen",
        "baotien",
        "baoduy",
        "datnguyenthu",
        "dat",
        "thu",
    }
)

# Structural JSON keys that leak into role position when a converter flattens a
# dict. Never roles; drop silently is wrong (see conventions §4) — the loader
# warns on anything here that carries nonzero effort.
NON_ROLE_KEYS: frozenset[str] = frozenset(
    {
        "roles",
        "note",
        "notes",
        "teamnote",
        "ratecard",
        "ratepercentages",
        "masterdatarates",
        "masterdataratios",
        "masterdataconfig",
    }
)


# ════════════════════════════════════════════════════════════════════════════
# 2. Man-day fields — 48 spellings collapsed onto roles + estimator
# ════════════════════════════════════════════════════════════════════════════

FieldKind = Literal["role", "total", "unallocated", "phase", "not_effort"]
Estimator = Literal["bnk", "partner"]

#: Which revision of the estimate a column belongs to. A single project carries
#: several — ``cr_original_md`` vs ``cr_updated_md``, ``phase2_internal_estimate_md``
#: vs ``phase2_client_quote_md``. Benchmarking across projects while mixing these
#: compares an internal figure against a negotiated one, so the axis has to be
#: explicit rather than flattened away.
Scenario = Literal["baseline", "original", "updated", "internal", "client_quote", "buffer"]


@dataclass(frozen=True)
class EffortField:
    """What one ``*_md`` column in a source WBS actually means.

    ``roles`` is empty for anything that is not attributable to a role. ``kind``
    tells the loader how to treat it:

    - ``role``        — attributable effort, emit an Assignment edge per role.
    - ``total``       — a rollup of other columns; never sum with them.
    - ``unallocated`` — real effort, role unknown (e.g. bare ``coding_md``).
    - ``phase``       — belongs to a phase, not a role (``maintenance_md``).
    - ``not_effort``  — a rate or a delta that merely ends in ``_md``.
    """

    roles: tuple[Role, ...]
    kind: FieldKind
    estimator: Estimator = "bnk"
    scenario: Scenario = "baseline"
    phases: tuple[Phase, ...] = ()
    note: str = ""


_F = EffortField

# Keyed by the field name lowercased — casing variants (BA_md / ba_md /
# Requirement_Analysis_MD) collapse here, which is 12 of the 48 spellings.
MD_FIELDS: dict[str, EffortField] = {
    # -- rollups: must never be added to the per-role columns ---------------
    "total_md": _F((), "total", note="2801 occurrences, on parents AND leaves"),
    "total_task_md": _F((), "total"),
    "estimated_md": _F((), "total"),
    "est_md": _F((), "total"),
    "md": _F((), "total", note="bare column in flat single-column sheets"),
    # -- per-role -----------------------------------------------------------
    "pm_md": _F(("PM",), "role"),
    "project_management_md": _F(("PM",), "role"),
    "ba_md": _F(("BA",), "role"),
    "requirement_analysis_md": _F(("BA",), "role"),
    "ra_md": _F(("BA",), "role"),
    "be_md": _F(("BE",), "role"),
    "be_coding_md": _F(("BE",), "role"),
    "be_dev_md": _F(("BE",), "role"),
    "fe_md": _F(("FE",), "role"),
    "fe_coding_md": _F(("FE",), "role"),
    "dev_fe_md": _F(("FE",), "role"),
    "mobile_md": _F(("MOBILE",), "role"),
    "mobile_coding_md": _F(("MOBILE",), "role"),
    "dev_mobile_md": _F(("MOBILE",), "role"),
    "testing_md": _F(("QC",), "role"),
    "qc_md": _F(("QC",), "role"),
    "qa_md": _F(("QC",), "role"),
    "ai_md": _F(("AI",), "role"),
    "rpa_md": _F(("RPA",), "role"),
    # -- composite columns --------------------------------------------------
    "fe_mobile_md": _F(("FE", "MOBILE"), "role"),
    "fe_mobile_coding_md": _F(("FE", "MOBILE"), "role"),
    "be_fe_md": _F(("BE", "FE"), "role"),
    "be_ai_md": _F(("BE", "AI"), "role", note="2802 MD — significant, do not drop"),
    "dev_be_iot_devops_md": _F(("BE", "DEVOPS"), "role"),
    # -- real effort, role not recoverable from the column name -------------
    "coding_md": _F((), "unallocated", note="3514 MD, generic dev column"),
    "dev_md": _F((), "unallocated"),
    # -- phase-scoped, not role-scoped --------------------------------------
    "maintenance_md": _F((), "phase", note="903 MD — post-golive, priced separately"),
    "monthly_md": _F((), "phase", note="recurring run-rate, not project effort"),
    # -- partner's own estimate: a different estimator, not a BnK role -------
    "oi_md": _F((), "total", "partner", note="Oi's estimate, parallel to BnK's"),
    "oi_estimated_md": _F((), "total", "partner"),
    # -- ends in _md but is not effort --------------------------------------
    "rate_per_md": _F((), "not_effort", note="a price per man-day"),
    "total_s2_target_md": _F((), "not_effort", note="a stream-2 target, not booked"),
}

#: Fields that roll up other fields. Summing these alongside per-role columns
#: double counts; :func:`classify_md_field` flags them so the loader can pick one
#: axis and stay on it.
ROLLUP_FIELDS: frozenset[str] = frozenset(name for name, f in MD_FIELDS.items() if f.kind == "total")


# ════════════════════════════════════════════════════════════════════════════
# 3. Phases vs feature modules — one field holding two node types
# ════════════════════════════════════════════════════════════════════════════
# `effort_by_module` mixes the standard BnK delivery skeleton (3 names covering
# ~half the corpus) with per-project feature groups (Booking Engine, Camera
# Registration, Land Class Data …). They are different kinds of thing and must
# not share a node type: the first is a closed vocabulary you can benchmark
# across projects, the second is open and project-local.

Phase = Literal["SETUP", "REQUIREMENT", "DEVELOPMENT", "TESTING", "DEPLOYMENT", "UAT", "MAINTENANCE"]

PHASES: tuple[Phase, ...] = (
    "SETUP",
    "REQUIREMENT",
    "DEVELOPMENT",
    "TESTING",
    "DEPLOYMENT",
    "UAT",
    "MAINTENANCE",
)

PHASE_ALIASES: dict[str, tuple[Phase, ...]] = {
    "development": ("DEVELOPMENT",),
    "systemdevelopment": ("DEVELOPMENT",),
    "developingnewmodules": ("DEVELOPMENT",),
    "setupinstallation": ("SETUP",),
    "setup": ("SETUP",),
    "requirementgathering": ("REQUIREMENT",),
    "setuprequirementgathering": ("SETUP", "REQUIREMENT"),
    "testingdeploymentsupport": ("TESTING", "DEPLOYMENT"),
    "testingqualityassurance": ("TESTING",),
    "situattesting": ("TESTING", "UAT"),
    "uat": ("UAT",),
    "solutionqualificationfixsituatissues": ("TESTING", "UAT"),
    "deploymentmaintenancepostgolivesupport": ("DEPLOYMENT", "MAINTENANCE"),
    "softwaremaintenance1year": ("MAINTENANCE",),
    "maintenancepackage1year": ("MAINTENANCE",),
    "nursingperiod": ("MAINTENANCE",),
    "integrationanddeployment": ("DEVELOPMENT", "DEPLOYMENT"),
}

#: Roman-numeral module codes are the real hierarchy in the BnK template
#: (``I.A``, ``II.A.3``, ``II.B``). Anything matching this is structural, not a
#: feature name, even when the label is project-specific.
MODULE_CODE_RE = re.compile(r"^(?P<top>[IVX]+)(?:\.(?P<mid>[A-Z]))?(?:\.(?P<leaf>\d+))?$")


# ════════════════════════════════════════════════════════════════════════════
# 4. Technology hygiene
# ════════════════════════════════════════════════════════════════════════════
# 944 distinct tech strings across solution_memory.json, 810 of them singletons
# (86%). Hand-curating that tail is not worth it; the plan is to resolve names
# against an external vocabulary (CSO 3.4.1 / Wikidata / CPE 2.3) and keep a node
# only when it recurs. What DOES need a hand-written list is the set of strings
# that are not technologies at all but were captured as such.

#: Methodologies, ceremonies, artefacts and generic nouns that landed in `tech[]`.
#: These become their own node types (or nothing), never a Technology.
TECH_STOPWORD_KEYS: frozenset[str] = frozenset(
    {
        "agile",
        "scrum",
        "kanban",
        "waterfall",
        "devops",
        "cicd",
        "cicdpipeline",
        "restapi",
        "api",
        "ai",
        "ml",
        "nlp",
        "ocr",
        "llm",
        "featureengineering",
        "uatenvironment",
        "testenvironment",
        "production",
        "staging",
        "congnghe",
        "technology",
        "techstack",
        "database",
        "frontend",
        "backend",
        "mobileapp",
        "webapp",
        "cloud",
        "microservices",
        "orchestrator",
    }
)

#: Minimum number of distinct projects a technology must appear in before it
#: becomes a graph node. Below this it stays an attribute on the project only —
#: this is what keeps the 810 singletons from becoming 810 dead nodes.
TECH_MIN_PROJECT_COUNT = 2


# ════════════════════════════════════════════════════════════════════════════
# 5. Text hygiene
# ════════════════════════════════════════════════════════════════════════════
# The corpus carries three encoding scars: U+FFFD where an en-dash was
# ("MODULE A � FRONTEND", "II � SYSTEM DEVELOPMENT"), vertical tabs from
# PowerPoint text frames, and 23 of 84 analysis files with Vietnamese diacritics
# stripped. The first two are repairable; the third is not, so every lookup key
# is accent-folded rather than accent-corrected.

_MOJIBAKE = {
    "�": "-",  # en-dash lost in a cp1252 round-trip
    "": " ",  # PowerPoint vertical tab
    " ": " ",  # non-breaking space
}


def clean_text(value: str) -> str:
    """Repair the known encoding scars and collapse whitespace."""
    for bad, good in _MOJIBAKE.items():
        value = value.replace(bad, good)
    return re.sub(r"\s+", " ", value).strip()


def strip_accents(value: str) -> str:
    """Fold Vietnamese diacritics so accented and stripped spellings match."""
    return "".join(c for c in unicodedata.normalize("NFD", value) if unicodedata.category(c) != "Mn")


def _key(value: str) -> str:
    """Normalise a free-text label to an alias-table lookup key."""
    return re.sub(r"[^a-z0-9]+", "", strip_accents(clean_text(value)).lower())


# ════════════════════════════════════════════════════════════════════════════
# 6. Resolution API
# ════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RoleResolution:
    """Outcome of resolving one free-text role string.

    ``roles`` empty with ``reason="person"`` means the cell held a human name; the
    caller should record the effort against the task but mint no role node.
    """

    roles: tuple[Role, ...]
    reason: Literal["mapped", "person", "structural", "phase", "unknown"]
    source: str


#: Given-name tokens observed inside role cells, often welded onto a real role
#: (``Frontend_Engineer_Tien``, ``AI_ML_Engineer_Backend_Bao``). Matched per
#: token so the role survives and the person does not.
_PERSON_TOKENS: frozenset[str] = frozenset(
    {
        "bao",
        "tien",
        "lich",
        "thuy",
        "trang",
        "quyen",
        "duy",
        "dat",
        "nguyen",
        "thu",
        "tran",
        "tra",
    }
)

#: Applied only when no other role token matched — a bare "Dev"/"Developer" is
#: the generic build pool, but in "BE Dev" the "BE" is the real signal.
_GENERIC_DEV_TOKENS: frozenset[str] = frozenset({"dev", "developer", "coder", "coding"})


def resolve_role(value: str) -> RoleResolution:
    """Map a free-text role label onto the canonical vocabulary.

    Exact alias lookup first, then per-token resolution so that compound and
    person-contaminated labels still yield their roles. Returns
    ``reason="unknown"`` rather than guessing — per conventions §4 an
    unrecognised label is a WARNING for the caller, not a silent drop.
    """
    raw = clean_text(value)
    key = _key(raw)
    if not key:
        return RoleResolution((), "unknown", raw)
    if key in PERSON_NAME_KEYS:
        return RoleResolution((), "person", raw)
    if key in NON_ROLE_KEYS:
        return RoleResolution((), "structural", raw)
    if key in ROLE_ALIASES:
        return RoleResolution(ROLE_ALIASES[key], "mapped", raw)

    toks = _tokens(strip_accents(raw))
    if not toks:
        return RoleResolution((), "unknown", raw)

    roles: tuple[Role, ...] = ()
    for tok in toks:
        roles += tuple(r for r in _ROLE_TOKENS.get(tok, ()) if r not in roles)
    if roles:
        return RoleResolution(roles, "mapped", raw)

    if set(toks) & _GENERIC_DEV_TOKENS:
        return RoleResolution(("BE", "FE"), "mapped", raw)
    if any(tok in _PHASE_TOKENS for tok in toks):
        return RoleResolution((), "phase", raw)
    if set(toks) & _PERSON_TOKENS:
        return RoleResolution((), "person", raw)
    return RoleResolution((), "unknown", raw)


#: Role tokens recognised inside a compound column name. Deliberately narrower
#: than ROLE_ALIASES: these are matched against name *fragments*, so a loose
#: entry here would misfire on unrelated columns.
_ROLE_TOKENS: dict[str, tuple[Role, ...]] = {
    "pm": ("PM",),
    "ba": ("BA",),
    "ra": ("BA",),
    "requirement": ("BA",),
    "be": ("BE",),
    "backend": ("BE",),
    "fe": ("FE",),
    "frontend": ("FE",),
    "mobile": ("MOBILE",),
    "qa": ("QC",),
    "qc": ("QC",),
    "testing": ("QC",),
    "test": ("QC",),
    "ai": ("AI",),
    "ml": ("AI",),
    "ds": ("DATA",),
    "data": ("DATA",),
    "rpa": ("RPA",),
    "devops": ("DEVOPS",),
    "iot": ("BE",),
    "ux": ("UX",),
    "ui": ("UX",),
    "designer": ("UX",),
}

#: Phase tokens. Checked before role tokens because ``uat_support_md`` is scoped
#: to a phase, not to whoever happens to staff it.
_PHASE_TOKENS: dict[str, tuple[Phase, ...]] = {
    "uat": ("UAT",),
    "sit": ("TESTING",),
    "deployment": ("DEPLOYMENT",),
    "deploy": ("DEPLOYMENT",),
    "golive": ("DEPLOYMENT",),
    "staging": ("DEPLOYMENT",),
    "production": ("DEPLOYMENT",),
    "maintenance": ("MAINTENANCE",),
    "support": ("MAINTENANCE",),
    "setup": ("SETUP",),
    "installation": ("SETUP",),
}

_SCENARIO_TOKENS: dict[str, Scenario] = {
    "original": "original",
    "updated": "updated",
    "internal": "internal",
    "quote": "client_quote",
    "buffer": "buffer",
}

#: A column naming a partner rather than BnK. ``oi`` is the only one observed,
#: but the check is a set so the next partner is a one-line change.
_PARTNER_TOKENS: frozenset[str] = frozenset({"oi"})

#: Tokens that mean the column holds money, elapsed time, or a difference —
#: anything but booked effort. ``duration_md`` is calendar days, not man-days.
_NOT_EFFORT_TOKENS: frozenset[str] = frozenset({"rate", "rates", "delta", "usd", "sgd", "vnd", "duration"})

#: Tokens marking an aggregate. ``phase``/``module`` count: a figure carried at
#: phase or module level is a rollup of the leaves beneath it, and adding it to
#: those leaves double counts.
_TOTAL_TOKENS: frozenset[str] = frozenset(
    {"total", "grand", "allocated", "weekly", "phase", "module", "estimate", "quote"}
)


def _tokens(name: str) -> list[str]:
    """Split a column name into lowercase word tokens, dropping the ``md`` tail
    and any trailing digits (``BE1_Algorithm`` and ``BE2_Integration`` are two
    seats on the same role, not two roles)."""
    parts = re.split(r"[^a-z0-9]+", name.strip().lower())
    out = []
    for part in parts:
        if not part or part == "md":
            continue
        out.append(re.sub(r"\d+$", "", part) or part)
    return out


def classify_md_field(name: str) -> EffortField | None:
    """Classify a ``*_md`` column.

    The explicit :data:`MD_FIELDS` table wins, because the columns in it are the
    ones whose meaning cannot be read off the name (``coding_md`` carries 3514 MD
    with no role in the name; ``oi_md`` names a partner, not a role). Everything
    else is derived from tokens, so a new spelling of an already-understood
    concept classifies itself instead of silently vanishing from the graph.

    Returns ``None`` only when the name yields no usable token at all.
    """
    explicit = MD_FIELDS.get(name.strip().lower())
    if explicit is not None:
        return explicit

    toks = _tokens(name)
    if not toks:
        return None
    tokset = set(toks)

    if tokset & _NOT_EFFORT_TOKENS:
        return EffortField((), "not_effort", note=f"derived from {name}")

    estimator: Estimator = "partner" if tokset & _PARTNER_TOKENS else "bnk"
    scenario: Scenario = "baseline"
    for tok in toks:
        if tok in _SCENARIO_TOKENS:
            scenario = _SCENARIO_TOKENS[tok]
            break

    phases: tuple[Phase, ...] = ()
    for tok in toks:
        phases += tuple(p for p in _PHASE_TOKENS.get(tok, ()) if p not in phases)

    roles: tuple[Role, ...] = ()
    for tok in toks:
        roles += tuple(r for r in _ROLE_TOKENS.get(tok, ()) if r not in roles)

    if tokset & _TOTAL_TOKENS:
        kind: FieldKind = "total"
    elif roles:
        kind = "role"
    elif phases:
        kind = "phase"
    elif scenario != "baseline":
        # A figure labelled with an estimate revision but no role or phase is an
        # aggregate for that revision — `cr_original_md`, `cr_updated_md`.
        kind = "total"
    else:
        kind = "unallocated"

    return EffortField(
        roles=roles,
        kind=kind,
        estimator=estimator,
        scenario=scenario,
        phases=phases,
        note=f"derived from {name}",
    )


def resolve_phase(value: str) -> tuple[Phase, ...]:
    """Map an ``effort_by_module`` name onto delivery phases.

    Empty result means the label is a project-specific feature module, which is a
    different node type — the caller should emit a ``FeatureModule``, not a
    ``Phase``.
    """
    return PHASE_ALIASES.get(_key(value), ())


def is_structural_module_code(code: str) -> bool:
    """True for the Roman-numeral codes that carry the BnK template hierarchy."""
    return bool(MODULE_CODE_RE.match(clean_text(code).upper()))


def is_technology(value: str) -> bool:
    """False for methodologies, environments and generic nouns caught in ``tech[]``."""
    key = _key(value)
    return bool(key) and key not in TECH_STOPWORD_KEYS and len(key) > 1
