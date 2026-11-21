"""Direct tests for the profile service query construction."""
from __future__ import annotations

import asyncio

import pytest

from backend.app.services.profiles import (
    MAX_PAGE_SIZE,
    count_admins,
    get_profile,
    list_profiles,
)
from backend.tests.v2.fakes import FakeDatabase, profile_row


def run(coro):
    return asyncio.run(coro)


def test_get_profile_returns_row_and_none():
    row = profile_row(email="one@example.test")
    db = FakeDatabase()
    db.queue_fetchrow(row, None)

    found = run(get_profile(db, row["id"]))
    missing = run(get_profile(db, row["id"]))

    assert found == row
    assert missing is None


def test_get_profile_rejects_malformed_uuid():
    db = FakeDatabase()

    with pytest.raises(ValueError):
        run(get_profile(db, "not-a-uuid"))


def test_list_profiles_uses_parameterized_filters_and_whitelisted_sort():
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    rows, total = run(
        list_profiles(
            db,
            search="  Alice ",
            approved=True,
            role="admin",
            limit=10_000,
            offset=-4,
            sort="created_at; drop table public.profiles",
            order="sideways",
        )
    )

    assert rows == []
    assert total == 0

    page_query, page_args = [
        call for call in db.calls if call[0] == "fetch"
    ][0][1:]
    assert "lower(email) like '%' || $1 || '%'" in page_query
    assert "is_approved = $2" in page_query
    assert "app_role = $3" in page_query
    assert "order by created_at desc" in page_query
    assert "drop table" not in page_query.lower()
    assert page_args == ("alice", True, "admin", MAX_PAGE_SIZE, 0)


def test_list_profiles_allows_whitelisted_email_sort():
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    run(list_profiles(db, limit=5, offset=0, sort="email", order="ASC"))

    page_query = [call for call in db.calls if call[0] == "fetch"][0][1]
    assert "order by lower(email) asc" in page_query
    assert "limit $1 offset $2" in page_query


def test_count_admins_reads_total():
    db = FakeDatabase()
    db.queue_fetchrow({"total": 3})

    assert run(count_admins(db)) == 3
