"""Real-PostgreSQL tests for cascades and the unique indexes services depend on.

Deleting a user must never delete shared media, and the dedupe/idempotency
guarantees must come from the database, not from application checks.
"""
from __future__ import annotations

import psycopg
import pytest

from backend.app.services import jobs, playlists
from backend.tests.integration.conftest import (
    cleanup_test_data,
    create_profile,
    create_ready_job,
    make_ready_asset,
)

pytestmark = pytest.mark.integration


async def _scalar(db, query: str, *args) -> int:
    row = await db.fetchrow(query, *args)
    return int(row["n"])


def test_deleting_a_profile_cascades_owned_rows_but_keeps_shared_media(
    db_run, media_storage
):
    async def scenario(db):
        owner = await create_profile(db)
        other = await create_profile(db)
        canonical = "youtube:cascade-shared"
        try:
            asset = await make_ready_asset(
                db, media_storage, canonical_id=canonical
            )
            job = await create_ready_job(
                db, user_id=owner["id"], asset_id=asset["id"], title="Mine"
            )
            other_job = await create_ready_job(
                db, user_id=other["id"], asset_id=asset["id"], title="Theirs"
            )
            source = await playlists.upsert_playlist(
                db,
                user_id=owner["id"],
                canonical_id="youtube:PLCASCADE",
                source_url="",
                title="Source",
                channel="",
                item_count=1,
                options_hash="c" * 64,
                format_selector="best",
            )
            await playlists.replace_items(
                db, source["id"], [{"canonical_id": canonical, "title": "A"}]
            )
            await playlists.update_item(
                db, source["id"], 1, status="ready", asset_id=asset["id"]
            )
            curated = await db.fetchrow(
                f"insert into {db.schema_sql}.user_playlists "
                "(user_id, name) values ($1, 'Curated') returning id",
                owner["id"],
            )
            track = await db.fetchrow(
                f"select id from {db.schema_sql}.user_tracks where user_id = $1",
                owner["id"],
            )
            await db.execute(
                f"insert into {db.schema_sql}.user_playlist_tracks "
                "(playlist_id, user_track_id, position) values ($1, $2, 0)",
                curated["id"],
                track["id"],
            )
            await db.execute(
                f"insert into {db.schema_sql}.auth_sessions "
                "(user_id, token_hash, expires_at) "
                "values ($1, $2, now() + interval '1 day')",
                owner["id"],
                "cascade-token-hash",
            )

            await db.execute(
                f"delete from {db.schema_sql}.profiles where id = $1",
                owner["id"],
            )

            schema = db.schema_sql
            for table, column in (
                ("download_jobs", "user_id"),
                ("playlists", "user_id"),
                ("user_tracks", "user_id"),
                ("user_playlists", "user_id"),
                ("auth_sessions", "user_id"),
            ):
                assert await _scalar(
                    db,
                    f"select count(*) as n from {schema}.{table} where {column} = $1",
                    owner["id"],
                ) == 0, table
            assert await _scalar(
                db,
                f"select count(*) as n from {schema}.playlist_items "
                "where playlist_id = $1",
                source["id"],
            ) == 0
            assert await _scalar(
                db,
                f"select count(*) as n from {schema}.user_playlist_tracks "
                "where playlist_id = $1",
                curated["id"],
            ) == 0

            # Shared media and the other user's history are untouched.
            kept = await db.fetchrow(
                f"select status, file_path from {schema}.media_assets where id = $1",
                asset["id"],
            )
            assert kept["status"] == "ready"
            assert media_storage.validate_relative_path(kept["file_path"]).is_file()
            other_row = await jobs.get_job(db, other_job["id"])
            assert other_row["asset_id"] == asset["id"]
            assert other_row["status"] == "ready"
        finally:
            await cleanup_test_data(
                db, profiles=[other], canonical_ids=[canonical]
            )

    db_run(scenario)


def test_asset_delete_clears_playlist_item_links(db_run, media_storage):
    async def scenario(db):
        owner = await create_profile(db)
        canonical = "youtube:cascade-item"
        try:
            asset = await make_ready_asset(
                db, media_storage, canonical_id=canonical
            )
            playlist = await playlists.upsert_playlist(
                db,
                user_id=owner["id"],
                canonical_id="youtube:PLITEM",
                source_url="",
                title="Items",
                channel="",
                item_count=1,
                options_hash="i" * 64,
                format_selector="best",
            )
            await playlists.replace_items(
                db, playlist["id"], [{"canonical_id": canonical, "title": "A"}]
            )
            await playlists.update_item(
                db, playlist["id"], 1, status="ready", asset_id=asset["id"]
            )

            await db.execute(
                f"delete from {db.schema_sql}.media_assets where id = $1",
                asset["id"],
            )
            items = await playlists.list_items(db, playlist["id"])
            assert len(items) == 1
            assert items[0]["asset_id"] is None
            assert items[0]["status"] == "ready"
        finally:
            await cleanup_test_data(
                db, profiles=[owner], canonical_ids=[canonical]
            )

    db_run(scenario)


def test_profile_email_is_unique_case_insensitively(db_run):
    async def scenario(db):
        email = "Unique.Case@Example.test"
        profile = await create_profile(db, email=email)
        try:
            with pytest.raises(psycopg.errors.UniqueViolation):
                await db.execute(
                    f"insert into {db.schema_sql}.profiles "
                    "(email, password_hash) values ($1, $2)",
                    email.upper(),
                    "other-hash",
                )
        finally:
            await cleanup_test_data(db, profiles=[profile])

    db_run(scenario)


def test_job_idempotency_index_allows_many_nulls(db_run):
    async def scenario(db):
        owner = await create_profile(db)
        try:
            for _ in range(2):
                await jobs.create_job(
                    db,
                    user_id=owner["id"],
                    source_url="https://example.test/x",
                    options_hash="n" * 64,
                )
            count = await _scalar(
                db,
                f"select count(*) as n from {db.schema_sql}.download_jobs "
                "where user_id = $1 and idempotency_key is null",
                owner["id"],
            )
            assert count == 2

            await jobs.create_job(
                db,
                user_id=owner["id"],
                source_url="https://example.test/x",
                options_hash="n" * 64,
                idempotency_key="dup",
            )
            with pytest.raises(psycopg.errors.UniqueViolation):
                await db.execute(
                    f"insert into {db.schema_sql}.download_jobs "
                    "(user_id, source_url, options_hash, idempotency_key) "
                    "values ($1, '', $2, 'dup')",
                    owner["id"],
                    "n" * 64,
                )
        finally:
            await cleanup_test_data(db, profiles=[owner])

    db_run(scenario)


def test_asset_dedupe_key_is_unique_per_output_intent(db_run, media_storage):
    async def scenario(db):
        canonical = "youtube:unique-asset"
        try:
            await make_ready_asset(
                db,
                media_storage,
                canonical_id=canonical,
                options_hash="o" * 64,
            )
            with pytest.raises(psycopg.errors.UniqueViolation):
                await db.execute(
                    f"insert into {db.schema_sql}.media_assets "
                    "(canonical_id, options_hash) values ($1, $2)",
                    canonical,
                    "o" * 64,
                )
        finally:
            await cleanup_test_data(db, canonical_ids=[canonical])

    db_run(scenario)


def test_playlists_are_unique_per_owner_source_and_intent(db_run):
    async def scenario(db):
        owner = await create_profile(db)
        other = await create_profile(db)
        try:
            playlist = await playlists.upsert_playlist(
                db,
                user_id=owner["id"],
                canonical_id="youtube:PLUNIQUE",
                source_url="",
                title="",
                channel="",
                item_count=0,
                options_hash="u" * 64,
                format_selector="best",
            )
            with pytest.raises(psycopg.errors.UniqueViolation):
                await db.execute(
                    f"insert into {db.schema_sql}.playlists "
                    "(user_id, canonical_id, options_hash) values ($1, $2, $3)",
                    owner["id"],
                    "youtube:PLUNIQUE",
                    "u" * 64,
                )
            # Another owner may register the same source.
            foreign = await playlists.upsert_playlist(
                db,
                user_id=other["id"],
                canonical_id="youtube:PLUNIQUE",
                source_url="",
                title="",
                channel="",
                item_count=0,
                options_hash="u" * 64,
                format_selector="best",
            )
            assert foreign["id"] != playlist["id"]
        finally:
            await cleanup_test_data(db, profiles=[owner, other])

    db_run(scenario)


def test_playlist_item_uniqueness_rules(db_run):
    async def scenario(db):
        owner = await create_profile(db)
        try:
            playlist = await playlists.upsert_playlist(
                db,
                user_id=owner["id"],
                canonical_id="youtube:PLITEMUNIQUE",
                source_url="",
                title="",
                channel="",
                item_count=0,
                options_hash="m" * 64,
                format_selector="best",
            )
            await playlists.replace_items(
                db,
                playlist["id"],
                [
                    {"canonical_id": "youtube:one", "title": "One"},
                    {"canonical_id": "", "title": "Anonymous A"},
                    {"canonical_id": "", "title": "Anonymous B"},
                ],
            )
            schema = db.schema_sql

            # A non-empty canonical id is unique within a playlist.
            with pytest.raises(psycopg.errors.UniqueViolation):
                await db.execute(
                    f"insert into {schema}.playlist_items "
                    "(playlist_id, position, canonical_id) values ($1, 9, $2)",
                    playlist["id"],
                    "youtube:one",
                )
            # Positions are unique within a playlist.
            with pytest.raises(psycopg.errors.UniqueViolation):
                await db.execute(
                    f"insert into {schema}.playlist_items "
                    "(playlist_id, position, canonical_id) values ($1, 1, '')",
                    playlist["id"],
                )
            # Empty canonical ids are exempt from the canonical index.
            anonymous = await _scalar(
                db,
                f"select count(*) as n from {schema}.playlist_items "
                "where playlist_id = $1 and canonical_id = ''",
                playlist["id"],
            )
            assert anonymous == 2
        finally:
            await cleanup_test_data(db, profiles=[owner])

    db_run(scenario)


def test_track_registry_is_unique_per_user_and_asset(db_run, media_storage):
    async def scenario(db):
        owner = await create_profile(db)
        canonical = "youtube:track-unique"
        try:
            asset = await make_ready_asset(
                db, media_storage, canonical_id=canonical
            )
            await create_ready_job(
                db, user_id=owner["id"], asset_id=asset["id"], title="One"
            )
            # A second ready job for the same asset does not duplicate the
            # per-user track row (the trigger inserts ... do nothing).
            await create_ready_job(
                db, user_id=owner["id"], asset_id=asset["id"], title="Two"
            )
            count = await _scalar(
                db,
                f"select count(*) as n from {db.schema_sql}.user_tracks "
                "where user_id = $1",
                owner["id"],
            )
            assert count == 1
            with pytest.raises(psycopg.errors.UniqueViolation):
                await db.execute(
                    f"insert into {db.schema_sql}.user_tracks "
                    "(user_id, asset_id) values ($1, $2)",
                    owner["id"],
                    asset["id"],
                )
        finally:
            await cleanup_test_data(
                db, profiles=[owner], canonical_ids=[canonical]
            )

    db_run(scenario)
