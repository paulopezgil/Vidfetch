"""Service tests for the per-user tracks query."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from backend.app.services import tracks
from backend.tests.v2.fakes import FakeDatabase, track_row


def run(coro):
    return asyncio.run(coro)


def test_list_tracks_scopes_visibility_and_orders_newest_downloaded_first():
    owner = uuid4()
    rows = [track_row(), track_row()]
    db = FakeDatabase()
    db.queue_fetchrow({"total": 2})
    db.queue_fetch(rows)

    page, total = run(tracks.list_tracks(db, owner, limit=10, offset=0))

    assert page == rows
    assert total == 2
    assert all(row["status"] == "ready" for row in page)

    count_query, count_args = db.calls[0][1], db.calls[0][2]
    assert 'from "public".user_tracks ut' in count_query
    assert 'join "public".media_assets a on a.id = ut.asset_id' in count_query
    assert "join lateral (" in count_query
    assert 'from "public".download_jobs j' in count_query
    assert "j.user_id = ut.user_id" in count_query
    assert "j.asset_id = ut.asset_id" in count_query
    assert "j.status = 'ready'" in count_query
    assert "j.library_hidden = false" in count_query
    assert "ut.user_id = $1" in count_query
    assert "ut.deleted_at is null" in count_query
    assert "a.status = 'ready'" in count_query
    assert count_args == (owner,)

    page_query, page_args = db.calls[1][1], db.calls[1][2]
    assert "j.library_hidden = false" in page_query
    assert "ut.deleted_at is null" in page_query
    assert "a.status = 'ready'" in page_query
    assert "order by ut.downloaded_at desc, ut.id desc" in page_query
    assert "limit $2 offset $3" in page_query
    assert page_args == (owner, 10, 0)


def test_list_tracks_selects_one_representative_ready_job_per_asset():
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    run(tracks.list_tracks(db, uuid4()))

    page_query = db.calls[1][1]
    assert (
        "order by j.completed_at desc nulls last, "
        "j.created_at desc, j.id desc limit 1"
    ) in page_query
    # The lateral join must be inner: a track with no eligible job must vanish.
    assert "left join lateral" not in page_query.lower()


def test_list_tracks_builds_the_contract_columns_with_title_precedence():
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    run(tracks.list_tracks(db, uuid4()))

    page_query = db.calls[1][1]
    assert (
        "coalesce(nullif(ut.custom_title, ''), nullif(j.title, ''), "
        "a.title, '')"
    ) in page_query
    assert "ut.custom_artist as artist" in page_query
    assert "ut.custom_album as album" in page_query
    assert "ut.cover_path, a.thumbnail_path" in page_query
    assert "a.duration_seconds, a.file_size_bytes" in page_query
    assert "a.output_ext, j.format_selector, j.playlist_id" in page_query
    assert "'ready' as status" in page_query
    assert "ut.downloaded_at, ut.updated_at" in page_query


def test_list_tracks_clamps_pagination_args():
    owner = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    page, total = run(tracks.list_tracks(db, owner, limit=10_000, offset=-5))

    assert page == []
    assert total == 0
    assert db.calls[0][2] == (owner,)
    assert db.calls[1][2] == (owner, tracks.MAX_PAGE_SIZE, 0)


def test_list_tracks_maps_a_missing_count_row_to_zero():
    db = FakeDatabase()
    db.queue_fetchrow(None)
    db.queue_fetch([])

    page, total = run(tracks.list_tracks(db, uuid4()))

    assert page == []
    assert total == 0


def test_list_tracks_rejects_an_invalid_user_id_without_querying():
    db = FakeDatabase()

    with pytest.raises(ValueError):
        run(tracks.list_tracks(db, "not-a-uuid"))

    assert db.calls == []
