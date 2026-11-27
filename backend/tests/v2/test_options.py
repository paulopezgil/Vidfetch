"""Tests for canonical option serialization and deduplication hashes."""
from __future__ import annotations

import hashlib
import json

import pytest

from backend.app.services.options import (
    OPTIONS_SCHEMA_VERSION,
    canonical_options,
    canonical_options_json,
    options_hash,
)


def test_hash_is_stable_and_sha256_shaped():
    first = options_hash("bestvideo+bestaudio/best", False)
    second = options_hash("bestvideo+bestaudio/best", False)

    assert first == second
    assert len(first) == 64
    assert first == first.lower()
    int(first, 16)


def test_hash_matches_independent_sha256_of_canonical_json():
    raw = canonical_options_json("720p", True, {"embed_thumbnail": True})

    expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    assert options_hash("720p", True, {"embed_thumbnail": True}) == expected


def test_canonical_json_is_sorted_and_compact():
    raw = canonical_options_json("best", False, {"b": 2, "a": 1})

    assert raw == (
        '{"embed_subs":false,"extra":{"a":1,"b":2},'
        '"format_selector":"best","schema_version":1}'
    )
    assert json.loads(raw)["schema_version"] == OPTIONS_SCHEMA_VERSION


def test_extra_key_order_does_not_change_hash():
    one = options_hash("best", False, {"a": 1, "b": {"x": 1, "y": 2}})
    two = options_hash("best", False, {"b": {"y": 2, "x": 1}, "a": 1})

    assert one == two


def test_none_extra_equals_empty_extra():
    assert options_hash("best", False, None) == options_hash("best", False, {})


def test_format_selector_whitespace_is_normalized():
    assert options_hash("  best  ", False) == options_hash("best", False)


@pytest.mark.parametrize(
    "format_selector,embed_subs,extra",
    [
        ("best", True, None),
        ("720p", False, None),
        ("best", False, {"embed_thumbnail": True}),
        ("best", False, {"audio_bitrate": "320"}),
    ],
)
def test_changing_any_intent_changes_hash(format_selector, embed_subs, extra):
    baseline = options_hash("best", False, None)

    assert options_hash(format_selector, embed_subs, extra) != baseline


def test_every_format_profile_gets_a_distinct_hash():
    formats = [
        "best",
        "2160p",
        "1440p",
        "1080p",
        "720p",
        "540p",
        "480p",
        "360p",
        "240p",
        "144p",
        "audio",
        "mp3",
    ]

    hashes = {options_hash(fmt, False) for fmt in formats}

    assert len(hashes) == len(formats)


def test_canonical_options_rejects_invalid_input():
    with pytest.raises(ValueError):
        canonical_options("", False)
    with pytest.raises(ValueError):
        canonical_options("   ", False)
    with pytest.raises(TypeError):
        canonical_options("best", "false")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        canonical_options("best", False, ["not", "a", "mapping"])  # type: ignore[arg-type]
