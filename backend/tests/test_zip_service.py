"""Tests for ZIP packaging."""
import zipfile
from pathlib import Path

import pytest

from backend.services import zip_service


def test_create_zip(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"a" * 100)
    (tmp_path / "b.mp3").write_bytes(b"b" * 200)
    dest = tmp_path / "out.zip"
    zip_service.create_zip([tmp_path / "a.mp4", tmp_path / "b.mp3"], dest)

    assert dest.exists()
    assert not (tmp_path / "out.zip.part").exists()
    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()
        assert "a.mp4" in names
        assert "b.mp3" in names


def test_create_zip_skips_missing_files(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    dest = tmp_path / "out.zip"
    zip_service.create_zip([tmp_path / "a.mp4", tmp_path / "missing.mp4"], dest)
    with zipfile.ZipFile(dest) as zf:
        assert zf.namelist() == ["a.mp4"]


def test_create_zip_empty_raises(tmp_path):
    with pytest.raises(ValueError):
        zip_service.create_zip([], tmp_path / "out.zip")


def test_progress_callback_reaches_one(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x" * 1000)
    seen = []
    zip_service.create_zip([tmp_path / "a.mp4"], tmp_path / "out.zip", seen.append)
    assert seen and seen[-1] == pytest.approx(1.0)
