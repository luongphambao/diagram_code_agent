"""Provider resolution + LLM construction, keyed off config.yaml's provider map.

Usage
-----
from config import make_llm, resolve_provider
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from .settings import get_config

logger = logging.getLogger(__name__)


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
            timeout=300,
            max_retries=6,
        )

    # OpenAI or OpenAI-compatible (mimo, etc.)
    from langchain_openai import ChatOpenAI

    # Streaming needs a long read window: the raw httpx read timeout is inter-byte
    # and, for endpoints that go fully silent (no SSE keepalives), fires as a bare
    # httpx.ReadTimeout. Do not pass stream_chunk_timeout here: current
    # langchain-openai forwards unknown kwargs to the provider API payload.
    kwargs: dict[str, Any] = dict(
        model=model,
        api_key=api_key,
        timeout=httpx.Timeout(connect=15.0, read=600.0, write=60.0, pool=600.0),
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
