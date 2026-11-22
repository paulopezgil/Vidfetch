"""Async PostgreSQL access for the v2 backend.

Supabase exposes Postgres through a PgBouncer/Supavisor pooler. In transaction
pooling mode server-side prepared statements are not safe, so the pool is
created with ``statement_cache_size=0`` and a small connection range.

Nothing here connects at import time. :func:`create_pool` is awaited during the
application lifespan; tests can construct :class:`Database` around any pool-like
object (including a fake) without a network.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import asyncpg

from .config import (
    DEFAULT_DB_SCHEMA,
    ConfigError,
    Settings,
    validate_schema_name,
)


class Database:
    """Thin async wrapper around an ``asyncpg`` pool.

    The wrapper acquires a connection per operation so concurrent requests do
    not share a mutable connection. Multi-statement work uses
    :meth:`transaction`, which pins one connection for the duration.

    ``schema`` is the application schema that owns every table the app reads or
    writes. ``schema_sql`` is the same name, safely quoted, for interpolation
    into SQL. Values are validated before they reach either property, so they
    are never caller-supplied SQL.
    """

    def __init__(self, pool: Any, schema: str = DEFAULT_DB_SCHEMA) -> None:
        if pool is None:
            raise ConfigError("A database pool is required.")
        self._pool = pool
        self._schema = validate_schema_name(schema)

    @property
    def pool(self) -> Any:
        return self._pool

    @property
    def schema(self) -> str:
        return self._schema

    @property
    def schema_sql(self) -> str:
        """Return the schema as a quoted SQL identifier (``'"vidfetch"'``)."""
        return f'"{self._schema}"'

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Any]:
        async with self._pool.acquire() as connection:
            yield connection

    async def fetch(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> list[Any]:
        async with self.acquire() as connection:
            return await connection.fetch(query, *args, timeout=timeout)

    async def fetchrow(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> Any:
        async with self.acquire() as connection:
            return await connection.fetchrow(query, *args, timeout=timeout)

    async def execute(
        self, query: str, *args: Any, timeout: float | None = None
    ) -> str:
        async with self.acquire() as connection:
            return await connection.execute(query, *args, timeout=timeout)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        """Yield a connection inside a database transaction.

        Commits on normal exit and rolls back when the body raises.
        """
        async with self.acquire() as connection:
            async with connection.transaction():
                yield connection

    async def close(self) -> None:
        await self._pool.close()


async def create_pool(
    settings: Settings,
    *,
    min_size: int = 1,
    max_size: int = 5,
) -> Database:
    """Create the application's asyncpg pool.

    The pool is intentionally small: v2 runs as a single backend process, and
    the Supabase pooler already multiplexes client connections. Await this
    during startup only, never at import time.
    """
    if not settings.database_url:
        raise ConfigError("DATABASE_URL (or SUPABASE_DB_URL) is not configured.")

    # Reject a bad schema before opening a connection. ``Database`` validates
    # again, but doing it here means a misconfigured deployment never touches
    # the database at all.
    schema = validate_schema_name(settings.db_schema)

    pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=min_size,
        max_size=max_size,
        # Required for Supabase's transaction-mode pooler.
        statement_cache_size=0,
        max_inactive_connection_lifetime=300,
    )
    if pool is None:  # pragma: no cover - asyncpg always returns a pool
        raise ConfigError("Failed to create the database pool.")
    return Database(pool, schema)
