"""Service tests for admin job/asset inventory and guarded deletion."""
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest

from backend.app.services import admin_inventory
from backend.app.services.profiles import ConflictError
from backend.app.services.storage import Storage
from backend.tests.v2.fakes import FakeDatabase, asset_row, job_row, make_settings


def run(coro):
    return asyncio.run(coro)


def _storage_files(tmp_path, asset_id):
    settings = make_settings(tmp_path)
    storage = Storage(settings.download_dir)
    storage.ensure_directories()
    media = storage.root / "assets" / str(asset_id) / "clip.mp4"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"clip-bytes")
    thumbnail = storage.root / "thumbnails" / f"{asset_id}.jpg"
    thumbnail.parent.mkdir(parents=True, exist_ok=True)
    thumbnail.write_bytes(b"thumb-bytes")
    return (
        storage,
        f"assets/{asset_id}/clip.mp4",
        f"thumbnails/{asset_id}.jpg",
    )


def test_list_jobs_joins_profiles_filters_and_paginates():
    owner = uuid4()
    row = {**job_row(user_id=owner, status="ready"), "user_email": "a@x.test"}
    db = FakeDatabase()
    db.queue_fetchrow({"total": 1})
    db.queue_fetch([row])

    page, total = run(
        admin_inventory.list_jobs(
            db,
            user_id=owner,
            status="ready",
            search="ALICE",
            limit=10_000,
            offset=-2,
        )
    )

    assert page == [row]
    assert total == 1

    count_query, count_args = db.calls[0][1], db.calls[0][2]
    assert 'from "public".download_jobs j' in count_query
    assert 'join "public".profiles p on p.id = j.user_id' in count_query
    assert "j.user_id = $1" in count_query
    assert "j.status = $2" in count_query
    assert "lower(p.email) like" in count_query
    assert "lower(j.title) like" in count_query
    assert count_args == (owner, "ready", "alice", "alice")

    page_query, page_args = db.calls[1][1], db.calls[1][2]
    assert "coalesce(p.email, '') as user_email" in page_query
    assert "order by j.created_at desc, j.id desc" in page_query
    assert "limit $5 offset $6" in page_query
    assert page_args == (
        owner,
        "ready",
        "alice",
        "alice",
        admin_inventory.MAX_PAGE_SIZE,
        0,
    )


def test_list_jobs_without_filters_lists_every_user():
    row = {**job_row(), "user_email": "b@x.test"}
    db = FakeDatabase()
    db.queue_fetchrow({"total": 1})
    db.queue_fetch([row])

    page, total = run(admin_inventory.list_jobs(db, limit=25, offset=5))

    assert page == [row]
    assert total == 1
    assert " where " not in db.calls[0][1]
    assert db.calls[0][2] == ()
    assert db.calls[1][2] == (25, 5)


def test_list_jobs_rejects_unknown_status_and_invalid_user():
    db = FakeDatabase()

    with pytest.raises(ValueError):
        run(admin_inventory.list_jobs(db, status="exploded"))
    with pytest.raises(ValueError):
        run(admin_inventory.list_jobs(db, user_id="not-a-uuid"))

    assert db.calls == []


def test_list_assets_includes_usage_counts_and_clamps():
    row = {
        **asset_row(status="ready", file_path="assets/a/clip.mp4"),
        "job_count": 4,
        "user_count": 2,
    }
    db = FakeDatabase()
    db.queue_fetchrow({"total": 1})
    db.queue_fetch([row])

    page, total = run(
        admin_inventory.list_assets(
            db, status="ready", search="CLIP", limit=9_999, offset=-1
        )
    )

    assert page == [row]
    assert total == 1

    count_query, count_args = db.calls[0][1], db.calls[0][2]
    assert 'from "public".media_assets a' in count_query
    assert "a.status = $1" in count_query
    assert "lower(a.title) like" in count_query
    assert "lower(a.canonical_id) like" in count_query
    assert count_args == ("ready", "clip", "clip")

    page_query, page_args = db.calls[1][1], db.calls[1][2]
    assert "as job_count" in page_query
    assert "count(distinct j.user_id)" in page_query
    assert "as user_count" in page_query
    assert "order by a.created_at desc, a.id desc" in page_query
    assert page_args == (
        "ready",
        "clip",
        "clip",
        admin_inventory.MAX_PAGE_SIZE,
        0,
    )


def test_list_assets_without_filters_has_no_where_filters():
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    page, total = run(admin_inventory.list_assets(db))

    assert page == []
    assert total == 0
    assert "where 1 = 1" in db.calls[0][1]
    assert " and " not in db.calls[0][1]
    assert db.calls[0][2] == ()


def test_list_assets_rejects_unknown_status():
    db = FakeDatabase()

    with pytest.raises(ValueError):
        run(admin_inventory.list_assets(db, status="missing"))

    assert db.calls == []


def test_delete_asset_refuses_while_a_non_terminal_job_uses_it(tmp_path):
    asset_id = uuid4()
    storage, media_path, _ = _storage_files(tmp_path, asset_id)
    asset = asset_row(
        asset_id=asset_id, status="ready", file_path=media_path
    )
    db = FakeDatabase()
    db.queue_fetchrow(asset, {"total": 1})

    with pytest.raises(ConflictError) as excinfo:
        run(admin_inventory.delete_asset(db, storage, asset_id, uuid4()))

    assert excinfo.value.code == "asset_in_use"
    assert db.connection.rollbacks == 1
    assert db.connection.commits == 0
    assert storage.validate_relative_path(media_path).exists()
    assert [call for call in db.calls if call[0] == "execute"] == []
    active_query = db.calls[1][1]
    for status in ("queued", "resolving", "downloading", "processing"):
        assert f"'{status}'" in active_query
    assert "ready" not in active_query


def test_delete_asset_removes_row_files_and_writes_audit(tmp_path):
    asset_id = uuid4()
    actor_id = uuid4()
    storage, media_path, thumbnail_path = _storage_files(tmp_path, asset_id)
    asset = asset_row(
        asset_id=asset_id,
        status="ready",
        file_path=media_path,
        thumbnail_path=thumbnail_path,
    )
    deleted = {**asset}
    db = FakeDatabase()
    db.queue_fetchrow(asset, {"total": 0}, deleted)

    result = run(
        admin_inventory.delete_asset(db, storage, asset_id, actor_id)
    )

    assert result == deleted
    assert db.connection.commits == 1
    assert db.connection.rollbacks == 0
    assert not storage.validate_relative_path(media_path).exists()
    assert not storage.validate_relative_path(thumbnail_path).exists()

    assert "for update" in db.calls[0][1]
    assert 'delete from "public".media_assets' in db.calls[2][1]
    assert db.calls[2][2] == (asset_id,)

    audit = db.calls[3]
    assert 'insert into "public".admin_audit_log' in audit[1]
    assert audit[2][0] == actor_id
    assert audit[2][1] == "delete_asset"
    assert json.loads(audit[2][2]) == {
        "asset_id": str(asset_id),
        "canonical_id": asset["canonical_id"],
    }


def test_delete_asset_returns_none_for_a_missing_asset(tmp_path):
    settings = make_settings(tmp_path)
    storage = Storage(settings.download_dir)
    storage.ensure_directories()
    db = FakeDatabase()
    db.queue_fetchrow(None)

    result = run(
        admin_inventory.delete_asset(db, storage, uuid4(), uuid4())
    )

    assert result is None
    assert len(db.calls) == 1
    assert [call for call in db.calls if call[0] == "execute"] == []


def test_delete_asset_ignores_unsafe_paths_without_touching_outside_files(
    tmp_path,
):
    asset_id = uuid4()
    settings = make_settings(tmp_path)
    storage = Storage(settings.download_dir)
    storage.ensure_directories()

    outside = storage.root.parent / "escape.txt"
    outside.write_text("must survive", encoding="utf-8")
    asset = asset_row(
        asset_id=asset_id, status="ready", file_path="../escape.txt"
    )
    deleted = {**asset}
    db = FakeDatabase()
    db.queue_fetchrow(asset, {"total": 0}, deleted)

    result = run(
        admin_inventory.delete_asset(db, storage, asset_id, uuid4())
    )

    assert result == deleted
    assert outside.read_text(encoding="utf-8") == "must survive"
    assert db.connection.commits == 1
