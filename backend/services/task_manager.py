"""Background task orchestration for downloads.

Design notes
------------
* A single global :class:`TaskManager` owns active tasks and persists their
  records to SQLite. Real-time progress lives in memory (guarded by a lock);
  durable state (status transitions, completion, errors) is written through to
  SQLite so history survives restarts.
* Downloads run in worker threads via ``asyncio.to_thread``, limited by a
  semaphore. The ``yt-dlp`` progress hook updates the in-memory task state and
  bumps a version counter that the SSE endpoint polls.
* Playlist downloads iterate items one at a time, updating per-item status in
  the database, then ZIP the successful items. Cancellation is checked between
  items and inside the progress hook.
"""
from __future__ import annotations

import asyncio
import hashlib
import shutil
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .. import database
from ..config import settings
from . import ytdlp_service, zip_service
from .filenames import sanitize_filename

TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

_USER_AGENT = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class Task:
    task_id: str
    url: str
    title: str = ""
    video_id: str = ""
    operation_type: str = "video"
    format: str = "best"
    embed_subs: bool = False
    status: str = "queued"
    progress: float = 0.0
    current_item_progress: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed: float = 0.0
    eta: float = 0.0
    item_index: int = 0
    item_count: int = 0
    completed_items: int = 0
    current_item_title: str = ""
    playlist_id: str = ""
    output_filename: str = ""
    error: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    completed_at: str = ""
    version: int = 0
    cancel_requested: bool = False

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "url": self.url,
            "title": self.title,
            "video_id": self.video_id,
            "operation_type": self.operation_type,
            "format": self.format,
            "embed_subs": self.embed_subs,
            "status": self.status,
            "progress": self.progress,
            "current_item_progress": self.current_item_progress,
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "speed": self.speed,
            "eta": self.eta,
            "item_index": self.item_index,
            "item_count": self.item_count,
            "completed_items": self.completed_items,
            "current_item_title": self.current_item_title,
            "playlist_id": self.playlist_id,
            "output_filename": self.output_filename,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }

    def _row(self) -> dict:
        return {
            "task_id": self.task_id,
            "url": self.url,
            "title": self.title,
            "video_id": self.video_id,
            "operation_type": self.operation_type,
            "format": self.format,
            "embed_subs": int(self.embed_subs),
            "status": self.status,
            "progress": self.progress,
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "speed": self.speed,
            "eta": self.eta,
            "item_index": self.item_index,
            "item_count": self.item_count,
            "completed_items": self.completed_items,
            "current_item_title": self.current_item_title,
            "playlist_id": self.playlist_id,
            "output_filename": self.output_filename,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._semaphore: Optional[asyncio.Semaphore] = None

    # -- public API --------------------------------------------------------- #

    def create_task(
        self,
        url: str,
        operation_type: str,
        format: str = "best",
        embed_subs: bool = False,
        title: str = "",
        playlist_id: str = "",
    ) -> str:
        task = Task(
            task_id=uuid.uuid4().hex,
            url=url,
            title=title,
            operation_type=operation_type,
            format=format,
            embed_subs=embed_subs,
            playlist_id=playlist_id,
        )
        with self._lock:
            self._tasks[task.task_id] = task
        database.insert_task(task._row())

        loop = asyncio.get_running_loop()
        if self._semaphore is None or self._loop is not loop:
            self._loop = loop
            self._semaphore = asyncio.Semaphore(settings.max_concurrent_downloads)
        loop.create_task(self._run(task.task_id))
        return task.task_id

    def cancel_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.status in TERMINAL_STATUSES:
            return False
        task.cancel_requested = True
        with self._lock:
            task.version += 1
        return True

    def get_task(self, task_id: str) -> Optional[Task]:
        task = self._tasks.get(task_id)
        if task is not None:
            return task
        # Fall back to persisted history (e.g. after a restart).
        row = database.get_task(task_id)
        if row is None:
            return None
        return self._task_from_row(row)

    def list_active(self) -> list[dict]:
        with self._lock:
            active = [
                t for t in self._tasks.values()
                if t.status not in TERMINAL_STATUSES
            ]
            return [t.to_dict() for t in sorted(active, key=lambda t: t.created_at)]

    # -- task execution ----------------------------------------------------- #

    async def _run(self, task_id: str) -> None:
        task = self._tasks[task_id]
        assert self._semaphore is not None
        async with self._semaphore:
            await asyncio.to_thread(self._execute, task)

    def _execute(self, task: Task) -> None:
        try:
            if task.operation_type == "playlist":
                self._execute_playlist(task)
            elif task.operation_type == "playlist_item":
                self._execute_playlist_item(task)
            else:
                self._execute_video(task)
        except ytdlp_service.DownloadCancelled:
            self._finish_cancelled(task)
        except ytdlp_service.DownloadError as exc:
            self._finish_failed(task, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._finish_failed(task, f"Unexpected error: {exc}")

    # -- single video ------------------------------------------------------- #

    def _execute_video(self, task: Task) -> None:
        self._run_single_download(task)
        self._set_status(task, "completed")
        self._persist(task)

    def _execute_playlist_item(self, task: Task) -> None:
        dest = self._run_single_download(task)

        if task.playlist_id:
            size = dest.stat().st_size
            database.update_playlist_item_status(
                task.playlist_id, task.url, "downloaded", dest.name, size, ""
            )
            playlist = database.get_playlist(task.playlist_id)
            if playlist:
                items = database.get_playlist_items(task.playlist_id)
                total = 0
                for item in items:
                    if item["status"] == "downloaded" and item["filename"]:
                        f = settings.download_dir / item["filename"]
                        if f.exists():
                            total += item["size"] or f.stat().st_size
                database.upsert_playlist({
                    **playlist,
                    "total_size": total,
                    "status": "completed",
                    "updated_at": _now(),
                })

        self._set_status(task, "completed")
        self._persist(task)

    def _run_single_download(self, task: Task) -> Path:
        """Fetch metadata, download, and finalise a single video. Returns dest."""
        self._set_status(task, "fetching information")
        info = ytdlp_service.get_info(task.url)
        if info.get("type") == "playlist":
            raise ytdlp_service.DownloadError(
                "This URL is a playlist. Use 'Download playlist' instead."
            )
        task.title = info["title"]
        task.video_id = info.get("id") or ""
        if info.get("thumbnail") and task.video_id:
            self._download_thumbnail(
                info["thumbnail"], settings.thumb_dir / f"{task.video_id}.jpg"
            )
        self._persist(task)

        workdir = settings.tmp_dir / task.task_id
        workdir.mkdir(parents=True, exist_ok=True)

        self._set_status(task, "downloading")
        result = ytdlp_service.download_video(
            task.url,
            task.format,
            task.embed_subs,
            workdir,
            self._progress_hook(task),
            self._cancelled(task),
        )
        if not result.get("filepath"):
            raise ytdlp_service.DownloadError(
                "Download completed but no output file was produced."
            )
        src = Path(result["filepath"])
        ext = src.suffix or ".mp4"
        dest = self._finalize_file(src, result["title"], result.get("id") or task.video_id, ext)
        size = dest.stat().st_size
        task.output_filename = dest.name
        task.downloaded_bytes = size
        task.total_bytes = size
        task.progress = 100.0
        self._cleanup_workdir(workdir)
        return dest

    # -- playlist ----------------------------------------------------------- #

    def _execute_playlist(self, task: Task) -> None:
        self._set_status(task, "fetching information")
        info = ytdlp_service.get_info(task.url)
        if info.get("type") != "playlist":
            raise ytdlp_service.DownloadError(
                "This URL is not a playlist. Use 'Download video' instead."
            )
        entries = info.get("entries") or []
        if not entries:
            raise ytdlp_service.DownloadError(
                "This playlist has no downloadable items."
            )

        playlist_id = "pl_" + hashlib.sha1(task.url.encode("utf-8")).hexdigest()[:12]
        task.playlist_id = playlist_id
        task.title = info["title"]
        task.item_count = len(entries)

        if info.get("thumbnail"):
            self._download_thumbnail(
                info["thumbnail"], settings.thumb_dir / f"playlist_{playlist_id}.jpg"
            )

        now = _now()
        existing = database.get_playlist(playlist_id)
        database.upsert_playlist({
            "playlist_id": playlist_id,
            "url": task.url,
            "title": info["title"],
            "channel": info.get("channel") or "",
            "thumbnail_path": f"playlist_{playlist_id}.jpg",
            "item_count": len(entries),
            "total_size": existing["total_size"] if existing else 0,
            "zip_path": existing["zip_path"] if existing else "",
            "status": "downloading",
            "created_at": existing["created_at"] if existing else now,
            "updated_at": now,
        })
        for i, e in enumerate(entries):
            database.upsert_playlist_item({
                "playlist_id": playlist_id,
                "item_index": i,
                "video_id": e.get("id") or "",
                "url": e.get("url") or "",
                "title": e.get("title") or f"Video {i + 1}",
                "duration": e.get("duration"),
                "status": "pending",
                "filename": "",
                "size": 0,
                "error": "",
            })

        task_base = settings.tmp_dir / task.task_id
        task_base.mkdir(parents=True, exist_ok=True)

        self._set_status(task, "downloading")
        succeeded_files: list[Path] = []
        total_size = 0
        new_items = 0

        items = database.get_playlist_items(playlist_id)
        for item in items:
            if task.cancel_requested:
                raise ytdlp_service.DownloadCancelled()

            task.item_index = item["item_index"] + 1
            task.current_item_title = item["title"]
            with self._lock:
                task.current_item_progress = 0.0
                task.version += 1

            # Skip items already downloaded whose file still exists.
            if item["status"] == "downloaded" and item["filename"]:
                f = settings.download_dir / item["filename"]
                if f.exists():
                    succeeded_files.append(f)
                    total_size += item["size"] or f.stat().st_size
                    task.completed_items += 1
                    continue

            item_workdir = task_base / str(item["item_index"])
            item_workdir.mkdir(parents=True, exist_ok=True)
            item_url = item["url"]
            if not item_url:
                database.update_playlist_item_status(
                    playlist_id, item_url or "", "failed", "", 0, "Missing video URL."
                )
                continue

            try:
                database.update_playlist_item_status(playlist_id, item_url, "downloading")
                result = ytdlp_service.download_video(
                    item_url,
                    task.format,
                    task.embed_subs,
                    item_workdir,
                    self._progress_hook(task),
                    self._cancelled(task),
                )
                if not result.get("filepath"):
                    raise ytdlp_service.DownloadError("No output file produced.")
                src = Path(result["filepath"])
                ext = src.suffix or ".mp4"
                dest = self._finalize_file(
                    src, result["title"], result.get("id") or item["video_id"], ext
                )
                size = dest.stat().st_size
                database.update_playlist_item_status(
                    playlist_id, item_url, "downloaded", dest.name, size, ""
                )
                succeeded_files.append(dest)
                total_size += size
                task.completed_items += 1
                new_items += 1
            except ytdlp_service.DownloadCancelled:
                raise
            except Exception as exc:  # noqa: BLE001
                msg = _friendly(exc)
                database.update_playlist_item_status(
                    playlist_id, item_url, "failed", "", 0, msg
                )
                task.error = msg
            finally:
                shutil.rmtree(item_workdir, ignore_errors=True)

            with self._lock:
                task.progress = round(
                    task.completed_items / max(task.item_count, 1) * 100, 1
                )
                task.current_item_progress = 0.0
                task.version += 1
            self._persist(task)

        # ZIP packaging.
        zip_name = ""
        if succeeded_files and not task.cancel_requested:
            zip_name = (
                f"{sanitize_filename(info['title'])} [{playlist_id}].zip"
            )
            zip_path = settings.download_dir / zip_name
            # Rebuild only when new items were added or the archive is missing;
            # a valid existing archive is never regenerated unless requested.
            need_zip = (new_items > 0) or (not zip_path.exists())
            if need_zip:
                self._set_status(task, "packaging zip")

                def zip_cb(_frac: float) -> None:
                    with self._lock:
                        task.version += 1

                zip_service.create_zip(succeeded_files, zip_path, zip_cb)
            task.output_filename = zip_name

        final_items = database.get_playlist_items(playlist_id)
        downloaded = [i for i in final_items if i["status"] == "downloaded"]
        failed = [i for i in final_items if i["status"] == "failed"]

        database.upsert_playlist({
            "playlist_id": playlist_id,
            "url": task.url,
            "title": info["title"],
            "channel": info.get("channel") or "",
            "thumbnail_path": f"playlist_{playlist_id}.jpg",
            "item_count": len(final_items),
            "total_size": total_size,
            "zip_path": zip_name,
            "status": "completed" if downloaded else "failed",
            "created_at": (database.get_playlist(playlist_id) or {}).get("created_at", now),
            "updated_at": _now(),
        })

        self._cleanup_workdir(task_base)

        if not downloaded:
            task.error = f"All {len(final_items)} items failed to download."
            task.progress = 0.0
            self._set_status(task, "failed")
        elif failed:
            task.error = f"{len(failed)} of {len(final_items)} items failed."
            task.progress = round(len(downloaded) / len(final_items) * 100, 1)
            self._set_status(task, "completed")
        else:
            task.progress = 100.0
            self._set_status(task, "completed")
        self._persist(task)

    # -- helpers ------------------------------------------------------------ #

    def _set_status(self, task: Task, status: str) -> None:
        with self._lock:
            task.status = status
            task.updated_at = _now()
            if status in TERMINAL_STATUSES:
                task.completed_at = task.updated_at
            task.version += 1
        self._persist(task)

    def _finish_failed(self, task: Task, message: str) -> None:
        task.error = message
        self._cleanup_workdir(settings.tmp_dir / task.task_id)
        self._finalize_playlist_on_terminal(task, "failed")
        self._set_status(task, "failed")

    def _finish_cancelled(self, task: Task) -> None:
        task.error = "Cancelled by user."
        self._cleanup_workdir(settings.tmp_dir / task.task_id)
        self._finalize_playlist_on_terminal(task, "cancelled")
        self._set_status(task, "cancelled")

    def _finalize_playlist_on_terminal(self, task: Task, status: str) -> None:
        """Keep playlist metadata consistent when a task ends unexpectedly."""
        if not task.playlist_id:
            return
        playlist = database.get_playlist(task.playlist_id)
        if playlist:
            database.upsert_playlist({
                **playlist,
                "status": status,
                "updated_at": _now(),
            })
        database.reset_downloading_items(task.playlist_id)

    def _progress_hook(self, task: Task) -> Callable[[dict], None]:
        def cb(data: dict) -> None:
            with self._lock:
                if data.get("status") == "downloading":
                    task.downloaded_bytes = data.get("downloaded_bytes", 0)
                    task.total_bytes = data.get("total_bytes", 0)
                    task.speed = data.get("speed", 0.0)
                    task.eta = data.get("eta", 0.0)
                    pct = data.get("percent", 0.0)
                    if task.operation_type == "playlist":
                        task.current_item_progress = pct
                        task.progress = round(
                            (task.completed_items + pct / 100.0)
                            / max(task.item_count, 1)
                            * 100,
                            1,
                        )
                    else:
                        task.progress = pct
                    task.status = "downloading"
                elif data.get("status") == "processing":
                    task.status = "processing"
                task.updated_at = _now()
                task.version += 1

        return cb

    def _cancelled(self, task: Task) -> Callable[[], bool]:
        return lambda: task.cancel_requested

    def _persist(self, task: Task) -> None:
        row = task._row()
        database.update_task(row)

    def _download_thumbnail(self, url: str, dest: Path) -> None:
        if not url or dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            req = urllib.request.Request(url, headers=_USER_AGENT)
            with urllib.request.urlopen(req, timeout=20) as resp, open(dest, "wb") as fh:
                shutil.copyfileobj(resp, fh)
        except Exception:
            dest.unlink(missing_ok=True)

    def _finalize_file(self, src: Path, title: str, video_id: str, ext: str) -> Path:
        stem = sanitize_filename(title)
        base = f"{stem} [{video_id}]" if video_id else stem
        dest = settings.download_dir / f"{base}{ext}"
        if dest.resolve() == src.resolve():
            return dest
        counter = 1
        while dest.exists():
            dest = settings.download_dir / f"{base} ({counter}){ext}"
            counter += 1
        shutil.move(str(src), str(dest))
        return dest

    def _cleanup_workdir(self, workdir: Path) -> None:
        shutil.rmtree(workdir, ignore_errors=True)

    @staticmethod
    def _task_from_row(row: dict) -> Task:
        return Task(
            task_id=row["task_id"],
            url=row["url"],
            title=row["title"],
            video_id=row["video_id"],
            operation_type=row["operation_type"],
            format=row["format"],
            embed_subs=bool(row["embed_subs"]),
            status=row["status"],
            progress=row["progress"],
            downloaded_bytes=row["downloaded_bytes"],
            total_bytes=row["total_bytes"],
            speed=row["speed"],
            eta=row["eta"],
            item_index=row["item_index"],
            item_count=row["item_count"],
            completed_items=row["completed_items"],
            current_item_title=row["current_item_title"],
            playlist_id=row["playlist_id"],
            output_filename=row["output_filename"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )


def _friendly(exc: Exception) -> str:
    import yt_dlp

    if isinstance(exc, ytdlp_service.DownloadError):
        return str(exc)
    if isinstance(exc, yt_dlp.utils.DownloadError):
        return ytdlp_service.friendly_error(exc)
    return f"Download failed: {exc}"


manager = TaskManager()
