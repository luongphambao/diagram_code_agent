"""Deterministic fallback when the provider rejects relayed images."""

from __future__ import annotations

import logging

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AnyMessage

logger = logging.getLogger(__name__)


class VisionErrorFallbackMiddleware(AgentMiddleware):
    """Deterministic fallback when the provider rejects relayed images.

    mimo intermittently 400s with "Multimodal data is corrupted" on the vision
    relay; without this the model just re-issues the same request and burns its
    call budget. On a vision 400, strip every image/image_url block from the
    request messages, add a text note, and retry ONCE — drawer/critic then
    proceed text-only (layout audit) instead of retry-storming.
    """

    name = "VisionErrorFallbackMiddleware"
    _MARKERS = ("multimodal", "corrupted")

    _NOTE = (
        "[image removed — the provider rejected the image payload. Review "
        "using the LAYOUT AUDIT text and the blueprint instead; do not "
        "request the image again.]"
    )

    @classmethod
    def _is_vision_error(cls, exc: Exception) -> bool:
        text = str(exc).lower()
        return any(m in text for m in cls._MARKERS)

    def _strip_images(self, messages: list[AnyMessage]) -> list[AnyMessage]:
        stripped: list[AnyMessage] = []
        for msg in messages:
            content = getattr(msg, "content", None)
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") in ("image", "image_url") for b in content
            ):
                new_content = [
                    {"type": "text", "text": self._NOTE}
                    if (isinstance(b, dict) and b.get("type") in ("image", "image_url"))
                    else b
                    for b in content
                ]
                stripped.append(msg.model_copy(update={"content": new_content}))
            else:
                stripped.append(msg)
        return stripped

    def wrap_model_call(self, request: ModelRequest, handler):
        try:
            return handler(request)
        except Exception as exc:  # noqa: BLE001 — provider-specific 400
            if not self._is_vision_error(exc):
                raise
            logger.warning("vision payload rejected (%s) — retrying once text-only", exc)
            request.messages = self._strip_images(request.messages)
            return handler(request)

    async def awrap_model_call(self, request: ModelRequest, handler):
        try:
            return await handler(request)
        except Exception as exc:  # noqa: BLE001 — provider-specific 400
            if not self._is_vision_error(exc):
                raise
            logger.warning("vision payload rejected (%s) — retrying once text-only", exc)
            request.messages = self._strip_images(request.messages)
            return await handler(request)
