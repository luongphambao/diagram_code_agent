"""Post-render artifact validation (improvement plan §0.3).

Isolation (Modal Sandbox, or the scrubbed local dev runner) stops a
malicious script from reaching the host or exfiltrating secrets, but it does
NOT make the *output bytes* trustworthy — the render is still attacker-
controlled Python deciding what to write to ``out.png`` / ``out.dot`` /
``out.drawio``. Treat every returned artifact as untrusted content that must
be validated before it is served to a browser, embedded in a PDF/PPTX, or
imported into draw.io. See the improvement plan's "Security requirements for
Modal — Artifact validation" section.

``validate_artifact`` is called by every :class:`SandboxRunner` (including
the local dev runner, not just Modal) right after a file is read back from
the render, so the guarantee holds regardless of which provider executed the
script. It raises :class:`ArtifactValidationError` on anything that fails
its checks; callers treat that the same as a failed render.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Hard ceilings independent of RenderLimits.max_artifact_bytes — these catch
# a technically-small-but-still-hostile file (e.g. a PNG with an absurd
# declared resolution that would blow up memory on decode).
_MAX_PNG_PIXELS = 64_000_000  # ~64 MP, generous for even a dense poster diagram
_MAX_DRAWIO_DEPTH = 64
_MAX_DRAWIO_NODES = 20_000
_MAX_DOT_BYTES = 5_000_000


class ArtifactValidationError(ValueError):
    """Raised when a render artifact fails post-execution validation."""


def validate_artifact(filename: str, data: bytes) -> None:
    """Validate *data* against the checks appropriate for *filename*'s type.

    Unknown extensions are treated as opaque bytes (already bounded by the
    caller's max_artifact_bytes check) — this function only adds *additional*
    type-specific checks for the formats this repo actually produces.
    """
    if filename.endswith(".png"):
        _validate_png(data)
    elif filename.endswith(".drawio"):
        _validate_drawio(data)
    elif filename.endswith(".dot"):
        _validate_dot(data)
    elif filename.endswith(".json"):
        _validate_json_text(data)


def _validate_png(data: bytes) -> None:
    if not data.startswith(_PNG_SIGNATURE):
        raise ArtifactValidationError("PNG artifact missing the PNG signature")
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        # Re-open after verify() (which leaves the image unusable) to read
        # dimensions — Pillow's documented pattern for verify-then-inspect.
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            if width * height > _MAX_PNG_PIXELS:
                raise ArtifactValidationError(
                    f"PNG artifact exceeds the maximum pixel count ({width}x{height} > {_MAX_PNG_PIXELS})"
                )
    except ArtifactValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 — any Pillow decode failure is a rejection
        raise ArtifactValidationError(f"PNG artifact failed to decode: {exc}") from exc


def _validate_drawio(data: bytes) -> None:
    if len(data) > 25_000_000:
        raise ArtifactValidationError("draw.io artifact exceeds the maximum size")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArtifactValidationError("draw.io artifact is not valid UTF-8") from exc

    # Reject external-entity/DOCTYPE declarations outright — draw.io XML never
    # legitimately needs one, and it is the classic XXE vector.
    lowered = text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ArtifactValidationError("draw.io artifact contains a disallowed DOCTYPE/ENTITY")

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ArtifactValidationError(f"draw.io artifact is not well-formed XML: {exc}") from exc

    if root.tag != "mxfile":
        raise ArtifactValidationError(f"draw.io artifact has unexpected root element {root.tag!r}")

    node_count = 0
    max_depth_seen = 0

    def _walk(el: ET.Element, depth: int) -> None:
        nonlocal node_count, max_depth_seen
        node_count += 1
        max_depth_seen = max(max_depth_seen, depth)
        if depth > _MAX_DRAWIO_DEPTH:
            raise ArtifactValidationError(
                f"draw.io artifact exceeds the maximum XML depth ({_MAX_DRAWIO_DEPTH})"
            )
        if node_count > _MAX_DRAWIO_NODES:
            raise ArtifactValidationError(
                f"draw.io artifact exceeds the maximum node count ({_MAX_DRAWIO_NODES})"
            )
        for child in el:
            _walk(child, depth + 1)

    _walk(root, 0)


def _validate_dot(data: bytes) -> None:
    if len(data) > _MAX_DOT_BYTES:
        raise ArtifactValidationError("DOT artifact exceeds the maximum size")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArtifactValidationError("DOT artifact is not valid UTF-8") from exc


def _validate_json_text(data: bytes) -> None:
    import json

    if len(data) > 10_000_000:
        raise ArtifactValidationError("JSON artifact exceeds the maximum size")
    try:
        json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactValidationError(f"JSON artifact is not valid JSON: {exc}") from exc
