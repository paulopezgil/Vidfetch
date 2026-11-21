"""Admin user-management endpoint tests against a canned asyncpg-like database."""
from __future__ import annotations

import json
from uuid import uuid4

from backend.tests.v2.fakes import (
    NOW,
    FakeDatabase,
    app_client,
    auth_headers,
    make_settings,
    make_token,
    profile_row,
)


def _admin(admin_id=None):
    return profile_row(
        user_id=admin_id,
        email="admin@example.test",
        is_approved=True,
        app_role="admin",
    )


def _query_calls(db: FakeDatabase, kind: str):
    return [call for call in db.calls if call[0] == kind]


def test_admin_can_list_users_with_filters_and_clamped_limit(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    target = profile_row(email="bob@example.test", is_approved=True)
    db = FakeDatabase()
    db.queue_fetchrow(admin, {"total": 1})
    db.queue_fetch([target])

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/admin/users?search=BOB&approved=true&role=user&limit=999&offset=-5",
            headers=auth_headers(make_token(admin["id"])),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 200
    assert body["offset"] == 0
    assert [item["email"] for item in body["items"]] == ["bob@example.test"]

    fetch_query, fetch_args = _query_calls(db, "fetch")[0][1:]
    assert "lower(email) like '%' || $1 || '%'" in fetch_query
    assert "limit $4 offset $5" in fetch_query
    assert fetch_args == ("bob", True, "user", 200, 0)


def test_admin_list_clamps_lower_limit(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    db = FakeDatabase()
    db.queue_fetchrow(admin, {"total": 0})
    db.queue_fetch([])

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/admin/users?limit=0",
            headers=auth_headers(make_token(admin["id"])),
        )

    assert response.status_code == 200
    assert response.json()["limit"] == 1


def test_admin_list_invalid_role_is_400(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    db = FakeDatabase()
    db.queue_fetchrow(admin)

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/admin/users?role=owner",
            headers=auth_headers(make_token(admin["id"])),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_admin_approve_records_audit_and_returns_profile(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    target = profile_row(email="new@example.test", is_approved=False)
    approved = profile_row(
        user_id=target["id"],
        email="new@example.test",
        is_approved=True,
        approved_at=NOW,
        approved_by=admin["id"],
    )
    db = FakeDatabase()
    db.queue_fetchrow(admin, approved)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/admin/users/{target['id']}/approve",
            headers=auth_headers(make_token(admin["id"])),
        )

    assert response.status_code == 200
    assert response.json()["is_approved"] is True
    assert db.connection.commits == 1
    assert db.connection.rollbacks == 0

    audit = _query_calls(db, "execute")[0]
    assert "insert into public.admin_audit_log" in audit[1]
    assert audit[2][1] == "approve_profile"
    assert audit[2][2] == target["id"]
    assert json.loads(audit[2][3]) == {"is_approved": True}


def test_admin_approve_unknown_user_is_404(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    db = FakeDatabase()
    db.queue_fetchrow(admin, None)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/admin/users/{uuid4()}/approve",
            headers=auth_headers(make_token(admin["id"])),
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "user_not_found"
    assert _query_calls(db, "execute") == []


def test_admin_revoke_succeeds_when_another_admin_remains(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    target = _admin()
    revoked = profile_row(
        user_id=target["id"],
        email="admin2@example.test",
        is_approved=False,
        app_role="admin",
    )
    db = FakeDatabase()
    db.queue_fetchrow(admin, target, revoked)
    db.queue_fetch([{"id": admin["id"]}, {"id": target["id"]}])

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/admin/users/{target['id']}/revoke",
            headers=auth_headers(make_token(admin["id"])),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["is_approved"] is False
    assert body["app_role"] == "admin"
    audit = _query_calls(db, "execute")[0]
    assert audit[2][1] == "revoke_profile"
    assert audit[2][2] == target["id"]


def test_admin_cannot_revoke_the_last_admin(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    db = FakeDatabase()
    db.queue_fetchrow(admin, admin)
    db.queue_fetch([{"id": admin["id"]}])

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/admin/users/{admin['id']}/revoke",
            headers=auth_headers(make_token(admin["id"])),
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_admin"
    assert _query_calls(db, "execute") == []


def test_admin_revoke_unknown_user_is_404(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    db = FakeDatabase()
    db.queue_fetchrow(admin, None)
    db.queue_fetch([])

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/admin/users/{uuid4()}/revoke",
            headers=auth_headers(make_token(admin["id"])),
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "user_not_found"


def test_admin_promotes_user_and_audits_role_change(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    target = profile_row(email="future-admin@example.test", is_approved=True)
    promoted = profile_row(
        user_id=target["id"],
        email="future-admin@example.test",
        is_approved=True,
        app_role="admin",
    )
    db = FakeDatabase()
    db.queue_fetchrow(admin, target, promoted)
    db.queue_fetch([{"id": admin["id"]}])

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/admin/users/{target['id']}/role",
            json={"app_role": "admin"},
            headers=auth_headers(make_token(admin["id"])),
        )

    assert response.status_code == 200
    assert response.json()["app_role"] == "admin"
    audit = _query_calls(db, "execute")[0]
    assert audit[2][1] == "set_profile_role"
    assert json.loads(audit[2][3]) == {"app_role": "admin"}


def test_admin_cannot_demote_the_last_admin(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    db = FakeDatabase()
    db.queue_fetchrow(admin, admin)
    db.queue_fetch([{"id": admin["id"]}])

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/admin/users/{admin['id']}/role",
            json={"app_role": "user"},
            headers=auth_headers(make_token(admin["id"])),
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_admin"
    assert _query_calls(db, "execute") == []


def test_admin_role_unknown_user_is_404(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    db = FakeDatabase()
    db.queue_fetchrow(admin, None)
    db.queue_fetch([{"id": admin["id"]}])

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/admin/users/{uuid4()}/role",
            json={"app_role": "user"},
            headers=auth_headers(make_token(admin["id"])),
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "user_not_found"


def test_admin_invalid_uuid_is_400(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    db = FakeDatabase()
    db.queue_fetchrow(admin)

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/admin/users/not-a-uuid/approve",
            headers=auth_headers(make_token(admin["id"])),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_admin_invalid_role_is_400(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    db = FakeDatabase()
    db.queue_fetchrow(admin)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/admin/users/{uuid4()}/role",
            json={"app_role": "superuser"},
            headers=auth_headers(make_token(admin["id"])),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
