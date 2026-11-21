"""Filename sanitisation for v2 storage.

This is a deliberate copy of the v1 helper in
:mod:`backend.services.filenames`; v2 code does not import v1 modules so the
two can evolve independently. Keeps Unicode titles while removing path
separators, control characters, and reserved characters.
"""
from __future__ import annotations

import re
import unicodedata

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Return a filesystem-safe, human-readable filename stem."""
    name = unicodedata.normalize("NFKC", name or "")
    name = _UNSAFE.sub("_", name)
    name = _WHITESPACE.sub(" ", name).strip(" .")
    if not name:
        name = "download"
    if len(name) > max_len:
        name = name[:max_len].rstrip(" .")
    return name
