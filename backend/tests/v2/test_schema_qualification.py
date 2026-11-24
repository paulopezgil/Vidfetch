"""Every service query must target the configured application schema.

These tests build the real service functions with a fake database whose
``schema`` is ``vidfetch`` and assert on the SQL strings actually emitted. A
default deployment keeps ``public`` (covered by the other service tests), but a
dedicated deployment must never leak a reference to ``public``.
"""
from __future__ import annotations

import asyncio
import base64
from uuid import uuid4

from backend.app.services import admin_inventory, assets, jobs, library, playlists
from backend.app.services import profiles, tracks, user_playlists
from backend.app.services.storage import Storage
from backend.tests.v2.fakes import (
    FakeDatabase,
    asset_row,
    job_row,
    library_row,
    playlist_row,
    profile_row,
    track_row,
    user_playlist_row,
)


def run(coro):
    return asyncio.run(coro)


def _vidfetch_db() -> FakeDatabase:
    return FakeDatabase(schema="vidfetch")


def _assert_qualified(db: FakeDatabase) -> None:
    assert db.calls, "expected at least one query"
    for _, query, _ in db.calls:
        assert '"vidfetch".' in query or "select 1" in query
        assert "public." not in query


def test_profiles_queries_use_configured_schema():
    user_id = uuid4()
    db = _vidfetch_db()
    db.queue_fetchrow(profile_row(user_id=user_id, is_approved=True))

    row = run(profiles.get_profile(db, user_id))

    assert row["id"] == user_id
    _assert_qualified(db)
    assert 'from "vidfetch".profiles where id = $1' in db.calls[0][1]


def test_profile_audit_insert_uses_configured_schema():
    user_id = uuid4()
    actor_id = uuid4()
    db = _vidfetch_db()
    db.queue_fetchrow(profile_row(user_id=user_id, is_approved=True))

    run(profiles.approve_profile(db, user_id, actor_id))

    _assert_qualified(db)
    assert 'update "vidfetch".profiles' in db.calls[0][1]
    assert 'insert into "vidfetch".admin_audit_log' in db.calls[1][1]


def test_admin_guard_locks_the_configured_schema():
    target = profile_row(app_role="user", is_approved=True)
    db = _vidfetch_db()
    db.queue_fetch([{"id": uuid4()}])
    db.queue_fetchrow(target)
    db.queue_fetchrow({**target, "is_approved": False})

    run(profiles.revoke_profile(db, target["id"], uuid4()))

    _assert_qualified(db)
    assert 'select id from "vidfetch".profiles' in db.calls[0][1]
    assert 'select' in db.calls[1][1] and 'from "vidfetch".profiles' in db.calls[1][1]
    assert 'update "vidfetch".profiles' in db.calls[2][1]
    assert 'insert into "vidfetch".admin_audit_log' in db.calls[3][1]


def test_jobs_queries_use_configured_schema():
    job = job_row()
    db = _vidfetch_db()
    db.queue_fetchrow(job)

    assert run(jobs.get_job(db, job["id"]))["id"] == job["id"]

    _assert_qualified(db)
    assert 'from "vidfetch".download_jobs where id = $1' in db.calls[0][1]


def test_job_insert_uses_configured_schema():
    job = job_row()
    db = _vidfetch_db()
    db.queue_fetchrow(job)

    run(
        jobs.create_job(
            db,
            user_id=job["user_id"],
            source_url="https://example.test/video",
            options_hash="a" * 64,
        )
    )

    _assert_qualified(db)
    assert 'insert into "vidfetch".download_jobs' in db.calls[0][1]


def test_assets_queries_use_configured_schema():
    asset = asset_row()
    db = _vidfetch_db()
    db.queue_fetchrow(asset)

    assert run(assets.get_asset(db, asset["id"]))["id"] == asset["id"]

    _assert_qualified(db)
    assert 'from "vidfetch".media_assets where id = $1' in db.calls[0][1]


def test_asset_touch_uses_configured_schema():
    db = _vidfetch_db()
    db.queue_execute("UPDATE 1")

    assert run(assets.touch_accessed(db, uuid4())) is True

    _assert_qualified(db)
    assert 'update "vidfetch".media_assets' in db.calls[0][1]


def test_playlists_queries_use_configured_schema():
    playlist = playlist_row()
    db = _vidfetch_db()
    db.queue_fetchrow(playlist)

    assert run(playlists.get_playlist(db, playlist["id"]))["id"] == playlist["id"]

    _assert_qualified(db)
    assert 'from "vidfetch".playlists where id = $1' in db.calls[0][1]


def test_playlist_upsert_conflict_target_is_qualified():
    playlist = playlist_row()
    db = _vidfetch_db()
    db.queue_fetchrow(playlist)

    run(
        playlists.upsert_playlist(
            db,
            user_id=playlist["user_id"],
            canonical_id="youtube:PL1",
            source_url="https://example.test/list",
            title="My playlist",
            channel="A channel",
            item_count=0,
            options_hash="c" * 64,
            format_selector="best",
        )
    )

    _assert_qualified(db)
    query = db.calls[0][1]
    assert 'insert into "vidfetch".playlists' in query
    assert '"vidfetch".playlists.thumbnail_path' in query


def test_library_queries_use_configured_schema():
    owner = uuid4()
    db = _vidfetch_db()
    db.queue_fetchrow({"total": 1})
    db.queue_fetch([library_row()])

    page, total = run(library.list_library(db, owner))

    assert total == 1
    assert len(page) == 1
    _assert_qualified(db)
    count_query = db.calls[0][1]
    assert 'from "vidfetch".download_jobs j' in count_query
    assert 'join "vidfetch".media_assets a on j.asset_id = a.id' in count_query


def test_library_hide_uses_configured_schema():
    db = _vidfetch_db()
    db.queue_fetchrow({"id": uuid4()})

    assert run(library.hide_library_item(db, uuid4(), uuid4())) is True

    _assert_qualified(db)
    assert 'update "vidfetch".download_jobs' in db.calls[0][1]


def test_tracks_queries_use_configured_schema():
    owner = uuid4()
    db = _vidfetch_db()
    db.queue_fetchrow({"total": 1})
    db.queue_fetch([track_row()])

    page, total = run(tracks.list_tracks(db, owner))

    assert total == 1
    assert len(page) == 1
    _assert_qualified(db)
    count_query = db.calls[0][1]
    assert 'from "vidfetch".user_tracks ut' in count_query
    assert 'join "vidfetch".media_assets a on a.id = ut.asset_id' in count_query
    assert 'from "vidfetch".download_jobs j' in count_query
    page_query = db.calls[1][1]
    assert 'from "vidfetch".user_tracks ut' in page_query
    assert 'from "vidfetch".download_jobs j' in page_query


def test_admin_job_inventory_uses_configured_schema():
    db = _vidfetch_db()
    db.queue_fetchrow({"total": 1})
    db.queue_fetch([{**job_row(), "user_email": "owner@example.test"}])

    items, total = run(admin_inventory.list_jobs(db))

    assert total == 1
    assert len(items) == 1
    _assert_qualified(db)
    count_query = db.calls[0][1]
    assert 'from "vidfetch".download_jobs j' in count_query
    assert 'join "vidfetch".profiles p on p.id = j.user_id' in count_query


def test_admin_asset_inventory_uses_configured_schema():
    db = _vidfetch_db()
    db.queue_fetchrow({"total": 1})
    db.queue_fetch([{**asset_row(), "job_count": 0, "user_count": 0}])

    items, total = run(admin_inventory.list_assets(db))

    assert total == 1
    assert len(items) == 1
    _assert_qualified(db)
    count_query = db.calls[0][1]
    assert 'from "vidfetch".media_assets a' in count_query
    page_query = db.calls[1][1]
    assert 'from "vidfetch".download_jobs j' in page_query
    assert 'from "vidfetch".media_assets a' in page_query


def test_admin_delete_asset_uses_configured_schema():
    asset = asset_row(status="ready")
    db = _vidfetch_db()
    db.queue_fetchrow(asset)
    db.queue_fetchrow({"total": 0})
    db.queue_fetchrow(asset)

    deleted = run(admin_inventory.delete_asset(db, None, asset["id"], uuid4()))

    assert deleted is not None
    _assert_qualified(db)
    assert 'from "vidfetch".media_assets' in db.calls[0][1]
    assert 'from "vidfetch".download_jobs' in db.calls[1][1]
    assert 'delete from "vidfetch".media_assets' in db.calls[2][1]
    assert 'insert into "vidfetch".admin_audit_log' in db.calls[3][1]


def test_curated_playlist_queries_use_configured_schema():
    owner = uuid4()
    playlist = user_playlist_row(user_id=owner)
    db = _vidfetch_db()
    db.queue_fetchrow({"total": 1})
    db.queue_fetch([playlist])

    items, total = run(user_playlists.list_user_playlists(db, owner))

    assert total == 1
    assert items == [playlist]
    _assert_qualified(db)
    total_query = db.calls[0][1]
    assert 'from "vidfetch".user_playlists p' in total_query
    page_query = db.calls[1][1]
    assert 'from "vidfetch".user_playlists p' in page_query
    assert 'from "vidfetch".user_playlist_tracks t' in page_query
    assert 'join "vidfetch".media_assets a on a.id = ut.asset_id' in page_query
    assert 'from "vidfetch".download_jobs j' in page_query


def test_curated_playlist_detail_uses_configured_schema():
    owner = uuid4()
    playlist = user_playlist_row(user_id=owner)
    track = track_row()
    db = _vidfetch_db()
    db.queue_fetchrow(playlist)
    db.queue_fetch([{"user_track_id": track["id"]}])
    db.queue_fetch([track])

    result = run(
        user_playlists.get_playlist_with_tracks(db, playlist["id"], owner)
    )

    assert result is not None
    _assert_qualified(db)
    assert 'from "vidfetch".user_playlists p' in db.calls[0][1]
    assert 'from "vidfetch".user_playlist_tracks t' in db.calls[1][1]
    assert 'from "vidfetch".user_tracks ut' in db.calls[2][1]
    assert 'from "vidfetch".download_jobs j' in db.calls[2][1]


def test_curated_playlist_writes_use_configured_schema():
    owner = uuid4()
    playlist = user_playlist_row(user_id=owner)
    db = _vidfetch_db()
    db.queue_fetchrow(playlist)
    run(
        user_playlists.create_user_playlist(
            db, owner, name="Mix", description=""
        )
    )
    _assert_qualified(db)
    assert 'insert into "vidfetch".user_playlists' in db.calls[0][1]

    db = _vidfetch_db()
    db.queue_fetchrow(playlist)
    run(
        user_playlists.update_user_playlist(
            db, playlist["id"], owner, {"name": "Renamed"}
        )
    )
    _assert_qualified(db)
    assert 'update "vidfetch".user_playlists p' in db.calls[0][1]
    assert 'from "vidfetch".user_playlist_tracks t' in db.calls[0][1]

    db = _vidfetch_db()
    db.queue_fetchrow({"id": playlist["id"]})
    assert run(
        user_playlists.delete_user_playlist(db, playlist["id"], owner)
    ) is True
    _assert_qualified(db)
    assert 'update "vidfetch".user_playlists' in db.calls[0][1]


def test_curated_playlist_mutations_use_configured_schema():
    owner = uuid4()
    playlist = user_playlist_row(user_id=owner)
    track = track_row()

    db = _vidfetch_db()
    db.queue_fetchrow({"id": playlist["id"]})
    db.queue_fetchrow({"id": track["id"]})
    run(
        user_playlists.add_track(
            db, playlist["id"], owner, track["id"]
        )
    )
    _assert_qualified(db)
    assert 'from "vidfetch".user_playlists p' in db.calls[0][1]
    assert 'from "vidfetch".user_tracks ut' in db.calls[1][1]
    assert 'insert into "vidfetch".user_playlist_tracks' in db.calls[2][1]

    db = _vidfetch_db()
    db.queue_fetchrow({"id": playlist["id"]})
    db.queue_fetchrow({"position": 0})
    assert run(
        user_playlists.remove_track(
            db, playlist["id"], owner, track["id"]
        )
    ) is True
    _assert_qualified(db)
    assert 'delete from "vidfetch".user_playlist_tracks' in db.calls[1][1]
    assert 'update "vidfetch".user_playlist_tracks t' in db.calls[2][1]

    db = _vidfetch_db()
    db.queue_fetchrow({"id": playlist["id"]})
    db.queue_fetch([{"user_track_id": track["id"]}])
    run(
        user_playlists.reorder_tracks(
            db, playlist["id"], owner, [track["id"]]
        )
    )
    _assert_qualified(db)
    assert 'from "vidfetch".user_playlist_tracks t' in db.calls[1][1]
    assert 'update "vidfetch".user_playlist_tracks' in db.calls[2][1]


def test_track_detail_and_metadata_queries_use_configured_schema():
    owner, track_id = uuid4(), uuid4()
    db = _vidfetch_db()
    db.queue_fetchrow(track_row(track_id=track_id))

    assert run(tracks.get_track(db, track_id, owner))["id"] == track_id
    _assert_qualified(db)
    assert 'from "vidfetch".user_tracks ut' in db.calls[0][1]
    assert '"vidfetch".media_assets a' in db.calls[0][1]
    assert 'from "vidfetch".download_jobs j' in db.calls[0][1]

    db = _vidfetch_db()
    db.queue_fetchrow({"id": track_id})
    db.queue_fetchrow(track_row(track_id=track_id))
    run(tracks.update_track(db, track_id, owner, {"custom_title": "Renamed"}))
    _assert_qualified(db)
    assert 'update "vidfetch".user_tracks ut' in db.calls[0][1]
    assert 'from "vidfetch".media_assets a' in db.calls[0][1]
    assert 'from "vidfetch".download_jobs j' in db.calls[0][1]
    assert 'from "vidfetch".user_tracks ut' in db.calls[1][1]

    db = _vidfetch_db()
    db.queue_fetch([])
    run(tracks.list_facets(db, owner, kind="artist"))
    _assert_qualified(db)
    assert 'from "vidfetch".user_tracks ut' in db.calls[0][1]


def test_track_cover_queries_use_configured_schema(tmp_path):
    owner, track_id = uuid4(), uuid4()
    storage = Storage(tmp_path / "downloads")
    storage.ensure_directories()
    payload = base64.b64encode(b"\x89PNG\r\n\x1a\npixels").decode("ascii")

    db = _vidfetch_db()
    db.queue_fetchrow({"id": track_id, "cover_path": None})
    relative = run(
        tracks.set_cover(
            db,
            storage,
            track_id,
            owner,
            content_type="image/png",
            data=payload,
        )
    )
    assert relative == f"covers/{owner}/{track_id}.png"
    _assert_qualified(db)
    assert 'from "vidfetch".user_tracks ut' in db.calls[0][1]
    assert 'update "vidfetch".user_tracks' in db.calls[1][1]

    db = _vidfetch_db()
    db.queue_fetchrow({"id": track_id, "cover_path": None})
    assert run(tracks.delete_cover(db, storage, track_id, owner)) is True
    _assert_qualified(db)
    assert 'update "vidfetch".user_tracks' in db.calls[1][1]

    db = _vidfetch_db()
    db.queue_fetchrow({"cover_path": None})
    assert run(tracks.resolve_cover_path(db, storage, track_id, owner)) is None
    _assert_qualified(db)
    assert 'from "vidfetch".user_tracks ut' in db.calls[0][1]


def test_curated_playlist_read_helpers_use_configured_schema():
    owner = uuid4()
    playlist = user_playlist_row(user_id=owner)

    db = _vidfetch_db()
    db.queue_fetchrow(playlist)
    assert (
        run(user_playlists.get_user_playlist(db, playlist["id"], owner))["id"]
        == playlist["id"]
    )
    _assert_qualified(db)
    assert 'from "vidfetch".user_playlists p' in db.calls[0][1]

    db = _vidfetch_db()
    db.queue_fetch([{"user_track_id": uuid4()}])
    run(user_playlists.list_track_ids(db, playlist["id"]))
    _assert_qualified(db)
    assert 'from "vidfetch".user_playlist_tracks t' in db.calls[0][1]
