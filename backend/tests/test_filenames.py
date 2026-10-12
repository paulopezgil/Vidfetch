"""Tests for filename sanitisation."""
from backend.services.filenames import sanitize_filename


def test_preserves_unicode():
    assert sanitize_filename("こんにちは 世界") == "こんにちは 世界"


def test_strips_path_separators():
    assert "/" not in sanitize_filename("a/b\\c:d*e?f\"g<h>i|j")
    assert sanitize_filename("a/b").replace("_", "") == "ab"


def test_strips_control_characters():
    assert "\n" not in sanitize_filename("line\nbreak")
    assert "\x00" not in sanitize_filename("nul\x00byte")


def test_empty_name_gets_fallback():
    assert sanitize_filename("") == "download"
    assert sanitize_filename("...") == "download"


def test_truncates_long_names():
    result = sanitize_filename("x" * 500)
    assert len(result) <= 120


def test_strips_leading_dots_and_spaces():
    assert sanitize_filename("...hidden") == "hidden"
    assert sanitize_filename("  spaced  ") == "spaced"
