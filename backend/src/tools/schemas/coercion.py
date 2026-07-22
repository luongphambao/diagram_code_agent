"""CoercingModel — auto-coerces mimo's non-standard Pydantic tool-call outputs."""

from __future__ import annotations

import typing as _t

from pydantic import BaseModel, model_validator


def _wants_structural(ann) -> bool:
    """True if the annotation expects a model/list/dict (not a bare str/number)."""
    for a in _t.get_args(ann) or (ann,):
        origin = _t.get_origin(a) or a
        if origin in (list, dict):
            return True
        if isinstance(origin, type) and issubclass(origin, BaseModel):
            return True
    return False


def _mimo_coerce_before(cls, values):
    """Before-validator: coerce mimo's non-standard outputs to what Pydantic expects.

    Structural coercion (str→json.loads, dict→list, None→[]) is delegated to the
    shared tool_coercion helper; this keeps only the gate-specific extras:
    non-numeric-keyed dict→list fallback and numeric range clamping.
    """
    if not isinstance(values, dict):
        return values
    from tool_coercion import coerce_model_values

    values = coerce_model_values(cls, values)
    for field_name in cls.model_fields:
        if field_name not in values:
            continue
        field = cls.model_fields[field_name]
        val = values[field_name]
        ann = field.annotation
        if ann is None:
            continue
        origin = _t.get_origin(ann)
        if origin is list:
            if isinstance(val, dict):
                values[field_name] = list(val.values())
            continue
        if origin is _t.Union:
            for arg in _t.get_args(ann):
                if _t.get_origin(arg) is list:
                    if isinstance(val, dict):
                        values[field_name] = list(val.values())
                    break
            continue
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            continue
        lo = hi = None
        for m in field.metadata:
            if getattr(m, "ge", None) is not None:
                lo = m.ge
            if getattr(m, "le", None) is not None:
                hi = m.le
        if lo is not None and val < lo:
            values[field_name] = lo
        elif hi is not None and val > hi:
            values[field_name] = hi
    return values


class CoercingModel(BaseModel):
    """BaseModel that auto-coerces dict-with-numeric-string-keys → list for list-typed fields."""

    @model_validator(mode="before")
    @classmethod
    def _coerce_dict_lists(cls, values):
        return _mimo_coerce_before(cls, values)
