"""Real-PostgreSQL tests for curated playlists and their ordered membership.

The ``(playlist_id, position)`` unique constraint is deferred, which is what
lets a reorder rewrite every position in one transaction. These tests exercise
that propaty, the visibility-aware counts, and concurrent membership changes.
"""
from __future__ import annotations

import asyncio

import psycopg
import pytest

from backend.app.core.db import create_pool
from backend.app.services import library, user_playlists
from backend.tests.integration.conftest import (
    cleanup_test_data,
    create_profile,
    create_ready_job,
    make_ready_asset,
)

pytestmark = pytest.mark.integration


async def _seed_tracks(db, storage, *, owner, count, prefix):
    """Create ``count`` ready assets/jobs and return (track_ids, canonical_ids)."""
    track_ids = []
    canonical_ids = []
    for index in range(count):
        canonical = f"youtube:{prefix}-{index}"
        canonical_ids.append(canonical)
        asset = await make_ready_asset(
            db, storage, canonical_id=canonical, title=f"{prefix} {index}"
        )
        await create_ready_job(
            db, user_id=owner["id"], asset_id=asset["id"], title=f"{prefix} {index}"
        )
        row = await db.fetchrow(
            f"select ut.id from {db.schema_sql}.user_tracks ut "
            "where ut.user_id = $1 and ut.asset_id = $2",
            owner["id"],
            asset["id"],
        )
        track_ids.append(row["id"])
    return track_ids, canonical_ids


def test_playlist_crud_soft_delete_and_membership_counts(db_run, media_storage):
    async def scenario(db):
        owner = await create_profile(db)
        other = await create_profile(db)
        try:
            track_ids, canonical_ids = await _seed_tracks(
                db, media_storage, owner=owner, count=2, prefix="crud"
            )
            created = await user_playlists.create_user_playlist(
                db, owner["id"], name="  Road trip  ", description="  songs "
            )
            assert created["name"] == "Road trip"
            assert created["description"] == "songs"
            assert created["track_count"] == 0

            listed, total = await user_playlists.list_user_playlists(db, owner["id"])
            assert total == 1
            assert [row["id"] for row in listed] == [created["id"]]

            assert await user_playlists.get_user_playlist(
                db, created["id"], other["id"]
            ) is None

            updated = await user_playlists.update_user_playlist(
                db,
                created["id"],
                owner["id"],
                {"name": "Renamed", "description": ""},
            )
            assert updated["name"] == "Renamed"
            assert updated["description"] == ""
            # Updating somebody else's playlist is a 404-shaped None.
            assert (
                await user_playlists.update_user_playlist(
                    db, created["id"], other["id"], {"name": "Hijack"}
                )
                is None
            )
            with pytest.raises(ValueError):
                await user_playlists.update_user_playlist(
                    db, created["id"], owner["id"], {"name": "   "}
                )
            with pytest.raises(ValueError):
                await user_playlists.update_user_playlist(
                    db, created["id"], owner["id"], {}
                )

            await user_playlists.add_track(db, created["id"], owner["id"], track_ids[0])
            await user_playlists.add_track(db, created["id"], owner["id"], track_ids[1])
            # Adding the same track twice is a no-op, not a duplicate row.
            await user_playlists.add_track(db, created["id"], owner["id"], track_ids[1])

            assert await user_playlists.list_track_ids(db, created["id"]) == track_ids
            detail, items = await user_playlists.get_playlist_with_tracks(
                db, created["id"], owner["id"]
            )
            assert detail["track_count"] == 2
            assert [item["id"] for item in items] == track_ids

            # Hiding a track's only ready job drops it from the count and the
            # detail view but keeps the membership row.
            jobs_rows = await db.fetch(
                f"select id, asset_id from {db.schema_sql}.download_jobs "
                "where user_id = $1 order by created_at",
                owner["id"],
            )
            await library.hide_library_item(db, owner["id"], jobs_rows[0]["id"])
            assert len(await user_playlists.list_track_ids(db, created["id"])) == 2
            detail, items = await user_playlists.get_playlist_with_tracks(
                db, created["id"], owner["id"]
            )
            assert detail["track_count"] == 1
            assert [item["id"] for item in items] == [track_ids[1]]

            # Removing the visible track compacts positions to 0..n-1.
            assert await user_playlists.remove_track(
                db, created["id"], owner["id"], track_ids[1]
            )
            assert not await user_playlists.remove_track(
                db, created["id"], owner["id"], track_ids[1]
            )
            remaining = await db.fetch(
                f"select user_track_id, position from "
                f"{db.schema_sql}.user_playlist_tracks "
                "where playlist_id = $1 order by position",
                created["id"],
            )
            assert [(row["user_track_id"], row["position"]) for row in remaining] == [
                (track_ids[0], 0)
            ]

            # Soft delete keeps the row (and memberships) for audit.
            assert await user_playlists.delete_user_playlist(
                db, created["id"], owner["id"]
            )
            assert not await user_playlists.delete_user_playlist(
                db, created["id"], owner["id"]
            )
            assert await user_playlists.get_user_playlist(
                db, created["id"], owner["id"]
            ) is None
            assert (await user_playlists.list_user_playlists(db, owner["id"]))[1] == 0
            raw = await db.fetchrow(
                f"select deleted_at from {db.schema_sql}.user_playlists "
                "where id = $1",
                created["id"],
            )
            assert raw["deleted_at"] is not None
            stored = await db.fetchrow(
                f"select count(*) as n from {db.schema_sql}.user_playlist_tracks "
                "where playlist_id = $1",
                created["id"],
            )
            assert stored["n"] == 1
        finally:
            await cleanup_test_data(
                db,
                profiles=[owner, other],
                canonical_ids=canonical_ids,
            )

    db_run(scenario)


def test_reorder_rewrites_positions_under_the_deferred_constraint(
    db_run, media_storage
):
    async def scenario(db):
        owner = await create_profile(db)
        other = await create_profile(db)
        try:
            track_ids, canonical_ids = await _seed_tracks(
                db, media_storage, owner=owner, count=3, prefix="order"
            )
            playlist = await user_playlists.create_user_playlist(
                db, owner["id"], name="Ordered"
            )
            for track_id in track_ids:
                await user_playlists.add_track(
                    db, playlist["id"], owner["id"], track_id
                )
            assert await user_playlists.list_track_ids(db, playlist["id"]) == track_ids

            reversed_ids = list(reversed(track_ids))
            await user_playlists.reorder_tracks(
                db, playlist["id"], owner["id"], reversed_ids
            )
            assert (
                await user_playlists.list_track_ids(db, playlist["id"])
                == reversed_ids
            )
            positions = await db.fetch(
                f"select user_track_id, position from "
                f"{db.schema_sql}.user_playlist_tracks "
                "where playlist_id = $1 order by position",
                playlist["id"],
            )
            assert [(row["user_track_id"], row["position"]) for row in positions] == [
                (track_id, index) for index, track_id in enumerate(reversed_ids)
            ]

            # A non-permutation (missing, extra, or duplicated ids) is refused
            # before anything is written.
            for invalid in (
                reversed_ids[:2],
                reversed_ids + [track_ids[0]],
                [reversed_ids[0], reversed_ids[0], reversed_ids[1]],
                [],
            ):
                with pytest.raises(user_playlists.InvalidTrackOrderError):
                    await user_playlists.reorder_tracks(
                        db, playlist["id"], owner["id"], invalid
                    )
            assert (
                await user_playlists.list_track_ids(db, playlist["id"])
                == reversed_ids
            )

            with pytest.raises(user_playlists.UserPlaylistNotFoundError):
                await user_playlists.reorder_tracks(
                    db, playlist["id"], other["id"], reversed_ids
                )
        finally:
            await cleanup_test_data(
                db, profiles=[owner, other], canonical_ids=canonical_ids
            )

    db_run(scenario)


def test_add_track_requires_a_visible_owned_track(db_run, media_storage):
    async def scenario(db):
        owner = await create_profile(db)
        other = await create_profile(db)
        try:
            owner_tracks, owner_assets = await _seed_tracks(
                db, media_storage, owner=owner, count=1, prefix="mine"
            )
            other_tracks, other_assets = await _seed_tracks(
                db, media_storage, owner=other, count=1, prefix="theirs"
            )
            playlist = await user_playlists.create_user_playlist(
                db, owner["id"], name="Mine"
            )

            with pytest.raises(user_playlists.UserPlaylistTrackNotFoundError):
                await user_playlists.add_track(
                    db, playlist["id"], owner["id"], other_tracks[0]
                )

            # Hiding the owner's job hides the track from membership changes.
            job = await db.fetchrow(
                f"select id from {db.schema_sql}.download_jobs where user_id = $1",
                owner["id"],
            )
            await library.hide_library_item(db, owner["id"], job["id"])
            with pytest.raises(user_playlists.UserPlaylistTrackNotFoundError):
                await user_playlists.add_track(
                    db, playlist["id"], owner["id"], owner_tracks[0]
                )
            assert await user_playlists.list_track_ids(db, playlist["id"]) == []

            # A playlist owned by somebody else is not addressable.
            with pytest.raises(user_playlists.UserPlaylistNotFoundError):
                await user_playlists.add_track(
                    db, playlist["id"], other["id"], other_tracks[0]
                )
        finally:
            await cleanup_test_data(
                db,
                profiles=[owner, other],
                canonical_ids=owner_assets + other_assets,
            )

    db_run(scenario)


def test_concurrent_membership_changes_serialize_on_the_playlist_lock(
    db_run, integration_settings, media_storage
):
    async def scenario(db):
        owner = await create_profile(db)
        second = await create_pool(integration_settings, min_size=1, max_size=2)
        try:
            track_ids, canonical_ids = await _seed_tracks(
                db, media_storage, owner=owner, count=3, prefix="race"
            )
            playlist = await user_playlists.create_user_playlist(
                db, owner["id"], name="Raced"
            )

            # Concurrent adds of the same track produce one membership row.
            await asyncio.gather(
                user_playlists.add_track(
                    db, playlist["id"], owner["id"], track_ids[0]
                ),
                user_playlists.add_track(
                    second, playlist["id"], owner["id"], track_ids[0]
                ),
            )
            rows = await db.fetch(
                f"select user_track_id from {db.schema_sql}.user_playlist_tracks "
                "where playlist_id = $1",
                playlist["id"],
            )
            assert [row["user_track_id"] for row in rows] == [track_ids[0]]

            for track_id in track_ids[1:]:
                await user_playlists.add_track(
                    db, playlist["id"], owner["id"], track_id
                )

            # Concurrent reorders serialize on the playlist row lock; the
            # deferred position constraint is satisfied at each commit.
            target = [track_ids[2], track_ids[0], track_ids[1]]
            await asyncio.gather(
                user_playlists.reorder_tracks(
                    db, playlist["id"], owner["id"], target
                ),
                user_playlists.reorder_tracks(
                    second, playlist["id"], owner["id"], target
                ),
            )
            assert await user_playlists.list_track_ids(db, playlist["id"]) == target
            positions = await db.fetch(
                f"select position from {db.schema_sql}.user_playlist_tracks "
                "where playlist_id = $1 order by position",
                playlist["id"],
            )
            assert [row["position"] for row in positions] == [0, 1, 2]
        finally:
            await second.close()
            await cleanup_test_data(
                db, profiles=[owner], canonical_ids=canonical_ids
            )

    db_run(scenario)


def test_deferred_position_constraint_is_checked_at_commit(db_run, media_storage):
    async def scenario(db):
        owner = await create_profile(db)
        try:
            track_ids, canonical_ids = await _seed_tracks(
                db, media_storage, owner=owner, count=2, prefix="defer"
            )
            playlist = await user_playlists.create_user_playlist(
                db, owner["id"], name="Deferred"
            )

            # Two rows at the same position are accepted inside the
            # transaction and rejected when it commits: this is exactly the
            # property reorder relies on.
            with pytest.raises(psycopg.errors.UniqueViolation):
                async with db.transaction() as connection:
                    await connection.execute(
                        f"insert into {db.schema_sql}.user_playlist_tracks "
                        "(playlist_id, user_track_id, position) "
                        "values ($1, $2, 0)",
                        playlist["id"],
                        track_ids[0],
                    )
                    await connection.execute(
                        f"insert into {db.schema_sql}.user_playlist_tracks "
                        "(playlist_id, user_track_id, position) "
                        "values ($1, $2, 0)",
                        playlist["id"],
                        track_ids[1],
                    )

            rows = await db.fetch(
                f"select position from {db.schema_sql}.user_playlist_tracks "
                "where playlist_id = $1",
                playlist["id"],
            )
            assert rows == []

            # A rolled-back manual edit leaves the membership untouched.
            await user_playlists.add_track(
                db, playlist["id"], owner["id"], track_ids[0]
            )
            with pytest.raises(RuntimeError, match="rollback"):
                async with db.transaction() as connection:
                    await connection.execute(
                        f"delete from {db.schema_sql}.user_playlist_tracks "
                        "where playlist_id = $1",
                        playlist["id"],
                    )
                    raise RuntimeError("rollback")
            assert await user_playlists.list_track_ids(db, playlist["id"]) == [
                track_ids[0]
            ]
        finally:
            await cleanup_test_data(
                db, profiles=[owner], canonical_ids=canonical_ids
            )

    db_run(scenario)
