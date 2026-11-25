"""Real-PostgreSQL tests for the durable job queue.

Covers idempotent creation under concurrency, pagination/filtering, atomic
worker claims, stale-lease recovery, and cancellation transitions.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.core.db import create_pool
from backend.app.services import jobs
from backend.tests.integration.conftest import (
    cleanup_test_data,
    create_profile,
)

pytestmark = pytest.mark.integration


def test_concurrent_idempotent_creates_share_one_row(db_run, integration_settings):
    async def scenario(db):
        profile = await create_profile(db)
        second = await create_pool(integration_settings, min_size=1, max_size=2)
        try:
            async def create(connection):
                return await jobs.create_job(
                    connection,
                    user_id=profile["id"],
                    source_url="https://example.test/video",
                    title="Idempotent",
                    options_hash="a" * 64,
                    idempotency_key="save-click-1",
                )

            first, other = await asyncio.gather(create(db), create(second))
            assert first["id"] == other["id"]

            rows = await db.fetch(
                f"select id from {db.schema_sql}.download_jobs where user_id = $1",
                profile["id"],
            )
            assert [row["id"] for row in rows] == [first["id"]]

            # The unique index is per user: another owner may reuse the key.
            other_user = await create_profile(db)
            try:
                distinct = await jobs.create_job(
                    db,
                    user_id=other_user["id"],
                    source_url="https://example.test/video",
                    options_hash="b" * 64,
                    idempotency_key="save-click-1",
                )
                assert distinct["id"] != first["id"]
            finally:
                await cleanup_test_data(db, profiles=[other_user])
        finally:
            await second.close()
            await cleanup_test_data(db, profiles=[profile])

    db_run(scenario)


def test_list_jobs_filters_status_and_paginates_newest_first(db_run):
    async def scenario(db):
        owner = await create_profile(db)
        other = await create_profile(db)
        created: list[dict] = []
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        try:
            for index, status in enumerate(
                ["queued", "ready", "failed", "ready", "queued"]
            ):
                job = await jobs.create_job(
                    db,
                    user_id=owner["id"],
                    source_url=f"https://example.test/{index}",
                    title=f"Job {index}",
                    options_hash=f"{index:064d}",
                )
                # created_at is not writable through the service; set it
                # directly so ordering is deterministic.
                await db.execute(
                    f"update {db.schema_sql}.download_jobs "
                    "set status = $2, created_at = $3 where id = $1",
                    job["id"],
                    status,
                    base + timedelta(minutes=index),
                )
                created.append({**job, "status": status})

            everything, total = await jobs.list_jobs(db, owner["id"], limit=10)
            assert total == 5
            assert [row["id"] for row in everything] == [
                row["id"] for row in reversed(created)
            ]

            ready, ready_total = await jobs.list_jobs(
                db, owner["id"], status="ready", limit=1, offset=0
            )
            assert ready_total == 2
            assert len(ready) == 1
            assert ready[0]["status"] == "ready"
            assert ready[0]["id"] == created[3]["id"]  # newest ready

            page_two, _ = await jobs.list_jobs(
                db, owner["id"], status="ready", limit=1, offset=1
            )
            assert [row["id"] for row in page_two] == [created[1]["id"]]

            # An unowned job never leaks into another user's history.
            assert (await jobs.list_jobs(db, other["id"]))[1] == 0

            # Limits clamp to the documented range.
            clamped, _ = await jobs.list_jobs(db, owner["id"], limit=10_000)
            assert len(clamped) == 5

            with pytest.raises(ValueError):
                await jobs.list_jobs(db, owner["id"], status="bogus")
        finally:
            await cleanup_test_data(db, profiles=[owner, other])

    db_run(scenario)


def test_claim_next_job_is_atomic_between_two_workers(db_run, integration_settings):
    async def scenario(db):
        owner = await create_profile(db)
        second = await create_pool(integration_settings, min_size=1, max_size=2)
        try:
            ids = set()
            for index in range(2):
                job = await jobs.create_job(
                    db,
                    user_id=owner["id"],
                    source_url=f"https://example.test/{index}",
                    options_hash=f"{index:064d}",
                )
                ids.add(job["id"])

            first, other = await asyncio.gather(
                jobs.claim_next_job(db), jobs.claim_next_job(second)
            )
            claimed = {row["id"] for row in (first, other) if row is not None}
            assert claimed == ids
            for row in (first, other):
                assert row["status"] == "resolving"
                assert row["started_at"] is not None

            assert await jobs.claim_next_job(db) is None
        finally:
            await second.close()
            await cleanup_test_data(db, profiles=[owner])

    db_run(scenario)


def test_recover_stale_jobs_requeues_only_expired_work(db_run):
    async def scenario(db):
        owner = await create_profile(db)
        try:
            # ``updated_at`` is maintained by a BEFORE UPDATE trigger, so a
            # stale row is seeded directly at insert time (the trigger only
            # touches UPDATEs). This represents a worker that died an hour ago.
            stale = await db.fetchrow(
                f"insert into {db.schema_sql}.download_jobs "
                "(user_id, source_url, options_hash, status, attempts, "
                "created_at, updated_at) "
                "values ($1, $2, $3, 'downloading', 2, "
                "now() - interval '1 hour', now() - interval '1 hour') "
                "returning id",
                owner["id"],
                "https://example.test/stale",
                "s" * 64,
            )
            fresh = await jobs.create_job(
                db,
                user_id=owner["id"],
                source_url="https://example.test/fresh",
                options_hash="f" * 64,
            )
            await jobs.update_job(db, fresh["id"], status="downloading")

            recovered = await jobs.recover_stale_jobs(db, lease_seconds=60)
            assert recovered == 1

            stale_row = await jobs.get_job(db, stale["id"], owner["id"])
            assert stale_row["status"] == "queued"
            assert stale_row["attempts"] == 3
            assert stale_row["started_at"] is None
            assert stale_row["error"] == ""

            fresh_row = await jobs.get_job(db, fresh["id"], owner["id"])
            assert fresh_row["status"] == "downloading"
            assert fresh_row["attempts"] == 0
        finally:
            await cleanup_test_data(db, profiles=[owner])

    db_run(scenario)


def test_request_cancel_differs_for_queued_and_running_jobs(db_run):
    async def scenario(db):
        owner = await create_profile(db)
        try:
            queued = await jobs.create_job(
                db,
                user_id=owner["id"],
                source_url="https://example.test/queued",
                options_hash="q" * 64,
            )
            running = await jobs.create_job(
                db,
                user_id=owner["id"],
                source_url="https://example.test/running",
                options_hash="r" * 64,
            )
            await jobs.update_job(db, running["id"], status="downloading")

            cancelled = await jobs.request_cancel(db, queued["id"])
            assert cancelled["status"] == "cancelled"
            assert cancelled["cancel_requested"] is True
            assert cancelled["completed_at"] is not None

            flagged = await jobs.request_cancel(db, running["id"])
            assert flagged["status"] == "downloading"
            assert flagged["cancel_requested"] is True
            assert flagged["completed_at"] is None

            # Finishing the running job records the cancellation.
            finished = await jobs.mark_cancelled(db, running["id"])
            assert finished["status"] == "cancelled"
            assert finished["cancel_requested"] is True
        finally:
            await cleanup_test_data(db, profiles=[owner])

    db_run(scenario)


def test_mark_failed_bounds_the_stored_message(db_run):
    async def scenario(db):
        owner = await create_profile(db)
        try:
            job = await jobs.create_job(
                db,
                user_id=owner["id"],
                source_url="https://example.test/x",
                options_hash="e" * 64,
            )
            failed = await jobs.mark_failed(db, job["id"], "boom " * 400)
            assert failed["status"] == "failed"
            assert len(failed["error"]) == 500
            assert failed["completed_at"] is not None
        finally:
            await cleanup_test_data(db, profiles=[owner])

    db_run(scenario)
