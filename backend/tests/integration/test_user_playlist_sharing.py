"""Real-PostgreSQL tests for curated-playlist sharing.

A share grants another approved account read-only access to the owner's
playlist and to the owner's visible ``user_tracks``. The ownership-scoped
mutation functions must keep refusing the shared viewer, and unsharing must
remove access again. Every row created here is deleted in ``finally``.
"""
from __future__ import annotations

import pytest

from backend.app.services import user_playlists
from backend.tests.integration.conftest import (
    cleanup_test_data,
    create_profile,
    create_ready_job,
    make_ready_asset,
    unique_email,
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
            db,
            user_id=owner["id"],
            asset_id=asset["id"],
            title=f"{prefix} {index}",
        )
        row = await db.fetchrow(
            f"select ut.id from {db.schema_sql}.user_tracks ut "
            "where ut.user_id = $1 and ut.asset_id = $2",
            owner["id"],
            asset["id"],
        )
        track_ids.append(row["id"])
    return track_ids, canonical_ids


def test_share_grants_read_only_access_until_unshared(db_run, media_storage):
    async def scenario(db):
        owner = await create_profile(db)
        viewer = await create_profile(db)
        try:
            track_ids, canonical_ids = await _seed_tracks(
                db, media_storage, owner=owner, count=2, prefix="share"
            )
            playlist = await user_playlists.create_user_playlist(
                db, owner["id"], name="Shared mix"
            )
            for track_id in track_ids:
                await user_playlists.add_track(
                    db, playlist["id"], owner["id"], track_id
                )

            # The lookup is case-insensitive and trims the submitted address.
            shared = await user_playlists.share_playlist_with_email(
                db,
                playlist["id"],
                owner["id"],
                f"  {viewer['email'].upper()}  ",
            )
            assert shared["user_id"] == viewer["id"]
            assert shared["email"] == viewer["email"]

            # Repeating the same share is idempotent.
            again = await user_playlists.share_playlist_with_email(
                db, playlist["id"], owner["id"], viewer["email"]
            )
            assert again["user_id"] == viewer["id"]
            shares = await user_playlists.list_playlist_shares(
                db, playlist["id"], owner["id"]
            )
            assert [(row["user_id"], row["email"]) for row in shares] == [
                (viewer["id"], viewer["email"])
            ]
            assert shares[0]["created_at"] is not None

            rows, total = await user_playlists.list_shared_with_user(
                db, viewer["id"]
            )
            assert total == 1
            assert len(rows) == 1
            row = rows[0]
            assert row["id"] == playlist["id"]
            assert row["owner_email"] == owner["email"]
            assert row["is_owner"] is False
            assert row["track_count"] == 2

            detail, items, is_owner = (
                await user_playlists.get_accessible_playlist_with_tracks(
                    db, playlist["id"], viewer["id"]
                )
            )
            assert detail["owner_email"] == owner["email"]
            assert detail["is_owner"] is False
            assert is_owner is False
            # A shared viewer sees the owner's visible tracks, not their own.
            assert [item["id"] for item in items] == track_ids

            # The owner still reads the same playlist with the owner flag.
            owned, owner_items, owner_is_owner = (
                await user_playlists.get_accessible_playlist_with_tracks(
                    db, playlist["id"], owner["id"]
                )
            )
            assert owned["owner_email"] == owner["email"]
            assert owner_is_owner is True
            assert [item["id"] for item in owner_items] == track_ids

            # Unsharing removes access for the viewer only.
            assert await user_playlists.unshare_playlist(
                db, playlist["id"], owner["id"], viewer["id"]
            )
            assert not await user_playlists.unshare_playlist(
                db, playlist["id"], owner["id"], viewer["id"]
            )
            assert (
                await user_playlists.get_accessible_playlist_with_tracks(
                    db, playlist["id"], viewer["id"]
                )
                is None
            )
            assert (
                await user_playlists.list_shared_with_user(db, viewer["id"])
            )[1] == 0
            assert (
                await user_playlists.get_accessible_playlist_with_tracks(
                    db, playlist["id"], owner["id"]
                )
            ) is not None
        finally:
            await cleanup_test_data(
                db,
                profiles=[owner, viewer],
                canonical_ids=canonical_ids,
            )

    db_run(scenario)


def test_share_rejects_self_unknown_pending_and_non_owner(db_run, media_storage):
    async def scenario(db):
        owner = await create_profile(db)
        other = await create_profile(db)
        pending = await create_profile(db, is_approved=False)
        try:
            track_ids, canonical_ids = await _seed_tracks(
                db, media_storage, owner=owner, count=1, prefix="reject"
            )
            playlist = await user_playlists.create_user_playlist(
                db, owner["id"], name="Private"
            )
            await user_playlists.add_track(
                db, playlist["id"], owner["id"], track_ids[0]
            )

            for email in (
                owner["email"],
                unique_email("unknown"),
                pending["email"],
            ):
                with pytest.raises(user_playlists.ShareRecipientError):
                    await user_playlists.share_playlist_with_email(
                        db, playlist["id"], owner["id"], email
                    )

            # No failed attempt created a share row.
            shares = await user_playlists.list_playlist_shares(
                db, playlist["id"], owner["id"]
            )
            assert shares == []

            # Another account cannot share, list shares, or unshare the
            # owner's playlist, even for a real recipient.
            with pytest.raises(user_playlists.UserPlaylistNotFoundError):
                await user_playlists.share_playlist_with_email(
                    db, playlist["id"], other["id"], pending["email"]
                )
            with pytest.raises(user_playlists.UserPlaylistNotFoundError):
                await user_playlists.list_playlist_shares(
                    db, playlist["id"], other["id"]
                )
            with pytest.raises(user_playlists.UserPlaylistNotFoundError):
                await user_playlists.unshare_playlist(
                    db, playlist["id"], other["id"], owner["id"]
                )
        finally:
            await cleanup_test_data(
                db,
                profiles=[owner, other, pending],
                canonical_ids=canonical_ids,
            )

    db_run(scenario)


def test_shared_viewer_cannot_mutate_the_owner_playlist(db_run, media_storage):
    async def scenario(db):
        owner = await create_profile(db)
        viewer = await create_profile(db)
        try:
            track_ids, canonical_ids = await _seed_tracks(
                db, media_storage, owner=owner, count=2, prefix="readonly"
            )
            playlist = await user_playlists.create_user_playlist(
                db, owner["id"], name="Read only", description="owner's mix"
            )
            for track_id in track_ids:
                await user_playlists.add_track(
                    db, playlist["id"], owner["id"], track_id
                )
            await user_playlists.share_playlist_with_email(
                db, playlist["id"], owner["id"], viewer["email"]
            )

            # Owner-scoped service mutations all refuse the shared viewer.
            assert (
                await user_playlists.update_user_playlist(
                    db, playlist["id"], viewer["id"], {"name": "Hijacked"}
                )
                is None
            )
            assert not await user_playlists.delete_user_playlist(
                db, playlist["id"], viewer["id"]
            )
            with pytest.raises(user_playlists.UserPlaylistNotFoundError):
                await user_playlists.add_track(
                    db, playlist["id"], viewer["id"], track_ids[0]
                )
            with pytest.raises(user_playlists.UserPlaylistNotFoundError):
                await user_playlists.remove_track(
                    db, playlist["id"], viewer["id"], track_ids[0]
                )
            with pytest.raises(user_playlists.UserPlaylistNotFoundError):
                await user_playlists.reorder_tracks(
                    db, playlist["id"], viewer["id"], list(reversed(track_ids))
                )

            # Nothing changed for the owner.
            owned = await user_playlists.get_user_playlist(
                db, playlist["id"], owner["id"]
            )
            assert owned is not None
            assert owned["name"] == "Read only"
            assert owned["description"] == "owner's mix"
            assert await user_playlists.list_track_ids(
                db, playlist["id"]
            ) == track_ids

            # The owner can still rename their playlist.
            renamed = await user_playlists.update_user_playlist(
                db, playlist["id"], owner["id"], {"name": "Renamed"}
            )
            assert renamed is not None
            assert renamed["name"] == "Renamed"
        finally:
            await cleanup_test_data(
                db,
                profiles=[owner, viewer],
                canonical_ids=canonical_ids,
            )

    db_run(scenario)
