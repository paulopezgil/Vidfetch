"""Tests for download task orchestration.

We exercise the synchronous ``_execute`` path directly, stubbing the yt-dlp
service so no network access is required. Settings point at a tmp directory and
a fresh SQLite database per test.
"""
import hashlib
import uuid
from pathlib import Path

import pytest

from backend import database
from backend.config import settings
from backend.services import ytdlp_service
from backend.services.task_manager import Task, TaskManager


@pytest.fixture
def env(tmp_path, monkeypatch):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    data = tmp_path / "data"
    monkeypatch.setattr(settings, "download_dir", downloads.resolve())
    monkeypatch.setattr(settings, "thumb_dir", (downloads / ".thumbnails").resolve())
    monkeypatch.setattr(settings, "tmp_dir", (downloads / ".tmp").resolve())
    monkeypatch.setattr(settings, "data_dir", data.resolve())
    monkeypatch.setattr(settings, "db_path", (data / "test.db").resolve())
    database.init_db()
    return downloads


def _make_task(tm: TaskManager, **kwargs) -> Task:
    kwargs.setdefault("url", "https://example.com/video")
    task = Task(task_id=uuid.uuid4().hex, **kwargs)
    with tm._lock:
        tm._tasks[task.task_id] = task
    database.insert_task(task._row())
    return task


def _successful_download(fail_urls=(), on_success=None):
    """Build a ``download_video`` stub that writes a file per video id."""
    def fake(url, fmt, embed_subs, workdir, progress_cb, cancel):
        if url in fail_urls:
            raise ytdlp_service.DownloadError("ERROR: HTTP Error 403: Forbidden")
        progress_cb({
            "status": "downloading",
            "downloaded_bytes": 10,
            "total_bytes": 10,
            "speed": 0.0,
            "eta": 0.0,
        })
        vid = url.rsplit("/", 1)[-1]
        path = Path(workdir) / f"{vid}.mp4"
        path.write_bytes(b"x" * 10)
        if on_success:
            on_success(url)
        return {
            "id": vid,
            "title": vid.upper(),
            "filepath": str(path),
            "thumbnail": None,
            "ext": "mp4",
        }
    return fake


def _playlist_info(entries):
    return {
        "type": "playlist",
        "id": "PL",
        "title": "My List",
        "channel": "Someone",
        "thumbnail": None,
        "video_count": len(entries),
        "entries": entries,
    }


def _entry(vid, title=None):
    return {
        "id": vid,
        "title": title or vid.upper(),
        "url": f"https://example.com/{vid}",
        "duration": 1,
        "thumbnail": None,
    }


# -- single video --------------------------------------------------------- #

def test_single_video_success(env, monkeypatch):
    monkeypatch.setattr(ytdlp_service, "get_info", lambda url: {
        "type": "video", "id": "v1", "title": "Hello/World", "thumbnail": None,
    })
    monkeypatch.setattr(ytdlp_service, "download_video", _successful_download())

    tm = TaskManager()
    task = _make_task(tm)
    tm._execute(task)

    assert task.status == "completed"
    assert task.progress == 100.0
    assert task.video_id == "v1"
    assert task.output_filename.endswith(".mp4")
    assert (settings.download_dir / task.output_filename).exists()
    # No leftover working directory.
    assert not (settings.tmp_dir / task.task_id).exists()


def test_cancelled_queued_task_skips_all_work(env, monkeypatch):
    called: list[str] = []
    monkeypatch.setattr(
        ytdlp_service, "get_info", lambda url: called.append(url) or {}
    )

    tm = TaskManager()
    task = _make_task(tm)
    task.cancel_requested = True
    tm._execute(task)

    assert called == []
    assert task.status == "cancelled"
    assert task.error == "Cancelled by user."


# -- playlists ------------------------------------------------------------ #

def test_playlist_partial_failure(env, monkeypatch):
    entries = [_entry("a"), _entry("b"), _entry("c")]
    monkeypatch.setattr(ytdlp_service, "get_info", lambda url: _playlist_info(entries))
    monkeypatch.setattr(
        ytdlp_service, "download_video",
        _successful_download(fail_urls={"https://example.com/b"}),
    )

    tm = TaskManager()
    task = _make_task(tm, url="https://example.com/playlist", operation_type="playlist")
    tm._execute(task)

    # Partial success is reported as completed with a summary error.
    assert task.status == "completed"
    assert task.completed_items == 2
    assert task.progress == pytest.approx(66.7)
    assert "1 of 3" in task.error

    items = {i["url"]: i for i in database.get_playlist_items(task.playlist_id)}
    assert items["https://example.com/a"]["status"] == "downloaded"
    assert items["https://example.com/c"]["status"] == "downloaded"
    assert items["https://example.com/b"]["status"] == "failed"
    assert "403" in items["https://example.com/b"]["error"]

    # A playlist run persists no archive: ZIPs are built on demand at request
    # time, so nothing must be written under the download directory.
    assert task.output_filename == ""
    assert not list(settings.download_dir.glob("*.zip"))
    assert not list(settings.download_dir.rglob("*.zip"))

    playlist = database.get_playlist(task.playlist_id)
    assert playlist["status"] == "completed"
    assert playlist["zip_path"] == ""

    # Working directory is cleaned up.
    assert not (settings.tmp_dir / task.task_id).exists()


def test_playlist_all_items_fail(env, monkeypatch):
    entries = [_entry("a"), _entry("b")]
    monkeypatch.setattr(ytdlp_service, "get_info", lambda url: _playlist_info(entries))
    monkeypatch.setattr(
        ytdlp_service, "download_video",
        _successful_download(fail_urls={"https://example.com/a", "https://example.com/b"}),
    )

    tm = TaskManager()
    task = _make_task(tm, url="https://example.com/playlist", operation_type="playlist")
    tm._execute(task)

    assert task.status == "failed"
    assert task.progress == 0.0
    assert "All 2 items failed" in task.error
    assert task.output_filename == ""
    assert database.get_playlist(task.playlist_id)["status"] == "failed"


def test_playlist_cancel_midway(env, monkeypatch):
    entries = [_entry("a"), _entry("b"), _entry("c")]
    monkeypatch.setattr(ytdlp_service, "get_info", lambda url: _playlist_info(entries))

    calls = {"n": 0}

    def fake(url, fmt, embed_subs, workdir, progress_cb, cancel):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ytdlp_service.DownloadCancelled()
        vid = url.rsplit("/", 1)[-1]
        path = Path(workdir) / f"{vid}.mp4"
        path.write_bytes(b"x")
        return {"id": vid, "title": vid.upper(), "filepath": str(path),
                "thumbnail": None, "ext": "mp4"}

    monkeypatch.setattr(ytdlp_service, "download_video", fake)

    tm = TaskManager()
    task = _make_task(tm, url="https://example.com/playlist", operation_type="playlist")
    tm._execute(task)

    assert task.status == "cancelled"
    assert task.error == "Cancelled by user."
    assert database.get_playlist(task.playlist_id)["status"] == "cancelled"

    items = {i["url"]: i["status"] for i in database.get_playlist_items(task.playlist_id)}
    assert items["https://example.com/a"] == "downloaded"
    # The in-flight item is reset so it can be retried; the untouched one stays pending.
    assert items["https://example.com/b"] == "pending"
    assert items["https://example.com/c"] == "pending"
    # No ZIP is produced for a cancelled run.
    assert task.output_filename == ""


def test_playlist_duplicate_urls_do_not_overflow_progress(env, monkeypatch):
    # Two entries share a URL; the DB collapses them into a single item.
    entries = [_entry("a"), _entry("a"), _entry("b")]
    monkeypatch.setattr(ytdlp_service, "get_info", lambda url: _playlist_info(entries))
    monkeypatch.setattr(ytdlp_service, "download_video", _successful_download())

    tm = TaskManager()
    task = _make_task(tm, url="https://example.com/playlist", operation_type="playlist")
    tm._execute(task)

    assert task.item_count == 2
    assert task.completed_items == 2
    assert task.progress == 100.0
    assert task.status == "completed"


def test_playlist_retry_does_not_create_archive(env, monkeypatch):
    """A retried item is never packaged into a persisted ZIP at download time."""
    monkeypatch.setattr(ytdlp_service, "get_info", lambda url: _playlist_info([_entry("a")]))
    monkeypatch.setattr(ytdlp_service, "download_video", _successful_download())

    tm = TaskManager()
    task = _make_task(tm, url="https://example.com/playlist", operation_type="playlist")
    tm._execute(task)

    assert task.status == "completed"
    assert task.output_filename == ""
    # The downloaded media file is present; only the (never-created) archive
    # would be absent.
    assert list(settings.download_dir.glob("*.mp4"))
    assert not list(settings.download_dir.rglob("*.zip"))


# -- single-item retries -------------------------------------------------- #

def test_playlist_item_failure_records_error_without_downgrading_playlist(
    env, monkeypatch
):
    database.upsert_playlist({
        "playlist_id": "pl_x", "url": "https://example.com/playlist",
        "title": "List", "channel": "", "thumbnail_path": "", "item_count": 1,
        "total_size": 0, "zip_path": "", "status": "completed",
        "created_at": database.iso_now(), "updated_at": database.iso_now(),
    })
    database.upsert_playlist_item({
        "playlist_id": "pl_x", "item_index": 0, "video_id": "b",
        "url": "https://example.com/b", "title": "B", "duration": 1,
        "status": "pending", "filename": "", "size": 0, "error": "",
    })

    monkeypatch.setattr(ytdlp_service, "get_info", lambda url: {
        "type": "video", "id": "b", "title": "B", "thumbnail": None,
    })
    monkeypatch.setattr(
        ytdlp_service, "download_video",
        _successful_download(fail_urls={"https://example.com/b"}),
    )

    tm = TaskManager()
    task = _make_task(
        tm, url="https://example.com/b", operation_type="playlist_item",
        playlist_id="pl_x",
    )
    tm._execute(task)

    assert task.status == "failed"
    # The failure is attributed to the item row...
    item = database.get_playlist_item("pl_x", "https://example.com/b")
    assert item["status"] == "failed"
    assert "403" in item["error"]
    # ...but the playlist-level status is left alone.
    assert database.get_playlist("pl_x")["status"] == "completed"


# -- item retention / pruning --------------------------------------------- #

def _playlist_id(url: str) -> str:
    return "pl_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def _seed_playlist(playlist_id, items):
    database.upsert_playlist({
        "playlist_id": playlist_id, "url": "https://example.com/playlist",
        "title": "List", "channel": "", "thumbnail_path": "", "item_count": len(items),
        "total_size": 0, "zip_path": "", "status": "completed",
        "created_at": database.iso_now(), "updated_at": database.iso_now(),
    })
    for item in items:
        database.upsert_playlist_item({
            "playlist_id": playlist_id, "duration": 1, "error": "",
            **item,
        })


def test_playlist_prunes_items_removed_from_source(env, monkeypatch):
    url = "https://example.com/playlist"
    pid = _playlist_id(url)

    # An earlier run tracked a, b and c with files already on disk.
    for i, vid in enumerate(["a", "b", "c"]):
        (env / f"{vid}.mp4").write_bytes(b"x" * (10 * (i + 1)))
    _seed_playlist(pid, [
        {"item_index": 0, "video_id": "a", "url": "https://example.com/a",
         "title": "A", "status": "downloaded", "filename": "a.mp4", "size": 10},
        {"item_index": 1, "video_id": "b", "url": "https://example.com/b",
         "title": "B", "status": "downloaded", "filename": "b.mp4", "size": 20},
        {"item_index": 2, "video_id": "c", "url": "https://example.com/c",
         "title": "C", "status": "downloaded", "filename": "c.mp4", "size": 30},
    ])

    # The source playlist now only contains a and b.
    entries = [_entry("a"), _entry("b")]
    monkeypatch.setattr(ytdlp_service, "get_info", lambda u: _playlist_info(entries))
    monkeypatch.setattr(ytdlp_service, "download_video", _successful_download())

    tm = TaskManager()
    task = _make_task(tm, url=url, operation_type="playlist")
    tm._execute(task)

    remaining = {i["url"] for i in database.get_playlist_items(pid)}
    assert remaining == {"https://example.com/a", "https://example.com/b"}
    # The stale item's file is intentionally retained on disk.
    assert (env / "c.mp4").exists()

    assert task.item_count == 2
    assert task.completed_items == 2
    assert task.progress == 100.0
    assert task.status == "completed"

    playlist = database.get_playlist(pid)
    assert playlist["item_count"] == 2
    assert playlist["total_size"] == 30  # only a (10) + b (20)


def test_playlist_total_size_ignores_stale_or_missing_files(env, monkeypatch):
    url = "https://example.com/playlist"
    pid = _playlist_id(url)

    # a exists on disk; b is marked downloaded but its file is gone, so it must
    # be re-downloaded. Its stale DB size (999) must not be counted.
    (env / "a.mp4").write_bytes(b"x" * 10)
    _seed_playlist(pid, [
        {"item_index": 0, "video_id": "a", "url": "https://example.com/a",
         "title": "A", "status": "downloaded", "filename": "a.mp4", "size": 10},
        {"item_index": 1, "video_id": "b", "url": "https://example.com/b",
         "title": "B", "status": "downloaded", "filename": "b.mp4", "size": 999},
    ])

    entries = [_entry("a"), _entry("b")]
    monkeypatch.setattr(ytdlp_service, "get_info", lambda u: _playlist_info(entries))
    monkeypatch.setattr(ytdlp_service, "download_video", _successful_download())

    tm = TaskManager()
    task = _make_task(tm, url=url, operation_type="playlist")
    tm._execute(task)

    assert task.completed_items == 2
    assert task.status == "completed"
    # 10 (existing a) + 10 (freshly written b), never the stale 999.
    assert database.get_playlist(pid)["total_size"] == 20


# -- disk space guard ----------------------------------------------------- #

class _FakeUsage:
    def __init__(self, free: int):
        self.free = free
        self.total = free
        self.used = 0


def test_download_fails_fast_when_disk_full(env, monkeypatch):
    monkeypatch.setattr(
        ytdlp_service, "get_info",
        lambda url: {"type": "video", "id": "v1", "title": "V", "thumbnail": None},
    )
    monkeypatch.setattr(ytdlp_service.shutil, "disk_usage", lambda path: _FakeUsage(1))

    tm = TaskManager()
    task = _make_task(tm)
    tm._execute(task)

    assert task.status == "failed"
    assert "disk space" in task.error.lower()
    assert task.output_filename == ""
