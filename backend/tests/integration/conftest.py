"""Fixtures for the real-PostgreSQL integration tests.

These tests are opt-in: they run only when ``TEST_DATABASE_URL`` points at a
throwaway database with ``db/migrations`` applied (normally a local Postgres
such as the docker-compose one on port 54322). They never touch the running
application database, and every row they create is deleted again.

psycopg's async connections (and its pool) are bound to the event loop that
created them, so each test opens a pool inside its own ``asyncio.run`` instead
of sharing a session-scoped one.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, TypeVar

import pytest

from backend.app.core.config import Settings
from backend.app.core.db import Database, create_pool
from backend.app.services import assets as assets_service
from backend.app.services import jobs as jobs_service
from backend.app.services.storage import Storage

T = TypeVar("T")

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()

SKIP_REASON = (
    "TEST_DATABASE_URL is not set; skipping PostgreSQL integration tests"
)


def pytest_collection_modifyitems(config, items) -> None:
    """Skip only the integration-marked tests when no test database is set."""
    if TEST_DATABASE_URL:
        return
    skip = pytest.mark.skip(reason=SKIP_REASON)
    for item in items:
        if item.get_closest_marker("integration") is not None:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def database_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip(SKIP_REASON)
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def integration_settings(database_url: str) -> Settings:
    return Settings.from_env(
        {
            "ENVIRONMENT": "test",
            "DATABASE_URL": database_url,
        }
    )


@pytest.fixture
def db_run(integration_settings: Settings) -> Callable[[Callable[[Database], Awaitable[T]]], T]:
    """Run an async scenario with its own pool/event loop and close it after.

    Usage::

        def test_something(db_run):
            async def scenario(db):
                return await db.fetchrow("select 1 as one")
            assert db_run(scenario) == {"one": 1}
    """

    def run(scenario: Callable[[Database], Awaitable[T]]) -> T:
        async def main() -> T:
            database = await create_pool(integration_settings)
            try:
                return await scenario(database)
            finally:
                await database.close()

        return asyncio.run(main())

    return run


def unique_email(prefix: str = "itest") -> str:
    """A per-test address that cannot collide with real or other test data."""
    return f"{prefix}-{uuid.uuid4().hex}@example.test"


async def delete_profiles(db: Database, *emails: str) -> None:
    """Delete test profiles (sessions cascade from the foreign key)."""
    if not emails:
        return
    await db.execute(
        f"delete from {db.schema_sql}.profiles "
        "where lower(email) = any($1::text[])",
        [email.lower() for email in emails],
    )


async def create_profile(
    db: Database,
    *,
    email: str | None = None,
    is_approved: bool = True,
    app_role: str = "user",
) -> dict[str, Any]:
    """Insert an approved (by default) test profile and return its row."""
    address = email or unique_email("itest-user")
    record = await db.fetchrow(
        f"insert into {db.schema_sql}.profiles "
        "(email, password_hash, is_approved, app_role) "
        "values ($1, $2, $3, $4) "
        "returning id, email, is_approved, app_role",
        address,
        "integration-test-hash",
        is_approved,
        app_role,
    )
    assert record is not None
    return dict(record)


async def make_ready_asset(
    db: Database,
    storage: Storage,
    *,
    canonical_id: str | None = None,
    options_hash: str | None = None,
    extractor_key: str = "youtube",
    source_url: str = "https://example.test/video",
    title: str = "Clip",
    duration_seconds: int | None = 30,
    payload: bytes = b"0123456789",
    thumbnail: bool = False,
    output_ext: str = "mp4",
) -> dict[str, Any]:
    """Claim, write a real file, and finalize a shared ready asset."""
    canonical = canonical_id or f"youtube:{uuid.uuid4().hex}"
    options = options_hash or uuid.uuid4().hex
    claim = await assets_service.claim_asset(
        db,
        storage,
        canonical_id=canonical,
        extractor_key=extractor_key,
        source_url=source_url,
        title=title,
        duration_seconds=duration_seconds,
        options_hash=options,
        format_selector="best",
        lease_seconds=60,
    )
    asset = claim.asset
    relative = f"assets/{asset['id']}/media.{output_ext or 'bin'}"
    path = storage.validate_relative_path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    thumbnail_path = None
    if thumbnail:
        thumbnail_path = f"assets/{asset['id']}/thumb.jpg"
        storage.validate_relative_path(thumbnail_path).write_bytes(
            b"\xff\xd8\xffthumb"
        )
    ready = await assets_service.mark_ready(
        db,
        asset["id"],
        file_path=relative,
        file_size_bytes=len(payload),
        output_ext=output_ext,
        thumbnail_path=thumbnail_path,
    )
    assert ready is not None
    return ready


async def create_ready_job(
    db: Database,
    *,
    user_id: Any,
    asset_id: Any,
    title: str = "Clip",
    completed_at: datetime | None = None,
    options_hash: str | None = None,
    source_url: str = "https://example.test/video",
) -> dict[str, Any]:
    """Create a job and finish it as ready in one service-level update.

    ``completed_at`` lets a test control ``user_tracks.downloaded_at`` (the
    database trigger copies it), which makes ordering assertions deterministic.
    """
    job = await jobs_service.create_job(
        db,
        user_id=user_id,
        source_url=source_url,
        title=title,
        options_hash=options_hash or uuid.uuid4().hex,
    )
    ready = await jobs_service.update_job(
        db,
        job["id"],
        status="ready",
        asset_id=asset_id,
        progress=100,
        completed_at=completed_at or datetime.now(timezone.utc),
    )
    assert ready is not None
    return ready


async def cleanup_test_data(
    db: Database,
    *,
    profiles: Iterable[dict[str, Any]] = (),
    canonical_ids: Iterable[str] = (),
) -> None:
    """Delete test profiles (cascading their rows) and shared test assets.

    Audit rows are removed first because deleting a profile nulls their
    ``actor_id``/``target_user_id`` and would leave them behind.
    """
    profile_rows = list(profiles)
    identifiers = [row["id"] for row in profile_rows]
    if identifiers:
        await db.execute(
            f"delete from {db.schema_sql}.admin_audit_log "
            "where actor_id = any($1::uuid[]) "
            "or target_user_id = any($1::uuid[])",
            identifiers,
        )
    await delete_profiles(db, *[row["email"] for row in profile_rows])
    assets = list(canonical_ids)
    if assets:
        await db.execute(
            f"delete from {db.schema_sql}.media_assets "
            "where canonical_id = any($1::text[])",
            assets,
        )


@pytest.fixture
def media_storage(tmp_path: Path) -> Storage:
    """A real storage root under the test's temporary directory."""
    storage = Storage(tmp_path / "media")
    storage.ensure_directories()
    return storage
