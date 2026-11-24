"""HTTP tests for per-user track cover upload, deletion, and serving."""
from __future__ import annotations

import base64
from uuid import uuid4

from backend.app.services import tracks
from backend.app.services.signing import sign_media_token, verify_media_token
from backend.app.services.storage import Storage
from backend.tests.v2.fakes import (
    FakeDatabase,
    app_client,
    auth_headers,
    make_settings,
    make_token,
    profile_row,
)

MEDIA_SECRET = "media-secret-for-tests"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"


def _approved():
    return profile_row(email="alice@example.test", is_approved=True)


def _headers(profile):
    return auth_headers(make_token(profile["id"]))


def _cover_token(settings, track_id, user_id):
    return sign_media_token(
        settings.media_token_secret,
        f"cover:{track_id}",
        str(user_id),
        settings.media_token_ttl_seconds,
    )


def _write_cover(settings, user_id, track_id, extension, payload):
    storage = Storage(settings.download_dir)
    storage.ensure_directories()
    relative = tracks.cover_relative_path(user_id, track_id, extension)
    path = storage.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return relative, path


def test_upload_cover_stores_bytes_and_returns_a_verified_url(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    payload = PNG_MAGIC + b"cover-pixels"
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"id": track_id, "cover_path": None})

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/tracks/{track_id}/cover",
            json={
                "content_type": "image/png",
                "data": base64.b64encode(payload).decode("ascii"),
            },
            headers=_headers(profile),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["cover_path"] == (
        f"covers/{profile['id']}/{track_id}.png"
    )
    assert body["cover_url"].startswith(f"/api/covers/{track_id}?token=")
    claims = verify_media_token(
        body["cover_url"].split("token=", 1)[1], MEDIA_SECRET
    )
    assert claims.asset_id == f"cover:{track_id}"
    assert claims.user_id == str(profile["id"])

    stored = settings.download_dir / body["cover_path"]
    assert stored.read_bytes() == payload

    update_query, update_args = db.calls[2][1], db.calls[2][2]
    assert "set cover_path = $3" in update_query
    assert update_args == (track_id, profile["id"], body["cover_path"])


def test_upload_cover_uses_public_api_url_for_the_signed_url(tmp_path):
    settings = make_settings(
        tmp_path,
        MEDIA_TOKEN_SECRET=MEDIA_SECRET,
        PUBLIC_API_URL="https://api.vidfetch.example",
    )
    profile = _approved()
    track_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"id": track_id, "cover_path": None})

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/tracks/{track_id}/cover",
            json={
                "content_type": "image/jpeg",
                "data": base64.b64encode(JPEG_MAGIC + b"x").decode("ascii"),
            },
            headers=_headers(profile),
        )

    assert response.status_code == 200
    assert response.json()["cover_url"].startswith(
        f"https://api.vidfetch.example/api/covers/{track_id}?token="
    )


def test_upload_cover_rejects_invalid_base64(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/tracks/{track_id}/cover",
            json={"content_type": "image/png", "data": "not base64!!"},
            headers=_headers(profile),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_cover"
    assert all(" set " not in call[1].lower() for call in db.calls)
    assert not (settings.download_dir / "covers").exists()


def test_upload_cover_rejects_magic_bytes_that_do_not_match(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/tracks/{track_id}/cover",
            json={
                "content_type": "image/png",
                "data": base64.b64encode(JPEG_MAGIC + b"jpeg").decode("ascii"),
            },
            headers=_headers(profile),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_cover"
    assert not (settings.download_dir / "covers").exists()


def test_upload_cover_rejects_payloads_over_five_mib(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    oversized = PNG_MAGIC + b"x" * tracks.MAX_COVER_BYTES
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/tracks/{track_id}/cover",
            json={
                "content_type": "image/png",
                "data": base64.b64encode(oversized).decode("ascii"),
            },
            headers=_headers(profile),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_cover"
    assert not (settings.download_dir / "covers").exists()


def test_upload_cover_returns_404_for_a_track_the_caller_cannot_see(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile, None)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/tracks/{track_id}/cover",
            json={
                "content_type": "image/webp",
                "data": base64.b64encode(
                    b"RIFF\x00\x00\x00\x00WEBPdata"
                ).decode("ascii"),
            },
            headers=_headers(profile),
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "track_not_found"
    assert not (settings.download_dir / "covers").exists()


def test_delete_cover_removes_the_file_and_returns_204(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    relative, path = _write_cover(
        settings, profile["id"], track_id, "png", PNG_MAGIC
    )
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"id": track_id, "cover_path": relative})

    with app_client(settings, db) as (app, client):
        response = client.delete(
            f"/api/tracks/{track_id}/cover", headers=_headers(profile)
        )

    assert response.status_code == 204
    assert response.content == b""
    assert not path.exists()
    update_query, update_args = db.calls[2][1], db.calls[2][2]
    assert "set cover_path = null" in update_query
    assert update_args == (track_id, profile["id"])


def test_delete_cover_returns_404_when_not_owned(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, None)

    with app_client(settings, db) as (app, client):
        response = client.delete(
            f"/api/tracks/{uuid4()}/cover", headers=_headers(profile)
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "track_not_found"


def test_cover_get_serves_the_bytes_without_a_bearer_header(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    payload = PNG_MAGIC + b"served"
    relative, _ = _write_cover(
        settings, profile["id"], track_id, "png", payload
    )
    token = _cover_token(settings, track_id, profile["id"])
    db = FakeDatabase()
    db.queue_fetchrow({"cover_path": relative})

    with app_client(settings, db) as (app, client):
        response = client.get(f"/api/covers/{track_id}?token={token}")

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, max-age=3600"
    assert db.calls[0][2] == (track_id, profile["id"])


def test_cover_get_rejects_a_token_for_a_different_subject(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    token = _cover_token(settings, uuid4(), profile["id"])
    db = FakeDatabase()

    with app_client(settings, db) as (app, client):
        response = client.get(f"/api/covers/{track_id}?token={token}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"
    assert db.calls == []


def test_cover_get_rejects_a_tampered_token(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    token = _cover_token(settings, track_id, profile["id"])
    payload, signature = token.split(".")
    tampered = f"{payload}.{'0' if signature[0] != '0' else '1'}{signature[1:]}"
    db = FakeDatabase()

    with app_client(settings, db) as (app, client):
        response = client.get(f"/api/covers/{track_id}?token={tampered}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"
    assert db.calls == []


def test_cover_get_returns_404_when_the_track_has_no_cover(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    token = _cover_token(settings, track_id, profile["id"])
    db = FakeDatabase()
    db.queue_fetchrow(None)

    with app_client(settings, db) as (app, client):
        response = client.get(f"/api/covers/{track_id}?token={token}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "cover_not_found"


def test_cover_get_is_scoped_to_the_token_user(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    _write_cover(settings, profile["id"], track_id, "png", PNG_MAGIC)
    stranger = uuid4()
    token = _cover_token(settings, track_id, stranger)
    db = FakeDatabase()
    db.queue_fetchrow(None)

    with app_client(settings, db) as (app, client):
        response = client.get(f"/api/covers/{track_id}?token={token}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "cover_not_found"
    assert db.calls[0][2] == (track_id, stranger)
    assert db.calls[0][2][1] != profile["id"]


def test_cover_get_does_not_serve_a_traversal_path(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    (settings.download_dir).mkdir(parents=True, exist_ok=True)
    (settings.download_dir / "outside.png").write_bytes(PNG_MAGIC)
    token = _cover_token(settings, track_id, profile["id"])
    db = FakeDatabase()
    db.queue_fetchrow({"cover_path": "../outside.png"})

    with app_client(settings, db) as (app, client):
        response = client.get(f"/api/covers/{track_id}?token={token}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "cover_not_found"


def test_upload_cover_rejects_blank_data(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/tracks/{track_id}/cover",
            json={"content_type": "image/png", "data": "   "},
            headers=_headers(profile),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_cover"
    assert not (settings.download_dir / "covers").exists()


def test_upload_cover_rejects_an_unsupported_content_type(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/tracks/{track_id}/cover",
            json={"content_type": "image/gif", "data": "R0lGODlh"},
            headers=_headers(profile),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert all(" set " not in call[1].lower() for call in db.calls)
    assert not (settings.download_dir / "covers").exists()


def test_cover_get_rejects_a_token_for_a_different_track(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    token = _cover_token(settings, uuid4(), profile["id"])
    db = FakeDatabase()

    with app_client(settings, db) as (app, client):
        response = client.get(f"/api/covers/{uuid4()}?token={token}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"
    assert db.calls == []


def test_cover_get_rejects_a_token_with_a_non_uuid_subject(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    track_id = uuid4()
    token = _cover_token(settings, track_id, "not-a-user-id")
    db = FakeDatabase()

    with app_client(settings, db) as (app, client):
        response = client.get(f"/api/covers/{track_id}?token={token}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"
    assert db.calls == []


def test_cover_get_does_not_serve_a_symlink_cover(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    storage = Storage(settings.download_dir)
    storage.ensure_directories()
    target = storage.root / "assets" / "shared.png"
    target.write_bytes(PNG_MAGIC + b"shared")
    relative = tracks.cover_relative_path(profile["id"], track_id, "png")
    link = storage.root / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    token = _cover_token(settings, track_id, profile["id"])
    db = FakeDatabase()
    db.queue_fetchrow({"cover_path": relative})

    with app_client(settings, db) as (app, client):
        response = client.get(f"/api/covers/{track_id}?token={token}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "cover_not_found"
    assert link.is_symlink()


def test_delete_cover_clears_the_row_when_the_file_is_missing(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    relative = tracks.cover_relative_path(profile["id"], track_id, "png")
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"id": track_id, "cover_path": relative})

    with app_client(settings, db) as (app, client):
        response = client.delete(
            f"/api/tracks/{track_id}/cover", headers=_headers(profile)
        )

    assert response.status_code == 204
    update_query, update_args = db.calls[2][1], db.calls[2][2]
    assert "set cover_path = null" in update_query
    assert update_args == (track_id, profile["id"])


def test_upload_cover_db_failure_is_503(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    db = FakeDatabase(fail_with=OSError("database is down"), fail_after=1)
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/tracks/{uuid4()}/cover",
            json={
                "content_type": "image/png",
                "data": base64.b64encode(PNG_MAGIC).decode("ascii"),
            },
            headers=_headers(profile),
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert not (settings.download_dir / "covers").exists()


def test_delete_cover_db_failure_is_503(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    db = FakeDatabase(fail_with=OSError("database is down"), fail_after=1)
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.delete(
            f"/api/tracks/{uuid4()}/cover", headers=_headers(profile)
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_cover_get_db_failure_is_503(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    track_id = uuid4()
    token = _cover_token(settings, track_id, profile["id"])
    db = FakeDatabase(fail_with=OSError("database is down"), fail_after=0)

    with app_client(settings, db) as (app, client):
        response = client.get(f"/api/covers/{track_id}?token={token}")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_upload_cover_requires_an_approved_user(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = profile_row(is_approved=False)
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/tracks/{uuid4()}/cover",
            json={
                "content_type": "image/png",
                "data": base64.b64encode(PNG_MAGIC).decode("ascii"),
            },
            headers=_headers(profile),
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "approval_required"
    assert not (settings.download_dir / "covers").exists()


def test_delete_cover_requires_an_approved_user(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = profile_row(is_approved=False)
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.delete(
            f"/api/tracks/{uuid4()}/cover", headers=_headers(profile)
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "approval_required"


def test_cover_endpoints_reject_invalid_track_ids(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, profile)

    with app_client(settings, db) as (app, client):
        upload = client.post(
            "/api/tracks/not-a-uuid/cover",
            json={
                "content_type": "image/png",
                "data": base64.b64encode(PNG_MAGIC).decode("ascii"),
            },
            headers=_headers(profile),
        )
        delete = client.delete(
            "/api/tracks/not-a-uuid/cover", headers=_headers(profile)
        )

    for response in (upload, delete):
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_request"
