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
from typing import Awaitable, Callable, TypeVar

import pytest

from backend.app.core.config import Settings
from backend.app.core.db import Database, create_pool

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
