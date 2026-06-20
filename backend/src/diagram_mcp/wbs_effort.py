"""Deterministic WBS effort model — the house "BnK overhead" derivation.

Pure, no-LLM, unit-testable helpers shared by the WBS tools, the Excel builder,
and the prototype script. The model is reverse-engineered from real BnK WBS
spreadsheets (``DATA/WBS/*.xlsx``) and verified to the cent against leaf items in
``[BnK] Clinic Management``, ``[BnK] Template``, ``[Oi] Commission`` and ``Avalant``.

Core idea: a senior estimator only sizes the **development** effort per feature
(BE / FE / Mobile / AI man-days). The non-dev roles are *derived* from fixed
ratios that live in the workbook's ``4. Master Data`` sheet:

    dev = BE + FE + Mobile + AI            # the only independently-estimated number
    BA  = ba_on_dev * dev                  # 10% of dev
    QC  = qc_on_dev * dev                  # 30% of dev
    PM  = pm_on_total * (dev + BA + QC)    # 10% of (dev+ba+qc); some projects 5%
    total = dev + BA + QC + PM             # ≈ 1.54 * dev for the 10/30/10 model

Ratios are configurable (the Master Data sheet differs per project) but default
to the most common BnK values. The Excel export keeps the *formulas* live and
references Master Data, so the values this module computes MUST match what Excel
would recompute — keep the formula builder (``wbs_excel``) and this module in sync.

Phase-gating — the ratios do NOT apply uniformly. Some kinds of work have no BA
or QC, or no dev at all. ``phase_type`` selects the gating:

    "development"  → dev + BA + QC + PM   (the default for feature leaves)
    "requirement"  → BA + PM only         (workshops, BRD; estimate lands in `ba`)
    "design"       → dev(BE) + PM only    (solution/architecture/DB design, setup)
    "uiux"         → dev(FE/Mobile) + PM  (UI/UX design)
    "deployment"   → dev(BE) only, PM=0   (prod deploy, app-store, data migration)
    "support"      → as given (UAT / post-go-live block, sized directly)
"""

from __future__ import annotations

from dataclasses import dataclass
import re

# Man-days per man-month used across the corpus (total_manmonths = mandays / 22).
MANDAYS_PER_MONTH = 22.0


@dataclass(frozen=True)
class Ratios:
    """Overhead ratios mirrored from the workbook's ``4. Master Data`` sheet."""

    ba_on_dev: float = 0.10   # Master Data C5
    qc_on_dev: float = 0.30   # Master Data C7
    pm_on_total: float = 0.10  # Master Data C4 (applied to dev+ba+qc)


RATIOS = Ratios()

# phase_type → which roles are active. None means "derived/absent per gating below".
DEV_TYPES = {"development", "design", "uiux", "deployment", "support"}


def _round(x: float, ndigits: int = 4) -> float:
    # Keep a few decimals; the source sheets carry float noise like 0.30000000004.
    return round(float(x), ndigits)


def derive_leaf_effort(
    be: float = 0.0,
    fe: float = 0.0,
    mobile: float = 0.0,
    ai: float = 0.0,
    ba: float = 0.0,
    phase_type: str = "development",
    ratios: Ratios = RATIOS,
) -> dict:
    """Return the full role breakdown for one leaf WBS item.

    ``be/fe/mobile/ai`` are the hand-estimated dev man-days. ``ba`` is only read
    for ``phase_type='requirement'`` (where the work itself is analysis and there
    is no dev). Returns a dict with be/fe/mobile/ai/ba/qc/pm/total (man-days),
    matching what the live Excel formulas recompute.
    """
    be = float(be or 0); fe = float(fe or 0)
    mobile = float(mobile or 0); ai = float(ai or 0); ba_in = float(ba or 0)
    dev = be + fe + mobile + ai
    pt = (phase_type or "development").lower()

    if pt == "requirement":
        ba_v, qc_v = ba_in, 0.0
        pm_v = ratios.pm_on_total * (dev + ba_v + qc_v)
    elif pt in ("design", "uiux", "setup"):
        ba_v, qc_v = 0.0, 0.0
        pm_v = ratios.pm_on_total * dev
    elif pt == "deployment":
        ba_v, qc_v, pm_v = 0.0, 0.0, 0.0
    elif pt == "support":
        # Sized as a single block; caller already put effort in be/fe(+ba). Derive
        # qc/pm modestly off dev so a lone support row still rolls up sensibly.
        ba_v = ratios.ba_on_dev * dev
        qc_v = ratios.qc_on_dev * dev
        pm_v = ratios.pm_on_total * (dev + ba_v + qc_v)
    else:  # development (default)
        ba_v = ratios.ba_on_dev * dev
        qc_v = ratios.qc_on_dev * dev
        pm_v = ratios.pm_on_total * (dev + ba_v + qc_v)

    total = dev + ba_v + qc_v + pm_v
    return {
        "be": _round(be), "fe": _round(fe), "mobile": _round(mobile),
        "ai": _round(ai), "ba": _round(ba_v), "qc": _round(qc_v),
        "pm": _round(pm_v), "total": _round(total),
    }


# Role keys used in the BnK template's "2. WBS" sheet, in column order G..K.
# RA = Requirement Analysis (BA), Testing = QC. Mobile and FE share one column.
WBS_ROLE_COLUMNS = ["be", "fe_mobile", "ba", "qc", "pm"]


def to_wbs_columns(eff: dict) -> dict:
    """Collapse the role breakdown into the template's 5 effort columns.

    The "2. WBS" sheet has: BE Coding | FE/Mobile Coding | Requirement Analysis |
    Testing | Project Management. Mobile/FE/AI all land in the FE/Mobile column.
    """
    return {
        "be": eff["be"],
        "fe_mobile": _round(eff["fe"] + eff["mobile"] + eff["ai"]),
        "ba": eff["ba"],
        "qc": eff["qc"],
        "pm": eff["pm"],
    }


def make_ref_code(project_code: str, seq: int) -> str:
    """Build a leaf Ref.Code the way the template's CONCATENATE formula does."""
    return f"{(project_code or 'BNK').strip()}-{seq}"


# Fuzzy mapping of the many role-key spellings seen across the 50 sample JSONs
# (BE Coding / BE_Coding / Backend, FE/Mobile / Mobile Coding, Requirement
# Analysis (BA) / RA, Testing / QA / QC, Project Management / PM ...).
_ROLE_PATTERNS = [
    ("be", r"^(be|back\s*end|backend|be[_\s]*coding|server)"),
    ("fe", r"^(fe|front\s*end|frontend|fe[_\s/]*mobile|mobile|web|ui[\s_]*coding)"),
    ("ai", r"^(ai|ml|data\s*scien|ds|model)"),
    ("ba", r"^(ba|business\s*anal|requirement|ra\b)"),
    ("qc", r"^(qc|qa|test)"),
    ("pm", r"^(pm|project\s*manag|coordinat)"),
]


def normalize_role_key(raw: str) -> str | None:
    """Map a free-form role/column name to a canonical key (be/fe/ai/ba/qc/pm)."""
    if not raw:
        return None
    s = str(raw).strip().lower()
    for canon, pat in _ROLE_PATTERNS:
        if re.search(pat, s):
            return canon
    return None


def rollup(items: list[dict]) -> dict:
    """Aggregate leaf items into per-role totals + man-months.

    Each item must carry numeric ``be/fe/mobile/ai/ba/qc/pm/total`` (as produced
    by :func:`derive_leaf_effort`). Returns effort_by_role, total_mandays and
    total_manmonths. Module/phase grouping is handled by the caller/Excel formulas;
    this is the flat reconciliation used by validators and the propose summary.
    """
    agg = {k: 0.0 for k in ("be", "fe", "mobile", "ai", "ba", "qc", "pm", "total")}
    for it in items:
        for k in agg:
            agg[k] += float(it.get(k, 0) or 0)
    total = _round(agg["total"])
    by_role = {
        "BE": _round(agg["be"]),
        "FE_Mobile": _round(agg["fe"] + agg["mobile"] + agg["ai"]),
        "BA": _round(agg["ba"]),
        "QC": _round(agg["qc"]),
        "PM": _round(agg["pm"]),
    }
    pct = {k: (_round(100 * v / total, 1) if total else 0.0) for k, v in by_role.items()}
    return {
        "total_mandays": total,
        "total_manmonths": _round(total / MANDAYS_PER_MONTH, 2),
        "effort_by_role": by_role,
        "effort_pct_by_role": pct,
    }


def delivery_grid(duration_weeks: int) -> dict:
    """Compute the Delivery-Plan calendar grid from a project duration.

    1 sprint = 2 weeks, 1 month = 4 weeks (2 sprints). Returns the counts the
    Excel builder needs so the Gantt always has ENOUGH month/sprint/week columns
    (the failure mode the template falls into when cloned with a fixed 20 weeks).
    """
    weeks = max(1, int(duration_weeks))
    sprints = (weeks + 1) // 2
    months = (weeks + 3) // 4
    return {"weeks": weeks, "sprints": sprints, "months": months,
            "weeks_per_month": 4, "weeks_per_sprint": 2}
