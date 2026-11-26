"""End-to-end authentication against a real PostgreSQL database.

Covers the session lifecycle, password changes, expiry, the admin reset, and
the HTTP surface with the real pool (which the fake-database tests cannot).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.core.security import hash_session_token, verify_password
from backend.app.main import create_app
from backend.app.services import auth
from backend.tests.integration.conftest import delete_profiles, unique_email

pytestmark = pytest.mark.integration


def test_register_login_change_password_and_logout(db_run):
    email = unique_email("itest-auth")

    async def scenario(db):
        try:
            registered = await auth.register(db, email, "first-password-1")

            profile = await auth.authenticate(db, registered.token)
            assert profile is not None
            assert profile["email"] == email
            assert profile["is_approved"] is False
            assert "password_hash" not in profile

            # Only the token hash is stored, never the token itself.
            stored = await db.fetchrow(
                f"select token_hash from {db.schema_sql}.auth_sessions "
                "where user_id = $1",
                registered.profile["id"],
            )
            assert stored["token_hash"] == hash_session_token(registered.token)
            assert registered.token not in stored["token_hash"]

            login = await auth.login(db, email, "first-password-1")
            assert login.profile["id"] == registered.profile["id"]
            assert login.token != registered.token

            with pytest.raises(auth.InvalidCredentialsError):
                await auth.login(db, email, "wrong-password-1")

            await auth.change_password(
                db,
                login.profile["id"],
                "first-password-1",
                "second-password-2",
                keep_token=login.token,
            )
            # The caller's session survives; every other session is revoked.
            assert await auth.authenticate(db, login.token) is not None
            assert await auth.authenticate(db, registered.token) is None

            with pytest.raises(auth.InvalidCredentialsError):
                await auth.login(db, email, "first-password-1")
            fresh = await auth.login(db, email, "second-password-2")
            assert fresh.profile["id"] == registered.profile["id"]

            await auth.revoke_session(db, fresh.token)
            assert await auth.authenticate(db, fresh.token) is None
            # Logging out one session does not touch the remaining one.
            assert await auth.authenticate(db, login.token) is not None
        finally:
            await delete_profiles(db, email)

    db_run(scenario)


def test_duplicate_email_is_case_insensitive(db_run):
    email = unique_email("itest-dup")

    async def scenario(db):
        try:
            await auth.register(db, email, "duplicate-password-1")
            for duplicate in (email.upper(), f"  {email}  "):
                with pytest.raises(auth.EmailTakenError):
                    await auth.register(db, duplicate, "duplicate-password-2")
            rows = await db.fetch(
                f"select id from {db.schema_sql}.profiles "
                "where lower(email) = $1",
                email,
            )
            assert len(rows) == 1
        finally:
            await delete_profiles(db, email)

    db_run(scenario)


def test_expired_sessions_do_not_authenticate(db_run):
    email = unique_email("itest-expiry")

    async def scenario(db):
        try:
            session = await auth.register(db, email, "expiry-password-1")
            await db.execute(
                f"update {db.schema_sql}.auth_sessions "
                "set expires_at = now() - interval '1 minute' "
                "where token_hash = $1",
                hash_session_token(session.token),
            )
            assert await auth.authenticate(db, session.token) is None

            # A later login is unaffected and issues a fresh valid session.
            fresh = await auth.login(db, email, "expiry-password-1")
            assert await auth.authenticate(db, fresh.token) is not None
        finally:
            await delete_profiles(db, email)

    db_run(scenario)


def test_authenticate_touches_last_used_at_only_for_valid_sessions(db_run):
    email = unique_email("itest-touch")

    async def scenario(db):
        try:
            session = await auth.register(db, email, "touch-password-1")
            token_hash = hash_session_token(session.token)
            await db.execute(
                f"update {db.schema_sql}.auth_sessions "
                "set last_used_at = now() - interval '1 hour' "
                "where token_hash = $1",
                token_hash,
            )

            assert await auth.authenticate(db, session.token) is not None

            touched = await db.fetchrow(
                f"select "
                "(last_used_at > now() - interval '1 minute') as touched, "
                "(last_used_at < now() - interval '30 minutes') as stale "
                f"from {db.schema_sql}.auth_sessions where token_hash = $1",
                token_hash,
            )
            assert touched == {"touched": True, "stale": False}
        finally:
            await delete_profiles(db, email)

    db_run(scenario)


def test_login_with_a_corrupt_stored_hash_fails_generically(db_run):
    email = unique_email("itest-corrupt")

    async def scenario(db):
        try:
            await db.execute(
                f"insert into {db.schema_sql}.profiles "
                "(email, password_hash) values ($1, $2)",
                email,
                "not-an-argon2-hash",
            )
            with pytest.raises(auth.InvalidCredentialsError):
                await auth.login(db, email, "any-password-value")
        finally:
            await delete_profiles(db, email)

    db_run(scenario)


def test_admin_password_reset_revokes_every_session(db_run):
    email = unique_email("itest-admin-reset")

    async def scenario(db):
        try:
            registered = await auth.register(db, email, "user-password-1")
            login = await auth.login(db, email, "user-password-1")

            assert await auth.set_password(
                db,
                registered.profile["id"],
                "reset-password-2",
                revoke_sessions=True,
            )

            assert await auth.authenticate(db, registered.token) is None
            assert await auth.authenticate(db, login.token) is None
            with pytest.raises(auth.InvalidCredentialsError):
                await auth.login(db, email, "user-password-1")
            assert (
                await auth.login(db, email, "reset-password-2")
            ).profile["id"] == registered.profile["id"]
        finally:
            await delete_profiles(db, email)

    db_run(scenario)


def test_http_auth_flow_with_the_real_pool(database_url, db_run, tmp_path):
    """The FastAPI app (own lifespan pool) signs up, reads /api/me, logs out."""
    settings = Settings.from_env(
        {
            "ENVIRONMENT": "test",
            "DATABASE_URL": database_url,
            "MEDIA_TOKEN_SECRET": "itest-media-secret",
            "DOWNLOAD_DIR": str(tmp_path / "downloads"),
        }
    )
    email = unique_email("itest-http")

    try:
        with TestClient(create_app(settings)) as client:
            registered = client.post(
                "/api/auth/register",
                json={"email": email, "password": "http-password-1"},
            )
            assert registered.status_code == 201
            body = registered.json()
            assert body["profile"]["email"] == email
            assert body["profile"]["is_approved"] is False
            headers = {"Authorization": f"Bearer {body['token']}"}

            me = client.get("/api/me", headers=headers)
            assert me.status_code == 200
            assert me.json()["email"] == email

            # Pending accounts are blocked from protected routes.
            assert client.get("/api/library", headers=headers).status_code == 403

            assert client.post("/api/auth/logout", headers=headers).status_code == 204
            assert client.get("/api/me", headers=headers).status_code == 401

            # Repeated logout stays a no-op success.
            assert client.post("/api/auth/logout", headers=headers).status_code == 204
    finally:
        db_run(lambda db: delete_profiles(db, email))


def test_cli_create_admin_against_postgres(database_url, db_run, monkeypatch, capsys):
    from backend.app.cli import create_admin

    email = unique_email("itest-cli")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.delenv("DB_SCHEMA", raising=False)

    async def load(db):
        row = await db.fetchrow(
            f"select id, email, is_approved, app_role, password_hash "
            f"from {db.schema_sql}.profiles where lower(email) = $1",
            email,
        )
        assert row is not None
        return row

    try:
        assert (
            create_admin.main(
                ["--email", email.upper(), "--password", "cli-password-1", "--admin"]
            )
            == 0
        )
        first_output = capsys.readouterr()
        assert "Created admin account" in first_output.out
        assert "cli-password-1" not in first_output.out + first_output.err

        row = db_run(load)
        assert row["email"] == email
        assert row["is_approved"] is True
        assert row["app_role"] == "admin"
        assert verify_password(row["password_hash"], "cli-password-1")
        user_id = row["id"]

        # Re-running without --admin changes the password but keeps the role.
        assert (
            create_admin.main(["--email", email, "--password", "cli-password-2"])
            == 0
        )
        assert "Updated admin account" in capsys.readouterr().out

        async def check_update(db):
            updated = await db.fetchrow(
                f"select app_role, password_hash from {db.schema_sql}.profiles "
                "where lower(email) = $1",
                email,
            )
            assert updated["app_role"] == "admin"
            assert verify_password(updated["password_hash"], "cli-password-2")
            assert not verify_password(updated["password_hash"], "cli-password-1")

            with pytest.raises(auth.InvalidCredentialsError):
                await auth.login(db, email, "cli-password-1")
            session = await auth.login(db, email, "cli-password-2")
            assert session.profile["id"] == user_id
            assert session.profile["app_role"] == "admin"

            count = await db.fetchrow(
                f"select count(*) as n from {db.schema_sql}.profiles "
                "where lower(email) = $1",
                email,
            )
            assert count["n"] == 1

        db_run(check_update)
    finally:
        db_run(lambda db: delete_profiles(db, email))
