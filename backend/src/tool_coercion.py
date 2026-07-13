"""Generic tool-argument coercion for providers that emit malformed tool calls.

mimo-v2.5 frequently sends list/dict tool arguments as JSON-encoded *strings*
(``queries='["vpn","azure"]'``, ``ratios='{"ba_on_dev":0.1}'``) or as
numeric-keyed dicts (``{"0": ..., "1": ...}``).  Pydantic rejects these, the
error ToolMessage echoes the full kwargs back into context, and the model
retries — burning both the per-agent call limit and tokens (LangSmith traces
2026-07-04 showed this across icon_resolver, drawer and wbs_planner).

Gate tools already had a per-model workaround (``analysis_tools.CoercingModel``)
but plain ``@tool`` tools and the deepagents filesystem built-ins had none.
``ToolArgCoercionMiddleware`` closes that gap for EVERY tool of EVERY agent:

- str → ``json.loads`` when the schema wants a list/dict/BaseModel and the
  parsed value actually matches (never parses fields annotated ``str``);
- numeric-keyed dict → ordered list for list fields;
- ``None`` → ``[]`` for list fields;
- recursive through ``Optional``/``Union``, ``list[Model]`` and nested models;
- per-tool defaults for known built-in slips (``ls`` without ``path``);
- rewrites tool-invocation error ToolMessages to a compact corrective form
  (no kwargs echo — the default template re-sends the whole arg blob).

Strictly a no-op for well-formed arguments.
"""

from __future__ import annotations

import json
import logging
import re
import typing as _t

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Missing-required-arg defaults for deepagents built-ins mimo trips over.
_TOOL_ARG_DEFAULTS: dict[str, dict] = {
    "ls": {"path": "/"},
}

_MAX_ERROR_CHARS = 800
_INVOCATION_ERROR_RE = re.compile(
    r"Error invoking tool '(?P<name>[^']+)' with kwargs .*? with error:\n(?P<error>.*)",
    re.DOTALL,
)


def _maybe_json(value: str):
    """Parse a string that looks like a list/dict container; None if not one.

    Tries strict JSON first, then a Python-literal fallback (``ast.literal_eval``) so
    a model that emits a single-quoted repr — ``"{'BE': 490}"`` — still coerces to a
    real dict instead of surviving as a string. A raw string reaching the frontend is
    what turned the WBS "Effort by Role" chips into per-character garbage
    (``Object.entries("...")`` iterates characters).
    """
    s = value.strip()
    if not s or s[0] not in "[{":
        return None
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        pass
    try:
        import ast
        parsed = ast.literal_eval(s)
        return parsed if isinstance(parsed, (list, dict)) else None
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None


def _numeric_dict_to_list(value: dict) -> list | None:
    keys = list(value.keys())
    if keys and all(str(k).isdigit() for k in keys):
        return [value[k] for k in sorted(value, key=lambda x: int(x))]
    return None


def _coerce_value(value, ann):
    """Recursively coerce *value* toward annotation *ann*. Returns value unchanged
    when it already fits or when no safe coercion applies."""
    if ann is None or ann is _t.Any:
        return value
    origin = _t.get_origin(ann)
    if origin is None and ann in (list, dict, tuple, set):
        origin = ann  # bare `list` / `dict` annotation (no type params)

    if origin is _t.Union:  # includes Optional[...]
        if value is None:
            return value  # Optional accepts None as-is
        args = [a for a in _t.get_args(ann) if a is not type(None)]
        for a in args:
            coerced = _coerce_value(value, a)
            if coerced is not value:
                return coerced
        return value

    if origin in (list, tuple, set):
        item_args = _t.get_args(ann)
        item_ann = item_args[0] if item_args else None
        if value is None:
            return []
        if isinstance(value, str):
            parsed = _maybe_json(value)
            if isinstance(parsed, (list, dict)):
                value = parsed
        if isinstance(value, dict):
            as_list = _numeric_dict_to_list(value)
            value = as_list if as_list is not None else list(value.values())
        if isinstance(value, list) and item_ann is not None:
            return [_coerce_value(v, item_ann) for v in value]
        return value

    if origin is dict:
        if isinstance(value, str):
            parsed = _maybe_json(value)
            if isinstance(parsed, dict):
                return parsed
        return value

    if isinstance(ann, type) and issubclass(ann, BaseModel):
        if isinstance(value, str):
            parsed = _maybe_json(value)
            if isinstance(parsed, dict):
                value = parsed
        if isinstance(value, dict):
            return coerce_model_values(ann, dict(value))
        return value

    return value


def coerce_model_values(cls: type[BaseModel], values):
    """Coerce a values-dict toward *cls*'s field annotations.

    Usable directly as the body of a ``model_validator(mode="before")`` —
    ``wbs_tools._CoercingModel`` and ``analysis_tools`` delegate here so the
    str→json branch exists in one place.
    """
    if not isinstance(values, dict):
        return values
    for name, field in cls.model_fields.items():
        if name not in values or field.annotation is None:
            continue
        values[name] = _coerce_value(values[name], field.annotation)
    return values


def _coerce_for_json_schema(schema: dict, args: dict) -> dict:
    props = schema.get("properties") or {}
    for name, spec in props.items():
        if name not in args or not isinstance(spec, dict):
            continue
        want = spec.get("type")
        val = args[name]
        if want == "array":
            if isinstance(val, str):
                parsed = _maybe_json(val)
                if isinstance(parsed, list):
                    args[name] = parsed
            elif isinstance(val, dict):
                as_list = _numeric_dict_to_list(val)
                if as_list is not None:
                    args[name] = as_list
        elif want == "object" and isinstance(val, str):
            parsed = _maybe_json(val)
            if isinstance(parsed, dict):
                args[name] = parsed
    return args


def coerce_args(args: dict, schema) -> dict:
    """Coerce a tool-call args dict against the tool's args_schema.

    *schema* may be a Pydantic model class, a JSON-schema dict, or None.
    Always returns a (possibly new) dict; never raises.
    """
    try:
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            return coerce_model_values(schema, dict(args))
        if isinstance(schema, dict):
            return _coerce_for_json_schema(schema, dict(args))
    except Exception:
        logger.debug("coerce_args failed; passing args through", exc_info=True)
    return args


def _required_fields(schema) -> list[str] | None:
    """Required field names for *schema* (Pydantic model class or JSON-schema dict)."""
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return [name for name, field in schema.model_fields.items() if field.is_required()]
    if isinstance(schema, dict):
        req = schema.get("required")
        if isinstance(req, list):
            return list(req)
    return None


def compact_invocation_error(text: str, schema=None, args: dict | None = None) -> str | None:
    """Rewrite the default tool-invocation error (which echoes the full kwargs
    blob) to a short corrective message. Returns None if *text* isn't one.

    When *schema* is given and EVERY required field is absent from *args* (the
    model called the tool with empty/near-empty args rather than a shape
    mistake), a distinct message names the missing fields and tells the model
    to copy the values from context instead of retrying blind — this is the
    "resolve_finding() with no args, 4 times in a row" failure mode, which the
    generic structural-mismatch message below doesn't address.
    """
    m = _INVOCATION_ERROR_RE.match(text)
    if not m:
        return None
    name = m.group("name")

    required = _required_fields(schema)
    if required:
        present = set((args or {}).keys())
        missing = [f for f in required if f not in present]
        if missing and len(missing) == len(required):
            return (
                f"Tool '{name}' was called with no usable arguments — every required "
                f"field is missing: {', '.join(required)}. Copy the exact values from "
                "the most recent relevant tool output above (e.g. the SF-xxxx id from "
                "CROSS-ARTIFACT CHECK) — do not guess, invent, or retry with empty "
                "args again. Call the tool again with every required field set."
            )

    error = " ".join(m.group("error").split())
    if len(error) > _MAX_ERROR_CHARS:
        error = error[:_MAX_ERROR_CHARS] + "..."
    return (
        f"Tool '{name}' argument validation failed: {error}\n"
        "Fix ONLY the invalid fields and call the tool again. Pass lists and "
        "objects as real JSON types (e.g. [\"a\",\"b\"]), never as quoted strings."
    )


class ToolArgCoercionMiddleware(AgentMiddleware):
    """Coerce malformed tool-call args before validation, for every tool.

    Runs in the ToolNode wrap chain, so it covers custom tools AND deepagents
    built-ins (ls/read_file/task/...). Uses ``request.override`` (mutating the
    request is deprecated in langgraph)."""

    name = "ToolArgCoercionMiddleware"

    def _coerced_request(self, request):
        tc = request.tool_call
        name = tc.get("name", "")
        args = tc.get("args")

        if isinstance(args, str):  # whole-args-as-string slip
            parsed = _maybe_json(args)
            args = parsed if isinstance(parsed, dict) else None
        if not isinstance(args, dict):
            args = {} if args is None else None
        if args is None:
            return request

        tool = request.tool
        schema = getattr(tool, "args_schema", None) if tool is not None else None
        new_args = coerce_args(args, schema)

        defaults = _TOOL_ARG_DEFAULTS.get(name)
        if defaults:
            for key, val in defaults.items():
                new_args.setdefault(key, val)

        if new_args == tc.get("args"):
            return request
        logger.info("ToolArgCoercionMiddleware: coerced args for tool %s", name)
        return request.override(tool_call={**tc, "args": new_args})

    @staticmethod
    def _compacted(result):
        if (
            isinstance(result, ToolMessage)
            and getattr(result, "status", None) == "error"
            and isinstance(result.content, str)
        ):
            compact = compact_invocation_error(result.content)
            if compact is not None:
                return result.model_copy(update={"content": compact})
        return result

    def wrap_tool_call(self, request, handler):
        return self._compacted(handler(self._coerced_request(request)))

    async def awrap_tool_call(self, request, handler):
        return self._compacted(await handler(self._coerced_request(request)))
