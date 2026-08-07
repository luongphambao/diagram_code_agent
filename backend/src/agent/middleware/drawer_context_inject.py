"""Embeds pre-computed workspace files into the drawer's task dispatch message."""

from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware

from backends import current_workspace

# render_spec.json/icon_plan.json/style_plan.json/label_fits.json are all
# pre-computed code-side (propose_blueprint -> write_style_and_fit_plans,
# _preseed_icon_plan) before drawer ever runs, and are bounded in size (a
# diagram is capped at ~48 nodes). If one somehow grows past this, skip
# embedding it rather than risk bloating the dispatch message itself — drawer
# still has read_file as a fallback.
_MAX_EMBED_CHARS = 20_000
# Hard ceiling on the whole injected block, independent of the per-file cap
# above. Without this, adding more optional files to _FILES silently scales
# the dispatch message injected on EVERY task(drawer) call (re-sent each of
# up to _DRAWER_CALL_LIMIT calls) — this caps that regardless of how many
# files are listed below.
_MAX_TOTAL_EMBED_CHARS = 60_000

_FILES = (
    "render_spec.json",
    "icon_plan.json",
    "style_plan.json",
    "label_fits.json",
    # Prior-round feedback (§ engineer loop). Injecting these turns "critic
    # finding reaches the drawer via the main model correctly transcribing it
    # into free-text prose" into "reaches the drawer by code" — round 2 of a
    # fresh drawer task (each task() call is a brand-new agent, see
    # prompts/_blocks.py) previously had NO way to know what round 1 already
    # tried short of the main agent's paraphrase. Harmless when absent (a
    # first-ever draw has none of these yet) — _read_workspace_file returns
    # None and the block is simply skipped for that file.
    "critique.json",
    "engineer_report.json",
    # quality_history.json deliberately NOT included: it's append-only
    # (tools/stage_markers.append_quality_history) and never trimmed, so it
    # grows unbounded across a long session. The _MAX_EMBED_CHARS per-file
    # cap only protects against a single oversized read, not against slowly
    # crossing that cap round after round and flipping between "included" and
    # "skipped" — drawer can still read_file() it directly if it needs
    # history, same fallback as any file that trips the per-file cap.
)


def _read_workspace_file(name: str) -> str | None:
    path = current_workspace() / name
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if len(text) > _MAX_EMBED_CHARS:
        return None
    return text


def _build_context_block() -> str:
    parts = []
    budget = _MAX_TOTAL_EMBED_CHARS
    for name in _FILES:
        content = _read_workspace_file(name)
        if content is None:
            continue
        chunk = f"\n\n--- {name} (already on disk, use the content below) ---\n{content}"
        if len(chunk) > budget:
            # Stop rather than truncate mid-JSON — a partial file is worse
            # than no file (drawer would parse garbage); it can still
            # read_file() this one directly.
            break
        parts.append(chunk)
        budget -= len(chunk)
    if not parts:
        return ""
    return (
        "\n\nThe following workspace files are already computed and included "
        "below verbatim — do NOT read_file() them again, use this content "
        "directly:" + "".join(parts)
    )


class DrawerContextInjectMiddleware(AgentMiddleware):
    """Append pre-computed workspace files to every `task(subagent_type="drawer")`
    dispatch, so drawer doesn't spend model calls `read_file`-ing files main
    already has on disk.

    A real trace showed drawer making 12 read_file + 4 grep + 3 ls + 2 glob
    calls (21 filesystem calls) across only 3 render rounds — ~2x its own
    "≤12 model calls" budget — much of it re-fetching render_spec.json/
    icon_plan.json/style_plan.json/label_fits.json, which the prompt already
    says to read "once" but the model doesn't reliably follow. Embedding them
    directly in the dispatch message removes the round trip (and the
    temptation to re-read them on a later revision round) instead of relying
    on prose alone.
    """

    name = "DrawerContextInjectMiddleware"

    @staticmethod
    def _augmented_request(request):
        tc = request.tool_call
        if tc.get("name") != "task":
            return request
        args = tc.get("args") or {}
        if args.get("subagent_type") != "drawer":
            return request
        block = _build_context_block()
        if not block:
            return request
        modified_call = {
            **tc,
            "args": {**args, "description": str(args.get("description") or "") + block},
        }
        return request.override(tool_call=modified_call)

    def wrap_tool_call(self, request, handler):
        return handler(self._augmented_request(request))

    async def awrap_tool_call(self, request, handler):
        return await handler(self._augmented_request(request))
