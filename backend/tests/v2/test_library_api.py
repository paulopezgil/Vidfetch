"""HTTP tests for the owner-scoped library and history endpoints."""
from __future__ import annotations

from uuid import uuid4

from backend.tests.v2.fakes import (
    FakeDatabase,
    app_client,
    auth_headers,
    job_row,
    library_row,
    make_settings,
    make_token,
    profile_row,
)


def _approved(email="alice@example.test"):
    return profile_row(email=email, is_approved=True)


def _headers(profile):
    return auth_headers(make_token(profile["id"]))


def test_list_library_returns_the_callers_visible_items(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    row = library_row(title="Ready clip", file_size_bytes=2048)
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"total": 1})
    db.queue_fetch([row])

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/library?limit=10&offset=0", headers=_headers(profile)
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 10
    assert body["offset"] == 0
    assert body["items"] == [
        {
            "job_id": str(row["job_id"]),
            "asset_id": str(row["asset_id"]),
            "title": "Ready clip",
            "file_size_bytes": 2048,
            "output_ext": "mp4",
            "thumbnail_path": None,
            "created_at": "2026-11-21T12:00:00Z",
            "status": "ready",
            "format_selector": "best",
            "playlist_id": None,
        }
    ]

    count_query, count_args = db.calls[1][1], db.calls[1][2]
    assert "j.library_hidden = false" in count_query
    assert "a.status = 'ready'" in count_query
    assert count_args == (profile["id"],)

    page_query, page_args = db.calls[2][1], db.calls[2][2]
    assert 'join "public".media_assets a on j.asset_id = a.id' in page_query
    assert "order by j.created_at desc, j.id desc" in page_query
    assert page_args == (profile["id"], 10, 0)


def test_delete_library_item_hides_a_ready_owned_job(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    job_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"id": job_id})

    with app_client(settings, db) as (app, client):
        response = client.delete(
            f"/api/library/{job_id}", headers=_headers(profile)
        )

    assert response.status_code == 204
    assert response.content == b""
    query, args = db.calls[1][1], db.calls[1][2]
    assert 'update "public".download_jobs' in query
    assert "set library_hidden = true" in query
    assert "delete from" not in query.lower()
    assert args == (job_id, profile["id"])


def test_delete_library_item_reports_404_for_another_users_job(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    job_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile, None)

    with app_client(settings, db) as (app, client):
        response = client.delete(
            f"/api/library/{job_id}", headers=_headers(profile)
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"
    assert "user_id = $2" in db.calls[1][1]
    assert db.calls[1][2] == (job_id, profile["id"])


def test_delete_library_item_with_invalid_uuid_is_400(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.delete(
            "/api/library/not-a-uuid", headers=_headers(profile)
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_library_requires_an_approved_user(tmp_path):
    settings = make_settings(tmp_path)
    profile = profile_row(is_approved=False)
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.get("/api/library", headers=_headers(profile))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "approval_required"


def test_library_db_failure_is_503(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase(fail_with=OSError("database is down"), fail_after=1)
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.get("/api/library", headers=_headers(profile))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_history_returns_jobs_including_hidden_library_entries(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    row = job_row(
        user_id=profile["id"],
        status="ready",
        title="Still in history",
        library_hidden=True,
    )
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"total": 1})
    db.queue_fetch([row])

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/history?status=ready&limit=25&offset=5",
            headers=_headers(profile),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [str(row["id"])]
    assert body["items"][0]["title"] == "Still in history"

    page_query, page_args = db.calls[2][1], db.calls[2][2]
    assert 'from "public".download_jobs' in page_query
    assert "library_hidden" not in page_query
    assert "status = $2" in page_query
    assert page_args == (profile["id"], "ready", 25, 5)


def test_history_rejects_unknown_status(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/history?status=exploded", headers=_headers(profile)
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
