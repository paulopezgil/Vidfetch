"""Real-PostgreSQL coverage for terminal per-item playlist jobs.

Ready playlist-item jobs must seed the user's track metadata from the source
channel and playlist name, failed item jobs must not create a track at all,
re-running a playlist must update the linked job instead of duplicating it, and
later downloads of a shared asset must never overwrite the user's own track
metadata.
"""
from __future__ import annotations

import pytest

from backend.app.services import jobs, playlists, tracks
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


def test_later_ready_jobs_never_overwrite_edited_track_metadata(
    db_run, media_storage
):
    """The trigger seeds defaults but keeps whatever the user has edited.

    A ready job seeds ``user_tracks`` from its ``artist``/``album`` the first
    time. Every later ready job for the same user and shared asset (an updated
    linked job or a brand new one) may only fill blank fields; edited values
    survive.
    """

    async def scenario(db):
        owner = await create_profile(db)
        canonical_edited = "youtube:item-defaults-edited"
        canonical_blank = "youtube:item-defaults-blank"
        try:
            playlist = await _create_playlist(db, owner["id"])

            # -- first ready job seeds artist and album --------------------
            asset = await make_ready_asset(
                db, media_storage, canonical_id=canonical_edited, title="A"
            )
            first_job = await jobs.record_playlist_item_job(
                db,
                user_id=owner["id"],
                playlist_id=playlist["id"],
                source_url="https://example.test/a",
                title="A",
                options_hash="v" * 64,
                format_selector="best",
                status="ready",
                asset_id=asset["id"],
                artist="Seed channel",
                album="Seed album",
                item_index=1,
                item_count=2,
            )
            seeded = await db.fetchrow(
                f"select id, custom_artist, custom_album "
                f"from {db.schema_sql}.user_tracks "
                "where user_id = $1 and asset_id = $2",
                owner["id"],
                asset["id"],
            )
            assert seeded is not None
            assert seeded["custom_artist"] == "Seed channel"
            assert seeded["custom_album"] == "Seed album"

            # -- the user renames the track --------------------------------
            edited = await tracks.update_track(
                db,
                seeded["id"],
                owner["id"],
                {"custom_artist": "My artist", "custom_album": "My album"},
            )
            assert edited["artist"] == "My artist"
            assert edited["album"] == "My album"

            # A playlist re-run updates the linked job with a different
            # channel/album; the update fires the trigger again.
            rerun = await jobs.record_playlist_item_job(
                db,
                user_id=owner["id"],
                playlist_id=playlist["id"],
                source_url="https://example.test/a",
                title="A",
                options_hash="v" * 64,
                format_selector="best",
                status="ready",
                asset_id=asset["id"],
                artist="Other channel",
                album="Other album",
                item_index=1,
                item_count=2,
                job_id=first_job["id"],
            )
            assert rerun["id"] == first_job["id"]
            preserved = await db.fetchrow(
                f"select custom_artist, custom_album "
                f"from {db.schema_sql}.user_tracks where id = $1",
                seeded["id"],
            )
            assert preserved["custom_artist"] == "My artist"
            assert preserved["custom_album"] == "My album"

            # A brand new ready job for the same shared asset (another
            # download) inserts its own row, which must not clobber either.
            second_job = await jobs.record_playlist_item_job(
                db,
                user_id=owner["id"],
                playlist_id=playlist["id"],
                source_url="https://example.test/a-again",
                title="A again",
                options_hash="v" * 64,
                format_selector="best",
                status="ready",
                asset_id=asset["id"],
                artist="Third channel",
                album="Third album",
                item_index=2,
                item_count=2,
            )
            assert second_job["id"] != first_job["id"]
            still_edited = await db.fetchrow(
                f"select custom_artist, custom_album "
                f"from {db.schema_sql}.user_tracks where id = $1",
                seeded["id"],
            )
            assert still_edited["custom_artist"] == "My artist"
            assert still_edited["custom_album"] == "My album"

            # -- a later job only fills the blank fields -------------------
            blank_asset = await make_ready_asset(
                db, media_storage, canonical_id=canonical_blank, title="B"
            )
            await jobs.record_playlist_item_job(
                db,
                user_id=owner["id"],
                playlist_id=playlist["id"],
                source_url="https://example.test/b",
                title="B",
                options_hash="v" * 64,
                format_selector="best",
                status="ready",
                asset_id=blank_asset["id"],
                artist="Seed channel",
                album="",
                item_index=1,
                item_count=1,
            )
            blank_seeded = await db.fetchrow(
                f"select id, custom_artist, custom_album "
                f"from {db.schema_sql}.user_tracks "
                "where user_id = $1 and asset_id = $2",
                owner["id"],
                blank_asset["id"],
            )
            assert blank_seeded["custom_artist"] == "Seed channel"
            assert blank_seeded["custom_album"] == ""

            await jobs.record_playlist_item_job(
                db,
                user_id=owner["id"],
                playlist_id=playlist["id"],
                source_url="https://example.test/b",
                title="B",
                options_hash="v" * 64,
                format_selector="best",
                status="ready",
                asset_id=blank_asset["id"],
                artist="Later channel",
                album="Later album",
                item_index=1,
                item_count=1,
            )
            filled = await db.fetchrow(
                f"select custom_artist, custom_album "
                f"from {db.schema_sql}.user_tracks where id = $1",
                blank_seeded["id"],
            )
            # Non-blank artist kept, blank album filled by the trigger.
            assert filled["custom_artist"] == "Seed channel"
            assert filled["custom_album"] == "Later album"
        finally:
            await cleanup_test_data(
                db,
                profiles=[owner],
                canonical_ids=[canonical_edited, canonical_blank],
            )

    db_run(scenario)
