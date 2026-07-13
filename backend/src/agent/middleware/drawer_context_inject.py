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

_FILES = ("render_spec.json", "icon_plan.json", "style_plan.json", "label_fits.json")


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
    for name in _FILES:
        content = _read_workspace_file(name)
        if content is None:
            continue
        parts.append(f"\n\n--- {name} (already on disk, use the content below) ---\n{content}")
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
