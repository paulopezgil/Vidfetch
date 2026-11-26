"""Tests for the durable download-job service."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from backend.app.services import jobs
from backend.tests.v2.fakes import FakeDatabase, job_row


def run(coro):
    return asyncio.run(coro)


def _create(db, **overrides):
    kwargs = {
        "user_id": uuid4(),
        "kind": "video",
        "source_url": "https://example.test/v",
        "title": "",
        "options_hash": "a" * 64,
        "format_selector": "best",
    }
    kwargs.update(overrides)
    return jobs.create_job(db, **kwargs)


def test_create_job_returns_existing_row_for_idempotency_key():
    existing = job_row(idempotency_key="key-1")
    db = FakeDatabase()
    db.queue_fetchrow(existing)

    result = run(_create(db, idempotency_key="key-1"))

    assert result == existing
    assert len(db.calls) == 1
    method, query, args = db.calls[0]
    assert "where user_id = $1 and idempotency_key = $2" in query
    assert args[1] == "key-1"


def test_create_job_inserts_queued_job_and_returns_row():
    owner = uuid4()
    inserted = job_row(user_id=owner, status="queued")
    db = FakeDatabase()
    db.queue_fetchrow(None, inserted)

    result = run(
        _create(
            db,
            user_id=owner,
            source_url="https://example.test/video",
            idempotency_key="new-key",
        )
    )

    assert result == inserted
    method, query, args = db.calls[1]
    assert 'insert into "public".download_jobs' in query
    assert args[0] == owner
    assert args[1] == "video"
    assert args[2] == "https://example.test/video"
    assert args[4] == "a" * 64
    assert args[5] == "best"
    assert args[6] == "new-key"


def test_create_job_validates_kind_options_and_key():
    db = FakeDatabase()

    with pytest.raises(ValueError):
        run(_create(db, kind="archive"))
    with pytest.raises(ValueError):
        run(_create(db, options_hash=""))
    with pytest.raises(ValueError):
        run(_create(db, idempotency_key="k" * 201))
    with pytest.raises(ValueError):
        run(_create(db, user_id="not-a-uuid"))

    assert db.calls == []


def test_get_job_is_user_scoped():
    owner = uuid4()
    row = job_row(user_id=owner)
    db = FakeDatabase()
    db.queue_fetchrow(row, None)

    found = run(jobs.get_job(db, row["id"], user_id=owner))
    missing = run(jobs.get_job(db, row["id"], user_id=owner))

    assert found == row
    assert missing is None
    query = db.calls[0][1]
    assert "where id = $1 and user_id = $2" in query
    assert db.calls[0][2][1] == owner


def test_get_job_without_scope_does_not_filter_by_user():
    row = job_row()
    db = FakeDatabase()
    db.queue_fetchrow(row)

    assert run(jobs.get_job(db, row["id"])) == row
    query = db.calls[0][1]
    assert "where id = $1" in query
    assert "and user_id" not in query
    assert len(db.calls[0][2]) == 1


def test_list_jobs_filters_scopes_and_clamps():
    owner = uuid4()
    rows = [job_row(user_id=owner), job_row(user_id=owner)]
    db = FakeDatabase()
    db.queue_fetchrow({"total": 2})
    db.queue_fetch(rows)

    page, total = run(
        jobs.list_jobs(db, owner, status="downloading", limit=10_000, offset=-5)
    )

    assert page == rows
    assert total == 2
    count_query = db.calls[0][1]
    assert "user_id = $1" in count_query
    assert "status = $2" in count_query
    page_query, page_args = db.calls[1][1], db.calls[1][2]
    assert "order by created_at desc" in page_query
    assert page_args[0] == owner
    assert page_args[1] == "downloading"
    assert page_args[2] == jobs.MAX_PAGE_SIZE
    assert page_args[3] == 0


def test_list_jobs_rejects_unknown_status():
    db = FakeDatabase()

    with pytest.raises(ValueError):
        run(jobs.list_jobs(db, uuid4(), status="exploded"))

    assert db.calls == []


def test_claim_next_job_uses_skip_locked_and_moves_to_resolving():
    row = job_row(status="queued")
    claimed = {**row, "status": "resolving"}
    db = FakeDatabase()
    db.queue_fetchrow(row, claimed)

    result = run(jobs.claim_next_job(db))

    assert result["status"] == "resolving"
    select_query = db.calls[0][1]
    assert "status = 'queued'" in select_query
    assert "for update skip locked limit 1" in select_query
    update_query = db.calls[1][1]
    assert "set status = 'resolving'" in update_query
    assert "started_at = now()" in update_query
    assert db.connection.transactions == 1


def test_claim_next_job_returns_none_when_queue_is_empty():
    db = FakeDatabase()
    db.queue_fetchrow(None)

    assert run(jobs.claim_next_job(db)) is None
    assert len(db.calls) == 1


def test_update_job_rejects_fields_outside_the_whitelist():
    db = FakeDatabase()

    with pytest.raises(ValueError):
        run(jobs.update_job(db, uuid4(), status="ready", user_id=uuid4()))
    with pytest.raises(ValueError):
        run(jobs.update_job(db, uuid4(), options_hash="nope"))

    assert db.calls == []


def test_update_job_sets_whitelisted_fields_and_updated_at():
    row = job_row(status="queued")
    updated = {**row, "status": "downloading", "progress": 12.5}
    db = FakeDatabase()
    db.queue_fetchrow(updated)

    result = run(
        jobs.update_job(db, row["id"], status="downloading", progress=12.5)
    )

    assert result == updated
    method, query, args = db.calls[0]
    assert "updated_at = now()" in query
    assert "status = $2" in query
    assert "progress = $3" in query
    assert args == (row["id"], "downloading", 12.5)


def test_mark_ready_sets_terminal_fields():
    row = job_row(status="processing")
    ready = {**row, "status": "ready", "progress": 100}
    db = FakeDatabase()
    db.queue_fetchrow(ready)

    run(jobs.mark_ready(db, row["id"], asset_id=uuid4()))

    query, args = db.calls[0][1], db.calls[0][2]
    assert "status = $2" in query
    assert args[1] == "ready"
    assert args[2] == 100
    assert args[3] == 100
    assert args[4] == ""
    assert "asset_id" in query


def test_mark_failed_bounds_and_stores_message():
    row = job_row(status="downloading")
    failed = {**row, "status": "failed"}
    db = FakeDatabase()
    db.queue_fetchrow(failed)

    run(jobs.mark_failed(db, row["id"], "boom " + "x" * 800))

    query, args = db.calls[0][1], db.calls[0][2]
    assert "status = $2" in query
    assert args[1] == "failed"
    assert len(args[2]) == 500


def test_mark_cancelled_sets_cancel_flag():
    row = job_row(status="downloading")
    cancelled = {**row, "status": "cancelled", "cancel_requested": True}
    db = FakeDatabase()
    db.queue_fetchrow(cancelled)

    run(jobs.mark_cancelled(db, row["id"]))

    query, args = db.calls[0][1], db.calls[0][2]
    assert args[1] == "cancelled"
    assert "cancel_requested = $3" in query


def test_request_cancel_marks_queued_jobs_cancelled_in_sql():
    row = job_row(status="queued")
    db = FakeDatabase()
    db.queue_fetchrow({**row, "status": "cancelled", "cancel_requested": True})

    result = run(jobs.request_cancel(db, row["id"]))

    assert result["status"] == "cancelled"
    query = db.calls[0][1]
    assert "cancel_requested = true" in query
    assert "case when status = 'queued' then 'cancelled'" in query


def test_recover_stale_jobs_requeues_and_counts():
    db = FakeDatabase()
    db.queue_fetchrow({"total": 2})

    recovered = run(jobs.recover_stale_jobs(db, 300))

    assert recovered == 2
    query, args = db.calls[0][1], db.calls[0][2]
    assert "status in ('resolving', 'downloading', 'processing')" in query
    assert "attempts = attempts + 1" in query
    assert "status = 'queued'" in query
    assert args == (300,)


def _record_item(db, **overrides):
    kwargs = {
        "user_id": uuid4(),
        "playlist_id": uuid4(),
        "source_url": "https://example.test/v1",
        "title": "Clip 1",
        "options_hash": "a" * 64,
        "format_selector": "best",
        "status": "ready",
        "asset_id": uuid4(),
        "artist": "The channel",
        "album": "The playlist",
        "item_index": 1,
        "item_count": 3,
    }
    kwargs.update(overrides)
    return jobs.record_playlist_item_job(db, **kwargs)


def test_record_playlist_item_job_inserts_a_terminal_ready_row():
    owner = uuid4()
    playlist_id = uuid4()
    asset_id = uuid4()
    inserted = job_row(
        user_id=owner,
        kind="playlist_item",
        status="ready",
        playlist_id=playlist_id,
        asset_id=asset_id,
        artist="The channel",
        album="The playlist",
        item_index=1,
        item_count=3,
    )
    db = FakeDatabase()
    db.queue_fetchrow(inserted)

    result = run(
        _record_item(
            db,
            user_id=owner,
            playlist_id=playlist_id,
            asset_id=asset_id,
        )
    )

    assert result == inserted
    assert len(db.calls) == 1
    method, query, args = db.calls[0]
    assert 'insert into "public".download_jobs' in query
    assert "'playlist_item'" in query
    # The row is terminal on insert, so the dispatcher can never claim it.
    assert args[6] == "ready"
    assert args[7] == 100
    assert args[8] == asset_id
    assert args[10] == "The channel"
    assert args[11] == "The playlist"
    assert args[12] == 1
    assert args[13] == 3


def test_record_playlist_item_job_updates_the_linked_job_instead_of_inserting():
    playlist_id = uuid4()
    existing = job_row(
        kind="playlist_item",
        status="ready",
        playlist_id=playlist_id,
        artist="Old channel",
    )
    failed = {
        **existing,
        "status": "failed",
        "asset_id": None,
        "error": "Network error.",
        "artist": "New channel",
    }
    db = FakeDatabase()
    db.queue_fetchrow(failed)

    result = run(
        _record_item(
            db,
            user_id=existing["user_id"],
            playlist_id=existing["playlist_id"],
            job_id=existing["id"],
            status="failed",
            error="Network error.",
            artist="New channel",
        )
    )

    assert result == failed
    assert len(db.calls) == 1
    method, query, args = db.calls[0]
    assert method == "fetchrow"
    assert "update " in query
    assert "kind = 'playlist_item'" in query
    assert "and kind = 'playlist_item' returning" in query
    assert args[0] == existing["id"]
    assert args[6] == "failed"
    assert args[7] == 0
    assert args[8] is None


def test_record_playlist_item_job_rejects_queued_status_and_missing_hash():
    db = FakeDatabase()
    with pytest.raises(ValueError):
        run(_record_item(db, status="queued"))
    with pytest.raises(ValueError):
        run(_record_item(db, options_hash=""))
    assert db.calls == []
