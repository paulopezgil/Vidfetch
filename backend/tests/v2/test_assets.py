"""Tests for the global media-asset claim/lease service."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from backend.app.services import assets
from backend.app.services.storage import Storage
from backend.tests.v2.fakes import FakeDatabase, asset_row


def run(coro):
    return asyncio.run(coro)


def _storage(tmp_path) -> Storage:
    storage = Storage(tmp_path / "downloads")
    storage.ensure_directories()
    return storage


def _ready_file(storage: Storage, asset_id, content: bytes = b"abc") -> str:
    relative = f"assets/{asset_id}/clip.mp4"
    path = storage.validate_relative_path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return relative


def _claim(db, storage, **overrides):
    kwargs = {
        "canonical_id": "youtube:vid1",
        "extractor_key": "youtube",
        "source_url": "https://example.test/v",
        "title": "Clip",
        "duration_seconds": 12,
        "options_hash": "b" * 64,
        "format_selector": "best",
        "lease_seconds": 300,
    }
    kwargs.update(overrides)
    return assets.claim_asset(db, storage, **kwargs)


def test_canonical_id_normalizes_and_requires_parts():
    assert assets.canonical_id("YouTube", "abc") == "youtube:abc"
    assert assets.canonical_id("  youtube ", " abc ") == "youtube:abc"

    with pytest.raises(ValueError):
        assets.canonical_id("", "abc")
    with pytest.raises(ValueError):
        assets.canonical_id("youtube", "")


def test_claim_inserts_processing_asset_with_aware_lease(tmp_path):
    storage = _storage(tmp_path)
    inserted = asset_row(status="processing", attempts=1)
    db = FakeDatabase()
    db.queue_fetchrow(None, inserted)

    claim = run(_claim(db, storage))

    assert claim.claimed is True
    assert claim.cache_hit is False
    assert claim.wait is False
    assert claim.asset["id"] == inserted["id"]

    method, query, args = db.calls[1]
    assert method == "fetchrow"
    assert 'insert into "public".media_assets' in query
    assert "'processing'" in query
    assert args[0] == "youtube:vid1"
    assert args[1] == "youtube"
    assert args[5] == "b" * 64
    assert args[7].tzinfo is not None
    assert args[8] > args[7]
    assert db.connection.transactions == 1
    assert db.connection.commits == 1


def test_claim_returns_cache_hit_and_touches_old_access(tmp_path):
    storage = _storage(tmp_path)
    asset_id = uuid4()
    relative = _ready_file(storage, asset_id)
    old = datetime.now(timezone.utc) - timedelta(minutes=10)
    row = asset_row(
        asset_id=asset_id,
        status="ready",
        file_path=relative,
        file_size_bytes=3,
        last_accessed_at=old,
    )
    touched = {**row, "last_accessed_at": datetime.now(timezone.utc)}
    db = FakeDatabase()
    db.queue_fetchrow(row, touched)

    claim = run(_claim(db, storage))

    assert claim.cache_hit is True
    assert claim.claimed is False
    assert claim.wait is False
    assert db.calls[0][1].endswith("for update")
    assert 'update "public".media_assets set last_accessed_at' in db.calls[1][1]
    assert db.calls[1][2][0] == asset_id


def test_claim_cache_hit_does_not_rewrite_recent_access(tmp_path):
    storage = _storage(tmp_path)
    asset_id = uuid4()
    relative = _ready_file(storage, asset_id)
    row = asset_row(
        asset_id=asset_id,
        status="ready",
        file_path=relative,
        file_size_bytes=3,
        last_accessed_at=datetime.now(timezone.utc),
    )
    db = FakeDatabase()
    db.queue_fetchrow(row)

    claim = run(_claim(db, storage))

    assert claim.cache_hit is True
    assert len(db.calls) == 1


def test_claim_repairs_ready_asset_with_missing_file(tmp_path):
    storage = _storage(tmp_path)
    asset_id = uuid4()
    row = asset_row(
        asset_id=asset_id,
        status="ready",
        file_path=f"assets/{asset_id}/gone.mp4",
        file_size_bytes=3,
    )
    repaired = {**row, "status": "processing", "attempts": 2}
    db = FakeDatabase()
    db.queue_fetchrow(row, repaired)

    claim = run(_claim(db, storage))

    assert claim.claimed is True
    assert claim.cache_hit is False
    query = db.calls[1][1]
    assert "attempts = attempts + 1" in query
    assert "status = 'processing'" in query


def test_claim_repairs_ready_asset_with_wrong_size(tmp_path):
    storage = _storage(tmp_path)
    asset_id = uuid4()
    relative = _ready_file(storage, asset_id, b"abc")
    row = asset_row(
        asset_id=asset_id,
        status="ready",
        file_path=relative,
        file_size_bytes=999,
    )
    repaired = {**row, "status": "processing", "attempts": 2}
    db = FakeDatabase()
    db.queue_fetchrow(row, repaired)

    claim = run(_claim(db, storage))

    assert claim.claimed is True
    assert "status = 'processing'" in db.calls[1][1]


def test_claim_waits_on_live_processing_lease(tmp_path):
    storage = _storage(tmp_path)
    row = asset_row(
        status="processing",
        lease_until=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    db = FakeDatabase()
    db.queue_fetchrow(row)

    claim = run(_claim(db, storage))

    assert claim.wait is True
    assert claim.claimed is False
    assert len(db.calls) == 1


def test_claim_reclaims_expired_lease(tmp_path):
    storage = _storage(tmp_path)
    row = asset_row(
        status="processing",
        lease_until=datetime.now(timezone.utc) - timedelta(seconds=5),
    )
    reclaimed = {**row, "status": "processing", "attempts": 2}
    db = FakeDatabase()
    db.queue_fetchrow(row, reclaimed)

    claim = run(_claim(db, storage))

    assert claim.claimed is True
    assert claim.wait is False
    assert "attempts = attempts + 1" in db.calls[1][1]


def test_claim_retries_failed_asset(tmp_path):
    storage = _storage(tmp_path)
    row = asset_row(status="failed", error="old failure")
    reclaimed = {**row, "status": "processing", "attempts": 2}
    db = FakeDatabase()
    db.queue_fetchrow(row, reclaimed)

    claim = run(_claim(db, storage))

    assert claim.claimed is True
    assert "error = ''" in db.calls[1][1]


def test_claim_rejects_missing_identity(tmp_path):
    storage = _storage(tmp_path)
    db = FakeDatabase()

    with pytest.raises(ValueError):
        run(_claim(db, storage, canonical_id=""))
    with pytest.raises(ValueError):
        run(_claim(db, storage, options_hash=""))


def test_mark_ready_validates_relative_paths(tmp_path):
    db = FakeDatabase()
    row = asset_row(status="ready", file_path="assets/x/clip.mp4")
    db.queue_fetchrow(row)

    result = run(
        assets.mark_ready(
            db,
            row["id"],
            file_path="assets/x/clip.mp4",
            file_size_bytes=10,
            output_ext="MP4",
            thumbnail_path="thumbnails/x.jpg",
        )
    )

    assert result["status"] == "ready"
    method, query, args = db.calls[0]
    assert "status = 'ready'" in query
    assert args[1] == "assets/x/clip.mp4"
    assert args[2] == 10
    assert args[3] == "mp4"
    assert args[4] == "thumbnails/x.jpg"

    with pytest.raises(ValueError):
        run(
            assets.mark_ready(
                db,
                row["id"],
                file_path="/etc/passwd",
                file_size_bytes=1,
                output_ext="mp4",
                thumbnail_path=None,
            )
        )
    with pytest.raises(ValueError):
        run(
            assets.mark_ready(
                db,
                row["id"],
                file_path="assets/x/clip.mp4",
                file_size_bytes=1,
                output_ext="mp4",
                thumbnail_path="../escape.jpg",
            )
        )


def test_mark_failed_stores_safe_truncated_message():
    db = FakeDatabase()
    row = asset_row(status="failed")
    db.queue_fetchrow(row)

    run(assets.mark_failed(db, row["id"], "x" * 800))

    method, query, args = db.calls[0]
    assert "status = 'failed'" in query
    assert "lease_until = null" in query
    assert len(args[1]) == 500


def test_renew_lease_extends_processing_asset():
    db = FakeDatabase()
    row = asset_row(status="processing")
    db.queue_fetchrow(row)

    run(assets.renew_lease(db, row["id"], 120))

    method, query, args = db.calls[0]
    assert "lease_until = $2" in query
    assert "status = 'processing'" in query
    assert args[1].tzinfo is not None


def test_get_asset_returns_row_or_none():
    row = asset_row()
    db = FakeDatabase()
    db.queue_fetchrow(row, None)

    assert run(assets.get_asset(db, row["id"])) == row
    assert run(assets.get_asset(db, row["id"])) is None


def test_touch_accessed_is_throttled_by_timestamp_and_reports_updates():
    db = FakeDatabase()
    db.queue_execute("UPDATE 1", "UPDATE 0")

    assert run(assets.touch_accessed(db, uuid4())) is True
    assert run(assets.touch_accessed(db, uuid4())) is False

    method, query, args = db.calls[0]
    assert method == "execute"
    assert "last_accessed_at <=" in query
    assert args[1].tzinfo is not None
