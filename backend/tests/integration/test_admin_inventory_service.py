"""Real-PostgreSQL tests for the admin inventory and guarded asset deletion."""
from __future__ import annotations

import pytest

from backend.app.services import admin_inventory, jobs
from backend.app.services.profiles import ConflictError
from backend.tests.integration.conftest import (
    cleanup_test_data,
    create_profile,
    create_ready_job,
    make_ready_asset,
)

pytestmark = pytest.mark.integration


def test_admin_job_inventory_filters_searches_and_paginates(db_run):
    async def scenario(db):
        alice = await create_profile(db, email="alice-admin-test@example.test")
        bob = await create_profile(db, email="bob-admin-test@example.test")
        try:
            first = await jobs.create_job(
                db,
                user_id=alice["id"],
                source_url="https://example.test/a",
                title="Alice queued",
                options_hash="a" * 64,
            )
            second = await jobs.create_job(
                db,
                user_id=bob["id"],
                source_url="https://example.test/b",
                title="Bob ready",
                options_hash="b" * 64,
            )
            await jobs.mark_ready(db, second["id"])

            rows, total = await admin_inventory.list_jobs(db)
            assert total == 2
            assert {row["id"] for row in rows} == {first["id"], second["id"]}
            by_id = {row["id"]: row for row in rows}
            assert by_id[first["id"]]["user_email"] == alice["email"]
            assert by_id[second["id"]]["user_email"] == bob["email"]

            filtered, filtered_total = await admin_inventory.list_jobs(
                db, status="ready"
            )
            assert filtered_total == 1
            assert filtered[0]["id"] == second["id"]

            owner_filtered, owner_total = await admin_inventory.list_jobs(
                db, user_id=alice["id"]
            )
            assert owner_total == 1
            assert owner_filtered[0]["id"] == first["id"]

            email_hits, email_total = await admin_inventory.list_jobs(
                db, search="alice-admin-test"
            )
            assert email_total == 1
            assert email_hits[0]["id"] == first["id"]

            title_hits, title_total = await admin_inventory.list_jobs(
                db, search="bob READY"
            )
            assert title_total == 1
            assert title_hits[0]["id"] == second["id"]

            page, page_total = await admin_inventory.list_jobs(db, limit=1, offset=1)
            assert page_total == 2
            assert len(page) == 1

            with pytest.raises(ValueError):
                await admin_inventory.list_jobs(db, status="bogus")
        finally:
            await cleanup_test_data(db, profiles=[alice, bob])

    db_run(scenario)


def test_admin_asset_inventory_counts_jobs_and_users(db_run, media_storage):
    async def scenario(db):
        alice = await create_profile(db)
        bob = await create_profile(db)
        canonical = "youtube:admin-counts"
        try:
            asset = await make_ready_asset(
                db, media_storage, canonical_id=canonical, title="Alpha Clip"
            )
            await create_ready_job(
                db, user_id=alice["id"], asset_id=asset["id"], title="One"
            )
            await create_ready_job(
                db, user_id=bob["id"], asset_id=asset["id"], title="Two"
            )
            await jobs.create_job(
                db,
                user_id=bob["id"],
                source_url="https://example.test/queued",
                title="Queued over asset",
                options_hash="q" * 64,
            )
            # A second queued job pointing at the asset via a direct update.
            queued = await jobs.create_job(
                db,
                user_id=alice["id"],
                source_url="https://example.test/queued2",
                options_hash="r" * 64,
            )
            await jobs.update_job(db, queued["id"], asset_id=asset["id"])

            rows, total = await admin_inventory.list_assets(db, search="alpha")
            assert total == 1
            row = rows[0]
            assert row["id"] == asset["id"]
            assert row["job_count"] == 3
            assert row["user_count"] == 2
            assert row["thumbnail_path"] is None
            assert row["canonical_id"] == canonical

            status_rows, status_total = await admin_inventory.list_assets(
                db, status="ready"
            )
            assert status_total == 1
            assert status_rows[0]["id"] == asset["id"]

            none_rows, none_total = await admin_inventory.list_assets(
                db, status="failed"
            )
            assert none_total == 0
            assert none_rows == []

            with pytest.raises(ValueError):
                await admin_inventory.list_assets(db, status="bogus")
        finally:
            await cleanup_test_data(
                db, profiles=[alice, bob], canonical_ids=[canonical]
            )

    db_run(scenario)


def test_delete_asset_refuses_active_references(db_run, media_storage):
    async def scenario(db):
        actor = await create_profile(db, app_role="admin")
        owner = await create_profile(db)
        canonical = "youtube:admin-active"
        try:
            asset = await make_ready_asset(
                db, media_storage, canonical_id=canonical
            )
            job = await create_ready_job(
                db, user_id=owner["id"], asset_id=asset["id"], title="Busy"
            )
            await jobs.update_job(db, job["id"], status="downloading")

            with pytest.raises(ConflictError) as raised:
                await admin_inventory.delete_asset(
                    db, media_storage, asset["id"], actor["id"]
                )
            assert raised.value.code == "asset_in_use"

            assert (await _count(db, "media_assets", asset["id"])) == 1
            audit = await db.fetchrow(
                f"select count(*) as n from {db.schema_sql}.admin_audit_log "
                "where action = 'delete_asset'"
            )
            assert audit["n"] == 0
            # The file was never touched.
            assert media_storage.validate_relative_path(
                asset["file_path"]
            ).is_file()
        finally:
            await cleanup_test_data(
                db, profiles=[actor, owner], canonical_ids=[canonical]
            )

    db_run(scenario)


async def _count(db, table: str, identifier) -> int:
    row = await db.fetchrow(
        f"select count(*) as n from {db.schema_sql}.{table} where id = $1",
        identifier,
    )
    return int(row["n"])


def test_delete_asset_removes_files_audits_and_clears_references(
    db_run, media_storage
):
    async def scenario(db):
        actor = await create_profile(db, app_role="admin")
        owner = await create_profile(db)
        canonical = "youtube:admin-delete"
        try:
            asset = await make_ready_asset(
                db, media_storage, canonical_id=canonical, thumbnail=True
            )
            job = await create_ready_job(
                db, user_id=owner["id"], asset_id=asset["id"], title="Done"
            )
            track = await db.fetchrow(
                f"select id from {db.schema_sql}.user_tracks where user_id = $1",
                owner["id"],
            )
            media_file = media_storage.validate_relative_path(asset["file_path"])
            thumbnail = media_storage.validate_relative_path(
                asset["thumbnail_path"]
            )
            assert media_file.is_file() and thumbnail.is_file()

            deleted = await admin_inventory.delete_asset(
                db, media_storage, asset["id"], actor["id"]
            )
            assert deleted["id"] == asset["id"]
            assert (await _count(db, "media_assets", asset["id"])) == 0
            assert not media_file.exists()
            assert not thumbnail.exists()

            # Historical references are cleared by the set-null foreign keys;
            # the per-user track (cascade) is gone.
            refreshed_job = await jobs.get_job(db, job["id"])
            assert refreshed_job["asset_id"] is None
            assert refreshed_job["status"] == "ready"
            assert await _count(db, "user_tracks", track["id"]) == 0

            audit = await db.fetchrow(
                f"select actor_id, action, metadata "
                f"from {db.schema_sql}.admin_audit_log "
                "where action = 'delete_asset'"
            )
            assert audit["actor_id"] == actor["id"]
            assert audit["metadata"]["asset_id"] == str(asset["id"])
            assert audit["metadata"]["canonical_id"] == canonical

            # Deleting an unknown asset is not an error.
            assert (
                await admin_inventory.delete_asset(
                    db, media_storage, asset["id"], actor["id"]
                )
                is None
            )
        finally:
            await cleanup_test_data(
                db, profiles=[actor, owner], canonical_ids=[canonical]
            )

    db_run(scenario)
