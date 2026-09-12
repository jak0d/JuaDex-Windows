"""Filename sanitation and non-overwriting collision handling (PRD FR-5).

Windows-specific hazards handled here: reserved device names, trailing dots and
spaces, illegal characters, path traversal via crafted PDF names, and overlong
paths.  Filenames from disk and metadata are treated as untrusted input.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Characters Windows forbids in a file name, plus the path separators.
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

#: Reserved DOS device names (case-insensitive, with or without extension).
_RESERVED_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)

#: Conservative cap for a single path component.
MAX_STEM_LENGTH = 120

FALLBACK_STEM = "document"


def sanitize_stem(stem: str, *, max_length: int = MAX_STEM_LENGTH) -> str:
    """Return a safe file *stem* (no extension, no directory component)."""

    if stem is None:
        return FALLBACK_STEM

    # Strip any directory component that sneaked in via a crafted name.
    candidate = str(stem).replace("\\", "/").split("/")[-1]
    candidate = _ILLEGAL_CHARS.sub("_", candidate)
    # Collapse runs of whitespace; keep Unicode letters intact.
    candidate = " ".join(candidate.split())
    # Windows silently drops trailing dots/spaces, which breaks the
    # "validate then rename" contract; remove them explicitly.
    candidate = candidate.rstrip(". ")
    candidate = candidate.lstrip(".")

    if not candidate:
        return FALLBACK_STEM

    root = candidate.split(".")[0].upper()
    if root in _RESERVED_NAMES:
        candidate = f"_{candidate}"

    if len(candidate) > max_length:
        candidate = candidate[:max_length].rstrip(". ")

    return candidate or FALLBACK_STEM


def split_name(stem: str, index: int, total: int | None = None, *, width: int = 3) -> str:
    """Build the split output name: ``<stem> - 001.pdf`` (at least 3 digits)."""

    digits = max(width, len(str(total))) if total else width
    return f"{sanitize_stem(stem)} - {index:0{digits}d}.pdf"


def cleaned_name(stem: str) -> str:
    """Build the blank-removal-only output name: ``<stem> - cleaned.pdf``."""

    return f"{sanitize_stem(stem)} - cleaned.pdf"


def unique_path(directory: Path, filename: str, *, reserved: set[Path] | None = None) -> Path:
    """Return a path inside ``directory`` that does not exist yet.

    Collisions get ``' (2)'``, ``' (3)'`` … appended before the extension.
    ``reserved`` lets a caller book names for files it is about to create, so
    two outputs in the same batch cannot race onto the same name.
    """

    directory = Path(directory)
    reserved = reserved if reserved is not None else set()

    base = Path(filename)
    stem, suffix = base.stem, base.suffix or ".pdf"

    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists() and candidate not in reserved:
        return candidate

    counter = 2
    while True:
        candidate = directory / f"{stem} ({counter}){suffix}"
        if not candidate.exists() and candidate not in reserved:
            return candidate
        counter += 1
        if counter > 9999:  # pragma: no cover - pathological directory
            raise OSError(
                f"Could not find an unused name for '{filename}' in {directory}."
            )


def is_within(path: Path, parent: Path) -> bool:
    """True when ``path`` is inside ``parent`` (after resolving both)."""

    try:
        path = Path(path).resolve()
        parent = Path(parent).resolve()
    except OSError:  # pragma: no cover - unresolvable network path
        return False
    if path == parent:
        return True
    return parent in path.parents


__all__ = [
    "MAX_STEM_LENGTH",
    "cleaned_name",
    "is_within",
    "sanitize_stem",
    "split_name",
    "unique_path",
]
