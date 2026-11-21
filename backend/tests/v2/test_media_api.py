"""HTTP tests for signed media token issuance and streaming."""
from __future__ import annotations

import time
from uuid import uuid4

from backend.app.services.signing import sign_media_token
from backend.app.services.storage import Storage
from backend.tests.v2.fakes import (
    FakeDatabase,
    app_client,
    asset_row,
    auth_headers,
    make_settings,
    make_token,
    profile_row,
)

MEDIA_SECRET = "media-secret-for-tests"


def _approved():
    return profile_row(email="alice@example.test", is_approved=True)


def _headers(profile):
    return auth_headers(make_token(profile["id"]))


def _seed_asset(
    settings,
    *,
    asset_id=None,
    body: bytes = b"media-bytes",
    thumbnail: bytes | None = b"thumbnail-bytes",
):
    storage = Storage(settings.download_dir)
    storage.ensure_directories()
    identifier = asset_id or uuid4()
    media_dir = storage.root / "assets" / str(identifier)
    media_dir.mkdir(parents=True, exist_ok=True)
    media_file = media_dir / "clip.mp4"
    media_file.write_bytes(body)

    thumbnail_rel = None
    if thumbnail is not None:
        thumb_dir = storage.root / "thumbnails"
        thumb_dir.mkdir(parents=True, exist_ok=True)
        (thumb_dir / f"{identifier}.jpg").write_bytes(thumbnail)
        thumbnail_rel = f"thumbnails/{identifier}.jpg"

    return asset_row(
        asset_id=identifier,
        status="ready",
        file_path=f"assets/{identifier}/clip.mp4",
        file_size_bytes=len(body),
        output_ext="mp4",
        thumbnail_path=thumbnail_rel,
    )


def _token(settings, asset_id, user_id, *, ttl=300, now=None):
    return sign_media_token(
        MEDIA_SECRET,
        str(asset_id),
        str(user_id),
        ttl,
        now=now,
    )


def test_token_issuance_returns_media_and_thumbnail_urls(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    asset = _seed_asset(settings)
    db = FakeDatabase()
    db.queue_fetchrow(profile, asset)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/media/{asset['id']}/token",
            headers=_headers(profile),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["token"]
    assert body["expires_in"] == settings.media_token_ttl_seconds
    assert body["url"] == f"/api/media/{asset['id']}?token={body['token']}"
    assert body["thumbnail_url"] == (
        f"/api/thumbnails/{asset['id']}?token={body['token']}"
    )
    assert body["expires_at"]


def test_token_issuance_omits_thumbnail_when_missing(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    asset = _seed_asset(settings, thumbnail=None)
    db = FakeDatabase()
    db.queue_fetchrow(profile, asset)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/media/{asset['id']}/token",
            headers=_headers(profile),
        )

    assert response.status_code == 200
    assert response.json()["thumbnail_url"] is None


def test_token_issuance_requires_ready_asset(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    asset = _seed_asset(settings)
    asset["status"] = "processing"
    db = FakeDatabase()
    db.queue_fetchrow(profile, asset)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/media/{asset['id']}/token",
            headers=_headers(profile),
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "asset_unavailable"


def test_stream_media_serves_inline_and_attachment_dispositions(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    asset = _seed_asset(settings)
    token = _token(settings, asset["id"], profile["id"])
    db = FakeDatabase()
    db.queue_fetchrow(profile, asset, profile, asset)

    with app_client(settings, db) as (app, client):
        inline = client.get(f"/api/media/{asset['id']}?token={token}")
        attachment = client.get(
            f"/api/media/{asset['id']}?token={token}&download=1"
        )

    assert inline.status_code == 200
    assert inline.content == b"media-bytes"
    assert inline.headers["content-disposition"].startswith("inline")
    assert inline.headers["cache-control"] == "private, no-store"

    assert attachment.status_code == 200
    assert attachment.content == b"media-bytes"
    assert attachment.headers["content-disposition"].startswith("attachment")


def test_stream_media_supports_range_requests(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    asset = _seed_asset(settings, body=b"0123456789")
    token = _token(settings, asset["id"], profile["id"])
    db = FakeDatabase()
    db.queue_fetchrow(profile, asset)

    with app_client(settings, db) as (app, client):
        response = client.get(
            f"/api/media/{asset['id']}?token={token}",
            headers={"Range": "bytes=0-3"},
        )

    assert response.status_code == 206
    assert response.content == b"0123"
    assert response.headers["content-range"] == "bytes 0-3/10"


def test_expired_token_is_rejected_before_database_access(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    asset = _seed_asset(settings)
    token = _token(
        settings,
        asset["id"],
        profile["id"],
        ttl=5,
        now=int(time.time()) - 100,
    )
    db = FakeDatabase()

    with app_client(settings, db) as (app, client):
        response = client.get(f"/api/media/{asset['id']}?token={token}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "expired_token"
    assert db.calls == []


def test_token_for_another_asset_is_rejected(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    asset = _seed_asset(settings)
    other_asset = _seed_asset(settings)
    token = _token(settings, other_asset["id"], profile["id"])
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.get(f"/api/media/{asset['id']}?token={token}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"
    assert len(db.calls) == 1


def test_token_user_must_still_be_approved(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = profile_row(is_approved=False)
    asset = _seed_asset(settings)
    token = _token(settings, asset["id"], profile["id"])
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.get(f"/api/media/{asset['id']}?token={token}")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "approval_required"


def test_missing_or_unready_asset_is_404_or_409(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    asset = _seed_asset(settings)
    token = _token(settings, asset["id"], profile["id"])
    db = FakeDatabase()
    db.queue_fetchrow(profile, None)

    with app_client(settings, db) as (app, client):
        missing = client.get(f"/api/media/{asset['id']}?token={token}")

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "asset_not_found"


def test_path_traversal_in_asset_row_is_never_served(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    asset = _seed_asset(settings)
    asset["file_path"] = "../outside.mp4"
    token = _token(settings, asset["id"], profile["id"])
    db = FakeDatabase()
    db.queue_fetchrow(profile, asset)

    with app_client(settings, db) as (app, client):
        response = client.get(f"/api/media/{asset['id']}?token={token}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "asset_unavailable"


def test_thumbnail_streaming_and_missing_thumbnail(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    asset = _seed_asset(settings)
    token = _token(settings, asset["id"], profile["id"])
    db = FakeDatabase()
    db.queue_fetchrow(profile, asset, profile, {**asset, "thumbnail_path": None})

    with app_client(settings, db) as (app, client):
        served = client.get(
            f"/api/thumbnails/{asset['id']}?token={token}"
        )
        missing = client.get(
            f"/api/thumbnails/{asset['id']}?token={token}"
        )

    assert served.status_code == 200
    assert served.content == b"thumbnail-bytes"
    assert served.headers["content-disposition"].startswith("inline")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "thumbnail_not_found"


def test_media_endpoint_does_not_require_a_bearer_header(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    asset = _seed_asset(settings)
    token = _token(settings, asset["id"], profile["id"])
    db = FakeDatabase()
    db.queue_fetchrow(profile, asset)

    with app_client(settings, db) as (app, client):
        response = client.get(f"/api/media/{asset['id']}?token={token}")

    assert response.status_code == 200
    assert response.content == b"media-bytes"
