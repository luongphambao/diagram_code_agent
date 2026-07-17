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

try:
    from .topology import build_drawio_from_spec
    from .layout_plan import TARGET_RATIO
except (ImportError, ValueError):  # pragma: no cover - import fallback
    from prettygraph.native.topology import build_drawio_from_spec  # type: ignore
    from prettygraph.native.layout_plan import TARGET_RATIO  # type: ignore

_MAX_CANDIDATES = 6


def semantic_stats(spec: dict, xml: str, plan: dict | None = None) -> dict:
    """Semantic preservation stats with bundle-aware edge accounting.

    A bundle-suppressed edge is intentionally absent (its representative
    carries the meaning) — only (s,t) pairs whose EVERY parallel edge was
    suppressed leave the expectation set.
    """
    from domain.validation.validate_drawio import check_semantic_preservation
    sup = {tuple(x) for x in (plan or {}).get("suppressed_edges", [])}
    edges = spec.get("edges", [])
    kept_pairs = {(e.get("from"), e.get("to")) for e in edges
                  if (e.get("from"), e.get("to"), e.get("label") or "") not in sup}
    src_nodes = [n.get("id") for n in spec.get("nodes", [])]
    src_edges = [(e.get("from"), e.get("to")) for e in edges
                 if (e.get("from"), e.get("to")) in kept_pairs]
    _, sem = check_semantic_preservation(src_nodes, src_edges, xml)
    if sup:
        sem["bundled_edges"] = len(sup)
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


def _variants_for(plan: dict | None, spec: dict,
                  baseline_metrics: dict) -> list[tuple[str, dict | None]]:
    """Rule-gated plan variants — only build what the baseline's symptoms call
    for (each candidate costs a full engine build; typical case adds 0-2)."""
    if not plan:
        return []
    out: list[tuple[str, dict | None]] = []
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
    return out[:_MAX_CANDIDATES - 2]


def _rank_key(res: dict) -> tuple:
    sc, m = res["scorecard"], res["metrics"]
    ratio = m.get("ratio")
    ratio_dist = abs((ratio if ratio is not None else TARGET_RATIO) - TARGET_RATIO)
    return (-sc["total"], m.get("edge_crossings") or 0, ratio_dist)


def auto_repair(spec: dict, name: str, plan: dict | None) -> tuple[dict | None, dict]:
    """Try plan variants, keep the best-scoring one.

    Returns ``(winning_plan, engineer_report)``. Never raises on a candidate
    failure — a candidate that errors is simply dropped (the baselines are
    built first, so there is always a result).
    """
    iterations = []
    results: list[tuple[str, dict | None, dict]] = []

    def _try(label: str, cand: dict | None) -> dict | None:
        try:
            res = _score_candidate(spec, name, cand)
        except Exception as exc:  # noqa: BLE001 — drop broken candidates
            iterations.append({"candidate": label, "error": str(exc)[:200]})
            return None
        results.append((label, cand, res))
        iterations.append({
            "candidate": label,
            "score": res["scorecard"]["total"],
            "pass": res["scorecard"]["pass"],
            "ratio": res["metrics"].get("ratio"),
            "crossings": res["metrics"].get("edge_crossings"),
            "collisions": res["scorecard"].get("collisions"),
        })
        return res

    baseline = _try("planned", plan)
    # A passing baseline needs no repair — skip the extra builds entirely.
    if baseline and not baseline["scorecard"]["pass"]:
        if plan is not None:
            _try("unplanned", None)
        for label, cand in _variants_for(plan, spec, baseline["metrics"]
                                         | {"collisions": baseline["scorecard"]["collisions"]}):
            if len(results) >= _MAX_CANDIDATES:
                break
            _try(label, cand)
    if not results:
        return plan, {"iterations": iterations, "chosen": "planned",
                      "final_score": None}
    label, best_plan, best = min(results, key=lambda r: _rank_key(r[2]))
    from domain.validation.validate_drawio import PRODUCTION_TARGET
    report = {
        "iterations": iterations,
        "chosen": label,
        "final_score": best["scorecard"]["total"],
        "final_pass": best["scorecard"]["pass"],
        "target": PRODUCTION_TARGET,
    }
    return best_plan, report
