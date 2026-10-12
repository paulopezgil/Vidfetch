"""Filename sanitisation helpers shared by download and ZIP services."""
from __future__ import annotations

import re
import unicodedata

# Characters that are invalid or unsafe in filenames across common filesystems.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Return a filesystem-safe, human-readable filename stem.

    Keeps Unicode (titles are preserved in their native script) while removing
    path separators, control characters, and other reserved characters.
    """
    name = unicodedata.normalize("NFKC", name or "")
    name = _UNSAFE.sub("_", name)
    name = _WHITESPACE.sub(" ", name).strip(" .")
    if not name:
        name = "download"
    if len(name) > max_len:
        name = name[:max_len].rstrip(" .")
    return name
