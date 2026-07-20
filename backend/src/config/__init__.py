"""Model & provider configuration loaded from backend/config.yaml.

Usage
-----
from config import get_model, make_llm

llm = make_llm(get_model("main", fallback="mimo-v2.5"))
"""

from .models import (
    get_system_prompt_prefix,
    make_llm,
    resolve_provider,
    supports_structured_output,
    vision_in_tools,
)
from .settings import (
    STAGE_BUDGETS_USDCENT,
    get_config,
    get_model,
    reload_config,
    stage_budget_cents,
)

__all__ = [
    "STAGE_BUDGETS_USDCENT",
    "get_config",
    "get_model",
    "get_system_prompt_prefix",
    "make_llm",
    "reload_config",
    "resolve_provider",
    "stage_budget_cents",
    "supports_structured_output",
    "vision_in_tools",
]
