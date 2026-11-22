"""Tests for the asyncpg pool wrapper.

A fake pool exercises the wrapper's real acquisition and transaction behavior
without a network. ``create_pool`` is tested by monkeypatching asyncpg's factory
so the required pooler options are asserted.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.app.core import db as db_module
from backend.app.core.config import ConfigError, Settings
from backend.app.core.db import Database, create_pool


class FakeTransaction:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def __aenter__(self) -> "FakeTransaction":
        self.log.append("begin")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.log.append("rollback" if exc_type else "commit")
        return False


class FakeConnection:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.calls: list[tuple[str, str, tuple[Any, ...], float | None]] = []

    async def fetch(self, query: str, *args: Any, timeout: float | None = None):
        self.calls.append(("fetch", query, args, timeout))
        return [{"query": query, "args": args}]

    async def fetchrow(self, query: str, *args: Any, timeout: float | None = None):
        self.calls.append(("fetchrow", query, args, timeout))
        return {"query": query, "args": args}

    async def execute(self, query: str, *args: Any, timeout: float | None = None):
        self.calls.append(("execute", query, args, timeout))
        return "UPDATE 1"

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self.log)


class FakeAcquire:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> FakeConnection:
        return self.connection

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class FakePool:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.connection = FakeConnection(self.log)
        self.acquire_count = 0
        self.closed = False

    def acquire(self) -> FakeAcquire:
        self.acquire_count += 1
        return FakeAcquire(self.connection)

    async def close(self) -> None:
        self.closed = True


def run(coro):
    return asyncio.run(coro)


def test_fetch_acquires_connection_and_passes_arguments():
    pool = FakePool()
    database = Database(pool)

    rows = run(database.fetch("SELECT $1::int AS n", 7, timeout=1.5))

    assert rows[0]["query"] == "SELECT $1::int AS n"
    assert rows[0]["args"] == (7,)
    assert pool.acquire_count == 1
    assert pool.connection.calls == [
        ("fetch", "SELECT $1::int AS n", (7,), 1.5)
    ]


def test_fetchrow_and_execute_delegate_to_connection():
    pool = FakePool()
    database = Database(pool)

    row = run(database.fetchrow("SELECT 1"))
    status = run(database.execute("UPDATE jobs SET status = $1", "ready"))

    assert row == {"query": "SELECT 1", "args": ()}
    assert status == "UPDATE 1"
    assert [call[0] for call in pool.connection.calls] == [
        "fetchrow",
        "execute",
    ]
    assert pool.acquire_count == 2


def test_transaction_commits_on_success():
    pool = FakePool()
    database = Database(pool)

    async def work() -> Any:
        async with database.transaction() as connection:
            return await connection.fetch("SELECT 1")

    result = run(work())

    assert result == [{"query": "SELECT 1", "args": ()}]
    assert pool.log == ["begin", "commit"]


def test_transaction_rolls_back_on_error():
    pool = FakePool()
    database = Database(pool)

    async def work() -> None:
        async with database.transaction() as connection:
            await connection.execute("UPDATE jobs SET status = 'failed'")
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        run(work())

    assert pool.log == ["begin", "rollback"]


def test_close_closes_pool():
    pool = FakePool()

    run(Database(pool).close())

    assert pool.closed is True


def test_database_requires_a_pool():
    with pytest.raises(ConfigError):
        Database(None)


def test_database_schema_defaults_to_public():
    database = Database(FakePool())

    assert database.schema == "public"
    assert database.schema_sql == '"public"'


def test_database_schema_is_validated_and_quoted():
    database = Database(FakePool(), "vidfetch")

    assert database.schema == "vidfetch"
    assert database.schema_sql == '"vidfetch"'


@pytest.mark.parametrize("schema", ["pg_catalog", "auth", "Bad", "vid-fetch"])
def test_database_rejects_invalid_schema(schema):
    with pytest.raises(ConfigError):
        Database(FakePool(), schema)


def test_create_pool_rejects_invalid_schema_before_connecting(monkeypatch):
    called = False

    async def fake_create_pool(**kwargs):
        nonlocal called
        called = True
        return FakePool()

    monkeypatch.setattr(db_module.asyncpg, "create_pool", fake_create_pool)
    settings = Settings.from_env(
        {"DATABASE_URL": "postgresql://user:pass@pooler.example.test:6543/postgres"}
    )
    settings.db_schema = "information_schema"

    with pytest.raises(ConfigError):
        run(create_pool(settings))

    assert called is False


def test_create_pool_requires_database_url():
    with pytest.raises(ConfigError):
        run(create_pool(Settings.from_env({})))


def test_create_pool_sets_pooler_safe_options(monkeypatch):
    captured: dict[str, Any] = {}
    pool = FakePool()

    async def fake_create_pool(**kwargs):
        captured.update(kwargs)
        return pool

    monkeypatch.setattr(db_module.asyncpg, "create_pool", fake_create_pool)
    settings = Settings.from_env(
        {"DATABASE_URL": "postgresql://user:pass@pooler.example.test:6543/postgres"}
    )

    database = run(create_pool(settings, min_size=1, max_size=4))

    assert captured["dsn"].startswith("postgresql://")
    assert captured["min_size"] == 1
    assert captured["max_size"] == 4
    assert captured["statement_cache_size"] == 0
    assert database.pool is pool
    assert database.schema == "public"
    assert database.schema_sql == '"public"'


def test_create_pool_passes_configured_schema(monkeypatch):
    pool = FakePool()

    async def fake_create_pool(**kwargs):
        return pool

    monkeypatch.setattr(db_module.asyncpg, "create_pool", fake_create_pool)
    settings = Settings.from_env(
        {
            "DATABASE_URL": "postgresql://user:pass@pooler.example.test:6543/postgres",
            "DB_SCHEMA": "vidfetch",
        }
    )

    database = run(create_pool(settings))

    assert database.schema == "vidfetch"
    assert database.schema_sql == '"vidfetch"'
