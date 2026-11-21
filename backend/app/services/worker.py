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
from pathlib import Path
from typing import Any

from ..core.config import Settings
from ..core.db import Database
from . import assets as assets_service
from . import jobs as jobs_service
from . import ytdlp as ytdlp_service
from .storage import Storage, StorageError

logger = logging.getLogger("vidfetch.worker")

TERMINAL_JOB_STATUSES = frozenset({"ready", "failed", "cancelled"})
DEFAULT_POLL_INTERVAL = 0.5
DEFAULT_PROGRESS_INTERVAL = 1.0
MAX_WAIT_SECONDS = 600


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

        if job.get("kind", "video") != "video":
            await self.jobs.mark_failed(
                self.db, key, "Only single-video downloads are supported yet."
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
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.wait_timeout
        while loop.time() < deadline:
            if cancel.is_set():
                await self.jobs.mark_cancelled(self.db, job_id)
                return
            try:
                asset = await self.assets.get_asset(self.db, asset_id)
            except Exception:  # noqa: BLE001 - retry until the deadline
                logger.exception("Asset poll failed for job %s", job_id)
                asset = None
            status = (asset or {}).get("status")
            if status == "ready":
                await self.jobs.mark_ready(self.db, job_id, asset_id=asset_id)
                return
            if status == "failed":
                await self.jobs.mark_failed(
                    self.db,
                    job_id,
                    "The existing download of this video failed. Try again.",
                )
                return
            await asyncio.sleep(self.poll_interval)

        await self.jobs.mark_failed(
            self.db,
            job_id,
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
    ) -> None:
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
            await self.jobs.update_job(
                self.db,
                job_id,
                status="downloading",
                asset_id=asset.get("id"),
                error="",
                progress=0,
                current_item_title=info.get("title") or "",
            )
            flusher = asyncio.get_running_loop().create_task(
                self._flush_progress(job_id, state), name=f"progress-{job_id}"
            )
            renewer = asyncio.get_running_loop().create_task(
                self._renew_lease(asset_id), name=f"lease-{asset_id}"
            )

            result = await asyncio.to_thread(
                self.ytdlp.download_video,
                job.get("source_url", ""),
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
            await self._persist_progress(job_id, state)

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
            await self.jobs.mark_ready(
                self.db, job_id, asset_id=asset.get("id")
            )
        except self.ytdlp.DownloadCancelled:
            await self._fail_claimed(
                job_id, asset_id, asset_ready, "Download cancelled.", cancelled=True
            )
        except self.ytdlp.DownloadError as exc:
            await self._fail_claimed(
                job_id, asset_id, asset_ready, exc.message
            )
        except (OSError, StorageError) as exc:
            logger.warning("Storage failure for job %s: %s", job_id, type(exc).__name__)
            await self._fail_claimed(
                job_id,
                asset_id,
                asset_ready,
                "The downloaded file could not be stored. Check server storage "
                "and try again.",
            )
        except Exception:  # noqa: BLE001 - unexpected failure
            logger.exception("Download failed for job %s", job_id)
            await self._fail_claimed(
                job_id,
                asset_id,
                asset_ready,
                "The download failed unexpectedly. Try again.",
            )
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
    ) -> None:
        safe = self.ytdlp.redact_sensitive(message)[:500]
        if not asset_ready:
            try:
                await self.assets.mark_failed(self.db, asset_id, safe)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to mark asset %s failed", asset_id)
        if cancelled:
            await self.jobs.mark_cancelled(self.db, job_id)
        else:
            await self.jobs.mark_failed(self.db, job_id, safe)

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
        self, job_id: str, state: _ProgressState
    ) -> None:
        try:
            while True:
                await asyncio.sleep(self.progress_interval)
                await self._persist_progress(job_id, state)
        except asyncio.CancelledError:
            raise

    async def _persist_progress(
        self, job_id: str, state: _ProgressState
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
