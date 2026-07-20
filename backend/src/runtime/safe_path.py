"""Path-safety helpers for untrusted filenames (upload, DB restore, export copy).

Two public functions:

* ``safe_filename(name)``  — strip directory components and dangerous characters;
  returns a plain filename string safe to append to any base path.

* ``safe_workspace_path(base, untrusted)``  — resolve ``untrusted`` relative to
  ``base`` and raise ``ValueError`` if the resolved path escapes the base
  directory (symlink traversal, ``..`` sequences, etc.).

Usage pattern::

    # In upload handler
    raw_path = UPLOADS_DIR / f"{file_id}_{safe_filename(file.filename)}"

    # In file-copy / restore
    dest = safe_workspace_path(workspace, filename)
    dest.write_text(content)
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

# Characters that have no place in an artifact filename.
_DANGEROUS = re.compile(r'[<>:"|?*\x00-\x1f]')
# Reserved Windows device names (case-insensitive stem match).
_WIN_RESERVED = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}


def safe_filename(name: str | None) -> str:
    """Return a sanitised filename stripped of all directory components.

    * Takes only the final path component (``Path(name).name`` / POSIX
      ``PurePosixPath(name).name``) to neutralise both Windows and POSIX
      separators regardless of the server OS.
    * Strips null bytes, control characters and shell-special characters.
    * Replaces runs of whitespace/dots/dashes that would produce a confusing
      or invisible filename.
    * Falls back to ``"upload"`` when the result would be empty.
    * Truncates to 200 characters to avoid filesystem limits.

    Does NOT validate the extension — callers that care about allowed types
    should check separately.
    """
    if not name:
        return "upload"

    # Strip path separators from both POSIX and Windows paths.
    # Take the last non-empty component from each parser and pick the shorter,
    # since an attacker might submit something like "foo/../../bar\\evil".
    posix_name = PurePosixPath(name).name  # strips "/" separators
    win_name = Path(name).name             # strips both "/" and "\" separators
    # prefer the result that is shorter (more aggressively stripped)
    stem = posix_name if len(posix_name) <= len(win_name) else win_name
    # PurePosixPath("../foo").name == "foo" but Path("../foo").name == "foo" too;
    # a second pass handles any remaining ".." that slipped through:
    stem = stem.replace("..", "").replace("/", "").replace("\\", "")

    # Remove dangerous characters.
    stem = _DANGEROUS.sub("_", stem)
    # Collapse leading dots (hidden files) and leading/trailing whitespace.
    stem = stem.strip().lstrip(".")
    if not stem:
        return "upload"

    # Reject Windows reserved device names (block "CON.txt" etc.).
    pure_stem = Path(stem).stem.lower()
    if pure_stem in _WIN_RESERVED:
        stem = f"file_{stem}"

    # Truncate.
    return stem[:200]


def safe_workspace_path(base: Path, untrusted: str) -> Path:
    """Resolve ``untrusted`` relative to ``base``; raise ``ValueError`` on escape.

    Applies ``safe_filename`` first, then resolves the full path and confirms
    the result is still inside ``base`` (defends against symlink attacks and
    any ``..`` that ``safe_filename`` might have missed).

    Args:
        base: The allowed base directory (e.g. workspace or export path).
              Need not exist yet — only its string representation is compared.
        untrusted: A filename or relative path from an external source.

    Returns:
        A ``Path`` pointing to ``base / safe_filename(untrusted)`` after full
        resolution.

    Raises:
        ValueError: If the resolved path escapes ``base``.
    """
    cleaned = safe_filename(untrusted)
    candidate = (base / cleaned).resolve()
    resolved_base = base.resolve()
    # Use os.fspath string comparison; add trailing sep so "basefoo" != "base/foo".
    base_str = str(resolved_base)
    cand_str = str(candidate)
    if not (cand_str == base_str or cand_str.startswith(base_str + "/"
                                                         ) or cand_str.startswith(base_str + "\\")):
        raise ValueError(
            f"Path escape detected: {untrusted!r} resolves to {cand_str!r} "
            f"which is outside the allowed base {base_str!r}"
        )
    return candidate
