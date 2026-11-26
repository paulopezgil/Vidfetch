"""Tests for the download worker's job flow (fake queue, fake yt-dlp, real disk)."""
from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.services import assets as assets_service
from backend.app.services import ytdlp as ytdlp_service
from backend.app.services.storage import Storage
from backend.app.services.worker import Worker
from backend.tests.v2.fakes import asset_row, job_row, make_settings

INFO = {
    "type": "video",
    "id": "vid1",
    "title": "Clip",
    "canonical_id": "youtube:vid1",
    "extractor_key": "youtube",
    "duration": 12,
    "channel": "Clip channel",
    "thumbnail": None,
}


def run(coro):
    return asyncio.run(coro)


class RecordingJobs:
    def __init__(self, rows=None):
        self.rows = {str(row["id"]): dict(row) for row in (rows or [])}
        self.updates: list[tuple[str, dict]] = []
        self.claims = deque()
        self.recovered = 0

    async def recover_stale_jobs(self, db, lease_seconds):
        self.recovered += 1
        return 0

    async def claim_next_job(self, db):
        return self.claims.popleft() if self.claims else None

    async def get_job(self, db, job_id, user_id=None):
        return self.rows.get(str(job_id))

    async def update_job(self, db, job_id, **fields):
        key = str(job_id)
        self.updates.append((key, dict(fields)))
        self.rows.setdefault(key, job_row(job_id=key)).update(fields)
        return self.rows[key]

    async def mark_ready(self, db, job_id, *, asset_id=None):
        fields = {"status": "ready"}
        if asset_id is not None:
            fields["asset_id"] = asset_id
        return await self.update_job(db, job_id, **fields)

    async def mark_failed(self, db, job_id, message):
        return await self.update_job(
            db, job_id, status="failed", error=message
        )

    async def mark_cancelled(self, db, job_id):
        return await self.update_job(
            db, job_id, status="cancelled", cancel_requested=True
        )


class RecordingAssets:
    def __init__(self, claim):
        self.claim = claim
        self.claim_kwargs = None
        self.ready: list[tuple[str, dict]] = []
        self.failed: list[tuple[str, str]] = []
        self.renewals = 0
        self.current = None
        self.claim_calls = 0

    async def claim_asset(self, db, storage, **kwargs):
        self.claim_calls += 1
        self.claim_kwargs = kwargs
        return self.claim

    async def mark_ready(self, db, asset_id, **fields):
        self.ready.append((str(asset_id), dict(fields)))

    async def mark_failed(self, db, asset_id, message):
        self.failed.append((str(asset_id), message))

    async def get_asset(self, db, asset_id):
        return self.current

    async def renew_lease(self, db, asset_id, lease_seconds):
        self.renewals += 1

    @staticmethod
    def canonical_id(extractor_key, media_id):
        return assets_service.canonical_id(extractor_key, media_id)


def _fake_ytdlp(*, info=None, download=None, thumbnail=None):
    return SimpleNamespace(
        get_info=info or (lambda url, settings: dict(INFO)),
        download_video=download,
        download_thumbnail=thumbnail or (lambda url, dest, settings: False),
        parse_intent=ytdlp_service.parse_intent,
        redact_sensitive=ytdlp_service.redact_sensitive,
        DownloadError=ytdlp_service.DownloadError,
        DownloadCancelled=ytdlp_service.DownloadCancelled,
    )


def _storage(tmp_path) -> Storage:
    storage = Storage(tmp_path / "downloads")
    storage.ensure_directories()
    return storage


def _worker(tmp_path, jobs, assets, ytdlp):
    settings = make_settings(tmp_path)
    return Worker(
        settings,
        db=None,
        storage=_storage(tmp_path),
        ytdlp=ytdlp,
        jobs=jobs,
        assets=assets,
        poll_interval=0.01,
        progress_interval=0.01,
        lease_renew_seconds=30,
        wait_timeout=2,
    )


def _writing_download(body: bytes = b"0123456789", progress=None):
    def download(url, fmt, embed_subs, workdir, progress_cb, cancel, settings, album="", cover=None):
        if progress:
            progress(progress_cb, cancel)
        path = Path(workdir) / "vid1.mp4"
        path.write_bytes(body)
        return {
            "id": "vid1",
            "title": "Clip",
            "filepath": str(path),
            "thumbnail": None,
            "ext": "mp4",
            "canonical_id": "youtube:vid1",
            "extractor_key": "youtube",
        }

    return download


# ---------------------------------------------------------------------------
# cache hit / wait
# ---------------------------------------------------------------------------


def test_cache_hit_marks_job_ready_without_downloading(tmp_path):
    job = job_row()
    jobs = RecordingJobs([job])
    asset = asset_row(status="ready")
    assets = RecordingAssets(
        assets_service.AssetClaim(asset=asset, cache_hit=True)
    )
    download_calls: list = []
    worker = _worker(
        tmp_path,
        jobs,
        assets,
        _fake_ytdlp(download=lambda *args, **kwargs: download_calls.append(args)),
    )

    run(worker.process_job(job))

    assert jobs.rows[str(job["id"])]["status"] == "ready"
    assert jobs.rows[str(job["id"])]["asset_id"] == asset["id"]
    assert jobs.rows[str(job["id"])]["title"] == "Clip"
    assert jobs.rows[str(job["id"])]["artist"] == "Clip channel"
    assert jobs.rows[str(job["id"])]["album"] == ""
    assert download_calls == []
    assert assets.claim_kwargs["canonical_id"] == "youtube:vid1"
    assert assets.claim_kwargs["options_hash"] == job["options_hash"]


def test_waits_for_another_job_then_marks_ready(tmp_path):
    job = job_row()
    jobs = RecordingJobs([job])
    asset = asset_row(status="processing")
    assets = RecordingAssets(
        assets_service.AssetClaim(asset=asset, wait=True)
    )
    assets.current = {**asset, "status": "ready"}
    worker = _worker(tmp_path, jobs, assets, _fake_ytdlp())

    run(worker.process_job(job))

    assert jobs.rows[str(job["id"])]["status"] == "ready"
    assert any(
        fields.get("status") == "processing"
        for _, fields in jobs.updates
    )


# ---------------------------------------------------------------------------
# claimed download success
# ---------------------------------------------------------------------------


def test_claimed_download_finalizes_file_asset_and_job(tmp_path):
    job = job_row()
    jobs = RecordingJobs([job])
    asset = asset_row(status="processing")
    assets = RecordingAssets(
        assets_service.AssetClaim(asset=asset, claimed=True)
    )
    worker = _worker(
        tmp_path, jobs, assets, _fake_ytdlp(download=_writing_download())
    )

    run(worker.process_job(job))

    assert jobs.rows[str(job["id"])]["status"] == "ready"
    assert jobs.rows[str(job["id"])]["artist"] == "Clip channel"
    assert jobs.rows[str(job["id"])]["album"] == ""
    assert len(assets.ready) == 1
    asset_id, fields = assets.ready[0]
    assert asset_id == str(asset["id"])
    final = worker.storage.validate_relative_path(fields["file_path"])
    assert final.read_bytes() == b"0123456789"
    assert fields["file_size_bytes"] == 10
    assert fields["output_ext"] == "mp4"
    assert fields["thumbnail_path"] is None
    assert not (worker.storage.root / ".tmp" / str(job["id"])).exists()
    assert assets.failed == []


def test_progress_is_persisted_at_most_once_per_interval(tmp_path):
    job = job_row()
    jobs = RecordingJobs([job])
    asset = asset_row(status="processing")
    assets = RecordingAssets(
        assets_service.AssetClaim(asset=asset, claimed=True)
    )

    def report(progress_cb, cancel):
        for step in range(1, 6):
            progress_cb(
                {
                    "status": "downloading",
                    "downloaded_bytes": step * 20,
                    "total_bytes": 100,
                    "speed": 1000.0,
                    "eta": 5,
                    "percent": step * 20,
                }
            )
            time.sleep(0.03)

    worker = _worker(
        tmp_path,
        jobs,
        assets,
        _fake_ytdlp(download=_writing_download(progress=report)),
    )

    run(worker.process_job(job))

    progress_updates = [
        fields
        for _, fields in jobs.updates
        if "progress" in fields and 0 < fields["progress"] < 100
    ]
    assert progress_updates, "expected at least one mid-download progress write"
    assert any(fields["downloaded_bytes"] > 0 for fields in progress_updates)
    assert all(fields["total_bytes"] == 100 for fields in progress_updates)
    assert jobs.rows[str(job["id"])]["status"] == "ready"


# ---------------------------------------------------------------------------
# failures and cancellation
# ---------------------------------------------------------------------------


def test_extraction_failure_marks_job_failed_without_claiming(tmp_path):
    job = job_row()
    jobs = RecordingJobs([job])
    assets = RecordingAssets(assets_service.AssetClaim(asset=asset_row()))

    def failing_info(url, settings):
        raise ytdlp_service.DownloadError("The video is unavailable.")

    worker = _worker(tmp_path, jobs, assets, _fake_ytdlp(info=failing_info))

    run(worker.process_job(job))

    assert jobs.rows[str(job["id"])]["status"] == "failed"
    assert jobs.rows[str(job["id"])]["error"] == "The video is unavailable."
    assert assets.claim_calls == 0


def test_download_failure_marks_asset_and_job_failed_and_cleans_tmp(tmp_path):
    job = job_row()
    jobs = RecordingJobs([job])
    asset = asset_row(status="processing")
    assets = RecordingAssets(
        assets_service.AssetClaim(asset=asset, claimed=True)
    )
    workdirs: list[Path] = []

    def failing_download(url, fmt, embed_subs, workdir, progress_cb, cancel, settings, album="", cover=None):
        workdirs.append(Path(workdir))
        raise ytdlp_service.DownloadError("Network error while contacting the site.")

    worker = _worker(tmp_path, jobs, assets, _fake_ytdlp(download=failing_download))

    run(worker.process_job(job))

    assert jobs.rows[str(job["id"])]["status"] == "failed"
    assert jobs.rows[str(job["id"])]["error"] == (
        "Network error while contacting the site."
    )
    assert assets.failed == [
        (str(asset["id"]), "Network error while contacting the site.")
    ]
    assert assets.ready == []
    assert workdirs and not workdirs[0].exists()


def test_job_with_cancel_requested_is_cancelled_before_resolving(tmp_path):
    job = job_row(cancel_requested=True)
    jobs = RecordingJobs([job])
    assets = RecordingAssets(assets_service.AssetClaim(asset=asset_row()))
    calls: list = []

    def info(url, settings):
        calls.append(url)
        return dict(INFO)

    worker = _worker(tmp_path, jobs, assets, _fake_ytdlp(info=info))

    run(worker.process_job(job))

    assert jobs.rows[str(job["id"])]["status"] == "cancelled"
    assert calls == []
    assert assets.claim_calls == 0


def test_active_download_is_cancelled_by_request_cancel(tmp_path):
    job = job_row()
    jobs = RecordingJobs([job])
    asset = asset_row(status="processing")
    assets = RecordingAssets(
        assets_service.AssetClaim(asset=asset, claimed=True)
    )
    started = threading.Event()

    def slow_download(url, fmt, embed_subs, workdir, progress_cb, cancel, settings, album="", cover=None):
        started.set()
        for _ in range(500):
            if cancel():
                raise ytdlp_service.DownloadCancelled()
            time.sleep(0.01)
        raise AssertionError("download was never cancelled")

    worker = _worker(tmp_path, jobs, assets, _fake_ytdlp(download=slow_download))

    async def scenario():
        task = asyncio.create_task(worker._run_job_task(job))
        while not started.is_set():
            await asyncio.sleep(0.01)
        cancelled = await worker.request_cancel(job["id"])
        await asyncio.wait_for(task, timeout=5)
        return cancelled

    assert run(scenario()) is True
    assert jobs.rows[str(job["id"])]["status"] == "cancelled"
    assert assets.failed == [(str(asset["id"]), "Download cancelled.")]


def test_request_cancel_marks_queued_job_cancelled(tmp_path):
    job = job_row(status="queued")
    jobs = RecordingJobs([job])
    worker = _worker(
        tmp_path,
        jobs,
        RecordingAssets(assets_service.AssetClaim(asset=asset_row())),
        _fake_ytdlp(),
    )

    assert run(worker.request_cancel(job["id"])) is True
    assert jobs.rows[str(job["id"])]["status"] == "cancelled"


# ---------------------------------------------------------------------------
# lifecycle / dispatcher
# ---------------------------------------------------------------------------


def test_start_recovers_stale_jobs_and_loop_processes_a_claimed_job(tmp_path):
    job = job_row()
    jobs = RecordingJobs([job])
    jobs.claims.append(job)
    asset = asset_row(status="ready")
    assets = RecordingAssets(
        assets_service.AssetClaim(asset=asset, cache_hit=True)
    )
    worker = _worker(tmp_path, jobs, assets, _fake_ytdlp())

    async def scenario():
        await worker.start()
        assert jobs.recovered == 1
        for _ in range(300):
            if jobs.rows[str(job["id"])]["status"] == "ready":
                break
            await asyncio.sleep(0.01)
        await worker.stop()
        return jobs.rows[str(job["id"])]["status"]

    assert run(scenario()) == "ready"


def test_start_is_idempotent_and_stop_is_clean(tmp_path):
    jobs = RecordingJobs([])
    worker = _worker(
        tmp_path,
        jobs,
        RecordingAssets(assets_service.AssetClaim(asset=asset_row())),
        _fake_ytdlp(),
    )

    async def scenario():
        await worker.start()
        await worker.start()
        assert worker._loop_task is not None
        await worker.stop()
        assert worker._loop_task is None
        await worker.stop()
        return jobs.recovered

    assert run(scenario()) == 1
