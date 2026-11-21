"""HTTP tests for admin job/asset inventory and asset deletion."""
from __future__ import annotations

from uuid import uuid4

from backend.app.services.storage import Storage
from backend.tests.v2.fakes import (
    FakeDatabase,
    app_client,
    asset_row,
    auth_headers,
    job_row,
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


def _headers(profile):
    return auth_headers(make_token(profile["id"]))


def _seed_asset_file(settings, asset_id):
    storage = Storage(settings.download_dir)
    storage.ensure_directories()
    path = storage.root / "assets" / str(asset_id) / "clip.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"clip-bytes")
    return storage, f"assets/{asset_id}/clip.mp4", path


def test_admin_jobs_returns_all_users_with_email_and_clamped_filters(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    owner = uuid4()
    row = {
        **job_row(user_id=owner, status="ready", title="Owner clip"),
        "user_email": "owner@example.test",
    }
    db = FakeDatabase()
    db.queue_fetchrow(admin, {"total": 1})
    db.queue_fetch([row])

    with app_client(settings, db) as (app, client):
        response = client.get(
            f"/api/admin/jobs?user_id={owner}&status=ready&search=OWNER"
            "&limit=999&offset=-3",
            headers=_headers(admin),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 200
    assert body["offset"] == 0
    assert body["items"][0]["user_email"] == "owner@example.test"
    assert body["items"][0]["id"] == str(row["id"])

    count_query, count_args = db.calls[1][1], db.calls[1][2]
    assert "join public.profiles p on p.id = j.user_id" in count_query
    assert count_args == (owner, "ready", "owner", "owner")
    page_query, page_args = db.calls[2][1], db.calls[2][2]
    assert "coalesce(p.email, '') as user_email" in page_query
    assert page_args == (owner, "ready", "owner", "owner", 200, 0)


def test_admin_jobs_requires_an_admin(tmp_path):
    settings = make_settings(tmp_path)
    user = profile_row(is_approved=True, app_role="user")
    db = FakeDatabase()
    db.queue_fetchrow(user)

    with app_client(settings, db) as (app, client):
        response = client.get("/api/admin/jobs", headers=_headers(user))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "admin_required"


def test_admin_jobs_rejects_unknown_status(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    db = FakeDatabase()
    db.queue_fetchrow(admin)

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/admin/jobs?status=exploded", headers=_headers(admin)
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_admin_jobs_db_failure_is_503(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    db = FakeDatabase(fail_with=OSError("database is down"), fail_after=1)
    db.queue_fetchrow(admin)

    with app_client(settings, db) as (app, client):
        response = client.get("/api/admin/jobs", headers=_headers(admin))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_admin_assets_returns_usage_counts_and_free_disk(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    asset_id = uuid4()
    row = {
        **asset_row(
            asset_id=asset_id,
            status="ready",
            file_path=f"assets/{asset_id}/clip.mp4",
        ),
        "job_count": 5,
        "user_count": 3,
    }
    db = FakeDatabase()
    db.queue_fetchrow(admin, {"total": 1})
    db.queue_fetch([row])

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/admin/assets?status=ready&search=clip&limit=5&offset=0",
            headers=_headers(admin),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 5
    assert body["offset"] == 0
    assert body["disk_free_bytes"] > 0
    assert body["items"][0]["job_count"] == 5
    assert body["items"][0]["user_count"] == 3
    assert body["items"][0]["id"] == str(asset_id)

    count_query, count_args = db.calls[1][1], db.calls[1][2]
    assert "a.status = $1" in count_query
    assert count_args == ("ready", "clip", "clip")


def test_admin_assets_requires_an_admin(tmp_path):
    settings = make_settings(tmp_path)
    user = profile_row(is_approved=True, app_role="user")
    db = FakeDatabase()
    db.queue_fetchrow(user)

    with app_client(settings, db) as (app, client):
        response = client.get("/api/admin/assets", headers=_headers(user))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "admin_required"


def test_admin_assets_rejects_unknown_status(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    db = FakeDatabase()
    db.queue_fetchrow(admin)

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/admin/assets?status=missing", headers=_headers(admin)
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_admin_delete_asset_requires_an_admin(tmp_path):
    settings = make_settings(tmp_path)
    user = profile_row(is_approved=True, app_role="user")
    db = FakeDatabase()
    db.queue_fetchrow(user)

    with app_client(settings, db) as (app, client):
        response = client.delete(
            f"/api/admin/assets/{uuid4()}", headers=_headers(user)
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "admin_required"


def test_admin_delete_asset_removes_file_and_audits(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    asset_id = uuid4()
    storage, relative, path = _seed_asset_file(settings, asset_id)
    asset = asset_row(
        asset_id=asset_id, status="ready", file_path=relative
    )
    deleted = {**asset}
    db = FakeDatabase()
    db.queue_fetchrow(admin, asset, {"total": 0}, deleted)

    with app_client(settings, db) as (app, client):
        response = client.delete(
            f"/api/admin/assets/{asset_id}", headers=_headers(admin)
        )

    assert response.status_code == 204
    assert response.content == b""
    assert not path.exists()
    assert db.connection.commits == 1
    audit = [call for call in db.calls if call[0] == "execute"][0]
    assert audit[2][1] == "delete_asset"


def test_admin_delete_asset_conflicts_when_a_job_is_active(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    asset_id = uuid4()
    storage, relative, path = _seed_asset_file(settings, asset_id)
    asset = asset_row(
        asset_id=asset_id, status="ready", file_path=relative
    )
    db = FakeDatabase()
    db.queue_fetchrow(admin, asset, {"total": 2})

    with app_client(settings, db) as (app, client):
        response = client.delete(
            f"/api/admin/assets/{asset_id}", headers=_headers(admin)
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "asset_in_use"
    assert path.exists()
    assert db.connection.rollbacks == 1
    assert [call for call in db.calls if call[0] == "execute"] == []


def test_admin_delete_asset_missing_is_404(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    db = FakeDatabase()
    db.queue_fetchrow(admin, None)

    with app_client(settings, db) as (app, client):
        response = client.delete(
            f"/api/admin/assets/{uuid4()}", headers=_headers(admin)
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "asset_not_found"


def test_admin_delete_asset_invalid_uuid_is_400(tmp_path):
    settings = make_settings(tmp_path)
    admin = _admin()
    db = FakeDatabase()
    db.queue_fetchrow(admin)

    with app_client(settings, db) as (app, client):
        response = client.delete(
            "/api/admin/assets/not-a-uuid", headers=_headers(admin)
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
