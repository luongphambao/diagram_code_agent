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


_BRIEF_ARRAY_FIELDS = (
    "analysis_signals",
    "stakeholders",
    "functional_requirements",
    "non_functional_requirements",
    "layout_constraints",
    "assumptions",
)


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
    result["monthly_budget_range_usd"] = _normalize_cost_range(result.get("monthly_budget_range_usd"))
    return result


def _normalize_cost_range(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        n = max(0, int(value))
        return {"min_usd": n, "max_usd": n}
    if isinstance(value, str):
        import re

        text = value.strip()
        if not text:
            return None
        numbers: list[int] = []
        for raw, suffix in re.findall(r"(\d+(?:\.\d+)?)\s*([kKmM]?)", text.replace(",", "")):
            n = float(raw)
            if suffix.lower() == "k":
                n *= 1_000
            elif suffix.lower() == "m":
                n *= 1_000_000
            numbers.append(max(0, int(n)))
        if numbers:
            return {"min_usd": min(numbers), "max_usd": max(numbers)}
        return None
    if not isinstance(value, dict):
        return value
    result = dict(value)
    if "min_usd" not in result and "min" in result:
        result["min_usd"] = result.get("min")
    if "max_usd" not in result and "max" in result:
        result["max_usd"] = result.get("max")
    return result


def _normalize_blueprint(bp) -> dict:
    if not isinstance(bp, dict):
        return bp or {}
    result = dict(bp)
    _ARRAY_FIELDS = (
        "nodes",
        "clusters",
        "edges",
        "key_decisions",
        "nfr_mapping",
        "analysis_signals",
        "stakeholders",
        "functional_requirements",
        "non_functional_requirements",
        "layout_constraints",
        "assumptions",
    )
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
    _LAYER_FIELDS = (
        "choice",
        "rationale",
        "cost_tier",
        "decision_criteria",
        "alternatives",
        "estimated_monthly_cost_usd",
        "capacity_sizing",
        "performance_target",
        "risks",
    )
    out: dict = {}
    if isinstance(ts, dict) and "layers" in ts:
        ts = ts["layers"]
    if isinstance(ts, list):
        for item in ts:
            if isinstance(item, dict) and item.get("layer"):
                layer_data = {f: item.get(f) for f in _LAYER_FIELDS}
                layer_data["alternatives"] = _coerce_list(layer_data.get("alternatives"))
                layer_data["risks"] = _coerce_list(layer_data.get("risks"))
                layer_data["estimated_monthly_cost_usd"] = _normalize_cost_range(
                    layer_data.get("estimated_monthly_cost_usd")
                )
                out[item["layer"]] = layer_data
    elif isinstance(ts, dict):
        for layer, info in ts.items():
            if isinstance(info, dict):
                layer_data = {f: info.get(f) for f in _LAYER_FIELDS}
                layer_data["alternatives"] = _coerce_list(layer_data.get("alternatives"))
                layer_data["risks"] = _coerce_list(layer_data.get("risks"))
                layer_data["estimated_monthly_cost_usd"] = _normalize_cost_range(
                    layer_data.get("estimated_monthly_cost_usd")
                )
                out[layer] = layer_data
            else:
                out[layer] = {
                    "choice": str(info),
                    "rationale": "",
                    "cost_tier": None,
                    "decision_criteria": None,
                    "alternatives": [],
                    "estimated_monthly_cost_usd": None,
                    "capacity_sizing": "",
                    "performance_target": "",
                    "risks": [],
                }
    return out


def _sum_layer_costs(ts: dict) -> dict | None:
    """Deterministic sum of every layer's ``estimated_monthly_cost_usd`` — never trust
    an LLM-asserted total (improvement plan §C: tech-stack cost fix). The model was
    free to state any total_monthly_cost figure independent of what it wrote per layer,
    and routinely did — a plausible-looking number that silently didn't match summing
    its own per-layer estimates. Returns None when no layer has a cost estimate (there
    is nothing to sum, not "$0/mo").
    """
    mins: list[int] = []
    maxs: list[int] = []
    for layer in (ts or {}).values():
        cost = (layer or {}).get("estimated_monthly_cost_usd")
        if isinstance(cost, dict) and cost.get("min_usd") is not None and cost.get("max_usd") is not None:
            mins.append(cost["min_usd"])
            maxs.append(cost["max_usd"])
    if not mins:
        return None
    return {"min_usd": sum(mins), "max_usd": sum(maxs)}
