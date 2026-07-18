"""BPMN Tier-1 swimlane domain layer — ported from drawio-ai-kit/src/bpmn.mjs.

Thin creators over the generic layout engine: each returns a {"kind":"box"}
node carrying its mxgraph.bpmn catalog style + {lane, col} cell tags. The
pool() primitive (layout_engine.py) places them in a sparse (lane x col)
grid; ``phases`` is an optional milestone-label overlay.

Canonical monochrome (white fill, neutral stroke); red accent for blocker end
events (error/cancel/terminate). Plain Task and collapsed Sub-process have no
stencil and are composed as rounded rects (mirrors the kit exactly).
"""

from __future__ import annotations

from .layout_engine import pool  # re-exported for callers, mirrors bpmn.mjs

try:
    from ..drawio_catalog import load_catalog as _load_catalog, get_icon as _get_icon
except (ImportError, ValueError):  # pragma: no cover - import fallback
    from domain.diagram.drawio_catalog import (  # type: ignore
        load_catalog as _load_catalog, get_icon as _get_icon)

__all__ = ["BPMN", "pool", "start", "intermediate", "end", "gateway",
           "user_task", "service_task", "manual_task", "script_task",
           "business_rule_task", "task", "sub_process"]

# Style tokens — canonical BPMN look (white fill, neutral stroke), red for
# error/cancel/terminate.
BPMN = {"fill": "#FFFFFF", "stroke": "#232F3E", "red": "#D90000",
        "task_w": 110, "task_h": 56}


def _look(name: str) -> dict:
    cat = _load_catalog()
    entry = _get_icon(cat, name)
    if not entry or not entry.get("style"):
        raise KeyError(f'BPMN shape not in catalog: "{name}" — verify with search_icon.')
    return entry


def _stencil(id: str, name: str, *, lane: int = 0, col: int = 0, label: str = "") -> dict:
    """A stenciled flow object (event/gateway/typed-task) placed in a pool cell."""
    s = _look(name)
    return {"kind": "box", "id": id, "lane": lane, "col": col, "label": label or "",
            "w": s.get("width", 40), "h": s.get("height", 40), "style": s["style"]}


# ---- events (circles; label renders below the shape via the catalog style) ---- #

def start(id: str, *, type: str = "none", lane: int = 0, col: int = 0, label: str = "") -> dict:
    """Start event. type: "none" (default) | "message" | "timer"."""
    return _stencil(id, f"bpmn_start_{type}", lane=lane, col=col, label=label)


def intermediate(id: str, *, type: str = "message", lane: int = 0, col: int = 0,
                 label: str = "") -> dict:
    """Intermediate event. type: "message" (default) | "timer" | "link"."""
    return _stencil(id, f"bpmn_intermediate_{type}", lane=lane, col=col, label=label)


def end(id: str, *, type: str = "none", lane: int = 0, col: int = 0, label: str = "") -> dict:
    """End event. type: "none" (default) | "terminate" | "error" | "cancel"
    (last three render red)."""
    return _stencil(id, f"bpmn_end_{type}", lane=lane, col=col, label=label)


# ---- gateways (diamonds; label below) ---- #

def gateway(id: str, *, type: str = "exclusive", lane: int = 0, col: int = 0,
           label: str = "") -> dict:
    """Gateway. type: "exclusive" (XOR, default) | "parallel" (AND) |
    "inclusive" (OR) | "event"."""
    return _stencil(id, f"bpmn_gateway_{type}", lane=lane, col=col, label=label)


# ---- activities (rounded rects; label centered inside) ---- #

def user_task(id: str, *, lane: int = 0, col: int = 0, label: str = "") -> dict:
    return _stencil(id, "bpmn_task_user", lane=lane, col=col, label=label)


def service_task(id: str, *, lane: int = 0, col: int = 0, label: str = "") -> dict:
    return _stencil(id, "bpmn_task_service", lane=lane, col=col, label=label)


def manual_task(id: str, *, lane: int = 0, col: int = 0, label: str = "") -> dict:
    return _stencil(id, "bpmn_task_manual", lane=lane, col=col, label=label)


def script_task(id: str, *, lane: int = 0, col: int = 0, label: str = "") -> dict:
    return _stencil(id, "bpmn_task_script", lane=lane, col=col, label=label)


def business_rule_task(id: str, *, lane: int = 0, col: int = 0, label: str = "") -> dict:
    return _stencil(id, "bpmn_task_business_rule", lane=lane, col=col, label=label)


def task(id: str, *, lane: int = 0, col: int = 0, label: str = "") -> dict:
    """Plain (untyped) Task — a marker-less rounded rectangle (canonical BPMN
    rendering); no stencil (composed, not looked up)."""
    return {"kind": "box", "id": id, "lane": lane, "col": col, "label": label or "",
            "w": BPMN["task_w"], "h": BPMN["task_h"],
            "fill": BPMN["fill"], "stroke": BPMN["stroke"], "round": True}


def sub_process(id: str, *, lane: int = 0, col: int = 0, label: str = "") -> dict:
    """Collapsed Sub-process — rounded rectangle, slightly larger than a Task.
    The bottom-center "+" marker is deferred (Tier-2); distinguish from a Task
    by naming ("Sub-process: ...") until the marker ships."""
    return {"kind": "box", "id": id, "lane": lane, "col": col, "label": label or "",
            "w": BPMN["task_w"] + 10, "h": BPMN["task_h"] + 14,
            "fill": BPMN["fill"], "stroke": BPMN["stroke"], "round": True}
