"""Model & provider configuration loaded from backend/config.yaml.

Usage
-----
from config import get_model, make_llm

llm = make_llm(get_model("main", fallback="mimo-v2.5"))
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# backend/src/config.py → parents[1] == backend/
_CONFIG_FILE = Path(__file__).resolve().parents[1] / "config.yaml"

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


def resolve_provider(model: str) -> tuple[str, dict[str, Any]]:
    """Return (provider_name, provider_cfg) for *model* based on its name prefix."""
    cfg = get_config()
    prefixes: dict = cfg.get("model_prefixes", {})
    providers: dict = cfg.get("providers", {})

    for prefix, pname in prefixes.items():
        if model.lower().startswith(prefix.lower()):
            return pname, providers.get(pname, {})

    logger.warning("No provider prefix matched model %r — defaulting to openai", model)
    return "openai", providers.get("openai", {})


def get_system_prompt_prefix(model: str) -> str:
    """Return a prefix to prepend to every system prompt for *model* (e.g. language instruction)."""
    _, pcfg = resolve_provider(model)
    return pcfg.get("system_prompt_prefix", "")


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


def vision_in_tools(model: str) -> bool:
    """Return True if the provider for *model* accepts image blocks in tool messages."""
    _, pcfg = resolve_provider(model)
    return bool(pcfg.get("vision_in_tools", True))


def supports_structured_output(model: str) -> bool:
    """Return True if the provider for *model* supports LangChain's structured-output
    methods (function_calling / json_schema).

    Some OpenAI-compatible endpoints (e.g. mimo) reject these with "Unsupported
    function" or ignore the schema in json_mode. LLMToolSelectorMiddleware relies
    on ``with_structured_output`` — when the main model can't honour it, tool
    selection returns off-task free text (no ``tools`` key → KeyError) and the
    model stops calling tools. Gate the selector on this flag. Defaults to True.
    """
    _, pcfg = resolve_provider(model)
    return bool(pcfg.get("supports_structured_output", True))


def make_llm(model: str):
    """Build a LangChain chat LLM for *model* using provider config from config.yaml."""
    provider_name, pcfg = resolve_provider(model)
    api_key_env = pcfg.get("api_key_env", "OPENAI_API_KEY")
    api_key = os.getenv(api_key_env)

    if not api_key:
        logger.warning(
            "API key env var %r is not set (required for model %r / provider %r)",
            api_key_env, model, provider_name,
        )

    if provider_name == "anthropic":
        from langchain_anthropic import ChatAnthropic

        max_tokens: int = int(pcfg.get("max_tokens", 16000))
        return ChatAnthropic(
            model=model,
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=0,
            timeout=90,
            max_retries=6,
        )

    # OpenAI or OpenAI-compatible (mimo, etc.)
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = dict(
        model=model,
        api_key=api_key,
        timeout=90,
        max_retries=6,
    )

    base_url = pcfg.get("base_url")
    if base_url:
        kwargs["base_url"] = base_url

    reasoning_effort = pcfg.get("reasoning_effort")
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort

    if pcfg.get("use_responses_api"):
        kwargs["use_responses_api"] = True

    logger.debug("make_llm  model=%s  provider=%s  base_url=%s", model, provider_name, base_url)
    return ChatOpenAI(**kwargs)
