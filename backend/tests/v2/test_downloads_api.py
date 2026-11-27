"""HTTP tests for the v2 info/downloads router (fake DB, fake worker)."""
from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.api.routes import downloads as downloads_module
from backend.app.services import ytdlp as ytdlp_service
from backend.app.services.options import options_hash
from backend.tests.v2.fakes import (
    FakeDatabase,
    app_client,
    auth_headers,
    job_row,
    make_settings,
    make_token,
    profile_row,
)

INFO_PAYLOAD = {
    "type": "video",
    "id": "vid1",
    "title": "Clip",
    "canonical_id": "youtube:vid1",
    "extractor_key": "youtube",
    "duration": 12,
    "thumbnail": "https://img.example.test/t.jpg",
    "formats": {"heights": [720], "has_720p": True, "has_audio": True},
    "entries": None,
    "item_count": 1,
    "truncated": False,
}


class FakeWorker:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    async def request_cancel(self, job_id):
        self.cancelled.append(str(job_id))
        return True


def _approved():
    return profile_row(email="alice@example.test", is_approved=True)


def _headers(profile):
    return auth_headers(make_token(profile["id"]))


# ---------------------------------------------------------------------------
# /api/info
# ---------------------------------------------------------------------------


def test_info_returns_normalized_metadata_for_approved_user(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)
    seen: list[tuple] = []

    def fake_get_info(url, resolved_settings):
        seen.append((url, resolved_settings))
        return dict(INFO_PAYLOAD)

    monkeypatch.setattr(downloads_module.ytdlp, "get_info", fake_get_info)

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/info",
            json={"url": "https://www.youtube.com/watch?v=vid1"},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["canonical_id"] == "youtube:vid1"
    assert body["type"] == "video"
    assert body["formats"]["has_720p"] is True
    assert seen and seen[0][0] == "https://www.youtube.com/watch?v=vid1"
    assert seen[0][1] is settings


def test_info_rejects_pending_user_before_resolving(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    profile = profile_row(is_approved=False)
    db = FakeDatabase()
    db.queue_fetchrow(profile)
    calls: list = []
    monkeypatch.setattr(
        downloads_module.ytdlp,
        "get_info",
        lambda url, resolved: calls.append(url) or dict(INFO_PAYLOAD),
    )

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/info",
            json={"url": "https://example.test/v"},
            headers=_headers(profile),
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "approval_required"
    assert calls == []


def test_info_rejects_credentials_and_non_http_urls(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, profile)

    with app_client(settings, db) as (app, client):
        credentials = client.post(
            "/api/info",
            json={"url": "https://user:pass@example.test/v"},
            headers=_headers(profile),
        )
        scheme = client.post(
            "/api/info",
            json={"url": "ftp://example.test/v"},
            headers=_headers(profile),
        )

    assert credentials.status_code == 400
    assert credentials.json()["error"]["code"] == "invalid_request"
    assert scheme.status_code == 400


def test_info_maps_ytdlp_validation_errors_to_400(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    def reject(url, resolved_settings):
        raise ytdlp_service.DownloadError(
            "This URL points to a private or reserved network address and is not allowed.",
            code="invalid_url",
        )

    monkeypatch.setattr(downloads_module.ytdlp, "get_info", reject)

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/info",
            json={"url": "https://internal.example.test/v"},
            headers=_headers(profile),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_url"


# ---------------------------------------------------------------------------
# POST /api/downloads
# ---------------------------------------------------------------------------


def test_create_download_queues_job_with_hashed_options(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    inserted = job_row(user_id=profile["id"], status="queued")
    db = FakeDatabase()
    db.queue_fetchrow(profile, inserted)

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/downloads",
            json={"url": "https://example.test/v", "format": "720p"},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(inserted["id"])
    assert body["status"] == "queued"
    assert body["cancel_requested"] is False
    assert body["item_index"] == 0

    insert_args = db.calls[1][2]
    assert insert_args[0] == profile["id"]
    assert insert_args[1] == "video"
    assert insert_args[4] == options_hash("720p", False, {"kind": "video"})
    assert insert_args[5] == "720p"


@pytest.mark.parametrize(
    "fmt",
    [
        "best",
        "2160p",
        "1440p",
        "1080p",
        "720p",
        "540p",
        "480p",
        "360p",
        "240p",
        "144p",
        "audio",
        "mp3",
    ],
)
def test_create_download_accepts_every_format_profile(tmp_path, fmt):
    settings = make_settings(tmp_path)
    profile = _approved()
    inserted = job_row(user_id=profile["id"], status="queued")
    db = FakeDatabase()
    db.queue_fetchrow(profile, inserted)

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/downloads",
            json={"url": "https://example.test/v", "format": fmt},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    assert response.json()["id"] == str(inserted["id"])
    insert_args = db.calls[1][2]
    assert insert_args[4] == options_hash(fmt, False, {"kind": "video"})
    assert insert_args[5] == fmt


def test_create_download_rejects_unknown_format(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/downloads",
            json={"url": "https://example.test/v", "format": "4k"},
            headers=_headers(profile),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    # Only the profile lookup ran; nothing was queued.
    assert len(db.calls) == 1


def test_create_download_is_idempotent_on_header_key(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    existing = job_row(
        user_id=profile["id"], status="ready", idempotency_key="key-1"
    )
    db = FakeDatabase()
    db.queue_fetchrow(profile, existing)

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/downloads",
            json={"url": "https://example.test/v"},
            headers={**_headers(profile), "Idempotency-Key": "key-1"},
        )

    assert response.status_code == 200
    assert response.json()["id"] == str(existing["id"])
    # profile + idempotency lookup, and no INSERT.
    assert len(db.calls) == 2
    assert db.calls[1][2][1] == "key-1"


def test_create_playlist_download_queues_a_playlist_job(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    inserted = job_row(
        user_id=profile["id"], kind="playlist", status="queued"
    )
    db = FakeDatabase()
    db.queue_fetchrow(profile, inserted)

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/downloads",
            json={
                "url": "https://example.test/list",
                "kind": "playlist",
                "format": "720p",
            },
            headers=_headers(profile),
        )

    assert response.status_code == 200
    assert response.json()["kind"] == "playlist"

    insert_args = db.calls[1][2]
    assert insert_args[1] == "playlist"
    assert insert_args[4] == options_hash(
        "720p", False, {"kind": "playlist"}
    )
    assert insert_args[5] == "720p"


def test_create_download_rejects_playlist_id_for_every_kind(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, profile)

    with app_client(settings, db) as (app, client):
        video = client.post(
            "/api/downloads",
            json={
                "url": "https://example.test/v",
                "playlist_id": str(uuid4()),
            },
            headers=_headers(profile),
        )
        playlist = client.post(
            "/api/downloads",
            json={
                "url": "https://example.test/list",
                "kind": "playlist",
                "playlist_id": str(uuid4()),
            },
            headers=_headers(profile),
        )

    assert video.status_code == 400
    assert playlist.status_code == 400
    assert playlist.json()["error"]["code"] == "invalid_request"


def test_create_download_rejects_playlist_id_for_video(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/downloads",
            json={
                "url": "https://example.test/v",
                "playlist_id": str(uuid4()),
            },
            headers=_headers(profile),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


# ---------------------------------------------------------------------------
# listing / detail
# ---------------------------------------------------------------------------


def test_list_downloads_returns_only_caller_jobs(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    row = job_row(user_id=profile["id"], status="ready")
    db = FakeDatabase()
    db.queue_fetchrow(profile)
    db.queue_fetchrow({"total": 1})
    db.queue_fetch([row])

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/downloads?status=ready&limit=10&offset=0",
            headers=_headers(profile),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 10
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == [str(row["id"])]
    count_query = db.calls[1][1]
    assert "user_id = $1" in count_query
    assert db.calls[1][2][0] == profile["id"]
    assert db.calls[1][2][1] == "ready"


def test_list_downloads_rejects_invalid_status(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/downloads?status=exploded", headers=_headers(profile)
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_get_download_returns_own_job(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    row = job_row(user_id=profile["id"])
    db = FakeDatabase()
    db.queue_fetchrow(profile, row)

    with app_client(settings, db) as (app, client):
        response = client.get(
            f"/api/downloads/{row['id']}", headers=_headers(profile)
        )

    assert response.status_code == 200
    assert response.json()["id"] == str(row["id"])
    assert "user_id = $2" in db.calls[1][1]


def test_get_download_hides_other_users_jobs_as_404(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, None)

    with app_client(settings, db) as (app, client):
        response = client.get(
            f"/api/downloads/{uuid4()}", headers=_headers(profile)
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------


def test_cancel_active_job_delegates_to_worker(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    queued = job_row(user_id=profile["id"], status="downloading")
    cancelled = {**queued, "status": "cancelled", "cancel_requested": True}
    db = FakeDatabase()
    db.queue_fetchrow(profile, queued, cancelled)
    worker = FakeWorker()

    with app_client(settings, db) as (app, client):
        app.state.worker = worker
        response = client.post(
            f"/api/downloads/{queued['id']}/cancel", headers=_headers(profile)
        )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert worker.cancelled == [str(queued["id"])]


def test_cancel_queued_job_without_worker_marks_it_cancelled(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    queued = job_row(user_id=profile["id"], status="queued")
    cancelled = {**queued, "status": "cancelled", "cancel_requested": True}
    db = FakeDatabase()
    db.queue_fetchrow(profile, queued, cancelled, cancelled)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/downloads/{queued['id']}/cancel", headers=_headers(profile)
        )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert "cancel_requested = true" in db.calls[2][1]


def test_cancel_terminal_job_does_not_invoke_worker(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    ready = job_row(user_id=profile["id"], status="ready")
    db = FakeDatabase()
    db.queue_fetchrow(profile, ready)
    worker = FakeWorker()

    with app_client(settings, db) as (app, client):
        app.state.worker = worker
        response = client.post(
            f"/api/downloads/{ready['id']}/cancel", headers=_headers(profile)
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert worker.cancelled == []


def test_cancel_other_users_job_is_404(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, None)
    worker = FakeWorker()

    with app_client(settings, db) as (app, client):
        app.state.worker = worker
        response = client.post(
            f"/api/downloads/{uuid4()}/cancel", headers=_headers(profile)
        )

    assert response.status_code == 404
    assert worker.cancelled == []


# ---------------------------------------------------------------------------
# auth / availability
# ---------------------------------------------------------------------------


def test_downloads_require_a_token(tmp_path):
    settings = make_settings(tmp_path)

    with app_client(settings) as (app, client):
        response = client.get("/api/downloads")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_token"


def test_downloads_map_database_failure_to_503(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase(fail_with=ConnectionError("down"))

    with app_client(settings, db) as (app, client):
        response = client.get("/api/downloads", headers=_headers(profile))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
