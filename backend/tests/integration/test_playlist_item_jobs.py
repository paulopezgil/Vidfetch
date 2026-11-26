"""Real-PostgreSQL coverage for terminal per-item playlist jobs.

Ready playlist-item jobs must seed the user's track metadata from the source
channel and playlist name, failed item jobs must not create a track at all, and
re-running a playlist must update the linked job instead of duplicating it.
"""
from __future__ import annotations

import pytest

from backend.app.services import jobs, playlists
from backend.tests.integration.conftest import (
    cleanup_test_data,
    create_profile,
    make_ready_asset,
)

pytestmark = pytest.mark.integration


async def _create_playlist(db, owner_id):
    return await playlists.upsert_playlist(
        db,
        user_id=owner_id,
        canonical_id="youtube:PL-ITEM",
        source_url="https://example.test/playlist",
        title="Playlist album",
        channel="Playlist channel",
        item_count=2,
        options_hash="p" * 64,
        format_selector="best",
    )


def test_ready_item_job_seeds_track_metadata_and_failed_item_does_not(
    db_run, media_storage
):
    async def scenario(db):
        owner = await create_profile(db)
        canonical = "youtube:item-metadata"
        try:
            playlist = await _create_playlist(db, owner["id"])
            asset = await make_ready_asset(
                db, media_storage, canonical_id=canonical, title="Clip"
            )
            ready = await jobs.record_playlist_item_job(
                db,
                user_id=owner["id"],
                playlist_id=playlist["id"],
                source_url="https://example.test/v1",
                title="Clip",
                options_hash="v" * 64,
                format_selector="best",
                status="ready",
                asset_id=asset["id"],
                artist="Item artist",
                album="Playlist album",
                item_index=1,
                item_count=2,
            )

            assert ready["kind"] == "playlist_item"
            assert ready["status"] == "ready"
            assert ready["progress"] == 100
            assert ready["started_at"] is not None
            assert ready["completed_at"] is not None

            track = await db.fetchrow(
                f"select id, custom_artist, custom_album "
                f"from {db.schema_sql}.user_tracks "
                "where user_id = $1 and asset_id = $2",
                owner["id"],
                asset["id"],
            )
            assert track is not None
            assert track["custom_artist"] == "Item artist"
            assert track["custom_album"] == "Playlist album"

            failed = await jobs.record_playlist_item_job(
                db,
                user_id=owner["id"],
                playlist_id=playlist["id"],
                source_url="https://example.test/v2",
                title="Other clip",
                options_hash="v" * 64,
                format_selector="best",
                status="failed",
                error="Network error while contacting the site.",
                artist="Item artist",
                album="Playlist album",
                item_index=2,
                item_count=2,
            )
            assert failed["status"] == "failed"
            assert failed["asset_id"] is None
            assert failed["completed_at"] is not None

            # A failed item never creates a track.
            count = await db.fetchrow(
                f"select count(*) as total from {db.schema_sql}.user_tracks "
                "where user_id = $1",
                owner["id"],
            )
            assert count["total"] == 1
        finally:
            await cleanup_test_data(
                db, profiles=[owner], canonical_ids=[canonical]
            )

    db_run(scenario)


def test_rerunning_an_item_updates_the_linked_job_instead_of_duplicating(
    db_run, media_storage
):
    async def scenario(db):
        owner = await create_profile(db)
        canonical = "youtube:item-rerun"
        try:
            playlist = await _create_playlist(db, owner["id"])
            asset = await make_ready_asset(
                db, media_storage, canonical_id=canonical, title="Clip"
            )
            first = await jobs.record_playlist_item_job(
                db,
                user_id=owner["id"],
                playlist_id=playlist["id"],
                source_url="https://example.test/v1",
                title="Clip",
                options_hash="v" * 64,
                format_selector="best",
                status="failed",
                error="Temporary failure.",
                artist="Item artist",
                album="Playlist album",
                item_index=1,
                item_count=1,
            )

            second = await jobs.record_playlist_item_job(
                db,
                user_id=owner["id"],
                playlist_id=playlist["id"],
                source_url="https://example.test/v1",
                title="Clip",
                options_hash="v" * 64,
                format_selector="best",
                status="ready",
                asset_id=asset["id"],
                artist="Item artist",
                album="Playlist album",
                item_index=1,
                item_count=1,
                job_id=first["id"],
            )

            assert second["id"] == first["id"]
            assert second["status"] == "ready"
            assert second["asset_id"] == asset["id"]
            assert second["error"] == ""

            rows = await db.fetch(
                f"select id, status from {db.schema_sql}.download_jobs "
                "where user_id = $1",
                owner["id"],
            )
            assert len(rows) == 1
            assert rows[0]["status"] == "ready"

            track = await db.fetchrow(
                f"select custom_artist, custom_album "
                f"from {db.schema_sql}.user_tracks "
                "where user_id = $1 and asset_id = $2",
                owner["id"],
                asset["id"],
            )
            assert track["custom_artist"] == "Item artist"
            assert track["custom_album"] == "Playlist album"
        finally:
            await cleanup_test_data(
                db, profiles=[owner], canonical_ids=[canonical]
            )

    db_run(scenario)
