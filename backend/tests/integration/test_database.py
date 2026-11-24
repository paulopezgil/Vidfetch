"""Real-PostgreSQL checks for the :class:`Database` adapter.

These are the cases the fake pool cannot prove: psycopg parameter binding,
data-modifying statements, transaction semantics, status tags, and timeout
recovery.
"""
from __future__ import annotations

import pytest

from backend.tests.integration.conftest import delete_profiles, unique_email

pytestmark = pytest.mark.integration


def test_placeholders_repeats_percent_escaping_and_status_tags(db_run):
    email = unique_email("itest-db")

    async def scenario(db):
        try:
            status = await db.execute(
                f"insert into {db.schema_sql}.profiles "
                "(email, password_hash) values ($1, $2)",
                email,
                "placeholder-hash",
            )
            assert status == "INSERT 0 1"

            row = await db.fetchrow(
                f"select id, email, is_approved, app_role, created_at "
                f"from {db.schema_sql}.profiles where email = $1",
                email,
            )
            assert isinstance(row, dict)
            assert row["email"] == email
            assert row["is_approved"] is False
            assert row["app_role"] == "user"
            assert row["created_at"].tzinfo is not None

            # A repeated placeholder duplicates its argument in order.
            repeated = await db.fetchrow(
                "select $1::text as a, $1::text as b, $2::int as c", "x", 3
            )
            assert repeated == {"a": "x", "b": "x", "c": 3}

            # Literal percent signs survive escaping, and the parameter is used
            # as an ILIKE pattern rather than being mangled by psycopg.
            escaped = await db.fetchrow(
                "select '50%'::text as pct, "
                "'100% cotton' ilike '%' || $1 || '%' as hit",
                "cotton",
            )
            assert escaped == {"pct": "50%", "hit": True}

            rows = await db.fetch(
                f"select email from {db.schema_sql}.profiles "
                "where email like '%' || $1 || '%' order by email",
                email[6:20],
            )
            assert [row["email"] for row in rows] == [email]

            assert (
                await db.execute(
                    f"update {db.schema_sql}.profiles set updated_at = now() "
                    "where email = $1",
                    email,
                )
                == "UPDATE 1"
            )
            assert (
                await db.execute(
                    f"update {db.schema_sql}.profiles set updated_at = now() "
                    "where email = $1",
                    "nobody@example.test",
                )
                == "UPDATE 0"
            )
        finally:
            await delete_profiles(db, email)

    db_run(scenario)


def test_transaction_commits_on_success_and_rolls_back_on_error(db_run):
    committed = unique_email("itest-commit")
    rolled_back = unique_email("itest-rollback")

    async def scenario(db):
        try:
            async with db.transaction() as connection:
                inserted = await connection.fetchrow(
                    f"insert into {db.schema_sql}.profiles "
                    "(email, password_hash) values ($1, $2) returning email",
                    committed,
                    "tx-hash",
                )
                assert inserted == {"email": committed}
            assert (
                await db.fetchrow(
                    f"select email from {db.schema_sql}.profiles "
                    "where email = $1",
                    committed,
                )
                == {"email": committed}
            )

            with pytest.raises(RuntimeError, match="boom"):
                async with db.transaction() as connection:
                    await connection.execute(
                        f"insert into {db.schema_sql}.profiles "
                        "(email, password_hash) values ($1, $2)",
                        rolled_back,
                        "tx-hash",
                    )
                    raise RuntimeError("boom")

            assert (
                await db.fetchrow(
                    f"select email from {db.schema_sql}.profiles "
                    "where email = $1",
                    rolled_back,
                )
                is None
            )
        finally:
            await delete_profiles(db, committed, rolled_back)

    db_run(scenario)


def test_timeout_discards_the_connection_and_the_pool_recovers(db_run):
    async def scenario(db):
        with pytest.raises(TimeoutError):
            await db.fetchrow("select pg_sleep($1)", 5.0, timeout=0.2)

        # The cancelled connection must be discarded and replaced, not reused.
        assert await db.fetchrow("select 1 as one") == {"one": 1}

    db_run(scenario)
