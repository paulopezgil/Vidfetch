"""Canonical output-option hashing for the global media cache.

The cache key is ``(canonical_id, options_hash)``. The hash must represent
*user intent* (selector profile, subtitle embedding, extra postprocessing), not
the resolved formats, so it stays stable when a site changes its format list.

Serialization is deterministic: sorted keys, compact separators, UTF-8, and a
schema version. Bump ``OPTIONS_SCHEMA_VERSION`` only when the canonical shape
changes; doing so intentionally invalidates the cache.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

OPTIONS_SCHEMA_VERSION = 1


def canonical_options(
    format_selector: str,
    embed_subs: bool,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the canonical options mapping for the given intent."""
    if not isinstance(format_selector, str) or not format_selector.strip():
        raise ValueError("format_selector is required.")
    if not isinstance(embed_subs, bool):
        raise TypeError("embed_subs must be a boolean.")
    if extra is None:
        extra = {}
    if not isinstance(extra, Mapping):
        raise TypeError("extra must be a mapping.")

    return {
        "schema_version": OPTIONS_SCHEMA_VERSION,
        "format_selector": format_selector.strip(),
        "embed_subs": embed_subs,
        "extra": dict(extra),
    }


def canonical_options_json(
    format_selector: str,
    embed_subs: bool,
    extra: Mapping[str, Any] | None = None,
) -> str:
    """Return the deterministic JSON string used as hashing input."""
    return json.dumps(
        canonical_options(format_selector, embed_subs, extra),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def options_hash(
    format_selector: str,
    embed_subs: bool,
    extra: Mapping[str, Any] | None = None,
) -> str:
    """SHA-256 hex digest of the canonical options JSON."""
    payload = canonical_options_json(format_selector, embed_subs, extra)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
