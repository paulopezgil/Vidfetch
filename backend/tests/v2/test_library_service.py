"""Service tests for library visibility and history delegation."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from backend.app.services import library
from backend.tests.v2.fakes import FakeDatabase, job_row, library_row


def run(coro):
    return asyncio.run(coro)


def test_list_library_scopes_filters_hidden_and_clamps_pagination():
    owner = uuid4()
    rows = [library_row(), library_row()]
    db = FakeDatabase()
    db.queue_fetchrow({"total": 2})
    db.queue_fetch(rows)

    page, total = run(
        library.list_library(db, owner, limit=10_000, offset=-5)
    )

    assert page == rows
    assert total == 2

    count_query, count_args = db.calls[0][1], db.calls[0][2]
    assert 'from "public".download_jobs j' in count_query
    assert 'join "public".media_assets a on j.asset_id = a.id' in count_query
    assert "j.user_id = $1" in count_query
    assert "j.status = 'ready'" in count_query
    assert "j.library_hidden = false" in count_query
    assert "a.status = 'ready'" in count_query
    assert count_args == (owner,)

    page_query, page_args = db.calls[1][1], db.calls[1][2]
    assert "j.library_hidden = false" in page_query
    assert "order by j.created_at desc, j.id desc" in page_query
    assert "limit $2 offset $3" in page_query
    assert page_args == (owner, library.MAX_PAGE_SIZE, 0)


def test_hide_library_item_updates_only_the_callers_ready_job():
    owner = uuid4()
    job_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow({"id": job_id})

    hidden = run(library.hide_library_item(db, owner, job_id))

    assert hidden is True
    query, args = db.calls[0][1], db.calls[0][2]
    assert 'update "public".download_jobs' in query
    assert "set library_hidden = true" in query
    assert "where id = $1 and user_id = $2 and status = 'ready'" in query
    assert "delete from" not in query.lower()
    assert args == (job_id, owner)


def test_hide_library_item_returns_false_when_the_row_does_not_match():
    db = FakeDatabase()
    db.queue_fetchrow(None)

    hidden = run(library.hide_library_item(db, uuid4(), uuid4()))

    assert hidden is False
    assert len(db.calls) == 1


def test_hide_library_item_rejects_invalid_identifiers_without_querying():
    db = FakeDatabase()

    with pytest.raises(ValueError):
        run(library.hide_library_item(db, uuid4(), "not-a-uuid"))
    with pytest.raises(ValueError):
        run(library.hide_library_item(db, "not-a-uuid", uuid4()))

    assert db.calls == []


def test_list_history_delegates_and_keeps_hidden_rows():
    owner = uuid4()
    row = job_row(user_id=owner, status="ready", library_hidden=True)
    db = FakeDatabase()
    db.queue_fetchrow({"total": 1})
    db.queue_fetch([row])

    page, total = run(
        library.list_history(db, owner, status="ready", limit=25, offset=5)
    )

    assert page == [row]
    assert total == 1
    query, args = db.calls[1][1], db.calls[1][2]
    assert 'from "public".download_jobs' in query
    assert "library_hidden" not in query
    assert "user_id = $1" in query
    assert "status = $2" in query
    assert args == (owner, "ready", 25, 5)


def test_list_history_rejects_unknown_status_without_querying():
    db = FakeDatabase()

    with pytest.raises(ValueError):
        run(library.list_history(db, uuid4(), status="exploded"))

    assert db.calls == []
