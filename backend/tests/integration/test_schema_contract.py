"""The migrated schema must satisfy the contract the service layer relies on.

Two failure modes have already reached integration in this project: a pool API
that only existed under asyncpg, and a service selecting a column the migrated
schema did not have. These tests pin the second one down from both directions:

* an explicit inventory of the columns, indexes, constraints, and triggers the
  services require (so a migration that drops or renames one fails here), and
* a projection check that runs each service's real column list against the live
  schema (so a service that starts selecting a column the schema lacks fails
  here instead of at request time).
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.services import (
    admin_inventory,
    assets,
    auth,
    jobs,
    library,
    playlists,
    profiles,
    tracks,
    user_playlists,
)

pytestmark = pytest.mark.integration

REQUIRED_COLUMNS: dict[str, set[str]] = {
    "profiles": {
        "id",
        "email",
        "password_hash",
        "is_approved",
        "app_role",
        "approved_at",
        "approved_by",
        "created_at",
        "updated_at",
    },
    "auth_sessions": {
        "id",
        "user_id",
        "token_hash",
        "user_agent",
        "created_at",
        "last_used_at",
        "expires_at",
    },
    "media_assets": {
        "id",
        "canonical_id",
        "extractor_key",
        "source_url",
        "title",
        "duration_seconds",
        "options_hash",
        "options_schema_version",
        "format_selector",
        "output_ext",
        "file_path",
        "thumbnail_path",
        "file_size_bytes",
        "file_sha256",
        "status",
        "error",
        "attempts",
        "claimed_at",
        "lease_until",
        "created_at",
        "updated_at",
        "last_accessed_at",
    },
    "download_jobs": {
        "id",
        "user_id",
        "asset_id",
        "playlist_id",
        "kind",
        "source_url",
        "title",
        "options_hash",
        "format_selector",
        "idempotency_key",
        "status",
        "progress",
        "downloaded_bytes",
        "total_bytes",
        "speed",
        "eta_seconds",
        "error",
        "attempts",
        "cancel_requested",
        "item_index",
        "item_count",
        "current_item_title",
        "current_item_progress",
        "library_hidden",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
    },
    "playlists": {
        "id",
        "user_id",
        "canonical_id",
        "source_url",
        "title",
        "channel",
        "thumbnail_path",
        "item_count",
        "options_hash",
        "format_selector",
        "status",
        "created_at",
        "updated_at",
    },
    "playlist_items": {
        "id",
        "playlist_id",
        "position",
        "canonical_id",
        "source_url",
        "title",
        "duration_seconds",
        "asset_id",
        "job_id",
        "status",
        "error",
        "created_at",
        "updated_at",
    },
    "user_tracks": {
        "id",
        "user_id",
        "asset_id",
        "custom_title",
        "custom_artist",
        "custom_album",
        "cover_path",
        "downloaded_at",
        "created_at",
        "updated_at",
        "deleted_at",
    },
    "user_playlists": {
        "id",
        "user_id",
        "name",
        "description",
        "cover_path",
        "created_at",
        "updated_at",
        "deleted_at",
    },
    "user_playlist_tracks": {
        "playlist_id",
        "user_track_id",
        "position",
        "added_at",
    },
    "admin_audit_log": {
        "id",
        "actor_id",
        "action",
        "target_user_id",
        "metadata",
        "created_at",
    },
}

# Indexes the migrations create by name. A rename or a dropped ``if not exists``
# clause changes this set, and the partial indexes encode real service rules.
REQUIRED_INDEXES = {
    "profiles_email_key",
    "profiles_is_approved_idx",
    "profiles_app_role_idx",
    "auth_sessions_token_key",
    "auth_sessions_user_idx",
    "auth_sessions_expires_idx",
    "media_assets_status_lease_idx",
    "media_assets_last_accessed_idx",
    "media_assets_canonical_idx",
    "playlists_user_created_idx",
    "download_jobs_user_idempotency_key_idx",
    "download_jobs_user_created_idx",
    "download_jobs_status_created_idx",
    "download_jobs_asset_idx",
    "download_jobs_user_library_idx",
    "playlist_items_playlist_canonical_idx",
    "playlist_items_playlist_idx",
    "user_tracks_user_downloaded_idx",
    "user_tracks_user_artist_idx",
    "user_tracks_user_album_idx",
    "user_playlists_user_updated_idx",
    "user_playlist_tracks_track_idx",
    "admin_audit_log_created_idx",
}

# ``contype`` -> ``confdeltype`` for each foreign key the service layer relies
# on. ``c`` cascade, ``n`` set null, ``a`` no action.
REQUIRED_FOREIGN_KEYS: dict[str, str] = {
    "auth_sessions_user_id_fkey": "c",
    "download_jobs_user_id_fkey": "c",
    "download_jobs_asset_id_fkey": "n",
    "download_jobs_playlist_id_fkey": "n",
    "playlists_user_id_fkey": "c",
    "playlist_items_playlist_id_fkey": "c",
    "playlist_items_asset_id_fkey": "n",
    "playlist_items_job_id_fkey": "n",
    "user_tracks_user_id_fkey": "c",
    "user_tracks_asset_id_fkey": "c",
    "user_playlists_user_id_fkey": "c",
    "user_playlist_tracks_playlist_id_fkey": "c",
    "user_playlist_tracks_user_track_id_fkey": "c",
    "profiles_approved_by_fkey": "n",
    "admin_audit_log_actor_id_fkey": "n",
    "admin_audit_log_target_user_id_fkey": "n",
}

REQUIRED_CHECKS = {
    "download_jobs_status_check",
    "download_jobs_kind_check",
    "download_jobs_progress_check",
    "download_jobs_current_item_progress_check",
    "media_assets_status_check",
    "media_assets_file_path_relative",
    "media_assets_thumbnail_path_relative",
    "playlists_status_check",
    "playlists_thumbnail_path_relative",
    "playlist_items_status_check",
    "user_tracks_cover_path_relative",
    "user_playlists_name_length",
    "user_playlists_cover_path_relative",
    "user_playlist_tracks_position_check",
}

REQUIRED_UNIQUE_CONSTRAINTS = {
    "media_assets_canonical_options_key",
    "playlists_user_canonical_options_key",
    "playlist_items_position_key",
    "user_tracks_user_asset_key",
    "user_playlist_tracks_pkey",
}

REQUIRED_TRIGGERS = {
    "profiles_set_updated_at",
    "media_assets_set_updated_at",
    "download_jobs_set_updated_at",
    "playlists_set_updated_at",
    "playlist_items_set_updated_at",
    "user_tracks_set_updated_at",
    "user_playlists_set_updated_at",
    "download_jobs_sync_user_track",
}


def test_migrated_schema_has_every_required_column(db_run):
    async def scenario(db):
        rows = await db.fetch(
            "select table_name, column_name from information_schema.columns "
            "where table_schema = $1",
            db.schema,
        )
        actual: dict[str, set[str]] = {}
        for row in rows:
            actual.setdefault(row["table_name"], set()).add(row["column_name"])

        problems: list[str] = []
        for table, required in REQUIRED_COLUMNS.items():
            missing_table = table not in actual
            if missing_table:
                problems.append(f"missing table {table!r}")
                continue
            missing = required - actual[table]
            if missing:
                problems.append(f"{table} missing columns: {sorted(missing)}")
        assert problems == [], "; ".join(problems)

        # The columns behind the last integration escape are called out
        # explicitly so a regression names the actual field.
        assert "thumbnail_path" in actual["media_assets"]
        assert {
            "progress",
            "current_item_progress",
            "cancel_requested",
            "library_hidden",
        } <= actual["download_jobs"]

    db_run(scenario)


def test_required_indexes_exist_with_the_service_rules(db_run):
    async def scenario(db):
        rows = await db.fetch(
            "select indexname, indexdef from pg_indexes where schemaname = $1",
            db.schema,
        )
        indexes = {
            row["indexname"]: " ".join(row["indexdef"].lower().split())
            for row in rows
        }

        missing = REQUIRED_INDEXES - set(indexes)
        assert missing == set(), f"missing indexes: {sorted(missing)}"

        # The unique partial index behind job idempotency.
        idempotency = indexes["download_jobs_user_idempotency_key_idx"]
        assert "unique" in idempotency
        assert "user_id, idempotency_key" in idempotency
        assert "idempotency_key is not null" in idempotency

        # The library listing index must exclude hidden rows at the ready status.
        library_index = indexes["download_jobs_user_library_idx"]
        assert "library_hidden" in library_index
        assert "status = 'ready'" in library_index

        # Canonical playlist membership is unique only for real ids.
        canonical_item = indexes["playlist_items_playlist_canonical_idx"]
        assert "unique" in canonical_item
        assert "canonical_id <> ''" in canonical_item

        # Case-insensitive email uniqueness.
        email = indexes["profiles_email_key"]
        assert "unique" in email
        assert "lower(email)" in email

        # Lease scans are the reclaim path.
        lease = indexes["media_assets_status_lease_idx"]
        assert "status, lease_until" in lease

    db_run(scenario)


def test_required_constraints_and_triggers_exist(db_run):
    async def scenario(db):
        rows = await db.fetch(
            """
            select c.conname,
                   c.contype,
                   c.condeferrable,
                   c.condeferred,
                   c.confdeltype,
                   pg_get_constraintdef(c.oid) as definition
            from pg_constraint c
            join pg_class t on t.oid = c.conrelid
            join pg_namespace n on n.oid = t.relnamespace
            where n.nspname = $1
            """,
            db.schema,
        )
        by_name = {row["conname"]: row for row in rows}

        for name, delete_rule in REQUIRED_FOREIGN_KEYS.items():
            assert name in by_name, f"missing foreign key {name}"
            assert by_name[name]["contype"] == "f"
            assert by_name[name]["confdeltype"] == delete_rule, (
                f"{name} delete rule is {by_name[name]['confdeltype']!r}, "
                f"expected {delete_rule!r}"
            )

        missing_checks = REQUIRED_CHECKS - set(by_name)
        assert missing_checks == set(), f"missing checks: {sorted(missing_checks)}"

        for name in REQUIRED_UNIQUE_CONSTRAINTS:
            assert name in by_name, f"missing unique constraint {name}"
            assert by_name[name]["contype"] in {"u", "p"}

        # Curated-playlist reordering rewrites every position in one
        # statement, so the uniqueness check has to be deferred to commit.
        position = by_name["user_playlist_tracks_position_key"]
        assert position["condeferrable"] is True
        assert position["condeferred"] is True

        trigger_rows = await db.fetch(
            """
            select t.tgname
            from pg_trigger t
            join pg_class c on c.oid = t.tgrelid
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = $1 and not t.tgisinternal
            """,
            db.schema,
        )
        triggers = {row["tgname"] for row in trigger_rows}
        assert REQUIRED_TRIGGERS - triggers == set()

    db_run(scenario)


def test_every_service_column_projection_resolves_against_the_schema(db_run):
    """Run the services' real projections against the live schema.

    ``limit 0`` still forces PostgreSQL to parse and plan the statement, so an
    undefined column (or a broken join) fails here. The services' own constants
    and FROM clauses are used deliberately: this is the drift guard.
    """

    async def scenario(db):
        schema = db.schema_sql
        probes = {
            "jobs": (
                f"select {jobs.JOB_COLUMNS} from {schema}.download_jobs limit 0",
                (),
            ),
            "assets": (
                f"select {assets.ASSET_COLUMNS} from {schema}.media_assets limit 0",
                (),
            ),
            "library": (
                f"select {library.LIBRARY_COLUMNS} "
                f"{library._library_from(schema)} {library.LIBRARY_WHERE} "
                "limit 0",
                (uuid4(),),
            ),
            "tracks": (
                f"select {tracks.TRACKS_COLUMNS} "
                f"{tracks._tracks_from(schema)} {tracks.TRACKS_WHERE} limit 0",
                (uuid4(), ""),
            ),
            "tracks_by_ids": (
                f"select {tracks.TRACKS_COLUMNS} "
                f"{tracks._tracks_from(schema)} {tracks.TRACKS_WHERE_BY_IDS} "
                "limit 0",
                (uuid4(), [uuid4()]),
            ),
            "playlists": (
                f"select {playlists.PLAYLIST_COLUMNS} "
                f"from {schema}.playlists limit 0",
                (),
            ),
            "playlist_items": (
                f"select {playlists.PLAYLIST_ITEM_COLUMNS} "
                f"from {schema}.playlist_items limit 0",
                (),
            ),
            "user_playlists": (
                f"select {user_playlists._playlist_columns(schema)} "
                f"from {schema}.user_playlists p limit 0",
                (),
            ),
            "profiles": (
                f"select {profiles._PROFILE_COLUMNS} "
                f"from {schema}.profiles limit 0",
                (),
            ),
            "auth_profile": (
                f"select {auth._SESSION_PROFILE_COLUMNS} "
                f"from {schema}.profiles p limit 0",
                (),
            ),
            "auth_profile_basic": (
                f"select {auth._PROFILE_COLUMNS} from {schema}.profiles limit 0",
                (),
            ),
            "admin_jobs": (
                f"select {admin_inventory.ADMIN_JOB_COLUMNS} "
                f"from {schema}.download_jobs j "
                f"join {schema}.profiles p on p.id = j.user_id limit 0",
                (),
            ),
            "admin_assets": (
                f"select {admin_inventory._admin_asset_columns(schema)} "
                f"{admin_inventory._admin_asset_from(schema)} limit 0",
                (),
            ),
        }
        for name, (query, args) in probes.items():
            try:
                rows = await db.fetch(query, *args)
            except Exception as exc:  # noqa: BLE001 - report which probe broke
                raise AssertionError(f"{name} projection failed: {exc}") from exc
            assert rows == [], f"{name} projection unexpectedly returned rows"

    db_run(scenario)
