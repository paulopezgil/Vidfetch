"""Authentication and authorization tests for ``/api/me`` and protected routes."""
from __future__ import annotations

from backend.tests.v2.fakes import (
    FakeDatabase,
    app_client,
    auth_headers,
    make_settings,
    make_token,
    profile_row,
)


def test_me_returns_profile_for_valid_token(tmp_path):
    settings = make_settings(tmp_path)
    row = profile_row(
        email="alice@example.test", is_approved=True
    )
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


def test_me_rejects_token_with_bad_signature(tmp_path):
    settings = make_settings(tmp_path)

    with app_client(settings) as (app, client):
        token = make_token("00000000-0000-0000-0000-000000000001", secret="wrong")
        response = client.get("/api/me", headers=auth_headers(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_me_rejects_expired_token(tmp_path):
    settings = make_settings(tmp_path)

    with app_client(settings) as (app, client):
        token = make_token(
            "00000000-0000-0000-0000-000000000001", expires_in=-10
        )
        response = client.get("/api/me", headers=auth_headers(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "token_expired"


def test_me_returns_401_when_profile_is_missing(tmp_path):
    settings = make_settings(tmp_path)
    db = FakeDatabase()
    db.queue_fetchrow(None)

    with app_client(settings, db) as (app, client):
        token = make_token("00000000-0000-0000-0000-000000000002")
        response = client.get("/api/me", headers=auth_headers(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "profile_missing"


def test_me_returns_503_when_database_is_unavailable(tmp_path):
    settings = make_settings(tmp_path)

    with app_client(settings) as (app, client):
        token = make_token("00000000-0000-0000-0000-000000000003")
        response = client.get("/api/me", headers=auth_headers(token))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_me_maps_database_errors_to_503(tmp_path):
    settings = make_settings(tmp_path)
    db = FakeDatabase(fail_with=ConnectionError("down"))

    with app_client(settings, db) as (app, client):
        token = make_token("00000000-0000-0000-0000-000000000004")
        response = client.get("/api/me", headers=auth_headers(token))

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
