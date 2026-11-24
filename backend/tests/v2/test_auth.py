"""Local authentication: HTTP endpoints, sessions, and service behavior.

The fake database returns the rows a test queues, so these tests exercise the
real service/route code (validation, Argon2 hashing, placeholder SQL) without a
network or Postgres. SQL-shape assertions pin the security-critical clauses
(expiry, ownership join, token hashing) that a canned row cannot demonstrate.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from backend.app.core.security import (
    hash_password,
    hash_session_token,
    verify_password,
)
from backend.app.services import auth
from backend.tests.v2.fakes import (
    FakeDatabase,
    app_client,
    auth_headers,
    make_settings,
    make_token,
    profile_row,
)

PASSWORD = "correct-horse-battery"
OTHER_PASSWORD = "a-different-password"


def run(coro):
    return asyncio.run(coro)


def _approved(**overrides):
    return profile_row(email="alice@example.test", is_approved=True, **overrides)


def _headers(profile):
    return auth_headers(make_token(profile["id"]))


def _calls_containing(db: FakeDatabase, needle: str):
    return [call for call in db.calls if needle in call[1]]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_creates_a_pending_account_and_session(tmp_path):
    settings = make_settings(tmp_path, AUTH_SESSION_TTL_SECONDS="1200")
    profile = profile_row(email="new@example.test", is_approved=False)
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/auth/register",
            json={"email": "  New@Example.TEST ", "password": PASSWORD},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["token"]
    assert body["profile"]["email"] == "new@example.test"
    assert body["profile"]["is_approved"] is False
    assert body["profile"]["app_role"] == "user"
    assert "password_hash" not in body["profile"]

    expires_at = datetime.fromisoformat(body["expires_at"])
    expected = datetime.now(timezone.utc) + timedelta(seconds=1200)
    assert abs((expires_at - expected).total_seconds()) < 60

    insert_query, insert_args = db.calls[0][1], db.calls[0][2]
    assert "insert into" in insert_query and "profiles" in insert_query
    assert insert_args[0] == "new@example.test"
    assert insert_args[1].startswith("$argon2id$")
    assert verify_password(insert_args[1], PASSWORD)

    session_query, session_args = db.calls[-1][1], db.calls[-1][2]
    assert "insert into" in session_query and "auth_sessions" in session_query
    assert session_args[1] == hash_session_token(body["token"])
    assert body["token"] not in session_args


def test_register_normalizes_email_and_cleans_up_expired_sessions():
    db = FakeDatabase()
    db.queue_fetchrow(profile_row())
    session_ttl = 3600

    session = run(
        auth.register(db, "  MiXeD@Example.TEST  ", PASSWORD, session_ttl_seconds=session_ttl)
    )

    assert db.calls[0][2][0] == "mixed@example.test"
    cleanup_query, cleanup_args = db.calls[1][1], db.calls[1][2]
    assert "delete from" in cleanup_query and "auth_sessions" in cleanup_query
    assert "expires_at <= now()" in cleanup_query
    assert cleanup_args == (session.profile["id"],)
    assert session.expires_at > datetime.now(timezone.utc)


def test_register_rejects_a_duplicate_email(tmp_path):
    settings = make_settings(tmp_path)
    db = FakeDatabase(fail_with=psycopg.errors.UniqueViolation("duplicate key"))

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/auth/register",
            json={"email": "taken@example.test", "password": PASSWORD},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


@pytest.mark.parametrize(
    "email,password,code",
    [
        ("not-an-email", PASSWORD, "invalid_email"),
        ("", PASSWORD, "invalid_email"),
        ("user@example.test", "short", "weak_password"),
        ("user@example.test", "", "weak_password"),
        ("user@example.test", "x" * 201, "invalid_password"),
    ],
)
def test_register_validates_input_before_touching_the_database(
    tmp_path, email, password, code
):
    settings = make_settings(tmp_path)
    db = FakeDatabase()

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/auth/register", json={"email": email, "password": password}
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == code
    assert db.calls == []


def test_register_requires_a_configured_database(tmp_path):
    settings = make_settings(tmp_path)

    with app_client(settings) as (app, client):
        response = client.post(
            "/api/auth/register",
            json={"email": "user@example.test", "password": PASSWORD},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_returns_a_session_for_valid_credentials(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved(password_hash=hash_password(PASSWORD))
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/auth/login",
            json={"email": "ALICE@example.test", "password": PASSWORD},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["id"] == str(profile["id"])
    assert "password_hash" not in body["profile"]

    lookup_query, lookup_args = db.calls[0][1], db.calls[0][2]
    assert "where lower(email) = $1" in lookup_query
    assert lookup_args == ("alice@example.test",)

    session_args = _calls_containing(db, "insert into")[-1][2]
    assert session_args[1] == hash_session_token(body["token"])


def test_login_works_for_an_unapproved_account(tmp_path):
    settings = make_settings(tmp_path)
    profile = profile_row(
        email="pending@example.test",
        is_approved=False,
        password_hash=hash_password(PASSWORD),
    )
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/auth/login",
            json={"email": "pending@example.test", "password": PASSWORD},
        )

    assert response.status_code == 200
    assert response.json()["profile"]["is_approved"] is False
    assert _calls_containing(db, "insert into")  # a session was created


def test_login_with_a_wrong_password_is_generic_and_creates_no_session(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved(password_hash=hash_password(PASSWORD))
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/auth/login",
            json={"email": "alice@example.test", "password": OTHER_PASSWORD},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert response.json()["error"]["message"] == "Invalid email or password."
    assert not _calls_containing(db, "auth_sessions")


def test_login_with_an_unknown_email_looks_identical(tmp_path):
    settings = make_settings(tmp_path)
    db = FakeDatabase()
    db.queue_fetchrow(None, None)

    with app_client(settings, db) as (app, client):
        unknown = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.test", "password": PASSWORD},
        )
        wrong = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.test", "password": OTHER_PASSWORD},
        )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    assert not _calls_containing(db, "auth_sessions")


def test_login_with_a_malformed_email_is_also_invalid_credentials(tmp_path):
    settings = make_settings(tmp_path)
    db = FakeDatabase()

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/auth/login",
            json={"email": "not-an-email", "password": PASSWORD},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert db.calls == []


def test_login_requires_a_configured_database(tmp_path):
    settings = make_settings(tmp_path)

    with app_client(settings) as (app, client):
        response = client.post(
            "/api/auth/login",
            json={"email": "user@example.test", "password": PASSWORD},
        )

    assert response.status_code == 503


# ---------------------------------------------------------------------------
# Sessions: authenticate, logout, expiry
# ---------------------------------------------------------------------------


def test_authenticate_hashes_the_token_and_requires_an_unexpired_session():
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    row = run(auth.authenticate(db, "raw-session-token"))

    assert row["id"] == profile["id"]
    query, args = db.calls[0][1], db.calls[0][2]
    assert "auth_sessions" in query and "profiles p" in query
    assert "token_hash = $1" in query
    assert "expires_at > now()" in query
    assert "join session s on s.user_id = p.id" in query
    assert "password_hash" not in query
    assert args == (hash_session_token("raw-session-token"),)


def test_authenticate_returns_none_for_an_expired_or_unknown_session():
    db = FakeDatabase()
    db.queue_fetchrow(None)

    assert run(auth.authenticate(db, "expired-token")) is None


def test_authenticate_ignores_an_empty_token_without_a_query():
    db = FakeDatabase()

    assert run(auth.authenticate(db, "")) is None
    assert db.calls == []


def test_logout_revokes_the_caller_session(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    token = make_token(profile["id"])
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.post("/api/auth/logout", headers=auth_headers(token))

    assert response.status_code == 204
    delete_query, delete_args = db.calls[-1][1], db.calls[-1][2]
    assert "delete from" in delete_query and "auth_sessions" in delete_query
    assert delete_args == (hash_session_token(token),)


def test_logout_without_a_token_is_401(tmp_path):
    settings = make_settings(tmp_path)

    with app_client(settings) as (app, client):
        response = client.post("/api/auth/logout")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_token"


def test_revoke_user_sessions_can_keep_the_current_session():
    user_id = uuid4()
    db = FakeDatabase()

    run(auth.revoke_user_sessions(db, user_id, keep_token="current-token"))

    query, args = db.calls[0][1], db.calls[0][2]
    assert "where user_id = $1 and token_hash <> $2" in query
    assert args == (user_id, hash_session_token("current-token"))


# ---------------------------------------------------------------------------
# Password changes and resets
# ---------------------------------------------------------------------------


def test_change_password_hashes_the_new_password_and_revokes_other_sessions(
    tmp_path,
):
    settings = make_settings(tmp_path)
    profile = _approved(password_hash=hash_password(PASSWORD))
    token = make_token(profile["id"])
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"password_hash": hash_password(PASSWORD)})

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/auth/password",
            json={"current_password": PASSWORD, "new_password": "brand-new-password"},
            headers=auth_headers(token),
        )

    assert response.status_code == 204
    update_query, update_args = _calls_containing(db, "update")[-1][1:3]
    assert "set password_hash = $2" in update_query
    assert verify_password(update_args[1], "brand-new-password")

    delete_query, delete_args = _calls_containing(db, "delete from")[-1][1:3]
    assert "token_hash <> $2" in delete_query
    assert delete_args == (profile["id"], hash_session_token(token))


def test_change_password_with_a_wrong_current_password_is_400_not_401(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved(password_hash=hash_password(PASSWORD))
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"password_hash": hash_password(OTHER_PASSWORD)})

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/auth/password",
            json={"current_password": PASSWORD, "new_password": "brand-new-password"},
            headers=_headers(profile),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_credentials"
    assert not _calls_containing(db, "set password_hash")
    assert not _calls_containing(db, "delete from")


def test_change_password_rejects_a_weak_new_password(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/auth/password",
            json={"current_password": PASSWORD, "new_password": "short"},
            headers=_headers(profile),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "weak_password"
    assert not _calls_containing(db, "set password_hash")


def test_admin_can_reset_a_password_and_revoke_every_session(tmp_path):
    settings = make_settings(tmp_path)
    admin = _approved(app_role="admin")
    target_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(admin, {"id": target_id})

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/admin/users/{target_id}/password",
            json={"password": "reset-by-admin"},
            headers=_headers(admin),
        )

    assert response.status_code == 204
    update_query, update_args = _calls_containing(db, "set password_hash")[-1][1:3]
    assert update_args[0] == target_id
    assert verify_password(update_args[1], "reset-by-admin")

    delete_query, delete_args = _calls_containing(db, "delete from")[-1][1:3]
    assert "where user_id = $1" in delete_query
    assert "token_hash <>" not in delete_query
    assert delete_args == (target_id,)


def test_admin_reset_of_an_unknown_user_is_404(tmp_path):
    settings = make_settings(tmp_path)
    admin = _approved(app_role="admin")
    db = FakeDatabase()
    db.queue_fetchrow(admin, None)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/admin/users/{uuid4()}/password",
            json={"password": "reset-by-admin"},
            headers=_headers(admin),
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "user_not_found"
    assert not _calls_containing(db, "delete from")


def test_admin_reset_rejects_a_weak_password(tmp_path):
    settings = make_settings(tmp_path)
    admin = _approved(app_role="admin")
    db = FakeDatabase()
    db.queue_fetchrow(admin)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/admin/users/{uuid4()}/password",
            json={"password": "short"},
            headers=_headers(admin),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "weak_password"
    assert not _calls_containing(db, "set password_hash")


def test_admin_reset_requires_an_administrator(tmp_path):
    settings = make_settings(tmp_path)
    user = _approved(app_role="user")
    db = FakeDatabase()
    db.queue_fetchrow(user)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/admin/users/{uuid4()}/password",
            json={"password": "reset-by-admin"},
            headers=_headers(user),
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "admin_required"
    assert not _calls_containing(db, "set password_hash")


def test_set_password_optionally_revokes_all_sessions():
    user_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow({"id": user_id})

    updated = run(
        auth.set_password(db, user_id, "another-password", revoke_sessions=True)
    )

    assert updated is True
    update_query, update_args = _calls_containing(db, "set password_hash")[-1][1:3]
    assert verify_password(update_args[1], "another-password")
    assert _calls_containing(db, "delete from")[-1][2] == (user_id,)


# ---------------------------------------------------------------------------
# Protected routes and the approval guard
# ---------------------------------------------------------------------------


def test_me_returns_the_profile_for_a_valid_session(tmp_path):
    settings = make_settings(tmp_path)
    row = profile_row(email="alice@example.test", is_approved=True)
    db = FakeDatabase()
    db.queue_fetchrow(row)

    with app_client(settings, db) as (app, client):
        response = client.get("/api/me", headers=auth_headers(make_token(row["id"])))

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(row["id"])
    assert body["email"] == "alice@example.test"
    assert body["is_approved"] is True
    assert body["app_role"] == "user"


def test_me_allows_pending_users(tmp_path):
    settings = make_settings(tmp_path)
    row = profile_row(email="pending@example.test", is_approved=False)
    db = FakeDatabase()
    db.queue_fetchrow(row)

    with app_client(settings, db) as (app, client):
        response = client.get("/api/me", headers=auth_headers(make_token(row["id"])))

    assert response.status_code == 200
    assert response.json()["is_approved"] is False


def test_me_missing_authorization_is_401(tmp_path):
    settings = make_settings(tmp_path)

    with app_client(settings) as (app, client):
        response = client.get("/api/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_token"


def test_me_with_an_unknown_or_expired_session_is_401(tmp_path):
    settings = make_settings(tmp_path)
    db = FakeDatabase()
    db.queue_fetchrow(None)

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/me", headers=auth_headers(make_token("stale-session"))
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session"


def test_me_returns_503_when_database_is_unavailable(tmp_path):
    settings = make_settings(tmp_path)

    with app_client(settings) as (app, client):
        response = client.get(
            "/api/me", headers=auth_headers(make_token(uuid4()))
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_me_maps_database_errors_to_503(tmp_path):
    settings = make_settings(tmp_path)
    db = FakeDatabase(fail_with=ConnectionError("down"))

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/me", headers=auth_headers(make_token(uuid4()))
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_pending_user_gets_approval_required_on_protected_route(tmp_path):
    settings = make_settings(tmp_path)
    row = profile_row(is_approved=False)
    db = FakeDatabase()
    db.queue_fetchrow(row)

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/admin/users", headers=auth_headers(make_token(row["id"]))
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "approval_required"


def test_approved_non_admin_gets_admin_required(tmp_path):
    settings = make_settings(tmp_path)
    row = profile_row(is_approved=True, app_role="user")
    db = FakeDatabase()
    db.queue_fetchrow(row)

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/admin/users", headers=auth_headers(make_token(row["id"]))
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "admin_required"


# ---------------------------------------------------------------------------
# Validation policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("password", ["", "short", "x" * 7])
def test_password_policy_rejects_short_passwords(password):
    with pytest.raises(auth.WeakPasswordError) as excinfo:
        auth.validate_password(password)
    assert excinfo.value.code == "weak_password"


def test_password_policy_rejects_overlong_passwords():
    with pytest.raises(auth.InvalidPasswordError) as excinfo:
        auth.validate_password("x" * 201)
    assert excinfo.value.code == "invalid_password"


@pytest.mark.parametrize(
    "password", ["p" * 8, "p" * 200, "correct horse battery staple"]
)
def test_password_policy_accepts_valid_passwords(password):
    assert auth.validate_password(password) == password


@pytest.mark.parametrize(
    "email",
    [
        "user@example.test",
        "FIRST.LAST+tag@sub.example.co.uk",
        "a@b.co",
    ],
)
def test_email_normalization_accepts_and_lowercases(email):
    assert auth.normalize_email(f"  {email}  ") == email.lower()


@pytest.mark.parametrize(
    "email",
    ["", "   ", "not-an-email", "user@", "@example.test", "a b@example.test",
     "user@example", "x" * 250 + "@example.test"],
)
def test_email_normalization_rejects_malformed_addresses(email):
    with pytest.raises(auth.InvalidEmailError) as excinfo:
        auth.normalize_email(email)
    assert excinfo.value.code == "invalid_email"
