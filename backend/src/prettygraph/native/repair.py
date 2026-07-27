"""Deterministic auto-repair: the 0-token tier of the engineer loop.

After the layout plan is computed, this module builds a small, rule-bounded
set of candidate layouts (plan variants — column counts, bundling on/off,
no-plan baseline), scores each candidate's STANDALONE body with
``validate_xml`` + ``production_scorecard`` (no temp files, no PNG renders
during the search), and returns the winning plan. The unplanned baseline is
always a candidate, so the loop can never deliver worse than today's build.

The chosen plan + per-candidate scores land in ``engineer_report.json`` so
the drawer/critic (and the human at the finalize gate) can see what the
engineer tried and why the winner won.
"""

from __future__ import annotations

import copy
import json

try:
    from .topology import build_drawio_from_spec
    from .layout_plan import TARGET_RATIO
except (ImportError, ValueError):  # pragma: no cover - import fallback
    from prettygraph.native.topology import build_drawio_from_spec  # type: ignore
    from prettygraph.native.layout_plan import TARGET_RATIO  # type: ignore

# NOTE: kept at 6, NOT raised, despite an earlier plan to try 8-10. Measured:
# build_drawio_from_spec on a realistic ~40-node spec (the system's practical
# per-diagram ceiling — see agent/middleware/drawer_context_inject.py's "~48
# nodes" comment) takes ~3.4s (icon preset) to ~7s (refined preset) PER BUILD —
# not the sub-150ms this budget assumed. Each round of auto_repair is meant to
# be the free 0-token tier; multiplying that cost by a higher cap would turn a
# "free" repair pass into a multi-minute one for exactly the large diagrams
# most likely to need repair. The multi-round restructuring below (§3.1) does
# NOT raise the total candidates tried — it only changes which candidates fill
# this same budget (variants of the current best each round, not just the
# original baseline's symptoms), so the worst-case latency ceiling is
# unchanged from before this change.
_MAX_CANDIDATES = 6
_MAX_ROUNDS = 2

# --------------------------------------------------------------------------- #
# Cross-thread "which knob tends to win" memory (§3.4). Read-only influence on
# TRY ORDER within a round — it can only affect which subset of variants gets
# scored before _MAX_CANDIDATES is hit, never which one wins among those tried
# (that's always _rank_key, untouched) and never whether the baselines
# ("planned"/"unplanned", always scored first) are skipped. A stale or empty
# file degrades to today's behavior (original generation order), so this can
# only help, never hurt, output quality.
# --------------------------------------------------------------------------- #

_LAYOUT_WINS_FILE = "layout_wins.json"
_LAYOUT_WINS_MAX_SIGNATURES = 200


def _bucket(n: int, edges: tuple[int, ...]) -> str:
    for e in edges:
        if n <= e:
            return f"<={e}"
    return f">{edges[-1]}"


def _spec_signature(spec: dict, plan: dict | None) -> str:
    """Cheap, stable key grouping similarly-shaped specs for the layout-wins
    memory — style_preset + bucketed node/edge counts + band count + whether
    there's a sidebar (cross-cutting cluster). Reuses band_order/sidebar_roots
    already computed on ``plan`` rather than re-deriving cluster topology."""
    preset = str(spec.get("style_preset") or "icon").lower()
    n_nodes = _bucket(len(spec.get("nodes") or []), (10, 20, 30, 48))
    n_edges = _bucket(len(spec.get("edges") or []), (10, 20, 40, 80))
    n_bands = len((plan or {}).get("band_order") or [])
    has_sidebar = bool((plan or {}).get("sidebar_roots"))
    return f"{preset}|nodes{n_nodes}|edges{n_edges}|bands{n_bands}|sidebar{int(has_sidebar)}"


def _load_layout_wins() -> dict:
    try:
        from backends import MEMORIES_DIR

        return json.loads((MEMORIES_DIR / _LAYOUT_WINS_FILE).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — missing/corrupt file just means no ranking hint
        return {}


def _record_layout_win(signature: str, label: str, score: float) -> None:
    """Best-effort: never raises, never blocks the repair result on I/O."""
    try:
        from backends import MEMORIES_DIR

        path = MEMORIES_DIR / _LAYOUT_WINS_FILE
        data = _load_layout_wins()
        bucket = data.setdefault(signature, {})
        entry = bucket.setdefault(label, {"wins": 0, "avg_score": score})
        n = int(entry.get("wins", 0))
        entry["avg_score"] = (float(entry.get("avg_score", score)) * n + score) / (n + 1)
        entry["wins"] = n + 1
        if len(data) > _LAYOUT_WINS_MAX_SIGNATURES:
            # Drop the signature with the fewest total wins recorded — the
            # least-established bucket, not necessarily the oldest, since this
            # file carries no timestamps (repo convention: avoid argless
            # datetime.now() so results stay reproducible across the codebase).
            stalest = min(data, key=lambda k: sum(v.get("wins", 0) for v in data[k].values()))
            if stalest != signature:
                data.pop(stalest, None)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _order_by_past_wins(
    signature: str, variants: list[tuple[str, dict | None]]
) -> list[tuple[str, dict | None]]:
    """Stable-sort variants so labels that have won before (for this spec
    shape) are tried first — ties (no history) keep the original order."""
    wins = _load_layout_wins().get(signature, {})
    if not wins:
        return variants
    return sorted(variants, key=lambda lc: -int(wins.get(lc[0], {}).get("wins", 0)))


def semantic_stats(spec: dict, xml: str, plan: dict | None = None) -> dict:
    """Semantic preservation stats with bundle-aware edge accounting.

    A bundle-suppressed edge is intentionally absent (its representative
    carries the meaning) — only (s,t) pairs whose EVERY parallel edge was
    suppressed leave the expectation set.

    Also runs the spec-level semantic gates (I1-I4: orphan components,
    relationship density, weak primary-path labels, icon-family mixing —
    see domain.validation.semantic_gates) and stashes their findings here so
    validate_xml can fold `hard` ones into its `errors` list. These MUST run
    on the spec, not the rendered XML — see semantic_gates.py's module
    docstring for why gating post-bundling produces false orphans.
    """
    from domain.validation.semantic_gates import audit_spec_semantics
    from domain.validation.validate_drawio import check_semantic_preservation

    sup = {tuple(x) for x in (plan or {}).get("suppressed_edges", [])}
    edges = spec.get("edges", [])
    kept_pairs = {
        (e.get("from"), e.get("to"))
        for e in edges
        if (e.get("from"), e.get("to"), e.get("label") or "") not in sup
    }
    src_nodes = [n.get("id") for n in spec.get("nodes", [])]
    src_edges = [(e.get("from"), e.get("to")) for e in edges if (e.get("from"), e.get("to")) in kept_pairs]
    _, sem = check_semantic_preservation(src_nodes, src_edges, xml)
    if sup:
        sem["bundled_edges"] = len(sup)
    try:
        gate_findings = audit_spec_semantics(spec, plan)
    except Exception:  # noqa: BLE001 — a gate bug must never block a render
        gate_findings = []
    sem["gate_findings"] = [
        {"code": f.code, "message": f.message, "severity": f.severity, "ids": f.ids} for f in gate_findings
    ]
    return sem


def _score_candidate(spec: dict, name: str, plan: dict | None) -> dict:
    from domain.validation.validate_drawio import validate_xml, production_scorecard

    xml, stats = build_drawio_from_spec(spec, name, flat=False, plan=plan)
    stats["semantic"] = semantic_stats(spec, xml, plan)
    report = validate_xml(xml, stats=stats)
    sc = production_scorecard(report, stats)
    m = report.get("layout_metrics") or {}
    return {"scorecard": sc, "metrics": m, "stats": stats}


def _wrappable_bands(plan: dict, spec: dict) -> list[str]:
    counts: dict[str, int] = {}
    cluster_root: dict[str, str] = {}
    clusters = {c["id"]: c for c in spec.get("clusters", []) if c.get("id")}
    for cid in clusters:
        cur, seen = cid, set()
        while cur in clusters and cur not in seen:
            seen.add(cur)
            pid = clusters[cur].get("parent")
            if not pid or pid not in clusters or pid == cur:
                break
            cur = pid
        cluster_root[cid] = cur
    for n in spec.get("nodes", []):
        r = cluster_root.get(n.get("cluster") or "")
        if r and r in (plan.get("band_order") or []):
            counts[r] = counts.get(r, 0) + 1
    return [cid for cid, n in counts.items() if n >= 4]


def _arrow_metrics(metrics: dict) -> dict:
    return metrics.get("arrow_clarity") or {}


def _arrow_poor(metrics: dict) -> bool:
    arrow = _arrow_metrics(metrics)
    if not arrow:
        return False
    return (
        float(arrow.get("arrow_clarity_score", 100.0)) < 75.0
        or float(arrow.get("crossings_per_edge", 0.0)) > 0.30
        or float(arrow.get("long_edge_ratio", 0.0)) > 0.15
        or int(arrow.get("edge_label_overlaps", 0)) > 0
    )


def _variants_for(plan: dict | None, spec: dict, baseline_metrics: dict) -> list[tuple[str, dict | None]]:
    """Rule-gated plan variants — only build what the baseline's symptoms call
    for (each candidate costs a full engine build; typical case adds 0-2)."""
    if not plan:
        return []
    out: list[tuple[str, dict | None]] = []
    is_refined = str(spec.get("style_preset") or "").lower() == "refined"

    aggressive_plan: dict | None = None
    if _arrow_poor(baseline_metrics) and not plan.get("aggressive_bundles"):
        try:
            from .layout_plan import analyze_layout
        except (ImportError, ValueError):  # pragma: no cover - import fallback
            from prettygraph.native.layout_plan import analyze_layout  # type: ignore
        aggressive_plan = analyze_layout(spec, aggressive_bundles=True)
        out.append(("aggressive-bundles", aggressive_plan))

    if is_refined:
        # The refined page template ignores band_cols — its knobs are zones
        # per main row and whether the ops shelves pack across the full
        # content width. Collect each symptom-triggered knob's candidate
        # value(s) first (single-knob variants below, unchanged labels/
        # behavior), THEN generate combos of up to 2 knobs whose OWN symptom
        # fired together — replacing what used to be a single hardcoded pair
        # (aggressive-bundles + zpr4) tried regardless of whether the ratio
        # symptom zpr4 addresses had actually fired.
        ratio = baseline_metrics.get("ratio")
        cur_zpr = int(plan.get("refined_zones_per_row") or 6)
        # knob -> (base plan to patch onto, [(label, value), ...]). aggressive_bundles
        # patches onto aggressive_plan (already re-analyzed with aggressive_bundles=
        # True, so its own bundling/suppression is recomputed) rather than a bare
        # flag flip on `plan`, mirroring what the old hardcoded combo did.
        knobs: dict[str, tuple[dict, list[tuple[str, object]]]] = {}
        if aggressive_plan is not None:
            knobs["aggressive_bundles"] = (aggressive_plan, [("aggressive-bundles", True)])
        if ratio is not None and ratio > 2.1:
            zpr_opts = [(f"zpr{zpr}", zpr) for zpr in (4, 5) if zpr < cur_zpr]
            if zpr_opts:
                knobs["refined_zones_per_row"] = (plan, zpr_opts)
        elif ratio is not None and ratio < 1.5 and cur_zpr < 6:
            knobs["refined_zones_per_row"] = (plan, [("zpr6", 6)])
        if (baseline_metrics.get("page_fill") or 1.0) < 0.5:
            knobs["refined_ops_pack"] = (
                plan,
                [("ops-pack-toggle", not plan.get("refined_ops_pack", True))],
            )

        for knob, (base, options) in knobs.items():
            if knob == "aggressive_bundles":
                continue  # already appended as the plain "aggressive-bundles" candidate above
            for label, value in options:
                v = copy.deepcopy(base)
                v[knob] = value
                out.append((label, v))

        knob_names = list(knobs.keys())
        for i in range(len(knob_names)):
            for j in range(i + 1, len(knob_names)):
                k1, k2 = knob_names[i], knob_names[j]
                base = aggressive_plan if "aggressive_bundles" in (k1, k2) else plan
                for label1, val1 in knobs[k1][1]:
                    for label2, val2 in knobs[k2][1]:
                        v = copy.deepcopy(base)
                        v[k1] = val1
                        v[k2] = val2
                        out.append((f"{label1}+{label2}", v))
        return out[: _MAX_CANDIDATES - 2]
    if _arrow_poor(baseline_metrics):
        # band_order is the single biggest lever on crossing count, but was
        # never varied here before — only bundling/column knobs. Refined
        # skips this (early-returned above): it uses zone rows, not band
        # order, for its layout. analyze_layout recomputes bundling/band_cols
        # consistently for the alternate order (see its band_order_rank note
        # for why patching plan["band_order"] alone would be unsafe).
        try:
            from .layout_plan import analyze_layout as _analyze_layout_rank
        except (ImportError, ValueError):  # pragma: no cover - import fallback
            from prettygraph.native.layout_plan import analyze_layout as _analyze_layout_rank  # type: ignore
        alt = _analyze_layout_rank(
            spec, aggressive_bundles=bool(plan.get("aggressive_bundles")), band_order_rank=1
        )
        if alt.get("band_order") != plan.get("band_order"):
            out.append(("band-order-2", alt))
    lo, hi = 1.3, 1.9
    ratio = baseline_metrics.get("ratio")
    wrappable = _wrappable_bands(plan, spec)
    if ratio is not None and ratio > hi and wrappable:
        # Too wide: force-wrap dense bands into grids (narrower, taller).
        for cols in (3, 4):
            if plan.get("band_cols", {}) != {c: cols for c in wrappable}:
                v = copy.deepcopy(plan)
                v["band_cols"] = {c: cols for c in wrappable}
                out.append((f"cols{cols}", v))
    elif ratio is not None and ratio < lo and plan.get("band_cols"):
        # Too tall: undo forced wrapping so bands spread horizontally again.
        v = copy.deepcopy(plan)
        v["band_cols"] = {}
        out.append(("no-cols", v))
    if (baseline_metrics.get("collisions") or 0) > 0 and plan.get("band_cols"):
        v = copy.deepcopy(plan)
        v["band_cols"] = {c: max(2, n - 1) for c, n in plan["band_cols"].items()}
        if v["band_cols"] != plan.get("band_cols"):
            out.append(("fewer-cols", v))
    return out[: _MAX_CANDIDATES - 2]


def _rank_key(res: dict) -> tuple:
    sc, m = res["scorecard"], res["metrics"]
    arrow = _arrow_metrics(m)
    ratio = m.get("ratio")
    ratio_dist = abs((ratio if ratio is not None else TARGET_RATIO) - TARGET_RATIO)
    return (
        -sc["total"],
        -float(arrow.get("arrow_clarity_score", 100.0)),
        m.get("edge_crossings") or 0,
        ratio_dist,
    )


def _plan_key(cand: dict | None) -> str:
    """Stable identity for a candidate plan, used to avoid re-scoring (and
    re-paying the multi-second build cost of) a plan already tried this call."""
    return json.dumps(cand, sort_keys=True) if cand is not None else "\x00unplanned"


def auto_repair(spec: dict, name: str, plan: dict | None) -> tuple[dict | None, dict]:
    """Try plan variants across up to ``_MAX_ROUNDS`` rounds, keep the best-scoring one.

    Round 1 tries the baselines ("planned" + "unplanned") plus symptom-gated
    variants of the ORIGINAL plan. If the best candidate so far still doesn't
    pass, round 2+ generates a FRESH set of variants from THAT winner's own
    remaining symptoms — e.g. a round-1 fix for arrow clarity that leaves the
    ratio off-target gets a round-2 ratio fix on top of it, instead of the
    search stopping after one hill-climbing pass. This never raises the total
    number of candidates tried (still capped at ``_MAX_CANDIDATES`` overall —
    see the module-level comment on why that cap stays at 6), it only changes
    which candidates fill that same budget.

    Returns ``(winning_plan, engineer_report)``. Never raises on a candidate
    failure — a candidate that errors is simply dropped (the baselines are
    built first, so there is always a result).
    """
    iterations = []
    results: list[tuple[str, dict | None, dict]] = []
    tried: set[str] = set()

    def _try(label: str, cand: dict | None) -> dict | None:
        key = _plan_key(cand)
        if key in tried:
            return None
        tried.add(key)
        try:
            res = _score_candidate(spec, name, cand)
        except Exception as exc:  # noqa: BLE001 — drop broken candidates
            iterations.append({"candidate": label, "error": str(exc)[:200]})
            return None
        results.append((label, cand, res))
        iterations.append(
            {
                "candidate": label,
                "score": res["scorecard"]["total"],
                "pass": res["scorecard"]["pass"],
                "ratio": res["metrics"].get("ratio"),
                "crossings": res["metrics"].get("edge_crossings"),
                "arrow_clarity_score": _arrow_metrics(res["metrics"]).get("arrow_clarity_score"),
                "visible_edge_count": _arrow_metrics(res["metrics"]).get("visible_edge_count"),
                "bundled_edge_count": _arrow_metrics(res["metrics"]).get("bundled_edge_count"),
                "crossings_per_edge": _arrow_metrics(res["metrics"]).get("crossings_per_edge"),
                "collisions": res["scorecard"].get("collisions"),
            }
        )
        return res

    signature = _spec_signature(spec, plan)
    baseline = _try("planned", plan)
    # A passing baseline needs no repair — skip the extra builds entirely.
    if baseline and not baseline["scorecard"]["pass"]:
        if plan is not None:
            _try("unplanned", None)
        cur_plan, cur_res = plan, baseline
        for _round in range(_MAX_ROUNDS):
            if len(results) >= _MAX_CANDIDATES or cur_res["scorecard"]["pass"]:
                break
            variants = _variants_for(
                cur_plan, spec, cur_res["metrics"] | {"collisions": cur_res["scorecard"]["collisions"]}
            )
            fresh = [(label, cand) for label, cand in variants if _plan_key(cand) not in tried]
            if not fresh:
                break  # this winner has nothing new left to try — converged
            # Try previously-winning knobs (for this spec shape) first, so a
            # historically-good fix is more likely to make it in before the
            # candidate budget runs out. Pure ordering hint — see the module
            # note above on why this can only help, never hurt.
            fresh = _order_by_past_wins(signature, fresh)
            for label, cand in fresh:
                if len(results) >= _MAX_CANDIDATES:
                    break
                _try(label, cand)
            # Re-derive the current best from ALL results so far (not just this
            # round) so the next round's variants are generated from whichever
            # candidate is actually winning, not just this round's newest try.
            _, cur_plan, cur_res = min(results, key=lambda r: _rank_key(r[2]))
    if not results:
        return plan, {"iterations": iterations, "chosen": "planned", "final_score": None}
    label, best_plan, best = min(results, key=lambda r: _rank_key(r[2]))
    from domain.validation.validate_drawio import PRODUCTION_TARGET

    report = {
        "iterations": iterations,
        "chosen": label,
        "final_score": best["scorecard"]["total"],
        "final_pass": best["scorecard"]["pass"],
        "target": PRODUCTION_TARGET,
    }
    _record_layout_win(signature, label, best["scorecard"]["total"])
    return best_plan, report
