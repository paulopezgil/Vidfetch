"""HTTP tests for the owner-scoped curated playlists API."""
from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.services.signing import verify_media_token
from backend.tests.v2.fakes import (
    NOW,
    FakeDatabase,
    app_client,
    auth_headers,
    make_settings,
    make_token,
    non_session_calls,
    profile_row,
    track_row,
    user_playlist_row,
)

MEDIA_SECRET = "media-secret-for-tests"


def _approved(email="alice@example.test"):
    return profile_row(email=email, is_approved=True)


def _headers(profile):
    return auth_headers(make_token(profile["id"]))


def test_list_user_playlists_returns_the_callers_page(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    row = user_playlist_row(
        user_id=profile["id"], name="Mix", description="chill", track_count=2
    )
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"total": 1})
    db.queue_fetch([row])

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/user-playlists?limit=10&offset=0", headers=_headers(profile)
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 10
    assert body["offset"] == 0
    assert body["items"] == [
        {
            "id": str(row["id"]),
            "user_id": str(profile["id"]),
            "name": "Mix",
            "description": "chill",
            "cover_path": None,
            "track_count": 2,
            "owner_email": "",
            "is_owner": True,
            "created_at": "2026-11-21T12:00:00Z",
            "updated_at": "2026-11-21T12:00:00Z",
        }
    ]

    assert db.calls[1][2] == (profile["id"],)
    page_query, page_args = db.calls[2][1], db.calls[2][2]
    assert 'from "public".user_playlists p' in page_query
    assert "order by p.updated_at desc, p.id desc" in page_query
    assert 'from "public".user_playlist_tracks t' in page_query
    assert 'join "public".media_assets a on a.id = ut.asset_id' in page_query
    assert "j.library_hidden = false" in page_query
    assert page_args == (profile["id"], 10, 0)


def test_list_user_playlists_requires_an_approved_user(tmp_path):
    settings = make_settings(tmp_path)
    profile = profile_row(is_approved=False)
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/user-playlists", headers=_headers(profile)
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "approval_required"
    assert len(db.calls) == 1


def test_create_user_playlist_trims_and_returns_201(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    created = user_playlist_row(
        user_id=profile["id"], name="Chill", description="late night"
    )
    db = FakeDatabase()
    db.queue_fetchrow(profile, created)

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/user-playlists",
            json={"name": "  Chill  ", "description": "  late night  "},
            headers=_headers(profile),
        )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Chill"
    assert body["description"] == "late night"
    assert body["track_count"] == 0
    assert body["user_id"] == str(profile["id"])

    query, args = db.calls[1][1], db.calls[1][2]
    assert 'insert into "public".user_playlists' in query
    assert args == (profile["id"], "Chill", "late night")


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "   "},
        {"name": "x" * 201},
        {"name": "Mix", "description": "y" * 501},
        {},
    ],
)
def test_create_user_playlist_rejects_invalid_metadata(tmp_path, payload):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/user-playlists", json=payload, headers=_headers(profile)
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert all("insert into" not in call[1] for call in db.calls)


def test_get_user_playlist_orders_items_by_position_and_visibility(tmp_path):
    settings = make_settings(tmp_path, MEDIA_TOKEN_SECRET=MEDIA_SECRET)
    profile = _approved()
    playlist = user_playlist_row(user_id=profile["id"], track_count=1)
    first = track_row(track_id=uuid4(), cover_path="covers/first.jpg")
    second = track_row(track_id=uuid4())
    hidden = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile, playlist)
    db.queue_fetch(
        [
            {"user_track_id": second["id"]},
            {"user_track_id": hidden},
            {"user_track_id": first["id"]},
        ]
    )
    # The track query returns rows in an arbitrary order.
    db.queue_fetch([first, second])

    with app_client(settings, db) as (app, client):
        response = client.get(
            f"/api/user-playlists/{playlist['id']}", headers=_headers(profile)
        )

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [
        str(second["id"]),
        str(first["id"]),
    ]
    assert body["items"][0]["cover_url"] is None
    cover_url = body["items"][1]["cover_url"]
    assert cover_url.startswith(f"/api/covers/{first['id']}?token=")
    claims = verify_media_token(cover_url.split("token=", 1)[1], MEDIA_SECRET)
    assert claims.asset_id == f"cover:{first['id']}"
    assert claims.user_id == str(profile["id"])

    membership_query, membership_args = db.calls[2][1], db.calls[2][2]
    assert (
        "order by t.position asc, t.user_track_id asc" in membership_query
    )
    assert membership_args == (playlist["id"],)
    tracks_query, tracks_args = db.calls[3][1], db.calls[3][2]
    assert "ut.id = any($2::uuid[])" in tracks_query
    assert tracks_args == (profile["id"], [second["id"], hidden, first["id"]])


def test_get_user_playlist_hides_another_users_playlist(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, None)

    with app_client(settings, db) as (app, client):
        response = client.get(
            f"/api/user-playlists/{uuid4()}", headers=_headers(profile)
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "playlist_not_found"
    query, args = db.calls[1][1], db.calls[1][2]
    assert "p.user_id = $2" in query
    assert "p.deleted_at is null" in query
    assert args[1] == profile["id"]
    assert len(db.calls) == 2


def test_patch_user_playlist_updates_only_provided_fields(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist_id = uuid4()
    updated = user_playlist_row(
        playlist_id=playlist_id,
        user_id=profile["id"],
        name="Renamed",
        description="old",
    )
    db = FakeDatabase()
    db.queue_fetchrow(profile, updated)

    with app_client(settings, db) as (app, client):
        response = client.patch(
            f"/api/user-playlists/{playlist_id}",
            json={"name": "  Renamed  "},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert response.json()["description"] == "old"

    query, args = db.calls[1][1], db.calls[1][2]
    assert "set updated_at = now(), name = $3" in query
    assert "description = " not in query
    assert "p.deleted_at is null" in query
    assert args == (playlist_id, profile["id"], "Renamed")


@pytest.mark.parametrize("payload", [{}, {"name": None}])
def test_patch_user_playlist_rejects_an_empty_body(tmp_path, payload):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.patch(
            f"/api/user-playlists/{uuid4()}",
            json=payload,
            headers=_headers(profile),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert all("update " not in call[1] for call in non_session_calls(db))


def test_patch_user_playlist_reports_404_when_not_owned(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, None)

    with app_client(settings, db) as (app, client):
        response = client.patch(
            f"/api/user-playlists/{uuid4()}",
            json={"description": "hello"},
            headers=_headers(profile),
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "playlist_not_found"


def test_delete_user_playlist_soft_deletes_it(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"id": playlist_id})

    with app_client(settings, db) as (app, client):
        response = client.delete(
            f"/api/user-playlists/{playlist_id}", headers=_headers(profile)
        )

    assert response.status_code == 204
    query, args = db.calls[1][1], db.calls[1][2]
    assert 'update "public".user_playlists set deleted_at = now()' in query
    assert "id = $1 and user_id = $2 and deleted_at is null" in query
    assert args == (playlist_id, profile["id"])


def test_delete_user_playlist_reports_404_when_not_owned(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, None)

    with app_client(settings, db) as (app, client):
        response = client.delete(
            f"/api/user-playlists/{uuid4()}", headers=_headers(profile)
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "playlist_not_found"


def test_add_playlist_track_appends_and_returns_the_detail(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist = user_playlist_row(user_id=profile["id"], track_count=1)
    track = track_row()
    db = FakeDatabase()
    db.queue_fetchrow(profile)
    db.queue_fetchrow({"id": playlist["id"]})
    db.queue_fetchrow({"id": track["id"]})
    db.queue_execute("INSERT 0 1")
    db.queue_execute("UPDATE 1")
    db.queue_fetchrow(playlist)
    db.queue_fetch([{"user_track_id": track["id"]}])
    db.queue_fetch([track])

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/user-playlists/{playlist['id']}/tracks",
            json={"track_id": str(track["id"])},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["track_count"] == 1
    assert [item["id"] for item in body["items"]] == [str(track["id"])]

    insert_query, insert_args = db.calls[3][1], db.calls[3][2]
    assert 'insert into "public".user_playlist_tracks' in insert_query
    assert "coalesce(max(t.position) + 1, 0)" in insert_query
    assert "on conflict (playlist_id, user_track_id) do nothing" in insert_query
    assert insert_args == (playlist["id"], track["id"])
    assert db.calls[4][2] == (playlist["id"], profile["id"])


def test_add_playlist_track_rejects_a_track_that_is_not_visible(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile)
    db.queue_fetchrow({"id": playlist_id})
    db.queue_fetchrow(None)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/user-playlists/{playlist_id}/tracks",
            json={"track_id": str(uuid4())},
            headers=_headers(profile),
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "track_not_found"
    assert all("insert into" not in call[1] for call in db.calls)
    assert db.connection.rollbacks == 1


def test_add_playlist_track_hides_a_foreign_playlist(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, None)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/user-playlists/{uuid4()}/tracks",
            json={"track_id": str(uuid4())},
            headers=_headers(profile),
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "playlist_not_found"


def test_remove_playlist_track_compacts_positions(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist_id = uuid4()
    track_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile)
    db.queue_fetchrow({"id": playlist_id})
    db.queue_fetchrow({"position": 1})
    db.queue_execute("DELETE 1")
    db.queue_execute("UPDATE 2")
    db.queue_execute("UPDATE 1")

    with app_client(settings, db) as (app, client):
        response = client.delete(
            f"/api/user-playlists/{playlist_id}/tracks/{track_id}",
            headers=_headers(profile),
        )

    assert response.status_code == 204
    delete_query, delete_args = db.calls[2][1], db.calls[2][2]
    assert 'delete from "public".user_playlist_tracks' in delete_query
    assert delete_args == (playlist_id, track_id)
    compact_query, compact_args = db.calls[3][1], db.calls[3][2]
    assert "set position = ranked.rn" in compact_query
    assert "row_number() over (order by s.position) - 1 as rn" in compact_query
    assert compact_args == (playlist_id,)
    assert db.connection.commits == 1


def test_remove_playlist_track_reports_404_when_not_a_member(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile)
    db.queue_fetchrow({"id": playlist_id})
    db.queue_fetchrow(None)

    with app_client(settings, db) as (app, client):
        response = client.delete(
            f"/api/user-playlists/{playlist_id}/tracks/{uuid4()}",
            headers=_headers(profile),
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "track_not_found"


def test_reorder_playlist_tracks_rewrites_and_returns_the_new_order(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist = user_playlist_row(user_id=profile["id"], track_count=2)
    first = track_row(title="One")
    second = track_row(title="Two")
    db = FakeDatabase()
    db.queue_fetchrow(profile)
    db.queue_fetchrow({"id": playlist["id"]})
    db.queue_fetch(
        [
            {"user_track_id": first["id"]},
            {"user_track_id": second["id"]},
        ]
    )
    db.queue_execute("UPDATE 1", "UPDATE 1", "UPDATE 1")
    db.queue_fetchrow(playlist)
    db.queue_fetch(
        [
            {"user_track_id": second["id"]},
            {"user_track_id": first["id"]},
        ]
    )
    db.queue_fetch([first, second])
    requested = [second["id"], first["id"]]

    with app_client(settings, db) as (app, client):
        response = client.put(
            f"/api/user-playlists/{playlist['id']}/tracks/order",
            json={"track_ids": [str(value) for value in requested]},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [
        str(second["id"]),
        str(first["id"]),
    ]

    updates = [call for call in db.calls if call[0] == "execute"]
    assert len(updates) == 3
    for position, value in enumerate(requested):
        query, args = updates[position][1], updates[position][2]
        assert (
            "set position = $3 where playlist_id = $1 and user_track_id = $2"
            in query
        )
        assert args == (playlist["id"], value, position)
    assert 'update "public".user_playlists' in updates[2][1]
    assert db.connection.transactions == 1
    assert db.connection.commits == 1


@pytest.mark.parametrize(
    "requested_factory",
    [
        lambda first, second: [first],
        lambda first, second: [first, first],
        lambda first, second: [first, second, uuid4()],
    ],
)
def test_reorder_playlist_tracks_rejects_a_non_permutation(
    tmp_path, requested_factory
):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist_id = uuid4()
    first, second = uuid4(), uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile)
    db.queue_fetchrow({"id": playlist_id})
    db.queue_fetch(
        [{"user_track_id": first}, {"user_track_id": second}]
    )
    requested = requested_factory(first, second)

    with app_client(settings, db) as (app, client):
        response = client.put(
            f"/api/user-playlists/{playlist_id}/tracks/order",
            json={"track_ids": [str(value) for value in requested]},
            headers=_headers(profile),
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert all(
        "set position" not in call[1] for call in db.calls
    )
    assert db.connection.transactions == 1
    assert db.connection.rollbacks == 1


def test_reorder_playlist_tracks_hides_a_foreign_playlist(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, None)

    with app_client(settings, db) as (app, client):
        response = client.put(
            f"/api/user-playlists/{uuid4()}/tracks/order",
            json={"track_ids": []},
            headers=_headers(profile),
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "playlist_not_found"


def test_create_user_playlist_accepts_metadata_at_the_limits(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    name = "n" * 200
    description = "d" * 500
    created = user_playlist_row(
        user_id=profile["id"], name=name, description=description
    )
    db = FakeDatabase()
    db.queue_fetchrow(profile, created)

    with app_client(settings, db) as (app, client):
        response = client.post(
            "/api/user-playlists",
            json={"name": name, "description": description},
            headers=_headers(profile),
        )

    assert response.status_code == 201
    assert response.json()["name"] == name
    assert response.json()["description"] == description
    assert db.calls[1][2] == (profile["id"], name, description)


def test_update_user_playlist_accepts_metadata_at_the_limits(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist_id = uuid4()
    name = "n" * 200
    description = "d" * 500
    updated = user_playlist_row(
        playlist_id=playlist_id,
        user_id=profile["id"],
        name=name,
        description=description,
    )
    db = FakeDatabase()
    db.queue_fetchrow(profile, updated)

    with app_client(settings, db) as (app, client):
        response = client.patch(
            f"/api/user-playlists/{playlist_id}",
            json={"name": name, "description": description},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    assert response.json()["name"] == name
    assert response.json()["description"] == description
    assert db.calls[1][2] == (playlist_id, profile["id"], name, description)


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
    ],
)
def test_list_user_playlists_rejects_out_of_range_pagination(tmp_path, params):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/user-playlists", params=params, headers=_headers(profile)
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert len(db.calls) == 1


def test_detail_track_count_matches_the_visible_items(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist = user_playlist_row(user_id=profile["id"], track_count=5)
    first, second = track_row(), track_row()
    hidden = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile, playlist)
    db.queue_fetch(
        [
            {"user_track_id": first["id"]},
            {"user_track_id": hidden},
            {"user_track_id": second["id"]},
        ]
    )
    db.queue_fetch([first, second])

    with app_client(settings, db) as (app, client):
        response = client.get(
            f"/api/user-playlists/{playlist['id']}", headers=_headers(profile)
        )

    assert response.status_code == 200
    body = response.json()
    assert body["track_count"] == 2
    assert len(body["items"]) == 2


def _playlist_request(operation: str, playlist_id):
    track_id = uuid4()
    base = f"/api/user-playlists/{playlist_id}"
    if operation == "get":
        return "GET", base, None
    if operation == "patch":
        return "PATCH", base, {"name": "Renamed"}
    if operation == "delete":
        return "DELETE", base, None
    if operation == "add":
        return "POST", f"{base}/tracks", {"track_id": str(track_id)}
    if operation == "reorder":
        return "PUT", f"{base}/tracks/order", {"track_ids": []}
    if operation == "remove":
        return "DELETE", f"{base}/tracks/{track_id}", None
    raise AssertionError(f"Unknown operation {operation}")


@pytest.mark.parametrize(
    "operation", ["get", "patch", "delete", "add", "reorder", "remove"]
)
def test_missing_soft_deleted_or_foreign_playlist_is_404(tmp_path, operation):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(profile, None)
    method, url, payload = _playlist_request(operation, playlist_id)

    with app_client(settings, db) as (app, client):
        response = client.request(
            method, url, json=payload, headers=_headers(profile)
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "playlist_not_found"
    assert len(db.calls) == 2
    assert all("deleted_at is null" in call[1] for call in db.calls[1:])
    # Every lookup/mutation is owner-scoped, never "id only then check".
    assert all("user_id = $2" in call[1] for call in db.calls[1:])


@pytest.mark.parametrize(
    "operation", ["get", "patch", "delete", "add", "reorder", "remove"]
)
def test_playlist_operations_require_an_approved_user(tmp_path, operation):
    settings = make_settings(tmp_path)
    profile = profile_row(is_approved=False)
    db = FakeDatabase()
    db.queue_fetchrow(profile)
    method, url, payload = _playlist_request(operation, uuid4())

    with app_client(settings, db) as (app, client):
        response = client.request(
            method, url, json=payload, headers=_headers(profile)
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "approval_required"
    assert len(db.calls) == 1


@pytest.mark.parametrize(
    "operation",
    [
        "list",
        "create",
        "get",
        "patch",
        "delete",
        "add",
        "reorder",
        "remove",
    ],
)
def test_playlist_db_failure_is_503(tmp_path, operation):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase(fail_with=OSError("database is down"), fail_after=1)
    db.queue_fetchrow(profile)
    if operation == "list":
        method, url, payload = "GET", "/api/user-playlists", None
    elif operation == "create":
        method, url, payload = (
            "POST",
            "/api/user-playlists",
            {"name": "Mix"},
        )
    else:
        method, url, payload = _playlist_request(operation, uuid4())

    with app_client(settings, db) as (app, client):
        response = client.request(
            method, url, json=payload, headers=_headers(profile)
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


@pytest.mark.parametrize(
    "operation", ["get", "patch", "delete", "add", "reorder", "remove"]
)
def test_playlist_operations_reject_invalid_uuids(tmp_path, operation):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile)
    base = "/api/user-playlists/not-a-uuid"
    if operation == "get":
        method, url, payload = "GET", base, None
    elif operation == "patch":
        method, url, payload = "PATCH", base, {"name": "Renamed"}
    elif operation == "delete":
        method, url, payload = "DELETE", base, None
    elif operation == "add":
        method, url, payload = (
            "POST",
            f"{base}/tracks",
            {"track_id": str(uuid4())},
        )
    elif operation == "reorder":
        method, url, payload = "PUT", f"{base}/tracks/order", {"track_ids": []}
    else:
        method, url, payload = (
            "DELETE",
            f"{base}/tracks/{uuid4()}",
            None,
        )

    with app_client(settings, db) as (app, client):
        response = client.request(
            method, url, json=payload, headers=_headers(profile)
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert all("user_playlists" not in call[1] for call in db.calls)


def test_add_playlist_track_twice_is_idempotent(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist = user_playlist_row(user_id=profile["id"], track_count=1)
    track = track_row()
    db = FakeDatabase()
    add_responses = (
        profile,
        {"id": playlist["id"]},
        {"id": track["id"]},
        playlist,
    )
    for _ in range(2):
        db.queue_fetchrow(*add_responses)
        db.queue_execute("INSERT 0 1", "UPDATE 1")
        db.queue_fetch([{"user_track_id": track["id"]}])
        db.queue_fetch([track])

    with app_client(settings, db) as (app, client):
        first = client.post(
            f"/api/user-playlists/{playlist['id']}/tracks",
            json={"track_id": str(track["id"])},
            headers=_headers(profile),
        )
        second = client.post(
            f"/api/user-playlists/{playlist['id']}/tracks",
            json={"track_id": str(track["id"])},
            headers=_headers(profile),
        )

    for response in (first, second):
        assert response.status_code == 200
        assert response.json()["track_count"] == 1
        assert [item["id"] for item in response.json()["items"]] == [
            str(track["id"])
        ]
    inserts = [
        call
        for call in db.calls
        if "insert into" in call[1] and "user_playlist_tracks" in call[1]
    ]
    assert len(inserts) == 2
    assert all(
        "on conflict (playlist_id, user_track_id) do nothing" in call[1]
        for call in inserts
    )


def test_reorder_empty_playlist_with_an_empty_order(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    playlist = user_playlist_row(user_id=profile["id"], track_count=0)
    db = FakeDatabase()
    db.queue_fetchrow(profile, {"id": playlist["id"]}, playlist)
    db.queue_fetch([], [])
    db.queue_execute("UPDATE 1")

    with app_client(settings, db) as (app, client):
        response = client.put(
            f"/api/user-playlists/{playlist['id']}/tracks/order",
            json={"track_ids": []},
            headers=_headers(profile),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["track_count"] == 0
    assert body["items"] == []
    assert db.connection.commits == 1
    assert all("set position" not in call[1] for call in db.calls)


def test_list_shared_playlists_is_routed_before_the_id_lookup(tmp_path):
    settings = make_settings(tmp_path)
    viewer = _approved(email="viewer@example.test")
    owner = _approved(email="owner@example.test")
    row = user_playlist_row(
        user_id=owner["id"],
        name="Owner mix",
        track_count=2,
        owner_email=owner["email"],
        is_owner=False,
    )
    db = FakeDatabase()
    db.queue_fetchrow(viewer, {"total": 1})
    db.queue_fetch([row])

    with app_client(settings, db) as (app, client):
        response = client.get(
            "/api/user-playlists/shared?limit=10&offset=5",
            headers=_headers(viewer),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 10
    assert body["offset"] == 5
    item = body["items"][0]
    assert item["name"] == "Owner mix"
    assert item["owner_email"] == owner["email"]
    assert item["is_owner"] is False
    assert item["track_count"] == 2

    total_query, total_args = db.calls[1][1], db.calls[1][2]
    assert "user_playlist_shares" in total_query
    assert "p.deleted_at is null" in total_query
    assert total_args == (viewer["id"],)
    page_query, page_args = db.calls[2][1], db.calls[2][2]
    assert "owner.email as owner_email" in page_query
    assert 'join "public".profiles owner on owner.id = p.user_id' in page_query
    assert page_args == (viewer["id"], 10, 5)


def test_share_playlist_with_email_returns_the_recipient(tmp_path):
    settings = make_settings(tmp_path)
    owner = _approved()
    friend = _approved(email="friend@example.test")
    playlist = user_playlist_row(user_id=owner["id"])
    db = FakeDatabase()
    db.queue_fetchrow(
        owner,
        playlist,
        friend,
        {"user_id": friend["id"], "created_at": NOW},
    )

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/user-playlists/{playlist['id']}/shares",
            json={"email": "  Friend@Example.Test  "},
            headers=_headers(owner),
        )

    assert response.status_code == 201
    assert response.json() == {
        "user_id": str(friend["id"]),
        "email": "friend@example.test",
        "created_at": "2026-11-21T12:00:00Z",
    }

    lookup_query, lookup_args = db.calls[2][1], db.calls[2][2]
    assert "lower(email) = lower($1)" in lookup_query
    assert lookup_args == ("friend@example.test",)
    insert_query, insert_args = db.calls[3][1], db.calls[3][2]
    assert 'insert into "public".user_playlist_shares' in insert_query
    assert "on conflict (playlist_id, user_id) do nothing" in insert_query
    assert insert_args == (playlist["id"], friend["id"])


@pytest.mark.parametrize("recipient", ["unknown@example.test", "self@example.test"])
def test_share_playlist_rejects_an_unknown_or_self_recipient(
    tmp_path, recipient
):
    settings = make_settings(tmp_path)
    owner = _approved(email="self@example.test")
    playlist = user_playlist_row(user_id=owner["id"])
    target = None
    if recipient == "self@example.test":
        target = dict(owner)
    db = FakeDatabase()
    db.queue_fetchrow(owner, playlist, target)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/user-playlists/{playlist['id']}/shares",
            json={"email": recipient},
            headers=_headers(owner),
        )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "invalid_request",
            "message": "That account cannot be added.",
        }
    }
    assert all(
        "insert into" not in call[1] for call in non_session_calls(db)
    )


def test_share_playlist_hides_a_foreign_or_missing_playlist(tmp_path):
    settings = make_settings(tmp_path)
    profile = _approved()
    db = FakeDatabase()
    db.queue_fetchrow(profile, None)

    with app_client(settings, db) as (app, client):
        response = client.post(
            f"/api/user-playlists/{uuid4()}/shares",
            json={"email": "friend@example.test"},
            headers=_headers(profile),
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "playlist_not_found"
    # The recipient lookup never runs once ownership fails.
    assert len(db.calls) == 2
    assert "user_playlists" in db.calls[1][1]
    assert "user_playlist_shares" not in db.calls[1][1]


def test_list_playlist_shares_returns_the_recipients(tmp_path):
    settings = make_settings(tmp_path)
    owner = _approved()
    friend = _approved(email="friend@example.test")
    playlist = user_playlist_row(user_id=owner["id"])
    db = FakeDatabase()
    db.queue_fetchrow(owner, playlist)
    db.queue_fetch(
        [{"user_id": friend["id"], "email": friend["email"], "created_at": NOW}]
    )

    with app_client(settings, db) as (app, client):
        response = client.get(
            f"/api/user-playlists/{playlist['id']}/shares",
            headers=_headers(owner),
        )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "user_id": str(friend["id"]),
                "email": "friend@example.test",
                "created_at": "2026-11-21T12:00:00Z",
            }
        ]
    }
    share_query, share_args = db.calls[2][1], db.calls[2][2]
    assert 'join "public".profiles p on p.id = s.user_id' in share_query
    assert share_args == (playlist["id"],)


def test_unshare_playlist_reports_a_missing_share(tmp_path):
    settings = make_settings(tmp_path)
    owner = _approved()
    playlist = user_playlist_row(user_id=owner["id"])
    friend_id = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow(owner, playlist, {"user_id": friend_id})
    db.queue_fetchrow(owner, playlist, None)

    with app_client(settings, db) as (app, client):
        removed = client.delete(
            f"/api/user-playlists/{playlist['id']}/shares/{friend_id}",
            headers=_headers(owner),
        )
        missing = client.delete(
            f"/api/user-playlists/{playlist['id']}/shares/{friend_id}",
            headers=_headers(owner),
        )

    assert removed.status_code == 204
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "share_not_found"
    delete_query, delete_args = db.calls[2][1], db.calls[2][2]
    assert 'delete from "public".user_playlist_shares' in delete_query
    assert delete_args == (playlist["id"], friend_id)
