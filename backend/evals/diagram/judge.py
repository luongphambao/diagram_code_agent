"""Two-layer eval judge for rendered diagrams.

Layer 1 — Structural F1: compares the produced blueprint (nodes/edges/clusters)
against the golden expected lists.  Deterministic, cheap, no LLM needed.

Layer 2 — Vision judge: calls the LLM with the rendered PNG + a rubric and
returns a JSON score.  Requires a vision-capable model.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("eval.judge")

# ---------------------------------------------------------------------------
# Layer 1: Structural F1
# ---------------------------------------------------------------------------

def _normalize(label: str) -> str:
    """Lower-case, strip punctuation for fuzzy label matching."""
    return label.lower().replace("-", "").replace("_", "").replace(" ", "")


def _soft_match(produced: list[str], expected: list[str]) -> tuple[int, int, int]:
    """Return (true_positives, false_positives, false_negatives) via substring match."""
    norm_produced = [_normalize(p) for p in produced]
    norm_expected = [_normalize(e) for e in expected]
    tp = sum(
        1 for e in norm_expected
        if any(e in p or p in e for p in norm_produced)
    )
    fp = len(norm_produced) - tp
    fn = len(norm_expected) - tp
    return tp, max(fp, 0), max(fn, 0)


def _f1(tp: int, fp: int, fn: int) -> float:
    if tp + fp + fn == 0:
        return 1.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def structural_f1(blueprint: dict | None, golden: dict) -> dict:
    """Compare produced blueprint against the golden case.

    Returns a dict with per-dimension F1 scores and an aggregate micro-F1.
    """
    if blueprint is None:
        return {
            "node_f1": 0.0, "edge_f1": 0.0, "cluster_f1": 0.0,
            "micro_f1": 0.0, "details": "no blueprint produced",
        }

    # Nodes
    produced_nodes = [n.get("label", n.get("id", "")) for n in (blueprint.get("nodes") or [])]
    expected_nodes = golden.get("expected_nodes", [])
    n_tp, n_fp, n_fn = _soft_match(produced_nodes, expected_nodes)

    # Edges: match as "from→to" strings
    produced_edges = [
        f"{e.get('from', e.get('from_', ''))}→{e.get('to', '')}"
        for e in (blueprint.get("edges") or [])
    ]
    expected_edges = [
        f"{e.get('from', '')}→{e.get('to', '')}"
        for e in golden.get("expected_edges", [])
    ]
    e_tp, e_fp, e_fn = _soft_match(produced_edges, expected_edges)

    # Clusters
    produced_clusters = [c.get("label", c.get("id", "")) for c in (blueprint.get("clusters") or [])]
    expected_clusters = golden.get("expected_clusters", [])
    c_tp, c_fp, c_fn = _soft_match(produced_clusters, expected_clusters)

    # Micro F1 (pool all counts)
    total_tp = n_tp + e_tp + c_tp
    total_fp = n_fp + e_fp + c_fp
    total_fn = n_fn + e_fn + c_fn

    result = {
        "node_f1": round(_f1(n_tp, n_fp, n_fn), 4),
        "edge_f1": round(_f1(e_tp, e_fp, e_fn), 4),
        "cluster_f1": round(_f1(c_tp, c_fp, c_fn), 4),
        "micro_f1": round(_f1(total_tp, total_fp, total_fn), 4),
        "produced_nodes": len(produced_nodes),
        "expected_nodes": len(expected_nodes),
        "produced_edges": len(produced_edges),
        "expected_edges": len(expected_edges),
        "produced_clusters": len(produced_clusters),
        "expected_clusters": len(expected_clusters),
    }

    # Minimum-count checks from the golden case.
    min_nodes = golden.get("min_nodes", 0)
    min_edges = golden.get("min_edges", 0)
    min_clusters = golden.get("min_clusters", 0)
    result["min_nodes_ok"] = len(produced_nodes) >= min_nodes
    result["min_edges_ok"] = len(produced_edges) >= min_edges
    result["min_clusters_ok"] = len(produced_clusters) >= min_clusters

    # --- Phase 1/2 quality rubric checks (structural, no LLM) ---
    pillar_coverage = blueprint.get("pillar_coverage") or {}
    if isinstance(pillar_coverage, dict) and pillar_coverage:
        pillar_names = [
            "operational_excellence", "security", "reliability",
            "performance_efficiency", "cost_optimization", "sustainability",
        ]
        covered_pillars = 0
        for pname in pillar_names:
            pdata = pillar_coverage.get(pname, {})
            if isinstance(pdata, dict) and (pdata.get("addressed_by") or pdata.get("gaps")):
                covered_pillars += 1
        result["pillar_coverage_count"] = covered_pillars
        result["pillar_coverage_pct"] = round(covered_pillars / len(pillar_names), 4)
        result["pillar_coverage_nontrivial"] = covered_pillars >= 4
    else:
        result["pillar_coverage_count"] = 0
        result["pillar_coverage_pct"] = 0.0
        result["pillar_coverage_nontrivial"] = False

    nfr_mapping = blueprint.get("nfr_mapping") or []
    result["nfr_mapping_count"] = len(nfr_mapping) if isinstance(nfr_mapping, list) else 0
    result["nfr_mapping_nontrivial"] = result["nfr_mapping_count"] >= 2

    # --- Sublabel coverage (% of nodes with non-empty tech field) ---
    nodes = blueprint.get("nodes") or []
    density = blueprint.get("density", "standard")
    nodes_with_tech = sum(
        1 for n in nodes
        if isinstance(n, dict) and n.get("tech", "").strip()
    )
    result["sublabel_coverage"] = round(nodes_with_tech / len(nodes), 4) if nodes else 1.0
    result["sublabel_coverage_nontrivial"] = (
        result["sublabel_coverage"] >= 0.8
        if density in ("detailed", "poster")
        else True  # not required for standard density
    )

    # --- Panel fill (from out.slide.json if available) ---
    slide_json_path = golden.get("slide_json_path")
    if slide_json_path:
        try:
            slide_data = json.loads(Path(slide_json_path).read_text(encoding="utf-8"))
            fill_pct = slide_data.get("layout", {}).get("panel_fill_pct")
            if fill_pct is not None:
                result["panel_fill_pct"] = round(fill_pct, 4)
                result["panel_fill_ok"] = fill_pct >= 0.65
        except Exception:  # noqa: BLE001
            pass

    return result


# ---------------------------------------------------------------------------
# Layer 2: Vision judge
# ---------------------------------------------------------------------------

_VISION_RUBRIC = """\
You are an expert architecture diagram reviewer. Evaluate the rendered diagram
image on the following rubric. Return ONLY valid JSON — no markdown fences.

Rubric dimensions (score 0.0–1.0 each):
1. completeness     — Are all major components visible? No obvious missing tiers.
2. readability      — Is the layout clean? Edges short and non-crossing, labels legible.
3. icon_quality     — Do nodes show real provider icons (not blank boxes)?
4. cluster_layout   — Are nodes grouped into labeled tier clusters? No floating boxes.
5. legend_quality   — Does the diagram have a legend that explains EVERY edge style and color
                       used? 1.0 = complete legend present, 0.5 = partial legend, 0.0 = missing.
                       Score 1.0 if only one edge style is used (no legend needed).
6. boundary_clarity — Are security/network boundaries (VPC, subnet, trust zone) clearly
                       visible when security concerns are implied? 1.0 = clearly shown,
                       0.5 = partially shown, 0.0 = missing when expected.
7. visual_density   — Does the diagram body fill the slide panel well, with appropriately
                       sized nodes? 1.0 = body fills the panel and nodes show tech detail
                       (sublabels visible); 0.5 = body fills about half the panel or nodes
                       show only titles; 0.0 = tiny diagram floating in large whitespace,
                       or no tech detail visible on any node.
8. overall          — Your holistic quality score.

Required JSON schema:
{
  "completeness":     <float 0-1>,
  "readability":      <float 0-1>,
  "icon_quality":     <float 0-1>,
  "cluster_layout":   <float 0-1>,
  "legend_quality":   <float 0-1>,
  "boundary_clarity": <float 0-1>,
  "visual_density":   <float 0-1>,
  "overall":          <float 0-1>,
  "reasoning":        "<1-2 sentence justification>"
}

Diagram context: {context}
"""


def vision_judge(png_path: str | Path, context: str, model: str) -> dict:
    """Call the LLM vision judge on a rendered PNG.

    Returns a dict matching the rubric JSON schema above, plus an 'error' key
    on failure.
    """
    try:
        from openai import OpenAI
    except ImportError:
        return {"error": "openai not installed"}

    png = Path(png_path)
    if not png.exists():
        return {"error": f"PNG not found: png_path"}

    b64 = base64.standard_b64encode(png.read_bytes()).decode("ascii")
    prompt = _VISION_RUBRIC.format(context=context)

    client = OpenAI()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }
            ],
            temperature=0,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("vision_judge failed: %s", exc)
        return {"error": str(exc)}
