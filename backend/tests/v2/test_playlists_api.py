"""HTTP tests for owner-scoped playlist endpoints and on-demand ZIPs."""
from __future__ import annotations

import io
import zipfile
from uuid import uuid4

from backend.app.api.routes.playlists import _item_out
from backend.app.services.signing import verify_media_token
from backend.app.services.storage import Storage
from backend.tests.v2.fakes import (
    FakeDatabase,
    app_client,
    asset_row,
    auth_headers,
    make_settings,
    make_token,
    playlist_item_row,
    playlist_row,
    profile_row,
)

MEDIA_SECRET = "test-media-secret-playlists"


def _approved():
    return profile_row(email="alice@example.test", is_approved=True)


def _headers(profile):
    return auth_headers(make_token(profile["id"]))


def _seed_file(settings, asset_id, name, body):
    storage = Storage(settings.download_dir)
    storage.ensure_directories()
    directory = storage.root / "assets" / str(asset_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(body)
    return f"assets/{asset_id}/{name}"


def test_list_playlists_returns_the_callers_page(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    row = playlist_row(user_id=profile["id"], item_count=3)
    db = FakeDatabase()
    db.queue_fetchrow(profile)
    db.queue_fetchrow({"total": 1})
    db.queue_fetch([row])

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/playlists?limit=10&offset=0", headers=_headers(profile)
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 10
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == [str(row["id"])]
    assert body["items"][0]["item_count"] == 3
    assert db.calls[1][2] == (profile["id"],)


def test_get_playlist_returns_items_in_position_order(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist = playlist_row(user_id=profile["id"])
    first = playlist_item_row(
        playlist_id=playlist["id"], position=1, title="One"
    )
    second = playlist_item_row(
        playlist_id=playlist["id"],
        position=2,
        title="Two",
        status="ready",
        asset_id=uuid4(),
    )
    db = FakeDatabase()
    db.queue_fetchrow(profile, playlist)
    db.queue_fetch([first, second])

    with app_client(settings, db) as (app, client):
        response = client.get(
            f"/api/playlists/{playlist['id']}", headers=_headers(profile)
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(playlist["id"])
    assert [item["position"] for item in body["items"]] == [1, 2]
    assert body["items"][1]["status"] == "ready"
    assert body["items"][1]["asset_id"] == str(second["asset_id"])
    assert "user_id = $2" in db.calls[1][1]


def test_get_playlist_signs_item_thumbnail_urls(tmp_path):
    settings = make_settings(
        tmp_path,
        MEDIA_TOKEN_SECRET=MEDIA_SECRET,
        PUBLIC_API_URL="https://api.example.test",
    )
    profile = _approved()
    playlist = playlist_row(user_id=profile["id"])
    asset_id = uuid4()
    with_thumbnail = playlist_item_row(
        playlist_id=playlist["id"],
        position=1,
        status="ready",
        asset_id=asset_id,
        asset_thumbnail_path=f"assets/{asset_id}/thumb.jpg",
    )
    without_thumbnail = playlist_item_row(
        playlist_id=playlist["id"],
        position=2,
        status="ready",
        asset_id=uuid4(),
        asset_thumbnail_path=None,
    )
    without_asset = playlist_item_row(
        playlist_id=playlist["id"],
        position=3,
        status="pending",
        asset_thumbnail_path=None,
    )
    db = FakeDatabase()
    db.queue_fetchrow(profile, playlist)
    db.queue_fetch([with_thumbnail, without_thumbnail, without_asset])

    with app_client(settings, db) as (app, client):
        response = client.get(
            f"/api/playlists/{playlist['id']}", headers=_headers(profile)
        )

    assert response.status_code == 200
    items = response.json()["items"]
    signed = items[0]["thumbnail_url"]
    assert signed.startswith(
        f"https://api.example.test/api/thumbnails/{asset_id}?token="
    )
    claims = verify_media_token(signed.split("token=", 1)[1], MEDIA_SECRET)
    assert claims.asset_id == str(asset_id)
    assert claims.user_id == str(profile["id"])
    assert items[1]["thumbnail_url"] is None
    assert items[2]["thumbnail_url"] is None
    # The storage-relative path is internal and must never leak.
    assert all("asset_thumbnail_path" not in item for item in items)
    assert "asset_thumbnail_path" not in _item_out(
        settings, profile["id"], dict(with_thumbnail)
    )

    query = db.calls[2][1]
    assert "left join" in query
    assert "a.thumbnail_path as asset_thumbnail_path" in query
    assert "order by pi.position asc, pi.id asc" in query


def test_get_playlist_hides_another_users_playlist(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, None)

    with app_client(settings, db) as (app, client):
        response = client.get(
            f"/api/playlists/{uuid4()}", headers=_headers(profile)
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "playlist_not_found"


def test_delete_playlist_reports_404_when_not_owned(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile, None)

    with app_client(settings, db) as (app, client):
        response = client.delete(
            f"/api/playlists/{playlist_id}", headers=_headers(profile)
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "playlist_not_found"
    assert "user_id = $2" in db.calls[1][1]
    assert db.calls[1][2] == (playlist_id, profile["id"])


def test_delete_playlist_removes_rows_only(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist = playlist_row(user_id=profile["id"])
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"id": playlist["id"]})

    with app_client(settings, db) as (app, client):
        response = client.delete(
            f"/api/playlists/{playlist['id']}", headers=_headers(profile)
        )

    assert response.status_code == 204
    assert response.content == b""
    assert 'delete from "public".playlists' in db.calls[1][1]


def test_playlist_zip_contains_ready_files_and_is_deleted_after_streaming(
    tmp_path,
):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist = playlist_row(user_id=profile["id"], title="Holiday")
    first_asset = uuid4()
    second_asset = uuid4()
    first_path = _seed_file(settings, first_asset, "one.mp4", b"one-bytes")
    missing_path = f"assets/{second_asset}/two.mp4"
    items = [
        playlist_item_row(
            playlist_id=playlist["id"],
            position=1,
            title="One",
            status="ready",
            asset_id=first_asset,
        ),
        playlist_item_row(
            playlist_id=playlist["id"],
            position=2,
            title="Two",
            status="ready",
            asset_id=second_asset,
        ),
    ]
    db = FakeDatabase()
    db.queue_fetchrow(profile, playlist)
    db.queue_fetch([items[0], items[1]])
    db.queue_fetchrow(
        asset_row(
            asset_id=first_asset,
            status="ready",
            file_path=first_path,
            file_size_bytes=9,
        )
    )
    db.queue_fetchrow(
        asset_row(
            asset_id=second_asset,
            status="ready",
            file_path=missing_path,
            file_size_bytes=9,
        )
    )

    with app_client(settings, db) as (app, client):
        response = client.get(
            f"/api/playlists/{playlist['id']}/zip",
            headers=_headers(profile),
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "Holiday.zip" in response.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert names == ["001 - One.mp4"]
        assert archive.read(names[0]) == b"one-bytes"

    assert list((Storage(settings.download_dir).root / ".tmp").glob("*.zip")) == []


def test_playlist_zip_404_when_no_files_exist(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist = playlist_row(user_id=profile["id"])
    asset_id = uuid4()
    item = playlist_item_row(
        playlist_id=playlist["id"],
        position=1,
        status="ready",
        asset_id=asset_id,
    )
    db = FakeDatabase()
    db.queue_fetchrow(profile, playlist)
    db.queue_fetch([item])
    db.queue_fetchrow(
        asset_row(
            asset_id=asset_id,
            status="ready",
            file_path=f"assets/{asset_id}/gone.mp4",
            file_size_bytes=3,
        )
    )

    with app_client(settings, db) as (app, client):
        response = client.get(
            f"/api/playlists/{playlist['id']}/zip",
            headers=_headers(profile),
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "playlist_empty"
    assert list((Storage(settings.download_dir).root / ".tmp").glob("*.zip")) == []


def test_playlist_zip_hides_another_users_playlist(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, None)

    with app_client(settings, db) as (app, client):
        response = client.get(
            f"/api/playlists/{uuid4()}/zip", headers=_headers(profile)
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "playlist_not_found"
    assert db.calls[1][2] == (db.calls[1][2][0], profile["id"])


def test_playlists_require_an_approved_user(tmp_path):
    settings = make_settings(tmp_path)
    profile = profile_row(is_approved=False)
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.get("/api/playlists", headers=_headers(profile))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "approval_required"
