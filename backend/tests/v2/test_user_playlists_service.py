"""Service tests for curated playlists and ordered membership."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from backend.app.services import user_playlists
from backend.tests.v2.fakes import (
    FakeDatabase,
    track_row,
    user_playlist_row,
)


def run(coro):
    return asyncio.run(coro)


def test_list_user_playlists_scopes_owner_and_counts_only_visible_tracks():
    owner = uuid4()
    row = user_playlist_row(user_id=owner, track_count=2)
    db = FakeDatabase()
    db.queue_fetchrow({"total": 1})
    db.queue_fetch([row])

    rows, total = run(
        user_playlists.list_user_playlists(db, owner, limit=10, offset=5)
    )

    assert rows == [row]
    assert total == 1

    total_query, total_args = db.calls[0][1], db.calls[0][2]
    assert 'from "public".user_playlists p' in total_query
    assert "p.user_id = $1" in total_query
    assert "p.deleted_at is null" in total_query
    assert total_args == (owner,)

    page_query, page_args = db.calls[1][1], db.calls[1][2]
    assert 'from "public".user_playlists p' in page_query
    assert "order by p.updated_at desc, p.id desc" in page_query
    assert "limit $2 offset $3" in page_query
    # The track count must use the same visibility rule as GET /api/tracks.
    assert 'from "public".user_playlist_tracks t' in page_query
    assert 'join "public".media_assets a on a.id = ut.asset_id' in page_query
    assert 'from "public".download_jobs j' in page_query
    assert "ut.id = t.user_track_id" in page_query
    assert "ut.user_id = p.user_id" in page_query
    assert "ut.deleted_at is null" in page_query
    assert "a.status = 'ready'" in page_query
    assert "j.status = 'ready'" in page_query
    assert "j.library_hidden = false" in page_query
    assert page_args == (owner, 10, 5)


def test_create_user_playlist_trims_name_and_description():
    owner = uuid4()
    created = user_playlist_row(user_id=owner, name="Chill", description="late")
    db = FakeDatabase()
    db.queue_fetchrow(created)

    row = run(
        user_playlists.create_user_playlist(
            db,
            owner,
            name="  Chill  ",
            description="  late  ",
        )
    )

    assert row == created
    query, args = db.calls[0][1], db.calls[0][2]
    assert 'insert into "public".user_playlists' in query
    assert "(user_id, name, description) values ($1, $2, $3)" in query
    assert "0 as track_count" in query
    assert args == (owner, "Chill", "late")


def test_create_user_playlist_defaults_a_missing_description_to_empty():
    owner = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(user_playlist_row(user_id=owner))

    run(
        user_playlists.create_user_playlist(
            db, owner, name="Mix", description=None
        )
    )

    assert db.calls[0][2] == (owner, "Mix", "")


@pytest.mark.parametrize(
    "name,description",
    [
        ("   ", ""),
        ("x" * 201, ""),
        ("Mix", "y" * 501),
    ],
)
def test_create_user_playlist_rejects_invalid_metadata(name, description):
    db = FakeDatabase()

    with pytest.raises(ValueError):
        run(
            user_playlists.create_user_playlist(
                db, uuid4(), name=name, description=description
            )
        )

    assert db.calls == []


def test_update_user_playlist_writes_only_the_provided_fields():
    owner = uuid4()
    playlist_id = uuid4()
    updated = user_playlist_row(playlist_id=playlist_id, name="Renamed")
    db = FakeDatabase()
    db.queue_fetchrow(updated)

    row = run(
        user_playlists.update_user_playlist(
            db, playlist_id, owner, {"name": "  Renamed  "}
        )
    )

    assert row == updated
    query, args = db.calls[0][1], db.calls[0][2]
    assert 'update "public".user_playlists p' in query
    assert "set updated_at = now(), name = $3" in query
    assert "description = " not in query
    assert "where p.id = $1 and p.user_id = $2" in query
    assert "p.deleted_at is null" in query
    assert args == (playlist_id, owner, "Renamed")


def test_update_user_playlist_rejects_an_empty_field_set():
    db = FakeDatabase()

    with pytest.raises(ValueError):
        run(
            user_playlists.update_user_playlist(
                db, uuid4(), uuid4(), {}
            )
        )

    assert db.calls == []


def test_update_user_playlist_returns_none_when_not_owned():
    db = FakeDatabase()
    db.queue_fetchrow(None)

    row = run(
        user_playlists.update_user_playlist(
            db, uuid4(), uuid4(), {"description": "new"}
        )
    )

    assert row is None
    assert "p.user_id = $2" in db.calls[0][1]


def test_delete_user_playlist_soft_deletes_the_owned_row():
    owner = uuid4()
    playlist_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow({"id": playlist_id})

    deleted = run(
        user_playlists.delete_user_playlist(db, playlist_id, owner)
    )

    assert deleted is True
    query, args = db.calls[0][1], db.calls[0][2]
    assert 'update "public".user_playlists set deleted_at = now()' in query
    assert "id = $1 and user_id = $2 and deleted_at is null" in query
    assert args == (playlist_id, owner)


def test_get_playlist_with_tracks_orders_by_position_and_filters_visibility():
    owner = uuid4()
    playlist = user_playlist_row(user_id=owner, track_count=1)
    first = track_row(track_id=uuid4())
    second = track_row(track_id=uuid4(), cover_path="covers/second.jpg")
    hidden = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(playlist)
    db.queue_fetch(
        [
            {"user_track_id": second["id"]},
            {"user_track_id": hidden},
            {"user_track_id": first["id"]},
        ]
    )
    # The database returns its own order; the service must restore playlist
    # order in Python and drop the invisible track.
    db.queue_fetch([first, second])

    result = run(
        user_playlists.get_playlist_with_tracks(db, playlist["id"], owner)
    )

    assert result is not None
    returned_playlist, items = result
    assert returned_playlist == playlist
    assert [item["id"] for item in items] == [second["id"], first["id"]]

    membership_query = db.calls[1][1]
    assert 'from "public".user_playlist_tracks t' in membership_query
    assert "t.playlist_id = $1" in membership_query
    assert "order by t.position asc, t.user_track_id asc" in membership_query

    tracks_query, tracks_args = db.calls[2][1], db.calls[2][2]
    assert 'from "public".user_tracks ut' in tracks_query
    assert "ut.id = any($2::uuid[])" in tracks_query
    assert "ut.deleted_at is null" in tracks_query
    assert "a.status = 'ready'" in tracks_query
    assert "j.library_hidden = false" in tracks_query
    assert tracks_args == (owner, [second["id"], hidden, first["id"]])


def test_get_playlist_with_tracks_returns_none_when_not_owned():
    db = FakeDatabase()
    db.queue_fetchrow(None)

    assert (
        run(user_playlists.get_playlist_with_tracks(db, uuid4(), uuid4()))
        is None
    )
    assert len(db.calls) == 1


def test_add_track_appends_at_the_end_idempotently():
    owner = uuid4()
    playlist_id = uuid4()
    track_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow({"id": playlist_id})
    db.queue_fetchrow({"id": track_id})
    db.queue_execute("INSERT 0 1")
    db.queue_execute("UPDATE 1")

    run(
        user_playlists.add_track(db, playlist_id, owner, track_id)
    )

    assert db.connection.transactions == 1
    assert db.connection.commits == 1
    assert db.connection.rollbacks == 0

    lock_query, lock_args = db.calls[0][1], db.calls[0][2]
    assert 'from "public".user_playlists p' in lock_query
    assert "p.id = $1 and p.user_id = $2" in lock_query
    assert "p.deleted_at is null for update" in lock_query
    assert lock_args == (playlist_id, owner)

    visible_query, visible_args = db.calls[1][1], db.calls[1][2]
    assert 'from "public".user_tracks ut' in visible_query
    assert 'join "public".media_assets a on a.id = ut.asset_id' in visible_query
    assert "ut.id = $1 and ut.user_id = $2" in visible_query
    assert "ut.deleted_at is null" in visible_query
    assert "a.status = 'ready'" in visible_query
    assert "j.status = 'ready'" in visible_query
    assert "j.library_hidden = false" in visible_query
    assert visible_args == (track_id, owner)

    insert_query, insert_args = db.calls[2][1], db.calls[2][2]
    assert 'insert into "public".user_playlist_tracks' in insert_query
    assert "select $1, $2, coalesce(max(t.position) + 1, 0)" in insert_query
    assert "on conflict (playlist_id, user_track_id) do nothing" in insert_query
    assert insert_args == (playlist_id, track_id)

    assert 'update "public".user_playlists' in db.calls[3][1]
    assert db.calls[3][2] == (playlist_id, owner)


def test_add_track_rejects_a_track_that_is_not_owned_or_visible():
    db = FakeDatabase()
    db.queue_fetchrow({"id": uuid4()})
    db.queue_fetchrow(None)

    with pytest.raises(user_playlists.UserPlaylistTrackNotFoundError):
        run(user_playlists.add_track(db, uuid4(), uuid4(), uuid4()))

    assert db.connection.transactions == 1
    assert db.connection.rollbacks == 1
    assert all(call[0] != "execute" for call in db.calls)


def test_add_track_rejects_a_foreign_or_deleted_playlist():
    db = FakeDatabase()
    db.queue_fetchrow(None)

    with pytest.raises(user_playlists.UserPlaylistNotFoundError):
        run(user_playlists.add_track(db, uuid4(), uuid4(), uuid4()))

    assert db.connection.rollbacks == 1
    assert len(db.calls) == 1


def test_remove_track_compacts_the_remaining_positions():
    owner = uuid4()
    playlist_id = uuid4()
    track_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow({"id": playlist_id})
    db.queue_fetchrow({"position": 1})
    db.queue_execute("DELETE 1")
    db.queue_execute("UPDATE 2")
    db.queue_execute("UPDATE 1")

    removed = run(
        user_playlists.remove_track(db, playlist_id, owner, track_id)
    )

    assert removed is True
    assert db.connection.transactions == 1
    assert db.connection.commits == 1

    delete_query, delete_args = db.calls[1][1], db.calls[1][2]
    assert 'delete from "public".user_playlist_tracks' in delete_query
    assert "playlist_id = $1 and user_track_id = $2" in delete_query
    assert "returning position" in delete_query
    assert delete_args == (playlist_id, track_id)

    compact_query, compact_args = db.calls[2][1], db.calls[2][2]
    assert 'update "public".user_playlist_tracks t' in compact_query
    assert "set position = ranked.rn" in compact_query
    assert "row_number() over (order by s.position) - 1 as rn" in compact_query
    assert "t.position <> ranked.rn" in compact_query
    assert compact_args == (playlist_id,)
    assert db.calls[3][2] == (playlist_id, owner)


def test_remove_track_returns_false_when_it_is_not_a_member():
    playlist_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow({"id": playlist_id})
    db.queue_fetchrow(None)

    removed = run(
        user_playlists.remove_track(db, playlist_id, uuid4(), uuid4())
    )

    assert removed is False
    assert len(db.calls) == 2
    assert db.connection.commits == 1


def test_reorder_tracks_rewrites_positions_in_one_transaction():
    owner = uuid4()
    playlist_id = uuid4()
    first, second, third = uuid4(), uuid4(), uuid4()
    requested = [third, first, second]
    db = FakeDatabase()
    db.queue_fetchrow({"id": playlist_id})
    db.queue_fetch(
        [
            {"user_track_id": first},
            {"user_track_id": second},
            {"user_track_id": third},
        ]
    )
    db.queue_execute(*["UPDATE 1"] * 4)

    run(
        user_playlists.reorder_tracks(db, playlist_id, owner, requested)
    )

    assert db.connection.transactions == 1
    assert db.connection.commits == 1
    assert db.connection.rollbacks == 0

    lock_query = db.calls[0][1]
    assert 'from "public".user_playlists p' in lock_query
    assert "for update" in lock_query

    membership_query = db.calls[1][1]
    assert 'from "public".user_playlist_tracks t' in membership_query
    assert "where t.playlist_id = $1 for update" in membership_query

    updates = [call for call in db.calls if call[0] == "execute"]
    assert len(updates) == 4
    for position, track in enumerate(requested):
        query, args = updates[position][1], updates[position][2]
        assert 'update "public".user_playlist_tracks' in query
        assert (
            "set position = $3 where playlist_id = $1 and user_track_id = $2"
            in query
        )
        assert args == (playlist_id, track, position)
    assert 'update "public".user_playlists' in updates[3][1]
    assert updates[3][2] == (playlist_id, owner)


@pytest.mark.parametrize(
    "requested_factory",
    [
        lambda ids: [ids[0], ids[1]],
        lambda ids: [ids[0], ids[0], ids[1]],
        lambda ids: [ids[0], ids[1], uuid4()],
    ],
)
def test_reorder_tracks_rejects_orders_that_are_not_a_permutation(
    requested_factory,
):
    ids = [uuid4(), uuid4(), uuid4()]
    db = FakeDatabase()
    db.queue_fetchrow({"id": uuid4()})
    db.queue_fetch([{"user_track_id": value} for value in ids])

    with pytest.raises(user_playlists.InvalidTrackOrderError):
        run(
            user_playlists.reorder_tracks(
                db, uuid4(), uuid4(), requested_factory(ids)
            )
        )

    assert db.connection.transactions == 1
    assert db.connection.rollbacks == 1
    assert all(call[0] != "execute" for call in db.calls)


def test_reorder_tracks_rejects_a_foreign_or_deleted_playlist():
    db = FakeDatabase()
    db.queue_fetchrow(None)

    with pytest.raises(user_playlists.UserPlaylistNotFoundError):
        run(
            user_playlists.reorder_tracks(
                db, uuid4(), uuid4(), [uuid4()]
            )
        )

    assert db.connection.rollbacks == 1
    assert len(db.calls) == 1


def test_list_user_playlists_clamps_pagination():
    owner = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    rows, total = run(
        user_playlists.list_user_playlists(
            db, owner, limit=10_000, offset=-5
        )
    )

    assert rows == []
    assert total == 0
    assert db.calls[0][2] == (owner,)
    assert db.calls[1][2] == (owner, user_playlists.MAX_PAGE_SIZE, 0)


def test_remove_track_rejects_a_foreign_or_deleted_playlist():
    db = FakeDatabase()
    db.queue_fetchrow(None)

    with pytest.raises(user_playlists.UserPlaylistNotFoundError):
        run(user_playlists.remove_track(db, uuid4(), uuid4(), uuid4()))

    assert db.connection.transactions == 1
    assert db.connection.rollbacks == 1
    assert all(call[0] != "delete" for call in db.calls)


def test_reorder_tracks_rejects_an_empty_order_for_a_non_empty_playlist():
    ids = [uuid4(), uuid4()]
    db = FakeDatabase()
    db.queue_fetchrow({"id": uuid4()})
    db.queue_fetch([{"user_track_id": value} for value in ids])

    with pytest.raises(user_playlists.InvalidTrackOrderError):
        run(user_playlists.reorder_tracks(db, uuid4(), uuid4(), []))

    assert db.connection.rollbacks == 1
    assert all(call[0] != "execute" for call in db.calls)


def test_reorder_tracks_accepts_an_empty_order_for_an_empty_playlist():
    playlist_id = uuid4()
    owner = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow({"id": playlist_id})
    db.queue_fetch([])
    db.queue_execute("UPDATE 1")

    run(user_playlists.reorder_tracks(db, playlist_id, owner, []))

    assert db.connection.commits == 1
    assert db.connection.rollbacks == 0
    updates = [call for call in db.calls if call[0] == "execute"]
    assert len(updates) == 1
    assert 'update "public".user_playlists' in updates[0][1]
    assert updates[0][2] == (playlist_id, owner)
    assert all("set position" not in call[1] for call in db.calls)
