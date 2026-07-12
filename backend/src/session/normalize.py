"""Array-coercion + blueprint/tech-stack shape normalization for provider quirks."""

from __future__ import annotations


def _coerce_list(val) -> list:
    """Coerce an array-typed field into a list.

    Some models (e.g. mimo) emit array-typed fields as plain objects with
    numeric string keys ({"0": ..., "1": ...}) instead of JSON arrays.
    """
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return list(val.values())
    return []


_BRIEF_ARRAY_FIELDS = ("analysis_signals", "stakeholders", "functional_requirements",
                       "non_functional_requirements", "layout_constraints", "assumptions")


def _coerce_brief(d) -> dict:
    if not isinstance(d, dict):
        return d
    result = dict(d)
    for field in _BRIEF_ARRAY_FIELDS:
        if field in result:
            result[field] = _coerce_list(result[field])
    return result


_ASSUMPTION_ARRAY_FIELDS = ("confirm_with_customer", "compliance")


def _coerce_assumptions(a):
    if not isinstance(a, dict):
        return a
    result = dict(a)
    for field in _ASSUMPTION_ARRAY_FIELDS:
        if field in result:
            result[field] = _coerce_list(result[field])
    return result


def _normalize_blueprint(bp) -> dict:
    if not isinstance(bp, dict):
        return bp or {}
    result = dict(bp)
    _ARRAY_FIELDS = ("nodes", "clusters", "edges", "key_decisions", "nfr_mapping",
                     "analysis_signals", "stakeholders", "functional_requirements",
                     "non_functional_requirements", "layout_constraints", "assumptions")
    for field in _ARRAY_FIELDS:
        val = result.get(field)
        if isinstance(val, dict):
            result[field] = list(val.values())
        elif val is None:
            result[field] = []
    return result


def _normalize_tech_stack(ts) -> dict:
    """Normalize the model's tech_stack into {layer: {choice, rationale, alternatives, ...}}.

    Tolerates list-of-layer-dicts, flat dict-by-layer, and the wrapped
    {layers: {...}, assumptions: ...} shape stored in the workspace.
    """
    _LAYER_FIELDS = ("choice", "rationale", "cost_tier", "decision_criteria", "alternatives",
                     "estimated_monthly_cost_usd", "capacity_sizing", "performance_target", "risks")
    out: dict = {}
    if isinstance(ts, dict) and "layers" in ts:
        ts = ts["layers"]
    if isinstance(ts, list):
        for item in ts:
            if isinstance(item, dict) and item.get("layer"):
                layer_data = {f: item.get(f) for f in _LAYER_FIELDS}
                layer_data["alternatives"] = _coerce_list(layer_data.get("alternatives"))
                layer_data["risks"] = _coerce_list(layer_data.get("risks"))
                out[item["layer"]] = layer_data
    elif isinstance(ts, dict):
        for layer, info in ts.items():
            if isinstance(info, dict):
                layer_data = {f: info.get(f) for f in _LAYER_FIELDS}
                layer_data["alternatives"] = _coerce_list(layer_data.get("alternatives"))
                layer_data["risks"] = _coerce_list(layer_data.get("risks"))
                out[layer] = layer_data
            else:
                out[layer] = {"choice": str(info), "rationale": "", "cost_tier": None,
                              "decision_criteria": None, "alternatives": [],
                              "estimated_monthly_cost_usd": None, "capacity_sizing": "",
                              "performance_target": "", "risks": []}
    return out
