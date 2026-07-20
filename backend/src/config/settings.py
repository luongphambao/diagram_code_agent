"""config.yaml loading + advisory per-stage cost budgets.

Usage
-----
from config import get_model, stage_budget_cents
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# backend/src/config/settings.py → parents[2] == backend/
_CONFIG_FILE = Path(__file__).resolve().parents[2] / "config.yaml"

_cfg: dict | None = None


def _load() -> dict:
    if not _CONFIG_FILE.exists():
        logger.warning("config.yaml not found at %s — using defaults", _CONFIG_FILE)
        return {}
    try:
        import yaml  # pyyaml
    except ImportError:
        logger.error("pyyaml is not installed; run: pip install pyyaml")
        return {}
    with open(_CONFIG_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    logger.info("Loaded model config from %s", _CONFIG_FILE)
    return data


def get_config() -> dict:
    global _cfg
    if _cfg is None:
        _cfg = _load()
    return _cfg


def reload_config() -> None:
    """Force a reload of config.yaml (useful in tests or hot-reload scenarios)."""
    global _cfg
    _cfg = None
    get_config()


def get_model(role: str, fallback: str = "mimo-v2.5") -> str:
    """Return the configured model name for *role*, or *fallback* if not set."""
    return get_config().get("models", {}).get(role) or fallback


# ---------------------------------------------------------------------------
# Per-stage cost budget (advisory — not a hard block at this tier).
# Set to 0 to disable.  Values are in USD cents (1 = $0.01).
# Override via environment variables of the same name.
# ---------------------------------------------------------------------------

def _budget_cents(stage: str, default: int) -> int:
    """Return the advisory budget in USD cents for *stage*."""
    return int(os.getenv(f"STAGE_BUDGET_USDCENT_{stage.upper()}", default))


STAGE_BUDGETS_USDCENT: dict[str, int] = {
    "intake":     _budget_cents("INTAKE",     50),   # $0.50
    "blueprint":  _budget_cents("BLUEPRINT",  100),  # $1.00
    "wbs":        _budget_cents("WBS",        100),  # $1.00
    "ppt":        _budget_cents("PPT",        100),  # $1.00
    "research":   _budget_cents("RESEARCH",   50),   # $0.50
}


def stage_budget_cents(stage: str) -> int:
    """Return the advisory cost budget in USD cents for *stage* (0 = unlimited)."""
    return STAGE_BUDGETS_USDCENT.get(stage.lower(), 0)
