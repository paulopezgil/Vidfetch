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


def test_list_media_files_classifies_media_types(tmp_path, monkeypatch):
    downloads = _setup(tmp_path, monkeypatch)
    (downloads / "clip.mp4").write_bytes(b"v")
    (downloads / "song.mp3").write_bytes(b"a")
    (downloads / "pic.png").write_bytes(b"i")
    (downloads / "photo.jpeg").write_bytes(b"i")
    (downloads / "vector.svg").write_bytes(b"<svg/>")

    files = {f["filename"]: f for f in library.list_media_files()}
    assert files["clip.mp4"]["media_type"] == "video"
    assert files["song.mp3"]["media_type"] == "audio"
    assert files["pic.png"]["media_type"] == "image"
    assert files["photo.jpeg"]["media_type"] == "image"
    # SVG is intentionally excluded (can carry script).
    assert "vector.svg" not in files


def test_delete_zip_file_has_no_special_handling(tmp_path, monkeypatch):
    downloads = _setup(tmp_path, monkeypatch)
    (downloads / "archive.zip").write_bytes(b"PK")

    result = library.delete_file("archive.zip")
    # No persisted archives exist, so a .zip is deleted like any other file and
    # there is no zip-specific result field.
    assert result == {
        "filename": "archive.zip", "deleted": True, "playlist_id": "",
    }
    assert not (downloads / "archive.zip").exists()
