"""HTTP tests for the owner-scoped tracks endpoint."""
from __future__ import annotations

from backend.tests.v2.fakes import (
    FakeDatabase,
    app_client,
    auth_headers,
    make_settings,
    make_token,
    profile_row,
    track_row,
)


def _approved(email="alice@example.test"):
    return profile_row(email=email, is_approved=True)


def _headers(profile):
    return auth_headers(make_token(profile["id"]))


def test_list_tracks_returns_the_callers_visible_tracks(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    row = track_row(
        title="Custom title",
        artist="An artist",
        album="An album",
        cover_path="covers/track.jpg",
        thumbnail_path="thumbs/track.jpg",
        duration_seconds=123,
        file_size_bytes=4567,
        output_ext="mp3",
        format_selector="mp3",
    )
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"total": 1})
    db.queue_fetch([row])

    with app_client(settings, db) as (app, client):
        response = client.get("/api/tracks?limit=10&offset=0", headers=_headers(profile))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 10
    assert body["offset"] == 0
    assert body["items"] == [
        {
            "id": str(row["id"]),
            "asset_id": str(row["asset_id"]),
            "job_id": str(row["job_id"]),
            "canonical_id": "youtube:vid1",
            "title": "Custom title",
            "artist": "An artist",
            "album": "An album",
            "cover_path": "covers/track.jpg",
            "thumbnail_path": "thumbs/track.jpg",
            "duration_seconds": 123,
            "file_size_bytes": 4567,
            "output_ext": "mp3",
            "format_selector": "mp3",
            "playlist_id": None,
            "status": "ready",
            "downloaded_at": "2026-11-21T12:00:00Z",
            "updated_at": "2026-11-21T12:00:00Z",
        }
    ]

    count_query, count_args = db.calls[1][1], db.calls[1][2]
    assert 'from "public".user_tracks ut' in count_query
    assert "ut.deleted_at is null" in count_query
    assert "j.library_hidden = false" in count_query
    assert "a.status = 'ready'" in count_query
    assert count_args == (profile["id"],)

    page_query, page_args = db.calls[2][1], db.calls[2][2]
    assert "order by ut.downloaded_at desc, ut.id desc" in page_query
    assert page_args == (profile["id"], 10, 0)


def test_list_tracks_requires_an_approved_user(tmp_path):
    settings = make_settings(tmp_path)
    profile = profile_row(is_approved=False)
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.get("/api/tracks", headers=_headers(profile))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "approval_required"
    assert len(db.calls) == 1


def test_list_tracks_db_failure_is_503(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase(fail_with=OSError("database is down"), fail_after=1)
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.get("/api/tracks", headers=_headers(profile))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
