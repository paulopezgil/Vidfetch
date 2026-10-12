"""Tests for download task orchestration.

We exercise the synchronous ``_execute`` path directly, stubbing the yt-dlp
service so no network access is required. Settings point at a tmp directory and
a fresh SQLite database per test.
"""
import uuid
import zipfile
from pathlib import Path

import pytest

from backend import database
from backend.config import settings
from backend.services import task_manager, ytdlp_service
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

    # The ZIP contains only the successful items.
    zip_path = settings.download_dir / task.output_filename
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        assert len(zf.namelist()) == 2

    playlist = database.get_playlist(task.playlist_id)
    assert playlist["status"] == "completed"

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


def test_cancel_during_zip_packaging(env, monkeypatch):
    monkeypatch.setattr(ytdlp_service, "get_info", lambda url: _playlist_info([_entry("a")]))
    monkeypatch.setattr(ytdlp_service, "download_video", _successful_download())

    holder: dict = {}

    def fake_zip(files, dest, cb=None):
        # Simulate the user cancelling while the archive is being written.
        holder["task"].cancel_requested = True
        cb(0.5)  # the manager's callback must raise DownloadCancelled
        raise AssertionError("packaging callback should have aborted")

    monkeypatch.setattr(task_manager.zip_service, "create_zip", fake_zip)

    tm = TaskManager()
    task = _make_task(tm, url="https://example.com/playlist", operation_type="playlist")
    holder["task"] = task
    tm._execute(task)

    assert task.status == "cancelled"
    assert task.output_filename == ""


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
