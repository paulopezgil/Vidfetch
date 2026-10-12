"""Tests for safe file resolution and deletion."""
from pathlib import Path

from backend import database
from backend.config import settings
from backend.services import library


def _setup(tmp_path, monkeypatch):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    data = tmp_path / "data"
    monkeypatch.setattr(settings, "download_dir", downloads.resolve())
    monkeypatch.setattr(settings, "thumb_dir", (downloads / ".thumbnails").resolve())
    monkeypatch.setattr(settings, "tmp_dir", (downloads / ".tmp").resolve())
    monkeypatch.setattr(settings, "data_dir", data.resolve())
    monkeypatch.setattr(settings, "db_path", (data / "test.db").resolve())
    database.init_db()
    (downloads / "video.mp4").write_bytes(b"data")
    (downloads / ".hidden").write_bytes(b"secret")
    (downloads / ".thumbnails" / "abc.jpg").write_bytes(b"img")
    return downloads


def test_resolve_plain_file(tmp_path, monkeypatch):
    downloads = _setup(tmp_path, monkeypatch)
    assert library.resolve_file("video.mp4") == (downloads / "video.mp4").resolve()


def test_reject_path_traversal(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert library.resolve_file("../etc/passwd") is None
    assert library.resolve_file("../../secret") is None
    assert library.resolve_file("/etc/passwd") is None


def test_reject_hidden_and_missing(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert library.resolve_file(".hidden") is None
    assert library.resolve_file("missing.mp4") is None


def test_delete_file_returns_none_for_bad_name(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert library.delete_file("../video.mp4") is None


def test_delete_file_removes(tmp_path, monkeypatch):
    downloads = _setup(tmp_path, monkeypatch)
    result = library.delete_file("video.mp4")
    assert result is not None and result["deleted"] is True
    assert not (downloads / "video.mp4").exists()


def test_list_media_files_excludes_hidden(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    files = library.list_media_files()
    names = [f["filename"] for f in files]
    assert "video.mp4" in names
    assert ".hidden" not in names
