"""Process-global deepagents harness-profile tuning: summarization backstop and
the general-purpose-subagent kill switch."""

from __future__ import annotations


def _register_tuned_summarization_profiles() -> None:
    """Tune deepagents' bundled SummarizationMiddleware for the models we use.

    create_deep_agent() always adds a SummarizationMiddleware safety net
    (compute_summarization_defaults). Every model we use (mimo-v2.5, gpt-5.4-mini)
    is built via ChatOpenAI (config.make_llm) — including mimo, which is an
    OpenAI-compatible endpoint reached through ChatOpenAI with a custom base_url —
    so `model.profile` is empty for both and the fallback branch kicks in:
    trigger=("tokens", 170_000), keep=("messages", 6). Since ClearToolUsesEdit
    (agent/middleware, CONTEXT_TRIGGER_TOKENS=30_000) already keeps the working
    set well under 170K tokens, that fallback almost never fires — it isn't the
    "long-run safety net" the module comment above assumes, just dead weight.
    Register a profile so it actually engages as a backstop once ClearToolUsesEdit
    alone isn't enough (e.g. a stuck drawer render-refine loop), well above
    CONTEXT_TRIGGER_TOKENS so it doesn't fire on every normal run.

    HarnessProfile keys are `provider:identifier`, where the provider comes from
    the *LangChain class*'s `_get_ls_params()["ls_provider"]` — for ChatOpenAI
    this is always "openai", regardless of a custom base_url — so both roles key
    under "openai:<model-name>", not "mimo:<model-name>".
    """
    from deepagents import HarnessProfile, register_harness_profile
    from deepagents.middleware.summarization import SummarizationMiddleware

    def _tuned_summarizer(model_str: str):
        def factory():
            from backends import make_local_backend
            from config import make_llm

            return [
                SummarizationMiddleware(
                    model=make_llm(model_str),
                    backend=make_local_backend(),
                    trigger=("tokens", 60_000),
                    keep=("messages", 12),
                )
            ]

        return factory

    for model_str in ("mimo-v2.5", "gpt-5.4-mini"):
        register_harness_profile(
            f"openai:{model_str}",
            HarnessProfile(
                excluded_middleware={"SummarizationMiddleware"},
                extra_middleware=_tuned_summarizer(model_str),
            ),
        )


_register_tuned_summarization_profiles()


def _set_general_purpose_enabled(enabled: bool, model_strs: set[str]) -> None:
    """Toggle deepagents' auto-added "general-purpose" subagent per model key.

    create_deep_agent() silently adds a "general-purpose" subagent (plus the
    SubAgentMiddleware `task` tool) to every agent that doesn't already define
    one. For worker subagents (icon_resolver/drawer/critic/ppt_generator) that
    tool is an unintended escape hatch: a failed render once led the drawer to
    retry via task(general-purpose) three times, each a stateless nested agent
    with no call limit — 1.66M tokens (42%) of a single 4M-token run.

    Harness profiles are keyed per provider:model and the registry is
    process-global, so per-agent behavior requires toggling around each
    create_deep_agent call in build_agent (profiles are read at build time,
    and register_harness_profile merges field-wise with incoming values
    winning). build_agent runs once at server startup, so the toggling is not
    a concurrency concern.
    """
    from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, register_harness_profile

    for model_str in model_strs:
        register_harness_profile(
            f"openai:{model_str}",
            HarnessProfile(
                general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=enabled),
            ),
        )
