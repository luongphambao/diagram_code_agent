"""Content-based file-type detection for uploads (improvement plan §0.4).

A client-supplied filename extension and ``Content-Type`` header are not
validation — either can be forged. This module checks the file's actual
magic bytes against the extension the upload endpoint is about to trust,
so a renamed executable or a zip bomb wearing a ``.pdf`` extension is
rejected before ``document_parsers.parsers.parse_file`` ever touches it.

Deliberately dependency-free (no ``python-magic``/libmagic) — the small set
of formats this repo accepts (PDF, DOCX, XLSX, PNG/JPEG/WEBP/GIF, plain
text/Markdown/CSV) is fully identifiable from a short byte prefix.
"""

from __future__ import annotations

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"  # DOCX is a zip archive
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_GIF_MAGIC = (b"GIF87a", b"GIF89a")

_BINARY_MAGIC_EXTENSIONS = {
    ".pdf": (_PDF_MAGIC,),
    ".docx": (_ZIP_MAGIC,),
    # .xlsx is also a zip (OOXML) container — same weak bar as .docx above (a
    # short byte prefix can't tell an xlsx from a docx from any other zip; both
    # only get this coarse check). document_parsers.parsers.parse_file() is what
    # actually validates the content — openpyxl raises if it isn't real xlsx.
    ".xlsx": (_ZIP_MAGIC,),
    ".png": (_PNG_MAGIC,),
    ".jpg": (_JPEG_MAGIC,),
    ".jpeg": (_JPEG_MAGIC,),
    ".gif": _GIF_MAGIC,
}
# .webp needs a two-part check (RIFF....WEBP), handled separately below.
# .md/.markdown/.txt/.csv have no magic bytes — validated by "looks like text"
# instead (see _looks_like_text).


def sniff_mismatch(extension: str, head: bytes) -> str | None:
    """Return a human-readable reason if *head* (the file's first ~64 bytes)
    doesn't match what *extension* claims to be, or ``None`` if it's fine.

    Unknown extensions are the upload endpoint's problem (rejected earlier
    via the SUPPORTED_EXT allowlist) — this function only flags a mismatch
    for extensions it knows how to fingerprint.
    """
    ext = extension.lower()

    if ext == ".webp":
        if not (head[:4] == b"RIFF" and head[8:12] == b"WEBP"):
            return "file does not start with a WEBP (RIFF....WEBP) signature"
        return None

    magics = _BINARY_MAGIC_EXTENSIONS.get(ext)
    if magics is not None:
        if not any(head.startswith(m) for m in magics):
            return f"file does not start with a valid {ext} signature"
        return None

    if ext in (".md", ".markdown", ".txt", ".csv"):
        if not _looks_like_text(head):
            return "file claims to be text but contains binary content"
        return None

    return None


def _looks_like_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        # Non-UTF-8 text (other encodings) is still plausible; only reject
        # content with NUL bytes or an excessive proportion of control
        # characters, which UTF-8 files with the occasional non-ASCII byte
        # won't trigger.
        pass
    control_count = sum(1 for b in head if b < 9 or (13 < b < 32))
    return control_count <= max(1, len(head) // 20)
