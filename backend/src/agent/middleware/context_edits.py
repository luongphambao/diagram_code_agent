"""Context-editing edits run inside ``ContextEditingMiddleware``: image handling,
tool-text sanitization, and gate-arg offloading.

ORDERING CONTRACT (enforced by tests/test_middleware_order.py — do not reorder
without updating that test): ``KeepLatestImagesEdit`` MUST run before
``InjectVisionAsUserEdit`` — it reduces the ToolMessage history down to a single
live image before the relay edit scans for images to relay. See
``InjectVisionAsUserEdit``'s docstring for why.
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.messages import AnyMessage, AIMessage, HumanMessage
from langchain_core.messages import ToolMessage as LCToolMessage

_IMAGE_TOOLS = frozenset({"render_diagram", "inspect_diagram"})


class KeepLatestImagesEdit:
    """Strip image blocks from all render/inspect ToolMessages except the most recent.

    count_tokens_approximately counts images as a flat 85 tokens regardless of size,
    so image accumulation is invisible to ClearToolUsesEdit.  This edit removes the
    base64 payload from every image-bearing ToolMessage except the last one, replacing
    each image block with a lightweight sentinel.  Runs unconditionally (no token
    threshold) so it applies on every model call.
    """

    _STRIPPED = {"type": "text", "text": "[image cleared — see latest render]"}

    def apply(self, messages: list[AnyMessage], *, count_tokens: Any) -> None:
        image_indices: list[int] = []
        for i, msg in enumerate(messages):
            if not isinstance(msg, LCToolMessage):
                continue
            if getattr(msg, "name", None) not in _IMAGE_TOOLS:
                continue
            content = msg.content
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "image" for b in content
            ):
                image_indices.append(i)

        # Keep the last one; strip the rest.
        for idx in image_indices[:-1]:
            msg = messages[idx]
            old = msg.content if isinstance(msg.content, list) else [msg.content]
            new_content = [
                self._STRIPPED if (isinstance(b, dict) and b.get("type") == "image") else b
                for b in old
            ]
            messages[idx] = msg.model_copy(update={"content": new_content})


class InjectVisionAsUserEdit:
    """Relay PNG images from tool messages into a follow-up user message.

    Some providers (e.g. mimo-v2.5) reject image blocks in tool messages with
    400: 'text' is not set, even though they accept images in user messages.
    This edit strips image blocks from render_diagram/inspect_diagram ToolMessages
    and injects a synthetic HumanMessage immediately after each one, so the model
    can still see the rendered PNG via the user-message path.

    Old relay messages (marked with _SENTINEL) are removed on every apply() call
    before new ones are injected — belt-and-suspenders cleanup; in practice edits
    are ephemeral (re-applied to a fresh copy of persisted history on every model
    call, never written back), so a prior call's relay message is never actually
    present here.

    Depends on KeepLatestImagesEdit running FIRST in _middleware()'s edits list:
    that edit trims the persisted ToolMessage history down to a single live image
    before this edit runs, so this edit only ever finds and relays that one image.
    If this edit ran first instead, it would relay every historical render/inspect
    image on every call (unbounded payload growth). Do not reorder without
    updating this note.
    """

    _SENTINEL = "[VISION_RELAY]"
    _MAX_B64_CHARS = int(os.getenv("VISION_RELAY_MAX_B64_CHARS", "1500000"))
    _INCLUDE_BLOCK_TEXT = os.getenv("MIMO_IMAGE_BLOCK_TEXT", "").strip().lower() in ("1", "true", "yes")

    def apply(self, messages: list[AnyMessage], *, count_tokens: Any) -> None:
        # Remove previously injected relay messages.
        i = 0
        while i < len(messages):
            msg = messages[i]
            if isinstance(msg, HumanMessage):
                c = msg.content
                is_relay = (
                    (isinstance(c, str) and c.startswith(self._SENTINEL))
                    or (
                        isinstance(c, list)
                        and any(
                            isinstance(b, dict) and str(b.get("text", "")).startswith(self._SENTINEL)
                            for b in c
                        )
                    )
                )
                if is_relay:
                    messages.pop(i)
                    continue
            i += 1

        # Strip images from ToolMessages and inject relay HumanMessages.
        # Iterate in reverse so insert() indices stay valid.
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if not isinstance(msg, LCToolMessage):
                continue
            if getattr(msg, "name", None) not in _IMAGE_TOOLS:
                continue
            content = msg.content
            if not isinstance(content, list):
                continue

            image_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "image"]
            if not image_blocks:
                continue

            # Strip image blocks from ToolMessage, keep text.
            text_only = [b for b in content if not (isinstance(b, dict) and b.get("type") == "image")]
            messages[i] = msg.model_copy(update={"content": text_only or "[rendered]"})

            # Build relay HumanMessage with image_url blocks (user-message format).
            relay_content: list = [{"type": "text", "text": self._SENTINEL + " Rendered diagram image:"}]
            for block in image_blocks:
                b64 = block.get("base64", "")
                mime = block.get("mime_type", "image/png")
                # An empty/oversized payload produces a guaranteed-corrupt data
                # URL — mimo rejects the whole request with 400 "Multimodal data
                # is corrupted" and the agent burns retries. Skip with a note.
                if not b64:
                    relay_content.append({
                        "type": "text",
                        "text": "[image unavailable — render produced no preview; "
                                "rely on the layout audit text]",
                    })
                    continue
                if len(b64) > self._MAX_B64_CHARS:
                    relay_content.append({
                        "type": "text",
                        "text": "[image too large to relay — rely on the layout "
                                "audit text]",
                    })
                    continue
                img_block: dict = {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                }
                if self._INCLUDE_BLOCK_TEXT:
                    # Non-standard key; some mimo deployments demanded a non-empty
                    # text on every block, others reject the extra key. Off by
                    # default — restore with MIMO_IMAGE_BLOCK_TEXT=1.
                    img_block["text"] = "[image]"
                relay_content.append(img_block)
            messages.insert(i + 1, HumanMessage(content=relay_content))


class SanitizeToolTextBlocksEdit:
    """Replace any ToolMessage content block missing a "text" key with a placeholder.

    mimo rejects any content block with no (or empty) "text" field — see
    InjectVisionAsUserEdit, which handles this for render_diagram/inspect_diagram
    specifically. Those are not the only source though: deepagents' built-in
    `read_file` tool (available to every agent, including icon_resolver, via the
    always-on FilesystemMiddleware) returns
    `content_blocks=[{"type": "image"/"file"/..., "base64": ..., "mime_type": ...}]`
    with no "text" key whenever the model reads a binary file (e.g. an icon
    .png) — this slipped straight through to mimo and 400'd, since neither
    KeepLatestImagesEdit nor InjectVisionAsUserEdit filter by tool name and
    read_file isn't in _IMAGE_TOOLS. This is a blanket safety net: it runs for
    every agent and every tool, stripping the (unusable — no vision-relay path
    for arbitrary tools) base64 payload and leaving a short text note instead.

    Must run AFTER KeepLatestImagesEdit/InjectVisionAsUserEdit in the edits list
    so it never touches the render_diagram/inspect_diagram flow those already
    handle correctly (by the time this edit runs, those ToolMessages are already
    text-only or "[rendered]").
    """

    def apply(self, messages: list[AnyMessage], *, count_tokens: Any) -> None:
        for i, msg in enumerate(messages):
            if not isinstance(msg, LCToolMessage):
                continue
            content = msg.content
            if not isinstance(content, list):
                continue
            changed = False
            new_content = []
            for block in content:
                if isinstance(block, dict) and block.get("type") != "text" and not block.get("text"):
                    mime = block.get("mime_type", "")
                    kind = block.get("type", "file")
                    suffix = f" ({mime})" if mime else ""
                    new_content.append({
                        "type": "text",
                        "text": f"[non-text {kind}{suffix} content omitted — "
                                "refer to the file path instead of inline content]",
                    })
                    changed = True
                else:
                    new_content.append(block)
            if changed:
                messages[i] = msg.model_copy(update={"content": new_content})


_OFFLOAD_GATE_TOOLS = frozenset({"propose_blueprint", "propose_tech_stack"})


class OffloadGateArgsEdit:
    """Replace large gate-tool call args with a pointer once the gate is resolved.

    propose_blueprint/propose_tech_stack receive the full Blueprint/tech_stack as
    *tool-call arguments* (not a return value — both tools only return a short
    confirmation string). Both are in GATE_TOOL_NAMES, so ClearToolUsesEdit's
    `exclude_tools=GATE_TOOL_NAMES` exempts them from clearing forever (needed so
    an interrupted gate stays resumable) — meaning this ~3-9K token blob rides
    along in every subsequent model call for the rest of the run even though
    nothing ever re-reads it (drawer/critic/icon_resolver all read
    render_spec.json/blueprint.json/tech_stack.json from disk instead).

    This edit only rewrites the transient request-local copy of `tool_calls[i].args`
    (it runs inside ContextEditingMiddleware like KeepLatestImagesEdit, so it never
    touches the persisted LangGraph checkpoint state — session_state.py's activity-log
    reconstruction reads that checkpoint directly and is unaffected). It only offloads
    once a ToolMessage is already paired with the call (i.e. the gate was approved and
    the run moved on), so a still-pending/interrupted gate is never touched.
    """

    _NOTE = "[cleared — full content persisted to disk, already applied]"

    def apply(self, messages: list[AnyMessage], *, count_tokens: Any) -> None:
        resolved_ids = {
            getattr(m, "tool_call_id", None)
            for m in messages
            if isinstance(m, LCToolMessage)
        }
        for i, msg in enumerate(messages):
            if not isinstance(msg, AIMessage) or not msg.tool_calls:
                continue
            new_calls = []
            changed = False
            for tc in msg.tool_calls:
                if (
                    tc.get("name") in _OFFLOAD_GATE_TOOLS
                    and tc.get("id") in resolved_ids
                    and tc.get("args")
                ):
                    tc = {**tc, "args": {"_offloaded": self._NOTE}}
                    changed = True
                new_calls.append(tc)
            if changed:
                messages[i] = msg.model_copy(update={"tool_calls": new_calls})
