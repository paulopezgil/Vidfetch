"""HTTP tests for the owner-scoped tracks endpoint."""
from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.services.signing import verify_media_token
from backend.tests.v2.fakes import (
    FakeDatabase,
    app_client,
    auth_headers,
    make_settings,
    make_token,
    non_session_calls,
    profile_row,
    track_row,
)

MEDIA_SECRET = "media-secret-for-tests"


def _approved(email="alice@example.test"):
    return profile_row(email=email, is_approved=True)


def _headers(profile):
    return auth_headers(make_token(profile["id"]))


def test_list_tracks_returns_the_callers_visible_tracks(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
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
    item = body["items"][0]
    cover_url = item.pop("cover_url")
    assert cover_url.startswith(f"/api/covers/{row['id']}?token=")
    claims = verify_media_token(
        cover_url.split("token=", 1)[1], MEDIA_SECRET
    )
    assert claims.asset_id == f"cover:{row['id']}"
    assert claims.user_id == str(profile["id"])

    thumbnail_url = item.pop("thumbnail_url")
    assert thumbnail_url.startswith(
        f"/api/thumbnails/{row['asset_id']}?token="
    )
    thumbnail_claims = verify_media_token(
        thumbnail_url.split("token=", 1)[1], MEDIA_SECRET
    )
    assert thumbnail_claims.asset_id == str(row["asset_id"])
    assert thumbnail_claims.user_id == str(profile["id"])
    assert item == {
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

    count_query, count_args = db.calls[1][1], db.calls[1][2]
    assert 'from "public".user_tracks ut' in count_query
    assert "ut.deleted_at is null" in count_query
    assert "j.library_hidden = false" in count_query
    assert "a.status = 'ready'" in count_query
    assert count_args == (profile["id"], "")

    page_query, page_args = db.calls[2][1], db.calls[2][2]
    assert "order by ut.downloaded_at desc, ut.id desc" in page_query
    assert page_args == (profile["id"], "", 10, 0)


def test_list_tracks_forwards_a_trimmed_search_term(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"total": 1})
    db.queue_fetch([track_row(title="Abbey Road")])

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/tracks",
            params={"q": "  abbey road  ", "limit": 25, "offset": 50},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Abbey Road"
    assert body["items"][0]["status"] == "ready"
    assert body["limit"] == 25
    assert body["offset"] == 50

    count_query, count_args = db.calls[1][1], db.calls[1][2]
    assert "ilike '%' || $2 || '%'" in count_query
    assert count_args == (profile["id"], "abbey road")
    assert db.calls[2][2] == (profile["id"], "abbey road", 25, 50)


def test_list_tracks_whitespace_only_search_is_no_filter(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"total": 0})
    db.queue_fetch([])

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/tracks",
            params={"q": "   "},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert db.calls[1][2] == (profile["id"], "")
    assert db.calls[2][2] == (profile["id"], "", 50, 0)


def test_list_tracks_rejects_an_overlong_search_term(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/tracks",
            params={"q": "x" * 201},
            headers=_headers(profile),
        )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "invalid_request",
            "message": "Invalid request parameters.",
        }
    }
    assert len(db.calls) == 1


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


def test_list_tracks_omits_cover_url_when_no_cover_exists(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"total": 1})
    db.queue_fetch([track_row(cover_path=None)])

    with app_client(settings, db) as (app, client):
        response = client.get("/api/tracks", headers=_headers(profile))

    assert response.status_code == 200
    assert response.json()["items"][0]["cover_url"] is None
    assert response.json()["items"][0]["thumbnail_url"] is None


def test_patch_track_updates_only_the_provided_fields(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    updated = track_row(
        track_id=track_id,
        title="Clip",
        artist="New artist",
        album="Old album",
    )
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"id": track_id}, updated)

    with app_client(settings, db) as (app, client):
        response = client.patch(
            f"/api/tracks/{track_id}",
            json={"custom_artist": "  New artist  "},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["artist"] == "New artist"
    assert body["album"] == "Old album"
    assert body["title"] == "Clip"
    assert body["cover_url"] is None

    update_query, update_args = db.calls[1][1], db.calls[1][2]
    assert "set updated_at = now(), custom_artist = $3" in update_query
    assert "custom_title = " not in update_query
    assert "custom_album = " not in update_query
    assert update_args == (track_id, profile["id"], "New artist")
    assert "ut.deleted_at is null" in update_query
    assert "j.library_hidden = false" in update_query
    assert "a.status = 'ready'" in update_query

    select_query, select_args = db.calls[2][1], db.calls[2][2]
    assert "where ut.id = $1 and ut.user_id = $2" in select_query
    assert select_args == (track_id, profile["id"])


def test_patch_track_returns_a_signed_cover_url_when_a_cover_exists(
    tmp_path,
):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    updated = track_row(
        track_id=track_id,
        cover_path=f"covers/{profile['id']}/{track_id}.jpg",
    )
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"id": track_id}, updated)

    with app_client(settings, db) as (app, client):
        response = client.patch(
            f"/api/tracks/{track_id}",
            json={"custom_title": "Renamed"},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    cover_url = response.json()["cover_url"]
    assert cover_url.startswith(f"/api/covers/{track_id}?token=")
    claims = verify_media_token(cover_url.split("token=", 1)[1], MEDIA_SECRET)
    assert claims.asset_id == f"cover:{track_id}"


def test_patch_track_accepts_an_empty_string_to_clear_a_field(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    updated = track_row(track_id=track_id, album="")
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"id": track_id}, updated)

    with app_client(settings, db) as (app, client):
        response = client.patch(
            f"/api/tracks/{track_id}",
            json={"custom_album": ""},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    assert response.json()["album"] == ""
    assert db.calls[1][2] == (track_id, profile["id"], "")


def test_patch_track_returns_404_when_not_visible_or_not_owned(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile, None)

    with app_client(settings, db) as (app, client):
        response = client.patch(
            f"/api/tracks/{track_id}",
            json={"custom_title": "Nope"},
            headers=_headers(profile),
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "track_not_found"
    assert len(db.calls) == 2


def test_patch_track_rejects_invalid_metadata(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile, profile, profile)

    with app_client(settings, db) as (app, client):
        empty = client.patch(
            f"/api/tracks/{track_id}", json={}, headers=_headers(profile)
        )
        too_long = client.patch(
            f"/api/tracks/{track_id}",
            json={"custom_title": " " + ("x" * 201) + " "},
            headers=_headers(profile),
        )
        null_value = client.patch(
            f"/api/tracks/{track_id}",
            json={"custom_artist": None},
            headers=_headers(profile),
        )

    for response in (empty, too_long, null_value):
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"
    # Only authentication touched the database; no UPDATE was attempted.
    assert all(
        " set " not in call[1].lower() for call in non_session_calls(db)
    )


def test_list_artist_facets_groups_and_clamps_the_limit(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)
    db.queue_fetch(
        [
            {"name": "Björk", "track_count": 3},
            {"name": "Aphex Twin", "track_count": 1},
        ]
    )

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/tracks/artists",
            params={"q": "  bj  ", "limit": 999},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {"name": "Björk", "track_count": 3},
            {"name": "Aphex Twin", "track_count": 1},
        ]
    }
    query, args = db.calls[1][1], db.calls[1][2]
    assert "btrim(ut.custom_artist)" in query
    assert "group by btrim(ut.custom_artist)" in query
    assert args == (profile["id"], "bj", 50)


def test_list_album_facets_uses_the_album_column(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)
    db.queue_fetch([{"name": "Homogenic", "track_count": 2}])

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/tracks/albums", headers=_headers(profile)
        )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {"name": "Homogenic", "track_count": 2}
    ]
    query, args = db.calls[1][1], db.calls[1][2]
    assert "btrim(ut.custom_album)" in query
    assert "btrim(ut.custom_artist)" not in query
    assert args == (profile["id"], "", 20)


def test_patch_track_accepts_metadata_at_the_length_limit(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    value = "x" * 200
    db = FakeDatabase()
    db.queue_fetchrow(
        profile, {"id": track_id}, track_row(track_id=track_id, title=value)
    )

    with app_client(settings, db) as (app, client):
        response = client.patch(
            f"/api/tracks/{track_id}",
            json={"custom_title": f"  {value}  "},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    assert response.json()["title"] == value
    assert db.calls[1][2] == (track_id, profile["id"], value)


def test_patch_track_trims_a_whitespace_only_value_to_clear_it(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(
        profile, {"id": track_id}, track_row(track_id=track_id, album="")
    )

    with app_client(settings, db) as (app, client):
        response = client.patch(
            f"/api/tracks/{track_id}",
            json={"custom_album": "   "},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    assert response.json()["album"] == ""
    assert db.calls[1][2] == (track_id, profile["id"], "")


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
    ],
)
def test_list_tracks_rejects_out_of_range_pagination(tmp_path, params):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/tracks", params=params, headers=_headers(profile)
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert len(db.calls) == 1


def test_list_artist_facets_clamps_a_negative_limit(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)
    db.queue_fetch([])

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/tracks/artists",
            params={"limit": -5},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    assert response.json() == {"items": []}
    assert db.calls[1][2] == (profile["id"], "", 1)


def test_list_facets_db_failure_is_503(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase(fail_with=OSError("database is down"), fail_after=1)
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.get("/api/tracks/albums", headers=_headers(profile))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_patch_track_db_failure_is_503(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase(fail_with=OSError("database is down"), fail_after=1)
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.patch(
            f"/api/tracks/{uuid4()}",
            json={"custom_title": "Renamed"},
            headers=_headers(profile),
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_patch_track_requires_an_approved_user(tmp_path):
    settings = make_settings(tmp_path)
    profile = profile_row(is_approved=False)
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.patch(
            f"/api/tracks/{uuid4()}",
            json={"custom_title": "Renamed"},
            headers=_headers(profile),
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "approval_required"
    assert all(
        " set " not in call[1].lower() for call in non_session_calls(db)
    )


def test_list_facets_requires_an_approved_user(tmp_path):
    settings = make_settings(tmp_path)
    profile = profile_row(is_approved=False)
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.get("/api/tracks/artists", headers=_headers(profile))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "approval_required"
    assert len(db.calls) == 1


def test_patch_track_rejects_an_invalid_uuid(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.patch(
            "/api/tracks/not-a-uuid",
            json={"custom_title": "Renamed"},
            headers=_headers(profile),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert all(
        " set " not in call[1].lower() for call in non_session_calls(db)
    )


def test_list_tracks_forwards_the_sort_order_and_search(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"total": 1})
    db.queue_fetch([track_row(title="Abbey Road")])

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/tracks",
            params={"sort": "title", "q": "road", "limit": 2, "offset": 4},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    page_query, page_args = db.calls[2][1], db.calls[2][2]
    assert (
        "order by lower(coalesce(nullif(ut.custom_title, ''), "
        "nullif(j.title, ''), a.title, '')) asc, ut.id asc"
    ) in page_query
    assert page_args == (profile["id"], "road", 2, 4)


def test_list_tracks_defaults_to_newest_downloaded(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"total": 0})
    db.queue_fetch([])

    with app_client(settings, db) as (app, client):
        response = client.get("/api/tracks", headers=_headers(profile))

    assert response.status_code == 200
    assert "order by ut.downloaded_at desc, ut.id desc" in db.calls[2][1]


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (
            "audio",
            "= any(array['mp3', 'm4a', 'aac', 'wav', 'flac', 'ogg', 'opus'])",
        ),
        (
            "audio",
            "= any(array['audio', 'mp3']) "
            "or lower(coalesce(j.format_selector, '')) like '%bestaudio%'",
        ),
        (
            "image",
            "= any(array['jpg', 'jpeg', 'png', 'webp', 'gif', 'avif', 'bmp'])",
        ),
        (
            "video",
            "not ((regexp_replace(lower(coalesce(a.output_ext, '')), "
            "'^\\.', '') = any(array['mp3'",
        ),
    ],
)
def test_list_tracks_forwards_the_media_kind_filter(tmp_path, kind, expected):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"total": 0})
    db.queue_fetch([])

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/tracks",
            params={"kind": kind, "limit": 3, "offset": 6},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    count_query, page_query = db.calls[1][1], db.calls[2][1]
    assert expected in count_query
    assert expected in page_query
    # The kind predicate is static SQL; the positional arguments are unchanged.
    assert db.calls[1][2] == (profile["id"], "")
    assert db.calls[2][2] == (profile["id"], "", 3, 6)
    assert "limit $3 offset $4" in page_query


def test_list_tracks_rejects_an_unknown_media_kind(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/tracks", params={"kind": "music"}, headers=_headers(profile)
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    # The invalid value never reaches the tracks query.
    assert all("user_tracks" not in call[1] for call in db.calls)


def test_list_tracks_rejects_an_unknown_sort_with_the_validation_envelope(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/tracks", params={"sort": "album"}, headers=_headers(profile)
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    # The invalid value never reaches the tracks query.
    assert all("user_tracks" not in call[1] for call in db.calls)
