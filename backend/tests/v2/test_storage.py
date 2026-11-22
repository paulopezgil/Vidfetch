"""Tests for path-safe storage, atomic finalization, and deletion."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.services.storage import Storage, StorageError

ASSET = "6f1d7c2e-0000-4000-8000-000000000001"


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    instance = Storage(tmp_path / "media")
    instance.ensure_directories()
    return instance


def test_ensure_directories_creates_layout(storage: Storage):
    assert storage.root.is_dir()
    assert (storage.root / "assets").is_dir()
    assert (storage.root / ".tmp").is_dir()


def test_free_bytes_reports_positive_space(storage: Storage):
    assert storage.free_bytes() > 0


@pytest.mark.parametrize(
    "asset_id",
    ["../escape", "a/b", "/absolute", "", "..", ".", "has space", "x" * 200],
)
def test_asset_dir_rejects_unsafe_ids(storage: Storage, asset_id: str):
    with pytest.raises(StorageError):
        storage.asset_dir(asset_id)


def test_asset_dir_is_under_root(storage: Storage):
    directory = storage.asset_dir(ASSET)

    assert directory == storage.root / "assets" / ASSET
    assert directory.is_relative_to(storage.root)


def test_final_path_sanitizes_title_and_canonical_id(storage: Storage):
    path = storage.final_path(
        ASSET,
        "../../etc/passwd",
        "youtube:../../dQw4w9WgXcQ",
        ".MP4",
    )

    assert path.parent == storage.asset_dir(ASSET)
    assert path.is_relative_to(storage.root)
    assert path.name.endswith(".mp4")
    assert "/" not in path.name
    assert "\\" not in path.name
    assert ":" not in path.name


@pytest.mark.parametrize(
    "extension",
    ["", "   ", "mp4/../../x", "a.b", "x" * 13, "mp4\n"],
)
def test_final_path_rejects_bad_extensions(storage: Storage, extension: str):
    with pytest.raises(StorageError):
        storage.final_path(ASSET, "Title", "youtube:abc", extension)


def test_validate_relative_path_accepts_safe_path(storage: Storage):
    resolved = storage.validate_relative_path("assets/one/file.mp4")

    assert resolved == (storage.root / "assets" / "one" / "file.mp4").resolve()
    assert resolved.is_relative_to(storage.root)


@pytest.mark.parametrize(
    "rel",
    [
        "",
        "   ",
        "/etc/passwd",
        "../outside",
        "assets/../../outside",
        "..\\..\\windows",
        "C:/windows/system32",
        "assets/\x00/file",
    ],
)
def test_validate_relative_path_rejects_unsafe_paths(storage: Storage, rel: str):
    with pytest.raises(StorageError):
        storage.validate_relative_path(rel)


def test_validate_relative_path_rejects_symlink_escape(storage: Storage, tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (storage.root / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(StorageError):
        storage.validate_relative_path("escape/secret.txt")


def test_validate_relative_path_rejects_symlinked_file_escape(
    storage: Storage, tmp_path: Path
):
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("secret", encoding="utf-8")
    (storage.root / "evil.mp4").symlink_to(outside_file)

    with pytest.raises(StorageError):
        storage.validate_relative_path("evil.mp4")


def test_atomic_finalize_moves_file_and_creates_parents(storage: Storage):
    source = storage.root / ".tmp" / "partial.mp4"
    source.write_bytes(b"media-bytes")
    destination = storage.final_path(ASSET, "My Video", "youtube:abc", "mp4")
    assert not destination.parent.exists()

    result = storage.atomic_finalize(source, destination)

    assert result == destination.resolve()
    assert destination.read_bytes() == b"media-bytes"
    assert not source.exists()


def test_atomic_finalize_rejects_paths_outside_root(storage: Storage, tmp_path: Path):
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"x")
    source = storage.root / ".tmp" / "inside.mp4"
    source.write_bytes(b"x")
    destination = storage.final_path(ASSET, "T", "youtube:a", "mp4")

    with pytest.raises(StorageError):
        storage.atomic_finalize(outside, destination)
    with pytest.raises(StorageError):
        storage.atomic_finalize(source, tmp_path / "escaped.mp4")


def test_atomic_finalize_requires_existing_source(storage: Storage):
    destination = storage.final_path(ASSET, "T", "youtube:a", "mp4")

    with pytest.raises(FileNotFoundError):
        storage.atomic_finalize(storage.root / ".tmp" / "missing.mp4", destination)


def test_delete_asset_file_removes_file_and_reports_missing(storage: Storage):
    destination = storage.final_path(ASSET, "T", "youtube:a", "mp4")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"x")
    relative = destination.relative_to(storage.root).as_posix()

    assert storage.delete_asset_file(relative) is True
    assert not destination.exists()
    assert storage.delete_asset_file(relative) is False


def test_delete_asset_file_refuses_symlinks_and_directories(
    storage: Storage, tmp_path: Path
):
    target = storage.root / "target.mp4"
    target.write_bytes(b"x")
    link = storage.root / "link.mp4"
    link.symlink_to(target)

    with pytest.raises(StorageError):
        storage.delete_asset_file("link.mp4")
    assert target.exists()

    directory = storage.root / "assets" / ASSET
    directory.mkdir(parents=True)
    with pytest.raises(IsADirectoryError):
        storage.delete_asset_file(f"assets/{ASSET}")
