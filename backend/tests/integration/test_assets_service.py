"""Real-PostgreSQL tests for the shared media cache claim/lease protocol.

The cache is global: two users (or two workers) can request the same
``(canonical_id, options_hash)`` at the same time. These tests drive two real
pooled connections so the race is the database's, not a fake's.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.core.db import create_pool
from backend.app.services import assets
from backend.tests.integration.conftest import cleanup_test_data

pytestmark = pytest.mark.integration


def _kwargs(canonical_id: str, options_hash: str = "o" * 64, **overrides):
    values = {
        "canonical_id": canonical_id,
        "extractor_key": "youtube",
        "source_url": "https://example.test/video",
        "title": "Clip",
        "duration_seconds": 30,
        "options_hash": options_hash,
        "format_selector": "best",
        "lease_seconds": 120,
    }
    values.update(overrides)
    return values


def test_concurrent_claims_never_raise_a_unique_violation(
    db_run, integration_settings, media_storage
):
    canonical = "youtube:race-claim"

    async def scenario(db):
        second = await create_pool(integration_settings, min_size=1, max_size=2)
        try:
            first, other = await asyncio.gather(
                assets.claim_asset(db, media_storage, **_kwargs(canonical)),
                assets.claim_asset(second, media_storage, **_kwargs(canonical)),
            )

            results = (first, other)
            assert sum(1 for result in results if result.claimed) == 1, results
            loser = next(result for result in results if not result.claimed)
            assert loser.wait is True
            assert loser.cache_hit is False

            rows = await db.fetch(
                f"select id, status, attempts from {db.schema_sql}.media_assets "
                "where canonical_id = $1",
                canonical,
            )
            assert len(rows) == 1
            assert rows[0]["status"] == "processing"
            # Only the winner increments attempts; the loser read the row.
            assert rows[0]["attempts"] == 1
        finally:
            await second.close()
            await cleanup_test_data(db, canonical_ids=[canonical])

    db_run(scenario)


def test_claim_waits_for_an_uncommitted_insert_instead_of_failing(
    db_run, integration_settings, media_storage
):
    """Deterministically force the loser onto the ``on conflict`` path.

    A competing transaction inserts the asset and holds it uncommitted. The
    service claim cannot see it with a plain SELECT, so its INSERT blocks on
    the unique index; once the winner commits, the claim must lock and inspect
    that row (here a live lease) rather than propagate ``UniqueViolation``.
    """
    canonical = "youtube:uncommitted-claim"

    async def _wait_for_blocked_insert(db) -> None:
        for _ in range(200):
            row = await db.fetchrow(
                "select count(*) as n from pg_stat_activity "
                "where state = 'active' and wait_event_type = 'Lock' "
                "and query ilike '%insert into%media_assets%'"
            )
            if row is not None and int(row["n"]) >= 1:
                return
            await asyncio.sleep(0.02)
        raise AssertionError("the claim never blocked on the uncommitted insert")

    async def scenario(db):
        second = await create_pool(integration_settings, min_size=1, max_size=2)
        try:
            lease_until = datetime.now(timezone.utc) + timedelta(seconds=120)
            claim_task: asyncio.Task | None = None
            async with second.transaction() as winner:
                await winner.execute(
                    f"insert into {db.schema_sql}.media_assets "
                    "(canonical_id, extractor_key, source_url, title, "
                    "options_hash, format_selector, status, attempts, "
                    "claimed_at, lease_until) "
                    "values ($1, 'youtube', 'https://example.test/video', "
                    "'Clip', $2, 'best', 'processing', 1, now(), $3)",
                    canonical,
                    "o" * 64,
                    lease_until,
                )
                claim_task = asyncio.create_task(
                    assets.claim_asset(
                        db, media_storage, **_kwargs(canonical)
                    )
                )
                await _wait_for_blocked_insert(db)
                assert not claim_task.done()

            result = await asyncio.wait_for(claim_task, timeout=10)
            assert result.claimed is False
            assert result.wait is True
            assert result.asset["canonical_id"] == canonical

            rows = await db.fetch(
                f"select attempts from {db.schema_sql}.media_assets "
                "where canonical_id = $1",
                canonical,
            )
            assert [row["attempts"] for row in rows] == [1]
        finally:
            await second.close()
            await cleanup_test_data(db, canonical_ids=[canonical])

    db_run(scenario)


def test_ready_asset_is_a_cache_hit_and_a_lost_file_is_repaired(
    db_run, media_storage
):
    canonical = "youtube:cache-hit"

    async def scenario(db):
        try:
            claimed = await assets.claim_asset(
                db, media_storage, **_kwargs(canonical)
            )
            asset_id = claimed.asset["id"]
            file_path = f"assets/{asset_id}/media.mp4"
            target = media_storage.validate_relative_path(file_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"0123456789")

            await assets.mark_ready(
                db,
                asset_id,
                file_path=file_path,
                file_size_bytes=10,
                output_ext="mp4",
                thumbnail_path=None,
            )
            # Age the access marker so the touch path is observable.
            await db.execute(
                f"update {db.schema_sql}.media_assets "
                "set last_accessed_at = now() - interval '1 hour' where id = $1",
                asset_id,
            )

            hit = await assets.claim_asset(
                db, media_storage, **_kwargs(canonical)
            )
            assert hit.cache_hit is True
            assert hit.claimed is False
            assert hit.asset["status"] == "ready"
            assert hit.asset["attempts"] == 1
            assert hit.asset["last_accessed_at"] > datetime.now(
                timezone.utc
            ) - timedelta(minutes=1)

            # A ready row whose file vanished must be repaired, not served.
            target.unlink()
            repaired = await assets.claim_asset(
                db, media_storage, **_kwargs(canonical)
            )
            assert repaired.claimed is True
            assert repaired.asset["status"] == "processing"
            assert repaired.asset["attempts"] == 2
            assert repaired.asset["file_path"] == file_path
        finally:
            await cleanup_test_data(db, canonical_ids=[canonical])

    db_run(scenario)


def test_a_truncated_file_is_not_a_cache_hit(db_run, media_storage):
    canonical = "youtube:truncated"

    async def scenario(db):
        try:
            claim = await assets.claim_asset(
                db, media_storage, **_kwargs(canonical)
            )
            asset_id = claim.asset["id"]
            file_path = f"assets/{asset_id}/media.mp4"
            target = media_storage.validate_relative_path(file_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"0123456789")
            await assets.mark_ready(
                db,
                asset_id,
                file_path=file_path,
                file_size_bytes=10,
                output_ext="mp4",
                thumbnail_path=None,
            )
            target.write_bytes(b"0123")  # recorded size no longer matches
            result = await assets.claim_asset(
                db, media_storage, **_kwargs(canonical)
            )
            assert result.cache_hit is False
            assert result.claimed is True
            assert result.asset["attempts"] == 2
        finally:
            await cleanup_test_data(db, canonical_ids=[canonical])

    db_run(scenario)


def test_live_lease_waits_and_an_expired_lease_is_reclaimed(db_run, media_storage):
    canonical = "youtube:lease"

    async def scenario(db):
        try:
            claim = await assets.claim_asset(
                db, media_storage, **_kwargs(canonical, lease_seconds=120)
            )
            asset_id = claim.asset["id"]
            assert claim.claimed is True

            waiting = await assets.claim_asset(
                db, media_storage, **_kwargs(canonical)
            )
            assert waiting.wait is True
            assert waiting.claimed is False

            # Simulate a worker that died before its lease expired.
            await db.execute(
                f"update {db.schema_sql}.media_assets "
                "set lease_until = now() - interval '1 minute' where id = $1",
                asset_id,
            )
            reclaimed = await assets.claim_asset(
                db, media_storage, **_kwargs(canonical)
            )
            assert reclaimed.claimed is True
            assert reclaimed.asset["attempts"] == 2
            assert reclaimed.asset["lease_until"] > datetime.now(timezone.utc)

            # Renewal only applies while processing.
            renewed = await assets.renew_lease(db, asset_id, 300)
            assert renewed["lease_until"] > reclaimed.asset["lease_until"]
            await assets.mark_ready(
                db,
                asset_id,
                file_path=f"assets/{asset_id}/media.mp4",
                file_size_bytes=0,
                output_ext="mp4",
                thumbnail_path=None,
            )
            assert await assets.renew_lease(db, asset_id, 300) is None
        finally:
            await cleanup_test_data(db, canonical_ids=[canonical])

    db_run(scenario)


def test_failed_asset_releases_its_lease_and_can_be_reclaimed(
    db_run, media_storage
):
    canonical = "youtube:failed"

    async def scenario(db):
        try:
            claim = await assets.claim_asset(
                db, media_storage, **_kwargs(canonical)
            )
            asset_id = claim.asset["id"]
            failed = await assets.mark_failed(db, asset_id, "network down")
            assert failed["status"] == "failed"
            assert failed["error"] == "network down"
            assert failed["lease_until"] is None
            assert failed["claimed_at"] is None

            reclaimed = await assets.claim_asset(
                db, media_storage, **_kwargs(canonical)
            )
            assert reclaimed.claimed is True
            assert reclaimed.asset["status"] == "processing"
            assert reclaimed.asset["attempts"] == 2
            assert reclaimed.asset["error"] == ""
        finally:
            await cleanup_test_data(db, canonical_ids=[canonical])

    db_run(scenario)


def test_mark_ready_rejects_unsafe_paths_without_changing_the_row(
    db_run, media_storage
):
    canonical = "youtube:unsafe"

    async def scenario(db):
        try:
            claim = await assets.claim_asset(
                db, media_storage, **_kwargs(canonical)
            )
            asset_id = claim.asset["id"]

            for file_path in ("../escape.mp4", "/abs/media.mp4", ""):
                with pytest.raises(ValueError):
                    await assets.mark_ready(
                        db,
                        asset_id,
                        file_path=file_path,
                        file_size_bytes=10,
                        output_ext="mp4",
                        thumbnail_path=None,
                    )
            with pytest.raises(ValueError):
                await assets.mark_ready(
                    db,
                    asset_id,
                    file_path="assets/x/media.mp4",
                    file_size_bytes=10,
                    output_ext="mp4",
                    thumbnail_path="/abs/thumb.jpg",
                )

            row = await assets.get_asset(db, asset_id)
            assert row["status"] == "processing"
            assert row["file_path"] is None
            assert row["thumbnail_path"] is None
        finally:
            await cleanup_test_data(db, canonical_ids=[canonical])

    db_run(scenario)


def test_different_options_hashes_are_separate_cache_entries(
    db_run, media_storage
):
    canonical = "youtube:variants"

    async def scenario(db):
        try:
            audio = await assets.claim_asset(
                db, media_storage, **_kwargs(canonical, options_hash="a" * 64)
            )
            video = await assets.claim_asset(
                db, media_storage, **_kwargs(canonical, options_hash="v" * 64)
            )
            assert audio.asset["id"] != video.asset["id"]
            assert audio.claimed and video.claimed

            rows = await db.fetch(
                f"select options_hash from {db.schema_sql}.media_assets "
                "where canonical_id = $1",
                canonical,
            )
            assert {row["options_hash"] for row in rows} == {"a" * 64, "v" * 64}
        finally:
            await cleanup_test_data(db, canonical_ids=[canonical])

    db_run(scenario)


def test_touch_accessed_respects_the_throttle(db_run, media_storage):
    canonical = "youtube:touch"

    async def scenario(db):
        try:
            claim = await assets.claim_asset(
                db, media_storage, **_kwargs(canonical)
            )
            asset_id = claim.asset["id"]
            await db.execute(
                f"update {db.schema_sql}.media_assets "
                "set last_accessed_at = now() where id = $1",
                asset_id,
            )
            # Within the throttle window nothing is written.
            assert await assets.touch_accessed(
                db, asset_id, throttle_seconds=3600
            ) is False

            await db.execute(
                f"update {db.schema_sql}.media_assets "
                "set last_accessed_at = now() - interval '2 hours' where id = $1",
                asset_id,
            )
            assert await assets.touch_accessed(
                db, asset_id, throttle_seconds=3600
            ) is True
        finally:
            await cleanup_test_data(db, canonical_ids=[canonical])

    db_run(scenario)
