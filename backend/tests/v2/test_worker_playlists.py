"""Worker playlist pipeline: success, partial failure, cancellation, dedupe."""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from backend.app.services import assets as assets_service
from backend.app.services import ytdlp as ytdlp_service
from backend.app.services.options import options_hash
from backend.app.services.storage import Storage
from backend.app.services.worker import Worker
from backend.tests.v2.fakes import (
    asset_row,
    job_row,
    make_settings,
    playlist_item_row,
    playlist_row,
)

USER_ID = uuid4()
PLAYLIST_ID = uuid4()
PLAYLIST_HASH = "p" * 64


def run(coro):
    return asyncio.run(coro)


class RecordingJobs:
    def __init__(self, rows=None):
        self.rows = {str(row["id"]): dict(row) for row in (rows or [])}
        self.updates: list[tuple[str, dict]] = []
        self.item_jobs: list[dict] = []

    async def recover_stale_jobs(self, db, lease_seconds):
        return 0

    async def claim_next_job(self, db):
        return None

    async def get_job(self, db, job_id, user_id=None):
        return self.rows.get(str(job_id))

    async def update_job(self, db, job_id, **fields):
        key = str(job_id)
        self.updates.append((key, dict(fields)))
        self.rows.setdefault(key, job_row(job_id=key)).update(fields)
        return self.rows[key]

    async def record_playlist_item_job(self, db, **kwargs):
        existing = kwargs.get("job_id")
        key = str(existing) if existing is not None else None
        row = self.rows.get(key) if key is not None else None
        if row is None or row.get("kind") != "playlist_item":
            row = job_row(
                user_id=kwargs["user_id"],
                kind="playlist_item",
                playlist_id=kwargs["playlist_id"],
                status=kwargs["status"],
            )
            self.rows[str(row["id"])] = row
        row.update(
            {
                "kind": "playlist_item",
                "playlist_id": kwargs["playlist_id"],
                "source_url": kwargs["source_url"],
                "title": kwargs["title"],
                "options_hash": kwargs["options_hash"],
                "format_selector": kwargs["format_selector"],
                "status": kwargs["status"],
                "progress": 100 if kwargs["status"] == "ready" else 0,
                "asset_id": kwargs.get("asset_id"),
                "error": kwargs.get("error") or "",
                "artist": kwargs.get("artist") or "",
                "album": kwargs.get("album") or "",
                "item_index": kwargs.get("item_index") or 0,
                "item_count": kwargs.get("item_count") or 0,
            }
        )
        self.item_jobs.append(dict(row))
        return dict(row)

    async def mark_ready(self, db, job_id, *, asset_id=None):
        fields = {"status": "ready", "progress": 100, "error": ""}
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


class RecordingPlaylists:
    def __init__(self, entries):
        self.playlist = playlist_row(
            playlist_id=PLAYLIST_ID,
            user_id=USER_ID,
            canonical_id="youtube:PL1",
            title="List",
            item_count=len(entries),
            options_hash=PLAYLIST_HASH,
            status="pending",
        )
        self.items = []
        for position, entry in enumerate(entries, start=1):
            self.items.append(
                playlist_item_row(
                    playlist_id=PLAYLIST_ID,
                    position=position,
                    canonical_id=entry["canonical_id"],
                    source_url=entry["source_url"],
                    title=entry["title"],
                    channel=entry.get("channel") or "",
                    duration_seconds=entry.get("duration_seconds"),
                )
            )
        self.upsert_kwargs = None
        self.status_updates: list[dict] = []
        self.item_updates: list[tuple[int, dict]] = []

    async def upsert_playlist(self, db, **kwargs):
        self.upsert_kwargs = dict(kwargs)
        self.playlist.update(
            {
                "source_url": kwargs["source_url"],
                "title": kwargs["title"],
                "channel": kwargs["channel"],
                "item_count": kwargs["item_count"],
                "options_hash": kwargs["options_hash"],
                "format_selector": kwargs["format_selector"],
            }
        )
        return dict(self.playlist)

    async def update_playlist(self, db, playlist_id, **fields):
        self.status_updates.append(dict(fields))
        self.playlist.update(fields)
        return dict(self.playlist)

    async def replace_items(self, db, playlist_id, entries):
        return [dict(item) for item in self.items]

    async def update_item(self, db, playlist_id, position, **fields):
        self.item_updates.append((position, dict(fields)))
        for item in self.items:
            if item["position"] == position:
                item.update(fields)
                return dict(item)
        return None

    async def list_items(self, db, playlist_id):
        return [dict(item) for item in self.items]


class PlaylistAssets:
    def __init__(self, *, ready_canonicals=()):
        self.ready_canonicals = set(ready_canonicals)
        self.ready_assets = {
            canonical: asset_row(
                asset_id=uuid4(),
                canonical_id=canonical,
                status="ready",
                file_path=f"assets/{uuid4()}/ready.mp4",
                file_size_bytes=1,
            )
            for canonical in self.ready_canonicals
        }
        self.assets: dict[str, dict] = {}
        self.claim_kwargs: list[dict] = []
        self.ready: list[tuple[str, dict]] = []
        self.failed: list[tuple[str, str]] = []
        self.renewals = 0

    async def claim_asset(self, db, storage, **kwargs):
        self.claim_kwargs.append(dict(kwargs))
        canonical = kwargs["canonical_id"]
        if canonical in self.ready_canonicals:
            return assets_service.AssetClaim(
                asset=self.ready_assets[canonical], cache_hit=True
            )
        asset = self.assets.get(canonical)
        if asset is None:
            asset = asset_row(
                asset_id=uuid4(),
                canonical_id=canonical,
                extractor_key=kwargs["extractor_key"],
                title=kwargs["title"],
                options_hash=kwargs["options_hash"],
                status="processing",
            )
            self.assets[canonical] = asset
        return assets_service.AssetClaim(asset=asset, claimed=True)

    async def mark_ready(self, db, asset_id, **fields):
        self.ready.append((str(asset_id), dict(fields)))

    async def mark_failed(self, db, asset_id, message):
        self.failed.append((str(asset_id), message))

    async def get_asset(self, db, asset_id):
        for asset in self.assets.values():
            if str(asset["id"]) == str(asset_id):
                return asset
        for asset in self.ready_assets.values():
            if str(asset["id"]) == str(asset_id):
                return asset
        return None

    async def renew_lease(self, db, asset_id, lease_seconds):
        self.renewals += 1

    @staticmethod
    def canonical_id(extractor_key, media_id):
        return assets_service.canonical_id(extractor_key, media_id)


def playlist_info(entries, *, thumbnail=None):
    return {
        "type": "playlist",
        "id": "PL1",
        "title": "List",
        "canonical_id": "youtube:PL1",
        "extractor_key": "youtube",
        "channel": "Channel",
        "thumbnail": thumbnail,
        "entries": [
            {
                "id": entry["canonical_id"].split(":", 1)[1],
                "title": entry["title"],
                "url": entry["source_url"],
                "canonical_id": entry["canonical_id"],
                "channel": entry.get("channel") or "",
                "duration": entry.get("duration_seconds"),
                "thumbnail": entry.get("thumbnail"),
            }
            for entry in entries
        ],
        "item_count": len(entries),
        "truncated": False,
    }


def _fake_ytdlp(*, info, download, thumbnail=None):
    return SimpleNamespace(
        get_info=info,
        download_video=download,
        download_thumbnail=thumbnail
        or (lambda url, dest, settings: False),
        parse_intent=ytdlp_service.parse_intent,
        redact_sensitive=ytdlp_service.redact_sensitive,
        DownloadError=ytdlp_service.DownloadError,
        DownloadCancelled=ytdlp_service.DownloadCancelled,
    )


def _writing_download(fail_urls=(), cancel_event=None, before=None):
    calls: list[str] = []

    def download(
        url,
        fmt,
        embed_subs,
        workdir,
        progress_cb,
        cancel,
        settings,
        album="",
        cover=None,
    ):
        calls.append(url)
        if before is not None:
            before(url)
        if cancel_event is not None and url.endswith("/v2"):
            cancel_event.set()
            raise ytdlp_service.DownloadCancelled()
        if any(url.endswith(suffix) for suffix in fail_urls):
            raise ytdlp_service.DownloadError(
                "Network error while contacting the site."
            )
        path = Path(workdir) / "video.mp4"
        path.write_bytes(f"bytes:{url}".encode("utf-8"))
        return {
            "id": url.rsplit("/", 1)[-1],
            "title": f"Video {url.rsplit('/', 1)[-1]}",
            "filepath": str(path),
            "thumbnail": None,
            "ext": "mp4",
            "canonical_id": "",
            "extractor_key": "youtube",
        }

    download.calls = calls
    return download


def _worker(tmp_path, jobs, playlists, assets, ytdlp):
    settings = make_settings(tmp_path)
    storage = Storage(settings.download_dir)
    storage.ensure_directories()
    return Worker(
        settings,
        db=None,
        storage=storage,
        ytdlp=ytdlp,
        jobs=jobs,
        assets=assets,
        playlists=playlists,
        poll_interval=0.01,
        progress_interval=0.01,
        lease_renew_seconds=30,
        wait_timeout=2,
    )


def _entries(count, *, channels=None):
    channels = channels or {}
    return [
        {
            "canonical_id": f"youtube:vid{position}",
            "source_url": f"https://example.test/v{position}",
            "title": f"Clip {position}",
            "channel": channels.get(position, ""),
            "duration_seconds": 10,
        }
        for position in range(1, count + 1)
    ]


def _playlist_job():
    return job_row(
        user_id=USER_ID,
        kind="playlist",
        source_url="https://example.test/list",
        options_hash=PLAYLIST_HASH,
        format_selector="720p",
        status="resolving",
    )


def test_playlist_success_downloads_every_item_and_links_assets(tmp_path):
    entries = _entries(2)
    job = _playlist_job()
    jobs = RecordingJobs([job])
    playlists = RecordingPlaylists(entries)
    assets = PlaylistAssets()
    ytdlp = _fake_ytdlp(
        info=lambda url, settings: playlist_info(entries),
        download=_writing_download(),
    )
    worker = _worker(tmp_path, jobs, playlists, assets, ytdlp)

    run(worker.process_job(job))

    assert playlists.upsert_kwargs["user_id"] == USER_ID
    assert playlists.upsert_kwargs["canonical_id"] == "youtube:PL1"
    assert playlists.upsert_kwargs["item_count"] == 2
    assert playlists.upsert_kwargs["options_hash"] == PLAYLIST_HASH
    assert playlists.playlist["status"] == "ready"

    assert [item["status"] for item in playlists.items] == ["ready", "ready"]
    assert all(item["asset_id"] for item in playlists.items)
    assert assets.failed == []
    assert len(assets.ready) == 2
    for _, fields in assets.ready:
        path = worker.storage.validate_relative_path(fields["file_path"])
        assert path.is_file()

    # Each successful item is recorded immediately as a terminal job and the
    # playlist item links to it.
    assert [job["status"] for job in jobs.item_jobs] == ["ready", "ready"]
    assert [job["kind"] for job in jobs.item_jobs] == [
        "playlist_item",
        "playlist_item",
    ]
    assert [job["item_index"] for job in jobs.item_jobs] == [1, 2]
    assert [job["item_count"] for job in jobs.item_jobs] == [2, 2]
    assert all(job["asset_id"] for job in jobs.item_jobs)
    assert [job["artist"] for job in jobs.item_jobs] == ["Channel", "Channel"]
    assert [job["album"] for job in jobs.item_jobs] == ["List", "List"]
    assert [item["job_id"] for item in playlists.items] == [
        job["id"] for job in jobs.item_jobs
    ]

    assert ytdlp.download_video.calls == [
        "https://example.test/v1",
        "https://example.test/v2",
    ]
    expected_hash = options_hash("720p", False, {"kind": "video"})
    assert [
        kwargs["options_hash"] for kwargs in assets.claim_kwargs
    ] == [expected_hash, expected_hash]

    row = jobs.rows[str(job["id"])]
    assert row["status"] == "ready"
    assert row["progress"] == 100
    assert row["item_index"] == 2
    assert row["item_count"] == 2
    assert row["error"] == ""
    assert row["playlist_id"] == PLAYLIST_ID


def test_playlist_partial_failure_marks_item_failed_and_job_ready(tmp_path):
    entries = _entries(2)
    job = _playlist_job()
    jobs = RecordingJobs([job])
    playlists = RecordingPlaylists(entries)
    assets = PlaylistAssets()
    ytdlp = _fake_ytdlp(
        info=lambda url, settings: playlist_info(entries),
        download=_writing_download(fail_urls=("/v2",)),
    )
    worker = _worker(tmp_path, jobs, playlists, assets, ytdlp)

    run(worker.process_job(job))

    assert playlists.playlist["status"] == "partial"
    assert [item["status"] for item in playlists.items] == ["ready", "failed"]
    assert playlists.items[1]["error"] == (
        "Network error while contacting the site."
    )
    assert len(assets.ready) == 1
    assert len(assets.failed) == 1

    # One ready and one failed item job; the failed job carries the safe error
    # and never an asset.
    assert [job["status"] for job in jobs.item_jobs] == ["ready", "failed"]
    ready_job, failed_job = jobs.item_jobs
    assert ready_job["asset_id"] is not None
    assert failed_job["asset_id"] is None
    assert failed_job["error"] == "Network error while contacting the site."
    assert failed_job["artist"] == "Channel"
    assert failed_job["album"] == "List"
    assert [item["job_id"] for item in playlists.items] == [
        ready_job["id"],
        failed_job["id"],
    ]

    row = jobs.rows[str(job["id"])]
    assert row["status"] == "ready"
    assert row["progress"] == 100
    assert row["error"] == (
        "1 of 2 items failed. Network error while contacting the site."
    )
    assert row["item_index"] == 2


def test_ready_item_job_is_recorded_before_the_next_item_starts(tmp_path):
    entries = _entries(2)
    job = _playlist_job()
    jobs = RecordingJobs([job])
    playlists = RecordingPlaylists(entries)
    assets = PlaylistAssets()

    def assert_first_item_recorded(url):
        if not url.endswith("/v2"):
            return
        # The first item's terminal job must already be observable while the
        # second item is still being downloaded.
        assert len(jobs.item_jobs) == 1
        assert jobs.item_jobs[0]["status"] == "ready"
        assert jobs.item_jobs[0]["item_index"] == 1
        assert playlists.items[0]["status"] == "ready"

    ytdlp = _fake_ytdlp(
        info=lambda url, settings: playlist_info(entries),
        download=_writing_download(before=assert_first_item_recorded),
    )
    worker = _worker(tmp_path, jobs, playlists, assets, ytdlp)

    run(worker.process_job(job))

    assert [job["status"] for job in jobs.item_jobs] == ["ready", "ready"]


def test_playlist_item_jobs_use_each_entry_channel_as_artist(tmp_path):
    entries = _entries(2, channels={1: "First artist", 2: "Second artist"})
    job = _playlist_job()
    jobs = RecordingJobs([job])
    playlists = RecordingPlaylists(entries)
    assets = PlaylistAssets()
    ytdlp = _fake_ytdlp(
        info=lambda url, settings: playlist_info(entries),
        download=_writing_download(),
    )
    worker = _worker(tmp_path, jobs, playlists, assets, ytdlp)

    run(worker.process_job(job))

    assert [job["artist"] for job in jobs.item_jobs] == [
        "First artist",
        "Second artist",
    ]
    assert [job["album"] for job in jobs.item_jobs] == ["List", "List"]


def test_playlist_cancellation_keeps_completed_assets_and_stops(tmp_path):
    entries = _entries(3)
    job = _playlist_job()
    jobs = RecordingJobs([job])
    playlists = RecordingPlaylists(entries)
    assets = PlaylistAssets()
    cancel_event = threading.Event()
    ytdlp = _fake_ytdlp(
        info=lambda url, settings: playlist_info(entries),
        download=_writing_download(cancel_event=cancel_event),
    )
    worker = _worker(tmp_path, jobs, playlists, assets, ytdlp)

    run(worker.process_job(job, cancel=cancel_event))

    assert playlists.playlist["status"] == "cancelled"
    assert [item["status"] for item in playlists.items] == [
        "ready",
        "cancelled",
        "cancelled",
    ]
    assert len(assets.ready) == 1
    path = worker.storage.validate_relative_path(
        assets.ready[0][1]["file_path"]
    )
    assert path.is_file()

    # Only the completed item produced a job; cancelled items never do.
    assert [job["status"] for job in jobs.item_jobs] == ["ready"]
    assert [item["job_id"] for item in playlists.items] == [
        jobs.item_jobs[0]["id"],
        None,
        None,
    ]

    row = jobs.rows[str(job["id"])]
    assert row["status"] == "cancelled"
    assert row["cancel_requested"] is True


def test_playlist_reuses_video_cache_hit_for_one_item(tmp_path):
    entries = _entries(2)
    job = _playlist_job()
    jobs = RecordingJobs([job])
    playlists = RecordingPlaylists(entries)
    assets = PlaylistAssets(ready_canonicals={"youtube:vid2"})
    ytdlp = _fake_ytdlp(
        info=lambda url, settings: playlist_info(entries),
        download=_writing_download(),
    )
    worker = _worker(tmp_path, jobs, playlists, assets, ytdlp)

    run(worker.process_job(job))

    assert ytdlp.download_video.calls == ["https://example.test/v1"]
    assert len(assets.ready) == 1
    assert playlists.items[1]["status"] == "ready"
    assert playlists.items[1]["asset_id"] == assets.ready_assets[
        "youtube:vid2"
    ]["id"]
    assert [item["status"] for item in playlists.items] == ["ready", "ready"]
    assert jobs.rows[str(job["id"])]["status"] == "ready"
    assert [item["status"] for item in jobs.item_jobs] == ["ready", "ready"]
    assert jobs.item_jobs[1]["asset_id"] == assets.ready_assets[
        "youtube:vid2"
    ]["id"]


def test_playlist_all_items_failing_marks_job_failed(tmp_path):
    entries = _entries(2)
    job = _playlist_job()
    jobs = RecordingJobs([job])
    playlists = RecordingPlaylists(entries)
    assets = PlaylistAssets()
    ytdlp = _fake_ytdlp(
        info=lambda url, settings: playlist_info(entries),
        download=_writing_download(fail_urls=("/v1", "/v2")),
    )
    worker = _worker(tmp_path, jobs, playlists, assets, ytdlp)

    run(worker.process_job(job))

    assert playlists.playlist["status"] == "failed"
    assert jobs.rows[str(job["id"])]["status"] == "failed"
    assert "2 of 2 items failed." in jobs.rows[str(job["id"])]["error"]
    assert all(item["status"] == "failed" for item in playlists.items)
    assert [job["status"] for job in jobs.item_jobs] == ["failed", "failed"]
    assert all(job["asset_id"] is None for job in jobs.item_jobs)
    assert all(job["error"] for job in jobs.item_jobs)


def test_playlist_item_thumbnail_from_flat_entry_is_stored(tmp_path):
    entries = [
        {
            "canonical_id": "youtube:vid1",
            "source_url": "https://example.test/v1",
            "title": "Clip 1",
            "duration_seconds": 10,
            "thumbnail": "https://img.example.test/item.jpg",
        }
    ]
    job = _playlist_job()
    jobs = RecordingJobs([job])
    playlists = RecordingPlaylists(entries)
    assets = PlaylistAssets()

    def thumbnail(url, dest, settings):
        destination = Path(dest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"item-thumb")
        return True

    ytdlp = _fake_ytdlp(
        info=lambda url, settings: playlist_info(entries),
        download=_writing_download(),
        thumbnail=thumbnail,
    )
    worker = _worker(tmp_path, jobs, playlists, assets, ytdlp)

    run(worker.process_job(job))

    asset_id, fields = assets.ready[0]
    assert fields["thumbnail_path"] == f"thumbnails/{asset_id}.jpg"
    path = worker.storage.validate_relative_path(fields["thumbnail_path"])
    assert path.read_bytes() == b"item-thumb"


def test_playlist_cover_is_downloaded_and_recorded(tmp_path):
    entries = _entries(1)
    job = _playlist_job()
    jobs = RecordingJobs([job])
    playlists = RecordingPlaylists(entries)
    assets = PlaylistAssets()
    written: list[Path] = []

    def thumbnail(url, dest, settings):
        destination = Path(dest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"cover")
        written.append(destination)
        return True

    ytdlp = _fake_ytdlp(
        info=lambda url, settings: playlist_info(
            entries, thumbnail="https://img.example.test/cover.jpg"
        ),
        download=_writing_download(),
        thumbnail=thumbnail,
    )
    worker = _worker(tmp_path, jobs, playlists, assets, ytdlp)

    run(worker.process_job(job))

    relative = f"playlists/{PLAYLIST_ID}.jpg"
    assert playlists.playlist["thumbnail_path"] == relative
    path = worker.storage.validate_relative_path(relative)
    assert path.read_bytes() == b"cover"
    assert written == [path]


def test_playlist_url_resolving_to_video_fails_without_items(tmp_path):
    job = _playlist_job()
    jobs = RecordingJobs([job])
    playlists = RecordingPlaylists([])
    assets = PlaylistAssets()
    ytdlp = _fake_ytdlp(
        info=lambda url, settings: {
            "type": "video",
            "id": "vid1",
            "title": "Not a playlist",
        },
        download=_writing_download(),
    )
    worker = _worker(tmp_path, jobs, playlists, assets, ytdlp)

    run(worker.process_job(job))

    assert jobs.rows[str(job["id"])]["status"] == "failed"
    assert jobs.rows[str(job["id"])]["error"] == "This URL is not a playlist."
    assert playlists.upsert_kwargs is None
    assert assets.claim_kwargs == []
