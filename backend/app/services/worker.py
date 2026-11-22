"""Background download worker for the v2 video pipeline.

One ``Worker`` runs per backend process. It claims queued jobs with
``FOR UPDATE SKIP LOCKED``, resolves metadata, claims the shared media asset,
and downloads at most ``MAX_CONCURRENT_DOWNLOADS`` files at once. yt-dlp runs in
a thread (``asyncio.to_thread``) while database writes stay on the event loop.

Progress is kept in a lock-protected state object (yt-dlp calls the hook from a
worker thread) and flushed to the database at most once per second. Cancellation
uses a ``threading.Event`` so the yt-dlp progress hook aborts promptly from the
worker thread.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.config import Settings
from ..core.db import Database
from . import assets as assets_service
from . import jobs as jobs_service
from . import playlists as playlists_service
from . import ytdlp as ytdlp_service
from .options import options_hash
from .storage import Storage, StorageError

logger = logging.getLogger("vidfetch.worker")

TERMINAL_JOB_STATUSES = frozenset({"ready", "failed", "cancelled"})
DEFAULT_POLL_INTERVAL = 0.5
DEFAULT_PROGRESS_INTERVAL = 1.0
MAX_WAIT_SECONDS = 600


@dataclass
class _DownloadOutcome:
    """Result of one asset download attempt."""

    asset_id: str | None = None
    error: str = ""
    cancelled: bool = False


@dataclass
class _PlaylistProgress:
    """Progress context for one playlist item."""

    total: int
    completed: int
    position: int
    title: str


class _ProgressState:
    """Thread-safe progress snapshot shared with the yt-dlp hook."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status = "downloading"
        self._progress = 0.0
        self._downloaded = 0
        self._total = 0
        self._speed = 0.0
        self._eta: int | None = None
        self._dirty = False

    def update(self, payload: dict[str, Any]) -> None:
        with self._lock:
            status = payload.get("status")
            if status in ("downloading", "processing"):
                self._status = status
            percent = payload.get("percent")
            if percent is not None:
                try:
                    self._progress = round(
                        max(0.0, min(100.0, float(percent))), 2
                    )
                except (TypeError, ValueError):
                    pass
            for attribute, key in (
                ("_downloaded", "downloaded_bytes"),
                ("_total", "total_bytes"),
            ):
                value = payload.get(key)
                if value is not None:
                    try:
                        setattr(self, attribute, max(0, int(value)))
                    except (TypeError, ValueError):
                        pass
            speed = payload.get("speed")
            if speed is not None:
                try:
                    setattr(self, "_speed", max(0.0, float(speed)))
                except (TypeError, ValueError):
                    pass
            eta = payload.get("eta")
            if eta is not None:
                try:
                    value = int(eta)
                    self._eta = value if value >= 0 else None
                except (TypeError, ValueError):
                    pass
            self._dirty = True

    def snapshot(self) -> tuple[dict[str, Any], bool]:
        with self._lock:
            data = {
                "status": self._status,
                "progress": self._progress,
                "downloaded_bytes": self._downloaded,
                "total_bytes": self._total,
                "speed": self._speed,
                "eta_seconds": self._eta,
            }
            dirty = self._dirty
            self._dirty = False
            return data, dirty


class Worker:
    """Bounded async job runner around the yt-dlp service."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        storage: Storage,
        *,
        ytdlp: Any = None,
        jobs: Any = None,
        assets: Any = None,
        playlists: Any = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        progress_interval: float = DEFAULT_PROGRESS_INTERVAL,
        lease_renew_seconds: int | None = None,
        wait_timeout: int | None = None,
    ) -> None:
        self.settings = settings
        self.db = db
        self.storage = storage
        self.ytdlp = ytdlp or ytdlp_service
        self.jobs = jobs or jobs_service
        self.assets = assets or assets_service
        self.playlists = playlists or playlists_service
        self.poll_interval = max(0.001, float(poll_interval))
        self.progress_interval = max(0.001, float(progress_interval))
        self.lease_renew_seconds = (
            max(5, int(lease_renew_seconds))
            if lease_renew_seconds is not None
            else max(5, min(60, int(settings.job_lease_seconds) // 2))
        )
        self.wait_timeout = (
            max(1, int(wait_timeout))
            if wait_timeout is not None
            else min(MAX_WAIT_SECONDS, max(30, int(settings.job_lease_seconds)))
        )

        self._loop_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._cancel_events: dict[str, threading.Event] = {}
        self._started = False
        self._stop_event: asyncio.Event | None = None

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Recover stale jobs and start the dispatcher loop."""
        if self._started:
            return
        self._stop_event = asyncio.Event()
        self._started = True
        try:
            await self.jobs.recover_stale_jobs(
                self.db, self.settings.job_lease_seconds
            )
        except Exception:  # noqa: BLE001 - startup must not crash the app
            logger.exception("Stale job recovery failed")
        loop = asyncio.get_running_loop()
        self._loop_task = loop.create_task(
            self._run_loop(), name="vidfetch-worker"
        )

    async def stop(self) -> None:
        """Stop claiming jobs and abort active downloads."""
        if not self._started:
            return
        self._started = False
        if self._stop_event is not None:
            self._stop_event.set()
        for event in list(self._cancel_events.values()):
            event.set()
        if self._loop_task is not None:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
            self._loop_task = None
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._cancel_events.clear()

    @property
    def active_job_ids(self) -> set[str]:
        return set(self._cancel_events)

    async def request_cancel(self, job_id: Any) -> bool:
        """Cancel a queued job directly or signal an active download."""
        key = str(job_id)
        event = self._cancel_events.get(key)
        if event is not None:
            event.set()
            try:
                await self.jobs.update_job(self.db, key, cancel_requested=True)
            except Exception:  # noqa: BLE001 - the event is the critical part
                logger.exception("Failed to persist cancel_requested for %s", key)
            return True

        job = await self.jobs.get_job(self.db, key)
        if job is None:
            return False
        status = job.get("status")
        if status in TERMINAL_JOB_STATUSES:
            return False
        if status == "queued":
            await self.jobs.mark_cancelled(self.db, key)
        else:
            await self.jobs.update_job(self.db, key, cancel_requested=True)
        return True

    # -- dispatcher ---------------------------------------------------------

    async def _run_loop(self) -> None:
        stop_event = self._stop_event
        assert stop_event is not None
        while not stop_event.is_set():
            try:
                while len(self._tasks) < max(
                    1, int(self.settings.max_concurrent_downloads)
                ):
                    job = await self.jobs.claim_next_job(self.db)
                    if job is None:
                        break
                    task = asyncio.get_running_loop().create_task(
                        self._run_job_task(job),
                        name=f"vidfetch-job-{job.get('id')}",
                    )
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop must survive
                logger.exception("Worker claim loop failed")
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self.poll_interval
                )
            except asyncio.TimeoutError:
                continue

    async def _run_job_task(self, job: dict[str, Any]) -> None:
        key = str(job.get("id"))
        event = threading.Event()
        self._cancel_events[key] = event
        try:
            await self.process_job(job, cancel=event)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - last-resort job failure
            logger.exception("Unhandled error while processing job %s", key)
            try:
                await self.jobs.mark_failed(
                    self.db, key, "The download failed unexpectedly."
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to mark job %s as failed", key)
        finally:
            self._cancel_events.pop(key, None)

    # -- job flow -----------------------------------------------------------

    async def process_job(
        self, job: dict[str, Any], cancel: threading.Event | None = None
    ) -> None:
        """Run one video job to a terminal state.

        Exposed for tests; the dispatcher creates the cancellation event.
        """
        key = str(job.get("id"))
        event = cancel or threading.Event()

        if job.get("cancel_requested"):
            await self.jobs.mark_cancelled(self.db, key)
            return
        if event.is_set():
            await self.jobs.mark_cancelled(self.db, key)
            return

        kind = job.get("kind", "video")
        if kind == "playlist":
            await self._process_playlist(job, event)
            return
        if kind != "video":
            await self.jobs.mark_failed(
                self.db, key, "Playlist item retries are not available yet."
            )
            return

        try:
            info = await asyncio.to_thread(
                self.ytdlp.get_info, job.get("source_url", ""), self.settings
            )
        except self.ytdlp.DownloadCancelled:
            await self.jobs.mark_cancelled(self.db, key)
            return
        except self.ytdlp.DownloadError as exc:
            await self.jobs.mark_failed(self.db, key, exc.message)
            return
        except Exception:  # noqa: BLE001 - unexpected extraction failure
            logger.exception("Metadata extraction failed for job %s", key)
            await self.jobs.mark_failed(
                self.db, key, "Could not retrieve information for this URL."
            )
            return

        if event.is_set():
            await self.jobs.mark_cancelled(self.db, key)
            return

        if info.get("type") != "video":
            await self.jobs.mark_failed(
                self.db, key, "Only single-video downloads are supported yet."
            )
            return

        try:
            canonical = info.get("canonical_id") or self.assets.canonical_id(
                info.get("extractor_key") or "", str(info.get("id") or "")
            )
        except ValueError:
            canonical = ""
        if not canonical:
            await self.jobs.mark_failed(
                self.db, key, "Could not determine a stable identity for this video."
            )
            return

        title = info.get("title") or job.get("title") or "download"
        extractor_key = info.get("extractor_key") or ""
        duration = info.get("duration")
        try:
            await self.jobs.update_job(self.db, key, title=title)
        except Exception:  # noqa: BLE001 - title persistence is best effort
            logger.exception("Failed to persist the title for job %s", key)
        try:
            duration_seconds = int(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration_seconds = None

        try:
            claim = await self.assets.claim_asset(
                self.db,
                self.storage,
                canonical_id=canonical,
                extractor_key=extractor_key,
                source_url=job.get("source_url", ""),
                title=title,
                duration_seconds=duration_seconds,
                options_hash=job.get("options_hash", ""),
                format_selector=job.get("format_selector", ""),
                lease_seconds=self.settings.job_lease_seconds,
            )
        except Exception:  # noqa: BLE001 - DB failure must fail the job cleanly
            logger.exception("Asset claim failed for job %s", key)
            await self.jobs.mark_failed(
                self.db, key, "The media cache is temporarily unavailable."
            )
            return

        if claim.cache_hit:
            await self.jobs.mark_ready(
                self.db, key, asset_id=claim.asset.get("id")
            )
            return

        if claim.wait:
            await self._wait_for_asset(key, claim.asset.get("id"), event)
            return

        await self._download_claimed(
            job, claim.asset, info, canonical, event
        )

    # -- playlist flow ------------------------------------------------------

    async def _process_playlist(
        self, job: dict[str, Any], cancel: threading.Event
    ) -> None:
        """Resolve a playlist, reconcile its items, and download each asset."""
        job_id = str(job.get("id"))
        try:
            info = await asyncio.to_thread(
                self.ytdlp.get_info, job.get("source_url", ""), self.settings
            )
        except self.ytdlp.DownloadCancelled:
            await self.jobs.mark_cancelled(self.db, job_id)
            return
        except self.ytdlp.DownloadError as exc:
            await self.jobs.mark_failed(self.db, job_id, exc.message)
            return
        except Exception:  # noqa: BLE001 - unexpected extraction failure
            logger.exception("Playlist extraction failed for job %s", job_id)
            await self.jobs.mark_failed(
                self.db,
                job_id,
                "Could not retrieve information for this playlist.",
            )
            return

        if cancel.is_set():
            await self.jobs.mark_cancelled(self.db, job_id)
            return

        if info.get("type") != "playlist":
            await self.jobs.mark_failed(
                self.db, job_id, "This URL is not a playlist."
            )
            return

        canonical = (info.get("canonical_id") or "").strip()
        if not canonical:
            try:
                canonical = self.assets.canonical_id(
                    info.get("extractor_key") or "",
                    str(info.get("id") or ""),
                )
            except ValueError:
                canonical = ""
        if not canonical:
            await self.jobs.mark_failed(
                self.db,
                job_id,
                "Could not determine a stable identity for this playlist.",
            )
            return

        title = info.get("title") or job.get("title") or "Playlist"
        channel = info.get("channel") or ""
        entries = [
            entry
            for entry in (info.get("entries") or [])
            if isinstance(entry, dict)
        ]
        fmt, embed_subs = self.ytdlp.parse_intent(
            job.get("format_selector", "")
        )
        playlist_options = (
            job.get("options_hash")
            or options_hash(fmt, embed_subs, {"kind": "playlist"})
        )

        try:
            playlist = await self.playlists.upsert_playlist(
                self.db,
                user_id=job.get("user_id"),
                canonical_id=canonical,
                source_url=job.get("source_url", ""),
                title=title,
                channel=channel,
                item_count=len(entries),
                options_hash=playlist_options,
                format_selector=job.get("format_selector", ""),
            )
        except Exception:  # noqa: BLE001 - DB failure must fail the job cleanly
            logger.exception("Playlist upsert failed for job %s", job_id)
            await self.jobs.mark_failed(
                self.db,
                job_id,
                "The playlist could not be saved. Try again.",
            )
            return

        playlist_id = playlist.get("id")
        if playlist_id is None:
            await self.jobs.mark_failed(
                self.db,
                job_id,
                "The playlist could not be saved. Try again.",
            )
            return

        if not cancel.is_set():
            cover = await self._fetch_playlist_cover(
                info, playlist_id, cancel
            )
            if cover:
                try:
                    await self.playlists.update_playlist(
                        self.db, playlist_id, thumbnail_path=cover
                    )
                except Exception:  # noqa: BLE001 - cover is best effort
                    logger.exception(
                        "Failed to store playlist cover for %s", playlist_id
                    )

        try:
            items = await self.playlists.replace_items(
                self.db,
                playlist_id,
                [
                    {
                        "canonical_id": entry.get("canonical_id") or "",
                        "source_url": entry.get("url") or "",
                        "title": entry.get("title") or "",
                        "duration_seconds": entry.get("duration"),
                    }
                    for entry in entries
                ],
            )
        except Exception:  # noqa: BLE001
            logger.exception("Playlist item reconciliation failed for %s", job_id)
            await self.jobs.mark_failed(
                self.db,
                job_id,
                "The playlist items could not be saved. Try again.",
            )
            return

        total = len(items)
        try:
            await self.playlists.update_playlist(
                self.db, playlist_id, status="downloading", item_count=total
            )
            await self.jobs.update_job(
                self.db,
                job_id,
                status="downloading",
                title=title,
                error="",
                progress=0,
                item_index=0,
                item_count=total,
                current_item_title="",
                current_item_progress=0,
                playlist_id=playlist_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to initialize playlist job %s", job_id)
            await self.jobs.mark_failed(
                self.db, job_id, "The playlist could not be started."
            )
            return

        if total == 0:
            message = "This playlist has no downloadable items."
            await self._finish_playlist_status(
                playlist_id, "failed", message
            )
            await self.jobs.mark_failed(self.db, job_id, message)
            return

        flat_thumbnails = {
            str(entry.get("canonical_id") or ""): entry.get("thumbnail")
            for entry in entries
            if entry.get("canonical_id")
        }
        successes = 0
        failures: list[str] = []
        cancelled = False

        for index, item in enumerate(items):
            position = int(item.get("position") or index + 1)
            item_title = item.get("title") or f"Item {position}"

            if cancel.is_set():
                cancelled = True
                await self._cancel_remaining_items(
                    playlist_id, items[index:]
                )
                break

            await self.jobs.update_job(
                self.db,
                job_id,
                status="downloading",
                item_index=position,
                item_count=total,
                current_item_title=item_title,
                current_item_progress=0,
                progress=round(successes / total * 100, 2),
            )
            try:
                await self.playlists.update_item(
                    self.db,
                    playlist_id,
                    position,
                    status="downloading",
                    error="",
                )
            except Exception:  # noqa: BLE001 - item status is best effort
                logger.exception(
                    "Failed to mark playlist item %s:%s downloading",
                    playlist_id,
                    position,
                )

            try:
                item_info = await self._resolve_playlist_item(
                    item,
                    cancel,
                    thumbnail=flat_thumbnails.get(
                        str(item.get("canonical_id") or "")
                    ),
                )
            except self.ytdlp.DownloadCancelled:
                cancelled = True
                await self._mark_item_cancelled(playlist_id, position)
                await self._cancel_remaining_items(
                    playlist_id, items[index + 1 :]
                )
                break
            except self.ytdlp.DownloadError as exc:
                message = self.ytdlp.redact_sensitive(exc.message)[:500]
                failures.append(message)
                await self._mark_item_failed(playlist_id, position, message)
                await self._update_playlist_job_progress(
                    job_id, position, total, successes
                )
                continue
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Failed to resolve playlist item %s:%s",
                    playlist_id,
                    position,
                )
                message = "Could not retrieve information for this video."
                failures.append(message)
                await self._mark_item_failed(playlist_id, position, message)
                await self._update_playlist_job_progress(
                    job_id, position, total, successes
                )
                continue

            if cancel.is_set():
                cancelled = True
                await self._mark_item_cancelled(playlist_id, position)
                await self._cancel_remaining_items(
                    playlist_id, items[index + 1 :]
                )
                break

            item_canonical = (item_info.get("canonical_id") or "").strip()
            if not item_canonical:
                try:
                    item_canonical = self.assets.canonical_id(
                        item_info.get("extractor_key") or "",
                        str(item_info.get("id") or ""),
                    )
                except ValueError:
                    item_canonical = ""
            if not item_canonical:
                message = "Could not determine a stable identity for this video."
                failures.append(message)
                await self._mark_item_failed(playlist_id, position, message)
                await self._update_playlist_job_progress(
                    job_id, position, total, successes
                )
                continue

            if (
                not item.get("canonical_id")
                or not item.get("source_url")
                or not item.get("title")
            ):
                try:
                    await self.playlists.update_item(
                        self.db,
                        playlist_id,
                        position,
                        status="downloading",
                        canonical_id=item_canonical,
                        source_url=(
                            item_info.get("webpage_url")
                            or item.get("source_url")
                            or ""
                        ),
                        title=item_info.get("title") or item_title,
                        duration_seconds=item_info.get("duration"),
                    )
                except Exception:  # noqa: BLE001 - metadata cache is best effort
                    logger.exception(
                        "Failed to cache metadata for playlist item %s:%s",
                        playlist_id,
                        position,
                    )

            source_url = (
                item_info.get("webpage_url")
                or item.get("source_url")
                or ""
            )
            duration = item_info.get("duration")
            if duration is None:
                duration = item.get("duration_seconds")
            try:
                duration_seconds = (
                    int(duration) if duration is not None else None
                )
            except (TypeError, ValueError):
                duration_seconds = None

            video_options = options_hash(
                fmt, embed_subs, {"kind": "video"}
            )
            try:
                claim = await self.assets.claim_asset(
                    self.db,
                    self.storage,
                    canonical_id=item_canonical,
                    extractor_key=item_info.get("extractor_key") or "",
                    source_url=source_url,
                    title=item_info.get("title") or item_title,
                    duration_seconds=duration_seconds,
                    options_hash=video_options,
                    format_selector=job.get("format_selector", ""),
                    lease_seconds=self.settings.job_lease_seconds,
                )
            except Exception:  # noqa: BLE001 - DB failure fails only this item
                logger.exception(
                    "Asset claim failed for playlist item %s:%s",
                    playlist_id,
                    position,
                )
                message = "The media cache is temporarily unavailable."
                failures.append(message)
                await self._mark_item_failed(playlist_id, position, message)
                await self._update_playlist_job_progress(
                    job_id, position, total, successes
                )
                continue

            if claim.cache_hit:
                successes += 1
                await self._mark_item_ready(
                    playlist_id,
                    position,
                    claim.asset.get("id"),
                    job_id,
                    total,
                    successes,
                )
                continue

            if claim.wait:
                await self.jobs.update_job(
                    self.db, job_id, status="processing"
                )
                state, message = await self._await_asset(
                    claim.asset.get("id"), cancel
                )
                if state == "ready":
                    successes += 1
                    await self._mark_item_ready(
                        playlist_id,
                        position,
                        claim.asset.get("id"),
                        job_id,
                        total,
                        successes,
                    )
                elif state == "cancelled":
                    cancelled = True
                    await self._mark_item_cancelled(playlist_id, position)
                    await self._cancel_remaining_items(
                        playlist_id, items[index + 1 :]
                    )
                    break
                else:
                    safe = self.ytdlp.redact_sensitive(message)[:500]
                    failures.append(safe)
                    await self._mark_item_failed(
                        playlist_id, position, safe
                    )
                    await self._update_playlist_job_progress(
                        job_id, position, total, successes
                    )
                continue

            progress_context = _PlaylistProgress(
                total=total,
                completed=successes,
                position=position,
                title=item_title,
            )
            outcome = await self._download_claimed(
                job,
                claim.asset,
                item_info,
                item_canonical,
                cancel,
                playlist=progress_context,
            )
            if outcome.cancelled:
                cancelled = True
                await self._mark_item_cancelled(
                    playlist_id, position, error=outcome.error
                )
                await self._cancel_remaining_items(
                    playlist_id, items[index + 1 :]
                )
                break
            if outcome.asset_id:
                successes += 1
                await self._mark_item_ready(
                    playlist_id,
                    position,
                    outcome.asset_id,
                    job_id,
                    total,
                    successes,
                )
            else:
                message = (
                    outcome.error or "The video could not be downloaded."
                )
                failures.append(message)
                await self._mark_item_failed(
                    playlist_id, position, message
                )
                await self._update_playlist_job_progress(
                    job_id, position, total, successes
                )

        if cancelled:
            await self._finish_playlist_status(
                playlist_id, "cancelled", ""
            )
            await self.jobs.mark_cancelled(self.db, job_id)
            return

        if successes == 0:
            summary = self._failure_summary(failures, total)
            await self._finish_playlist_status(
                playlist_id, "failed", summary
            )
            await self.jobs.mark_failed(self.db, job_id, summary)
            return

        playlist_status = "partial" if failures else "ready"
        note = self._failure_summary(failures, total) if failures else ""
        await self._finish_playlist_status(
            playlist_id, playlist_status, note
        )
        await self.jobs.update_job(
            self.db,
            job_id,
            status="ready",
            progress=100,
            item_index=total,
            item_count=total,
            current_item_title="",
            current_item_progress=100,
            error=note,
            completed_at=datetime.now(timezone.utc),
        )

    async def _resolve_playlist_item(
        self,
        item: dict[str, Any],
        cancel: threading.Event,
        *,
        thumbnail: str | None = None,
    ) -> dict[str, Any]:
        """Return enough video metadata to claim and download one item.

        Flat entries often already carry their canonical id. In that case no
        extra network extraction is needed; otherwise the item URL is resolved
        lazily and the result is cached on the playlist item.
        """
        source_url = str(item.get("source_url") or "").strip()
        canonical = str(item.get("canonical_id") or "").strip()

        if canonical and source_url:
            extractor_key, _, media_id = canonical.partition(":")
            return {
                "type": "video",
                "id": media_id or None,
                "title": item.get("title") or "download",
                "canonical_id": canonical,
                "extractor_key": extractor_key,
                "duration": item.get("duration_seconds"),
                "thumbnail": thumbnail,
                "webpage_url": source_url,
            }

        if not source_url:
            raise self.ytdlp.DownloadError(
                "This playlist item has no source URL.", code="item_failed"
            )

        info = await asyncio.to_thread(
            self.ytdlp.get_info, source_url, self.settings
        )
        if cancel.is_set():
            raise self.ytdlp.DownloadCancelled()
        if info.get("type") != "video":
            raise self.ytdlp.DownloadError(
                "This playlist item is not a video.", code="item_failed"
            )
        return info

    async def _mark_item_ready(
        self,
        playlist_id: Any,
        position: int,
        asset_id: Any,
        job_id: str,
        total: int,
        successes: int,
    ) -> None:
        try:
            await self.playlists.update_item(
                self.db,
                playlist_id,
                position,
                status="ready",
                asset_id=asset_id,
                error="",
            )
        except Exception:  # noqa: BLE001 - job completion can still proceed
            logger.exception(
                "Failed to mark playlist item %s:%s ready",
                playlist_id,
                position,
            )
        progress = round(successes / total * 100, 2) if total else 100
        await self.jobs.update_job(
            self.db,
            job_id,
            progress=progress,
            item_index=position,
            item_count=total,
            current_item_progress=100,
        )

    async def _mark_item_failed(
        self, playlist_id: Any, position: int, message: str
    ) -> None:
        safe = self.ytdlp.redact_sensitive(message)[:500]
        try:
            await self.playlists.update_item(
                self.db,
                playlist_id,
                position,
                status="failed",
                error=safe,
            )
        except Exception:  # noqa: BLE001 - continue with other items
            logger.exception(
                "Failed to mark playlist item %s:%s failed",
                playlist_id,
                position,
            )

    async def _mark_item_cancelled(
        self, playlist_id: Any, position: int, *, error: str = ""
    ) -> None:
        try:
            await self.playlists.update_item(
                self.db,
                playlist_id,
                position,
                status="cancelled",
                error=self.ytdlp.redact_sensitive(error)[:500],
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to mark playlist item %s:%s cancelled",
                playlist_id,
                position,
            )

    async def _cancel_remaining_items(
        self, playlist_id: Any, items: list[dict[str, Any]]
    ) -> None:
        for item in items:
            if item.get("status") == "ready":
                continue
            position = int(item.get("position") or 0)
            if position <= 0:
                continue
            await self._mark_item_cancelled(playlist_id, position)

    async def _update_playlist_job_progress(
        self, job_id: str, position: int, total: int, successes: int
    ) -> None:
        progress = round(successes / total * 100, 2) if total else 0
        await self.jobs.update_job(
            self.db,
            job_id,
            progress=progress,
            item_index=position,
            item_count=total,
            current_item_progress=0,
        )

    async def _finish_playlist_status(
        self, playlist_id: Any, status: str, error: str
    ) -> None:
        try:
            await self.playlists.update_playlist(
                self.db, playlist_id, status=status
            )
        except Exception:  # noqa: BLE001 - job status still matters
            logger.exception(
                "Failed to mark playlist %s as %s", playlist_id, status
            )
        if error:
            logger.info("Playlist %s finished %s: %s", playlist_id, status, error)

    @staticmethod
    def _failure_summary(failures: list[str], total: int) -> str:
        if not failures:
            return ""
        summary = f"{len(failures)} of {total} items failed."
        first = failures[0].strip()
        if first:
            summary = f"{summary} {first}"
        return summary[:500]

    async def _fetch_playlist_cover(
        self, info: dict[str, Any], playlist_id: Any, cancel: threading.Event
    ) -> str | None:
        url = info.get("thumbnail")
        if not url or cancel.is_set():
            return None
        try:
            relative = playlists_service.playlist_cover_path(playlist_id)
            destination = self.storage.validate_relative_path(relative)
        except (ValueError, StorageError):
            return None
        try:
            downloaded = await asyncio.to_thread(
                self.ytdlp.download_thumbnail,
                url,
                destination,
                self.settings,
            )
        except Exception:  # noqa: BLE001 - covers are optional
            logger.exception(
                "Playlist cover download failed for %s", playlist_id
            )
            return None
        return relative if downloaded else None

    # -- waiting on another download ---------------------------------------

    async def _wait_for_asset(
        self, job_id: str, asset_id: Any, cancel: threading.Event
    ) -> None:
        if asset_id is None:
            await self.jobs.mark_failed(
                self.db, job_id, "The media cache is temporarily unavailable."
            )
            return
        await self.jobs.update_job(self.db, job_id, status="processing")
        state, message = await self._await_asset(asset_id, cancel)
        if state == "ready":
            await self.jobs.mark_ready(self.db, job_id, asset_id=asset_id)
        elif state == "cancelled":
            await self.jobs.mark_cancelled(self.db, job_id)
        else:
            await self.jobs.mark_failed(self.db, job_id, message)

    async def _await_asset(
        self, asset_id: Any, cancel: threading.Event
    ) -> tuple[str, str]:
        """Poll a processing asset and report ready/failed/cancelled."""
        if asset_id is None:
            return (
                "failed",
                "The media cache is temporarily unavailable.",
            )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.wait_timeout
        while loop.time() < deadline:
            if cancel.is_set():
                return "cancelled", "Download cancelled."
            try:
                asset = await self.assets.get_asset(self.db, asset_id)
            except Exception:  # noqa: BLE001 - retry until the deadline
                logger.exception("Asset poll failed for %s", asset_id)
                asset = None
            status = (asset or {}).get("status")
            if status == "ready":
                return "ready", ""
            if status == "failed":
                return (
                    "failed",
                    "The existing download of this video failed. Try again.",
                )
            await asyncio.sleep(self.poll_interval)

        return (
            "failed",
            "Timed out waiting for an existing download of this video.",
        )

    # -- downloading --------------------------------------------------------

    async def _download_claimed(
        self,
        job: dict[str, Any],
        asset: dict[str, Any],
        info: dict[str, Any],
        canonical: str,
        cancel: threading.Event,
        *,
        playlist: _PlaylistProgress | None = None,
    ) -> _DownloadOutcome:
        job_id = str(job.get("id"))
        asset_id = str(asset.get("id"))
        fmt, embed_subs = self.ytdlp.parse_intent(
            job.get("format_selector", "")
        )

        workdir = self.storage.root / ".tmp" / self._safe_job_dir(job_id)
        state = _ProgressState()
        flusher: asyncio.Task[None] | None = None
        renewer: asyncio.Task[None] | None = None
        asset_ready = False
        try:
            workdir.mkdir(parents=True, exist_ok=True)
            fields: dict[str, Any] = {
                "status": "downloading",
                "error": "",
                "progress": 0,
                "current_item_title": info.get("title") or "",
            }
            if playlist is None:
                fields["asset_id"] = asset.get("id")
            else:
                fields.update(
                    {
                        "item_index": playlist.position,
                        "item_count": playlist.total,
                        "current_item_progress": 0,
                    }
                )
            await self.jobs.update_job(self.db, job_id, **fields)
            flusher = asyncio.get_running_loop().create_task(
                self._flush_progress(job_id, state, playlist),
                name=f"progress-{job_id}",
            )
            renewer = asyncio.get_running_loop().create_task(
                self._renew_lease(asset_id), name=f"lease-{asset_id}"
            )

            download_url = job.get("source_url", "")
            if playlist is not None:
                download_url = (
                    info.get("webpage_url")
                    or info.get("original_url")
                    or download_url
                )
            result = await asyncio.to_thread(
                self.ytdlp.download_video,
                download_url,
                fmt,
                embed_subs,
                workdir,
                state.update,
                cancel.is_set,
                self.settings,
            )

            if cancel.is_set():
                raise self.ytdlp.DownloadCancelled()

            await self._stop_task(flusher)
            flusher = None
            await self._persist_progress(job_id, state, playlist)

            source = Path(result["filepath"])
            title = result.get("title") or info.get("title") or "download"
            extension = (
                result.get("ext")
                or source.suffix.lstrip(".")
                or "mp4"
            )
            final_path = self.storage.final_path(
                asset_id, title, canonical, extension
            )
            self.storage.atomic_finalize(source, final_path)
            relative = final_path.relative_to(self.storage.root).as_posix()
            size = final_path.stat().st_size
            extension = final_path.suffix.lstrip(".").lower() or extension

            thumbnail_path = await self._fetch_thumbnail(
                info, asset_id, cancel
            )

            await self.assets.mark_ready(
                self.db,
                asset_id,
                file_path=relative,
                file_size_bytes=size,
                output_ext=extension,
                thumbnail_path=thumbnail_path,
            )
            asset_ready = True
            if playlist is None:
                await self.jobs.mark_ready(
                    self.db, job_id, asset_id=asset.get("id")
                )
            return _DownloadOutcome(asset_id=asset_id)
        except self.ytdlp.DownloadCancelled:
            message = await self._fail_claimed(
                job_id,
                asset_id,
                asset_ready,
                "Download cancelled.",
                cancelled=True,
                fail_job=playlist is None,
            )
            return _DownloadOutcome(error=message, cancelled=True)
        except self.ytdlp.DownloadError as exc:
            message = await self._fail_claimed(
                job_id,
                asset_id,
                asset_ready,
                exc.message,
                fail_job=playlist is None,
            )
            return _DownloadOutcome(error=message)
        except (OSError, StorageError) as exc:
            logger.warning("Storage failure for job %s: %s", job_id, type(exc).__name__)
            message = await self._fail_claimed(
                job_id,
                asset_id,
                asset_ready,
                "The downloaded file could not be stored. Check server storage "
                "and try again.",
                fail_job=playlist is None,
            )
            return _DownloadOutcome(error=message)
        except Exception:  # noqa: BLE001 - unexpected failure
            logger.exception("Download failed for job %s", job_id)
            message = await self._fail_claimed(
                job_id,
                asset_id,
                asset_ready,
                "The download failed unexpectedly. Try again.",
                fail_job=playlist is None,
            )
            return _DownloadOutcome(error=message)
        finally:
            await self._stop_task(flusher)
            await self._stop_task(renewer)
            shutil.rmtree(workdir, ignore_errors=True)

    async def _fail_claimed(
        self,
        job_id: str,
        asset_id: str,
        asset_ready: bool,
        message: str,
        *,
        cancelled: bool = False,
        fail_job: bool = True,
    ) -> str:
        safe = self.ytdlp.redact_sensitive(message)[:500]
        if not asset_ready:
            try:
                await self.assets.mark_failed(self.db, asset_id, safe)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to mark asset %s failed", asset_id)
        if fail_job:
            if cancelled:
                await self.jobs.mark_cancelled(self.db, job_id)
            else:
                await self.jobs.mark_failed(self.db, job_id, safe)
        return safe

    async def _fetch_thumbnail(
        self, info: dict[str, Any], asset_id: str, cancel: threading.Event
    ) -> str | None:
        url = info.get("thumbnail")
        if not url or cancel.is_set():
            return None
        relative = f"thumbnails/{asset_id}.jpg"
        try:
            destination = self.storage.validate_relative_path(relative)
        except (StorageError, ValueError):
            return None
        try:
            downloaded = await asyncio.to_thread(
                self.ytdlp.download_thumbnail,
                url,
                destination,
                self.settings,
            )
        except Exception:  # noqa: BLE001 - thumbnails are optional
            logger.exception("Thumbnail download failed for asset %s", asset_id)
            return None
        return relative if downloaded else None

    # -- progress and leases ------------------------------------------------

    async def _flush_progress(
        self,
        job_id: str,
        state: _ProgressState,
        playlist: _PlaylistProgress | None = None,
    ) -> None:
        try:
            while True:
                await asyncio.sleep(self.progress_interval)
                await self._persist_progress(job_id, state, playlist)
        except asyncio.CancelledError:
            raise

    async def _persist_progress(
        self,
        job_id: str,
        state: _ProgressState,
        playlist: _PlaylistProgress | None = None,
    ) -> None:
        data, dirty = state.snapshot()
        if not dirty:
            return
        fields: dict[str, Any] = {
            "status": data["status"],
            "progress": data["progress"],
            "downloaded_bytes": data["downloaded_bytes"],
            "total_bytes": data["total_bytes"],
            "speed": data["speed"],
        }
        if playlist is not None:
            item_progress = float(data["progress"])
            overall = 0.0
            if playlist.total > 0:
                overall = (
                    playlist.completed + item_progress / 100.0
                ) / playlist.total * 100.0
            fields.update(
                {
                    "progress": round(min(100.0, max(0.0, overall)), 2),
                    "item_index": playlist.position,
                    "item_count": playlist.total,
                    "current_item_title": playlist.title,
                    "current_item_progress": round(
                        min(100.0, max(0.0, item_progress)), 2
                    ),
                }
            )
        if data["eta_seconds"] is not None:
            fields["eta_seconds"] = data["eta_seconds"]
        try:
            await self.jobs.update_job(self.db, job_id, **fields)
        except Exception:  # noqa: BLE001 - progress is best effort
            logger.exception("Failed to persist progress for job %s", job_id)

    async def _renew_lease(self, asset_id: str) -> None:
        try:
            while True:
                await asyncio.sleep(self.lease_renew_seconds)
                try:
                    await self.assets.renew_lease(
                        self.db, asset_id, self.settings.job_lease_seconds
                    )
                except Exception:  # noqa: BLE001 - keep trying
                    logger.exception("Failed to renew lease for asset %s", asset_id)
        except asyncio.CancelledError:
            raise

    @staticmethod
    async def _stop_task(task: asyncio.Task[None] | None) -> None:
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    @staticmethod
    def _safe_job_dir(job_id: str) -> str:
        """Keep the temp directory name safe even for odd job identifiers."""
        candidate = "".join(
            character
            for character in str(job_id)
            if character.isalnum() or character in "-_."
        )
        return candidate or "job"
