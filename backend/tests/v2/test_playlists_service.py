"""Tests for the playlist service SQL and row reconciliation."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from backend.app.services import playlists
from backend.tests.v2.fakes import (
    FakeDatabase,
    playlist_item_row,
    playlist_row,
)


def run(coro):
    return asyncio.run(coro)


def test_upsert_uses_user_canonical_options_conflict_key():
    user_id = uuid4()
    row = playlist_row(user_id=user_id)
    db = FakeDatabase()
    db.queue_fetchrow(row)

    result = run(
        playlists.upsert_playlist(
            db,
            user_id=user_id,
            canonical_id="youtube:PL1",
            source_url="https://example.test/list",
            title="My playlist",
            channel="A channel",
            item_count=4,
            options_hash="d" * 64,
            format_selector="720p",
            thumbnail_path="playlists/cover.jpg",
        )
    )

    assert result["id"] == row["id"]
    kind, query, args = db.calls[0]
    assert kind == "fetchrow"
    assert "on conflict (user_id, canonical_id, options_hash) do update" in query
    assert "thumbnail_path = coalesce(excluded.thumbnail_path" in query
    assert args == (
        user_id,
        "youtube:PL1",
        "https://example.test/list",
        "My playlist",
        "A channel",
        "playlists/cover.jpg",
        4,
        "d" * 64,
        "720p",
    )


def test_upsert_rejects_empty_identity_and_hash():
    db = FakeDatabase()
    with pytest.raises(ValueError):
        run(
            playlists.upsert_playlist(
                db,
                user_id=uuid4(),
                canonical_id="",
                source_url="",
                title="",
                channel="",
                item_count=0,
                options_hash="x",
                format_selector="best",
            )
        )
    with pytest.raises(ValueError):
        run(
            playlists.upsert_playlist(
                db,
                user_id=uuid4(),
                canonical_id="youtube:PL1",
                source_url="",
                title="",
                channel="",
                item_count=0,
                options_hash="",
                format_selector="best",
            )
        )


def test_get_playlist_is_scoped_when_user_given():
    playlist_id = uuid4()
    user_id = uuid4()
    row = playlist_row(playlist_id=playlist_id, user_id=user_id)
    db = FakeDatabase()
    db.queue_fetchrow(row, None)

    owned = run(playlists.get_playlist(db, playlist_id, user_id=user_id))
    missing = run(
        playlists.get_playlist(db, playlist_id, user_id=uuid4())
    )

    assert owned["id"] == playlist_id
    assert missing is None
    assert "user_id = $2" in db.calls[0][1]
    assert db.calls[0][2] == (playlist_id, user_id)


def test_list_playlists_returns_page_and_total_scoped_to_owner():
    user_id = uuid4()
    row = playlist_row(user_id=user_id)
    db = FakeDatabase()
    db.queue_fetchrow({"total": 1})
    db.queue_fetch([row])

    rows, total = run(
        playlists.list_playlists(db, user_id, limit=10, offset=5)
    )

    assert total == 1
    assert [item["id"] for item in rows] == [row["id"]]
    assert "where user_id = $1" in db.calls[0][1]
    assert db.calls[0][2] == (user_id,)
    assert db.calls[1][2] == (user_id, 10, 5)


def test_replace_items_preserves_matched_asset_and_prunes_stale_rows():
    playlist_id = uuid4()
    kept = playlist_item_row(
        playlist_id=playlist_id,
        position=2,
        canonical_id="youtube:two",
        asset_id=uuid4(),
        status="ready",
    )
    stale = playlist_item_row(
        playlist_id=playlist_id,
        position=1,
        canonical_id="youtube:one",
    )
    moved = {
        **kept,
        "position": 1,
        "title": "Two moved",
    }
    inserted = playlist_item_row(
        playlist_id=playlist_id,
        position=2,
        canonical_id="youtube:three",
    )
    db = FakeDatabase()
    db.queue_fetch([stale, kept])
    db.queue_execute("UPDATE 2")
    db.queue_fetchrow(moved)
    db.queue_fetchrow(inserted)
    db.queue_execute("DELETE 1")

    rows = run(
        playlists.replace_items(
            db,
            playlist_id,
            [
                {
                    "canonical_id": "youtube:two",
                    "source_url": "https://example.test/two",
                    "title": "Two moved",
                    "channel": "Two channel",
                    "duration_seconds": 12,
                },
                {
                    "canonical_id": "youtube:three",
                    "source_url": "https://example.test/three",
                    "title": "Three",
                    "channel": "Three channel",
                    "duration_seconds": 9,
                },
            ],
        )
    )

    assert [row["position"] for row in rows] == [1, 2]
    assert [row["canonical_id"] for row in rows] == [
        "youtube:two",
        "youtube:three",
    ]

    update_query, update_args = db.calls[2][1], db.calls[2][2]
    assert "asset_id = case when canonical_id = $4 then asset_id" in update_query
    assert (
        "channel = case when canonical_id = $4 and channel <> '' "
        "then channel else $8 end" in update_query
    )
    assert update_args[0] == kept["id"]
    assert update_args[2] == 1
    assert update_args[7] == "Two channel"

    insert_query, insert_args = db.calls[3][1], db.calls[3][2]
    assert "(playlist_id, position, canonical_id, source_url, title, channel" in (
        insert_query
    )
    assert insert_args[5] == "Three channel"

    prune_query = db.calls[4][1]
    assert "position < 0" in prune_query
    assert db.calls[4][2] == (playlist_id,)


def test_replace_items_inserts_when_no_rows_exist_and_dedupes_canonical():
    playlist_id = uuid4()
    first = playlist_item_row(
        playlist_id=playlist_id,
        position=1,
        canonical_id="youtube:same",
    )
    db = FakeDatabase()
    db.queue_fetch([])
    db.queue_fetchrow(first)

    rows = run(
        playlists.replace_items(
            db,
            playlist_id,
            [
                {
                    "canonical_id": "youtube:same",
                    "source_url": "https://example.test/a",
                    "title": "First",
                    "channel": "A channel",
                },
                {
                    "canonical_id": "youtube:same",
                    "source_url": "https://example.test/b",
                    "title": "Duplicate",
                    "channel": "B channel",
                },
            ],
        )
    )

    assert [row["canonical_id"] for row in rows] == ["youtube:same"]
    assert len([call for call in db.calls if call[0] == "fetchrow"]) == 1
    assert 'insert into "public".playlist_items' in db.calls[1][1]
    assert db.calls[1][2][5] == "A channel"


def test_update_item_only_sets_supplied_link_columns():
    playlist_id = uuid4()
    asset_id = uuid4()
    updated = playlist_item_row(
        playlist_id=playlist_id,
        position=2,
        asset_id=asset_id,
        status="ready",
    )
    db = FakeDatabase()
    db.queue_fetchrow(updated)

    result = run(
        playlists.update_item(
            db,
            playlist_id,
            2,
            status="ready",
            asset_id=asset_id,
            error="",
        )
    )

    assert result["status"] == "ready"
    query, args = db.calls[0][1], db.calls[0][2]
    assert "status = $3" in query
    assert "asset_id = $5" in query
    assert "job_id = $" not in query
    assert args == (playlist_id, 2, "ready", "", asset_id)


def test_update_item_persists_a_resolved_channel():
    playlist_id = uuid4()
    updated = playlist_item_row(
        playlist_id=playlist_id,
        position=1,
        channel="Resolved channel",
    )
    db = FakeDatabase()
    db.queue_fetchrow(updated)

    result = run(
        playlists.update_item(
            db,
            playlist_id,
            1,
            status="downloading",
            channel="Resolved channel",
        )
    )

    assert result["channel"] == "Resolved channel"
    query, args = db.calls[0][1], db.calls[0][2]
    assert "channel = $5" in query
    assert args == (playlist_id, 1, "downloading", "", "Resolved channel")


def test_update_item_rejects_invalid_status():
    db = FakeDatabase()
    with pytest.raises(ValueError):
        run(
            playlists.update_item(
                db, uuid4(), 1, status="exploded"
            )
        )
    assert db.calls == []


def test_update_playlist_whitelists_columns():
    playlist_id = uuid4()
    updated = playlist_row(playlist_id=playlist_id, status="downloading")
    db = FakeDatabase()
    db.queue_fetchrow(updated)

    result = run(
        playlists.update_playlist(
            db, playlist_id, status="downloading", item_count=3
        )
    )

    assert result["status"] == "downloading"
    query, args = db.calls[0][1], db.calls[0][2]
    assert "status = $2" in query
    assert "item_count = $3" in query
    assert args == (playlist_id, "downloading", 3)

    with pytest.raises(ValueError):
        run(playlists.update_playlist(db, playlist_id, user_id=uuid4()))


def test_delete_playlist_returns_false_for_another_user():
    playlist_id = uuid4()
    owner = uuid4()
    stranger = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(None)
    db.queue_fetchrow({"id": playlist_id})

    missing = run(playlists.delete_playlist(db, playlist_id, stranger))
    deleted = run(playlists.delete_playlist(db, playlist_id, owner))

    assert missing is False
    assert deleted is True
    assert "user_id = $2" in db.calls[0][1]
    assert db.calls[0][2] == (playlist_id, stranger)
    assert db.calls[1][2] == (playlist_id, owner)


def test_playlist_cover_path_is_storage_relative():
    playlist_id = uuid4()
    assert (
        playlists.playlist_cover_path(playlist_id)
        == f"playlists/{playlist_id}.jpg"
    )
