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
MANDAYS_PER_WEEK = 5


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


def pert_percentile(o: float, m: float, p: float, q: float) -> float:
    """PERT normal approximation: mu + q*sigma.

    q=0.0 → P50 (= expected value), q=0.842 → P80.
    Assumes PERT beta distribution; normal approx is standard PM tooling practice.
    """
    mu = (o + 4 * m + p) / 6
    sigma = (p - o) / 6
    return _round(mu + q * sigma)


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


def critical_path(items: list[dict]) -> dict:
    """CPM forward/backward pass over leaf items with optional lag and SS/FF edges.

    Each item's duration is ``item['pert_expected_md']`` when a 3-point estimate was
    supplied (>0), else its derived ``item['total']``. Dependencies are read from
    ``item['dependencies']`` (list of dicts with predecessor_ref/lag_days/relationship)
    when present; falls back to ``item['predecessors']`` (plain ref_code list, FS+lag=0)
    for backwards compatibility. Unknown refs are silently skipped. A dependency cycle
    does NOT raise — the schedule degrades to "no float info" rather than crashing.

    Supported relationship types: FS (Finish-Start), SS (Start-Start), FF (Finish-Finish).

    Returns::

        {"project_duration_md": float,
         "critical_path_ref_codes": [ref_code, ...],
         "items": [{"ref_code", "early_start", "early_finish",
                    "late_start", "late_finish", "float_md", "critical"}, ...]}

    Isolated tasks (no predecessors and no successors) get ``float_md=None`` and
    ``critical=False``.
    """
    nodes = [it for it in items if it.get("ref_code")]
    by_ref = {it["ref_code"]: it for it in nodes}
    dur = {r: (float(it.get("pert_expected_md") or 0) or float(it.get("total") or 0))
           for r, it in by_ref.items()}

    # preds[r] = list of (pred_ref, lag_days, relationship) triples.
    # succs[r] = list of successor ref_codes.
    preds: dict[str, list[tuple[str, float, str]]] = {}
    succs: dict[str, list[str]] = {r: [] for r in by_ref}
    indeg: dict[str, int] = {}
    for r, it in by_ref.items():
        edges: list[tuple[str, float, str]] = []
        deps = it.get("dependencies") or []
        if deps:
            for d in deps:
                p_ref = str(d.get("predecessor_ref", "")).strip()
                if p_ref in by_ref and p_ref != r:
                    lag = float(d.get("lag_days", 0) or 0)
                    rel = str(d.get("relationship", "FS")).upper()
                    if rel not in ("FS", "SS", "FF"):
                        rel = "FS"
                    edges.append((p_ref, lag, rel))
        else:
            # backwards compat: plain predecessors list → FS, lag=0
            for p in (it.get("predecessors") or []):
                p = str(p).strip()
                if p in by_ref and p != r:
                    edges.append((p, 0.0, "FS"))
        preds[r] = edges
        indeg[r] = len(edges)
        for (p, *_) in edges:
            succs[p].append(r)

    def _bare(reason_no_path: bool) -> dict:
        out = [{"ref_code": r, "early_start": None, "early_finish": None,
                "late_start": None, "late_finish": None, "float_md": None,
                "critical": False} for r in by_ref]
        return {"project_duration_md": _round(max(dur.values(), default=0.0)),
                "critical_path_ref_codes": [], "items": out}

    # Kahn topological order.
    queue = [r for r in by_ref if indeg[r] == 0]
    topo: list[str] = []
    rem = dict(indeg)
    while queue:
        r = queue.pop()
        topo.append(r)
        for s in succs[r]:
            rem[s] -= 1
            if rem[s] == 0:
                queue.append(s)
    if len(topo) != len(by_ref):
        return _bare(reason_no_path=True)

    # Forward pass: compute ES/EF per relationship type.
    es: dict[str, float] = {r: 0.0 for r in by_ref}
    ef: dict[str, float] = {r: 0.0 for r in by_ref}
    for r in topo:
        for (p, lag, rel) in preds[r]:
            if rel == "FS":
                es[r] = max(es[r], ef[p] + lag)
            elif rel == "SS":
                es[r] = max(es[r], es[p] + lag)
            elif rel == "FF":
                # j must finish when i finishes: EF(j) >= EF(i)+lag → ES(j) >= EF(i)+lag-dur(j)
                es[r] = max(es[r], ef[p] + lag - dur[r])
        ef[r] = es[r] + dur[r]
    project_ef = max(ef.values(), default=0.0)

    # Backward pass: LF/LS per relationship type.
    # For SS edges: constrains LS(pred), not LF(pred).
    lf: dict[str, float] = {r: project_ef for r in by_ref}
    ls: dict[str, float] = {r: project_ef - dur[r] for r in by_ref}
    for r in reversed(topo):
        lf_cand = project_ef
        ls_cand = project_ef - dur[r]
        for j in succs[r]:
            for (p, lag, rel) in preds[j]:
                if p != r:
                    continue
                if rel == "FS":
                    lf_cand = min(lf_cand, ls[j] - lag)
                elif rel == "FF":
                    lf_cand = min(lf_cand, lf[j] - lag)
                elif rel == "SS":
                    ls_cand = min(ls_cand, ls[j] - lag)
        # SS tightens LS; recompute LF to be consistent.
        lf[r] = min(lf_cand, ls_cand + dur[r])
        ls[r] = lf[r] - dur[r]

    out = []
    crit: list[str] = []
    for it in nodes:
        r = it["ref_code"]
        isolated = not preds[r] and not succs[r]
        flt = None if isolated else _round(ls[r] - es[r])
        is_crit = (flt is not None and flt <= 0.001)
        if is_crit:
            crit.append(r)
        out.append({
            "ref_code": r,
            "early_start": _round(es[r]), "early_finish": _round(ef[r]),
            "late_start": _round(ls[r]), "late_finish": _round(lf[r]),
            "float_md": flt, "critical": is_crit,
        })
    return {"project_duration_md": _round(project_ef),
            "critical_path_ref_codes": crit, "items": out}


def assign_sprints(items: list[dict], peak_dev_fte: float,
                   weeks_per_sprint: int = 2) -> None:
    """Set ``assigned_sprint`` on each item in-place based on its CPM Early Start.

    Converts Early Start (man-days) to a calendar week using ``peak_dev_fte`` and
    ``MANDAYS_PER_WEEK``, then maps the week to a sprint number. Items without
    ``early_start`` (isolated tasks or no PERT data) get ``assigned_sprint=None``.
    Sprint numbering starts at 1.
    """
    import math
    fte = max(0.5, float(peak_dev_fte or 1.0))
    for it in items:
        raw_es = it.get("early_start")
        if raw_es is None:
            it["assigned_sprint"] = None
            continue
        cal_week = float(raw_es) / (fte * MANDAYS_PER_WEEK)
        it["assigned_sprint"] = max(1, math.ceil(cal_week / weeks_per_sprint))


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


def level_resources(
    items: list[dict],
    *,
    role_fte: dict[str, float],
    weeks_per_sprint: int = 2,
    tolerance: float = 0.01,
) -> dict:
    """Check whether CPM-assigned sprints exceed team capacity per role pool.

    Args:
        items: WBS items with ``assigned_sprint`` and per-role MD columns
               (be, fe_mobile, fe, mobile, ai, ba, qc, pm).
        role_fte: staffing assumptions per pool: ``{"dev": x, "ba": y, "qc": z, "pm": w}``.
            BE + FE/Mobile/AI → pool ``dev``; ba/qc/pm map directly.
        weeks_per_sprint: sprint length in weeks (default 2 → 10 MD/FTE).
        tolerance: overflow threshold in MD to avoid floating-point noise.

    Returns a dict with ``by_sprint``, ``capacity``, ``overloads``,
    ``peak_util``, and ``assumptions``. ``overloads`` is a list of
    ``{sprint, role, demand_md, capacity_md, overflow_md}`` dicts.
    """
    cap_per_sprint: dict[str, float] = {
        pool: float(fte) * weeks_per_sprint * MANDAYS_PER_WEEK
        for pool, fte in role_fte.items()
    }

    by_sprint: dict[int, dict[str, float]] = {}
    for it in items:
        sprint = it.get("assigned_sprint")
        if sprint is None:
            continue
        sprint = int(sprint)
        # Collapse BE + FE/Mobile variants into dev pool.
        dev_md = (float(it.get("be", 0) or 0)
                  + float(it.get("fe_mobile", 0) or 0)
                  + float(it.get("fe", 0) or 0)
                  + float(it.get("mobile", 0) or 0)
                  + float(it.get("ai", 0) or 0))
        pool_md: dict[str, float] = {
            "dev": dev_md,
            "ba": float(it.get("ba", 0) or 0),
            "qc": float(it.get("qc", 0) or 0),
            "pm": float(it.get("pm", 0) or 0),
        }
        row = by_sprint.setdefault(sprint, {p: 0.0 for p in role_fte})
        for pool in role_fte:
            row[pool] = _round(row.get(pool, 0.0) + pool_md.get(pool, 0.0))

    overloads: list[dict] = []
    for sprint in sorted(by_sprint):
        for pool, cap in cap_per_sprint.items():
            demand = by_sprint[sprint].get(pool, 0.0)
            if demand > cap + tolerance:
                overloads.append({
                    "sprint": sprint,
                    "role": pool,
                    "demand_md": _round(demand),
                    "capacity_md": _round(cap),
                    "overflow_md": _round(demand - cap),
                })

    peak_util: dict[str, float | None] = {}
    for pool, cap in cap_per_sprint.items():
        if cap > 0 and by_sprint:
            peak_demand = max(by_sprint[s].get(pool, 0.0) for s in by_sprint)
            peak_util[pool] = _round(peak_demand / cap, 3)
        else:
            peak_util[pool] = None

    return {
        "by_sprint": {str(k): v for k, v in sorted(by_sprint.items())},
        "capacity": {pool: _round(cap) for pool, cap in cap_per_sprint.items()},
        "overloads": overloads,
        "peak_util": peak_util,
        "assumptions": dict(role_fte),
    }
