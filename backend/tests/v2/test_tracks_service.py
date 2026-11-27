"""Service tests for the per-user tracks query, facets, and cover art."""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from uuid import uuid4

import pytest

from backend.app.services import tracks
from backend.app.services.storage import Storage
from backend.tests.v2.fakes import FakeDatabase, track_row

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    instance = Storage(tmp_path / "downloads")
    instance.ensure_directories()
    return instance


def run(coro):
    return asyncio.run(coro)


def test_list_tracks_scopes_visibility_and_orders_newest_downloaded_first():
    owner = uuid4()
    rows = [track_row(), track_row()]
    db = FakeDatabase()
    db.queue_fetchrow({"total": 2})
    db.queue_fetch(rows)

    page, total = run(tracks.list_tracks(db, owner, limit=10, offset=0))

    assert page == rows
    assert total == 2
    assert all(row["status"] == "ready" for row in page)

    count_query, count_args = db.calls[0][1], db.calls[0][2]
    assert 'from "public".user_tracks ut' in count_query
    assert 'join "public".media_assets a on a.id = ut.asset_id' in count_query
    assert "join lateral (" in count_query
    assert 'from "public".download_jobs j' in count_query
    assert "j.user_id = ut.user_id" in count_query
    assert "j.asset_id = ut.asset_id" in count_query
    assert "j.status = 'ready'" in count_query
    assert "j.library_hidden = false" in count_query
    assert "ut.user_id = $1" in count_query
    assert "ut.deleted_at is null" in count_query
    assert "a.status = 'ready'" in count_query
    assert count_args == (owner, "")

    page_query, page_args = db.calls[1][1], db.calls[1][2]
    assert "j.library_hidden = false" in page_query
    assert "ut.deleted_at is null" in page_query
    assert "a.status = 'ready'" in page_query
    assert "order by ut.downloaded_at desc, ut.id desc" in page_query
    assert "limit $3 offset $4" in page_query
    assert page_args == (owner, "", 10, 0)


def test_list_tracks_selects_one_representative_ready_job_per_asset():
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    run(tracks.list_tracks(db, uuid4()))

    page_query = db.calls[1][1]
    assert (
        "order by j.completed_at desc nulls last, "
        "j.created_at desc, j.id desc limit 1"
    ) in page_query
    # The lateral join must be inner: a track with no eligible job must vanish.
    assert "left join lateral" not in page_query.lower()


def test_list_tracks_builds_the_contract_columns_with_title_precedence():
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    run(tracks.list_tracks(db, uuid4()))

    page_query = db.calls[1][1]
    assert (
        "coalesce(nullif(ut.custom_title, ''), nullif(j.title, ''), "
        "a.title, '')"
    ) in page_query
    assert "ut.custom_artist as artist" in page_query
    assert "ut.custom_album as album" in page_query
    assert "ut.cover_path, a.thumbnail_path" in page_query
    assert "a.duration_seconds, a.file_size_bytes" in page_query
    assert "a.output_ext, j.format_selector, j.playlist_id" in page_query
    assert "'ready' as status" in page_query
    assert "ut.downloaded_at, ut.updated_at" in page_query


def test_list_tracks_clamps_pagination_args():
    owner = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    page, total = run(tracks.list_tracks(db, owner, limit=10_000, offset=-5))

    assert page == []
    assert total == 0
    assert db.calls[0][2] == (owner, "")
    assert db.calls[1][2] == (owner, "", tracks.MAX_PAGE_SIZE, 0)


def test_list_tracks_search_matches_the_resolved_title():
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    run(tracks.list_tracks(db, uuid4(), q="Abbey"))

    page_query = db.calls[1][1]
    assert (
        "coalesce(nullif(ut.custom_title, ''), nullif(j.title, ''), "
        "a.title, '') ilike '%' || $2 || '%'"
    ) in page_query


def test_list_tracks_search_matches_the_artist():
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    run(tracks.list_tracks(db, uuid4(), q="Abbey"))

    page_query = db.calls[1][1]
    assert "coalesce(ut.custom_artist, '') ilike '%' || $2 || '%'" in page_query


def test_list_tracks_search_matches_the_album():
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    run(tracks.list_tracks(db, uuid4(), q="Abbey"))

    page_query = db.calls[1][1]
    assert "coalesce(ut.custom_album, '') ilike '%' || $2 || '%'" in page_query


def test_list_tracks_search_clause_is_skipped_for_an_empty_term():
    owner = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    run(tracks.list_tracks(db, owner, limit=5, offset=10))

    count_query = db.calls[0][1]
    # The empty-string guard makes the three ILIKE branches inert.
    assert "$2 = ''" in count_query
    assert db.calls[0][2] == (owner, "")
    assert db.calls[1][2] == (owner, "", 5, 10)


def test_list_tracks_trims_the_search_term_argument():
    owner = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    run(tracks.list_tracks(db, owner, q="  Abbey Road  "))

    assert db.calls[0][2] == (owner, "Abbey Road")
    assert db.calls[1][2] == (owner, "Abbey Road", 50, 0)


def test_list_tracks_treats_a_whitespace_only_search_as_no_filter():
    owner = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    run(tracks.list_tracks(db, owner, q=" \t\n "))

    assert db.calls[0][2] == (owner, "")
    assert db.calls[1][2] == (owner, "", 50, 0)


def test_list_tracks_keeps_page_args_in_order_with_a_search_term():
    owner = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow({"total": 3})
    db.queue_fetch([track_row()])

    page, total = run(tracks.list_tracks(db, owner, q="jazz", limit=25, offset=50))

    assert total == 3
    assert len(page) == 1
    assert db.calls[0][2] == (owner, "jazz")
    page_query, page_args = db.calls[1][1], db.calls[1][2]
    assert page_args == (owner, "jazz", 25, 50)
    assert "limit $3 offset $4" in page_query


def test_list_tracks_maps_a_missing_count_row_to_zero():
    db = FakeDatabase()
    db.queue_fetchrow(None)
    db.queue_fetch([])

    page, total = run(tracks.list_tracks(db, uuid4()))

    assert page == []
    assert total == 0


def test_list_tracks_rejects_an_invalid_user_id_without_querying():
    db = FakeDatabase()

    with pytest.raises(ValueError):
        run(tracks.list_tracks(db, "not-a-uuid"))

    assert db.calls == []


def test_update_track_only_writes_the_provided_fields():
    owner, track_id = uuid4(), uuid4()
    row = track_row(track_id=track_id, artist="New artist")
    db = FakeDatabase()
    db.queue_fetchrow({"id": track_id})
    db.queue_fetchrow(row)

    updated = run(
        tracks.update_track(
            db, track_id, owner, {"custom_artist": "New artist"}
        )
    )

    assert updated == row
    update_query, update_args = db.calls[0][1], db.calls[0][2]
    assert "set updated_at = now(), custom_artist = $3" in update_query
    assert "custom_title" not in update_query
    assert "custom_album" not in update_query
    assert "ut.deleted_at is null" in update_query
    assert "a.status = 'ready'" in update_query
    assert "j.status = 'ready'" in update_query
    assert "j.library_hidden = false" in update_query
    assert update_args == (track_id, owner, "New artist")

    select_query, select_args = db.calls[1][1], db.calls[1][2]
    assert "order by j.completed_at desc nulls last" in select_query
    assert select_args == (track_id, owner)
    assert db.connection.transactions == 1
    assert db.connection.commits == 1


def test_update_track_returns_none_when_not_visible_and_skips_the_select():
    db = FakeDatabase()
    db.queue_fetchrow(None)

    assert run(tracks.update_track(db, uuid4(), uuid4(), {"custom_title": "x"})) is None
    assert len(db.calls) == 1
    assert "returning ut.id" in db.calls[0][1]


def test_update_track_rejects_unknown_or_empty_fields():
    db = FakeDatabase()

    with pytest.raises(ValueError):
        run(tracks.update_track(db, uuid4(), uuid4(), {}))
    with pytest.raises(ValueError):
        run(tracks.update_track(db, uuid4(), uuid4(), {"cover_path": "x"}))
    with pytest.raises(ValueError):
        run(tracks.update_track(db, uuid4(), uuid4(), {"custom_title": 1}))

    assert db.calls == []


def test_list_facets_groups_by_the_trimmed_artist_column():
    owner = uuid4()
    rows = [{"name": "Björk", "track_count": 2}]
    db = FakeDatabase()
    db.queue_fetch(rows)

    result = run(
        tracks.list_facets(db, owner, kind="artist", q="  bj  ", limit=20)
    )

    assert result == rows
    query, args = db.calls[0][1], db.calls[0][2]
    assert "btrim(ut.custom_artist) as name" in query
    assert "count(*)::int as track_count" in query
    assert "ut.deleted_at is null" in query
    assert "btrim(coalesce(ut.custom_artist, '')) <> ''" in query
    assert "btrim(ut.custom_artist) ilike '%' || $2 || '%'" in query
    assert "group by btrim(ut.custom_artist)" in query
    assert "order by count(*) desc, name asc" in query
    assert args == (owner, "bj", 20)


def test_list_facets_uses_the_album_column_and_clamps_the_limit():
    owner = uuid4()
    db = FakeDatabase()
    db.queue_fetch([])

    run(tracks.list_facets(db, owner, kind="album", limit=0))
    low_query, low_args = db.calls[0][1], db.calls[0][2]
    assert "ut.custom_album" in low_query
    assert "ut.custom_artist" not in low_query
    assert low_args == (owner, "", 1)

    db.queue_fetch([])
    run(tracks.list_facets(db, owner, kind="album", limit=500))
    assert db.calls[1][2] == (owner, "", 50)


def test_list_facets_rejects_an_unknown_kind_without_querying():
    db = FakeDatabase()

    with pytest.raises(ValueError):
        run(tracks.list_facets(db, uuid4(), kind="title"))

    assert db.calls == []


def test_cover_paths_are_storage_relative_and_typed():
    owner, track_id = uuid4(), uuid4()

    relative = tracks.cover_relative_path(owner, track_id, ".PNG")

    assert relative == f"covers/{owner}/{track_id}.png"
    assert tracks.cover_media_type(relative) == "image/png"
    with pytest.raises(ValueError):
        tracks.cover_relative_path(owner, track_id, "exe")


def test_set_cover_writes_the_decoded_bytes_and_updates_the_row(
    storage: Storage,
):
    owner, track_id = uuid4(), uuid4()
    payload = PNG_MAGIC + b"pixels"
    db = FakeDatabase()
    db.queue_fetchrow({"id": track_id, "cover_path": None})

    relative = run(
        tracks.set_cover(
            db,
            storage,
            track_id,
            owner,
            content_type="image/png",
            data=base64.b64encode(payload).decode("ascii"),
        )
    )

    assert relative == f"covers/{owner}/{track_id}.png"
    assert (storage.root / relative).read_bytes() == payload
    select_query, select_args = db.calls[0][1], db.calls[0][2]
    assert "for update" in select_query
    assert select_args == (track_id, owner)
    update_query, update_args = db.calls[1][1], db.calls[1][2]
    assert "set cover_path = $3" in update_query
    assert update_args == (track_id, owner, relative)


def test_set_cover_removes_a_stale_cover_with_another_extension(
    storage: Storage,
):
    owner, track_id = uuid4(), uuid4()
    stale = storage.root / "covers" / str(owner) / f"{track_id}.jpg"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"old")
    db = FakeDatabase()
    db.queue_fetchrow(
        {
            "id": track_id,
            "cover_path": f"covers/{owner}/{track_id}.jpg",
        }
    )

    run(
        tracks.set_cover(
            db,
            storage,
            track_id,
            owner,
            content_type="image/png",
            data=base64.b64encode(PNG_MAGIC + b"new").decode("ascii"),
        )
    )

    assert not stale.exists()
    assert (storage.root / "covers" / str(owner) / f"{track_id}.png").is_file()


def test_set_cover_rejects_bad_payloads_before_touching_storage_or_db(
    storage: Storage,
):
    owner, track_id = uuid4(), uuid4()
    db = FakeDatabase()

    with pytest.raises(tracks.CoverValidationError):
        run(
            tracks.set_cover(
                db,
                storage,
                track_id,
                owner,
                content_type="image/png",
                data=base64.b64encode(b"not a png").decode("ascii"),
            )
        )
    with pytest.raises(tracks.CoverValidationError):
        run(
            tracks.set_cover(
                db,
                storage,
                track_id,
                owner,
                content_type="image/png",
                data="not-base64!!!",
            )
        )
    assert db.calls == []
    assert not (storage.root / "covers").exists()


def test_set_cover_returns_none_for_a_track_that_is_not_visible(
    storage: Storage,
):
    db = FakeDatabase()
    db.queue_fetchrow(None)

    result = run(
        tracks.set_cover(
            db,
            storage,
            uuid4(),
            uuid4(),
            content_type="image/png",
            data=base64.b64encode(PNG_MAGIC).decode("ascii"),
        )
    )

    assert result is None
    assert len(db.calls) == 1
    assert not (storage.root / "covers").exists()


def test_delete_cover_clears_the_row_and_removes_the_file(storage: Storage):
    owner, track_id = uuid4(), uuid4()
    relative = f"covers/{owner}/{track_id}.webp"
    path = storage.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF....WEBP")
    db = FakeDatabase()
    db.queue_fetchrow({"id": track_id, "cover_path": relative})

    deleted = run(tracks.delete_cover(db, storage, track_id, owner))

    assert deleted is True
    assert not path.exists()
    update_query, update_args = db.calls[1][1], db.calls[1][2]
    assert "set cover_path = null" in update_query
    assert update_args == (track_id, owner)


def test_delete_cover_returns_false_when_not_owned(storage: Storage):
    db = FakeDatabase()
    db.queue_fetchrow(None)

    assert run(tracks.delete_cover(db, storage, uuid4(), uuid4())) is False
    assert len(db.calls) == 1


def test_resolve_cover_path_validates_storage_paths(storage: Storage):
    owner, track_id = uuid4(), uuid4()
    relative = f"covers/{owner}/{track_id}.jpg"
    path = storage.root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xd8\xffbytes")
    db = FakeDatabase()
    db.queue_fetchrow({"cover_path": relative})
    db.queue_fetchrow({"cover_path": "../escape.jpg"})
    db.queue_fetchrow({"cover_path": None})
    db.queue_fetchrow(None)
    db.queue_fetchrow({"cover_path": relative}, None)

    assert run(tracks.resolve_cover_path(db, storage, track_id, owner)) == path.resolve()
    assert run(tracks.resolve_cover_path(db, storage, track_id, owner)) is None
    assert run(tracks.resolve_cover_path(db, storage, track_id, owner)) is None
    # A missing row is "not found" too.
    assert run(tracks.resolve_cover_path(db, storage, track_id, owner)) is None
    # A row pointing at a file that no longer exists is also "not found".
    path.unlink()
    assert run(tracks.resolve_cover_path(db, storage, track_id, owner)) is None
    assert run(tracks.resolve_cover_path(db, storage, track_id, owner)) is None


def test_list_tracks_by_ids_preserves_order_and_filters_invisible_rows():
    owner = uuid4()
    first, second, third = uuid4(), uuid4(), uuid4()
    db = FakeDatabase()
    db.queue_fetch(
        [
            track_row(track_id=third),
            track_row(track_id=first),
        ]
    )

    rows = run(
        tracks.list_tracks_by_ids(
            db, owner, [first, second, third, first]
        )
    )

    assert [row["id"] for row in rows] == [first, third]
    query, args = db.calls[0][1], db.calls[0][2]
    assert 'from "public".user_tracks ut' in query
    assert 'join "public".media_assets a on a.id = ut.asset_id' in query
    assert "ut.user_id = $1" in query
    assert "ut.deleted_at is null" in query
    assert "a.status = 'ready'" in query
    assert "j.library_hidden = false" in query
    assert "ut.id = any($2::uuid[])" in query
    # Duplicate ids are collapsed before the query runs.
    assert args == (owner, [first, second, third])


def test_list_facets_clamps_a_negative_limit():
    owner = uuid4()
    db = FakeDatabase()
    db.queue_fetch([])

    run(tracks.list_facets(db, owner, kind="artist", limit=-10))

    assert db.calls[0][2] == (owner, "", 1)


def test_get_track_scopes_owner_and_visibility():
    owner, track_id = uuid4(), uuid4()
    row = track_row(track_id=track_id)
    db = FakeDatabase()
    db.queue_fetchrow(row)

    assert run(tracks.get_track(db, track_id, owner)) == row

    query, args = db.calls[0][1], db.calls[0][2]
    assert 'from "public".user_tracks ut' in query
    assert 'join "public".media_assets a on a.id = ut.asset_id' in query
    assert "join lateral (" in query
    assert "ut.id = $1 and ut.user_id = $2" in query
    assert "ut.deleted_at is null" in query
    assert "a.status = 'ready'" in query
    assert "j.library_hidden = false" in query
    assert args == (track_id, owner)

    db = FakeDatabase()
    db.queue_fetchrow(None)
    assert run(tracks.get_track(db, track_id, uuid4())) is None


def test_decode_cover_rejects_empty_or_unsupported_payloads():
    for content_type, data in (
        ("image/png", ""),
        ("image/png", "   "),
        ("image/gif", "R0lGODlh"),
    ):
        with pytest.raises(tracks.CoverValidationError):
            tracks.decode_cover(content_type, data)


def test_resolve_cover_path_refuses_a_symlink_cover(storage: Storage):
    owner, track_id = uuid4(), uuid4()
    target = storage.root / "assets" / "shared.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(PNG_MAGIC + b"shared")
    relative = f"covers/{owner}/{track_id}.png"
    link = storage.root / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    db = FakeDatabase()
    db.queue_fetchrow({"cover_path": relative})

    assert run(tracks.resolve_cover_path(db, storage, track_id, owner)) is None
    assert link.is_symlink()
    assert target.is_file()


def test_resolve_cover_path_refuses_a_directory(storage: Storage):
    owner, track_id = uuid4(), uuid4()
    relative = f"covers/{owner}/{track_id}.png"
    directory = storage.root / relative
    directory.mkdir(parents=True)
    db = FakeDatabase()
    db.queue_fetchrow({"cover_path": relative})

    assert run(tracks.resolve_cover_path(db, storage, track_id, owner)) is None
    assert directory.is_dir()


def test_list_tracks_by_ids_skips_the_query_for_an_empty_list():
    db = FakeDatabase()

    assert run(tracks.list_tracks_by_ids(db, uuid4(), [])) == []
    assert db.calls == []


def test_list_tracks_sorts_by_resolved_title_case_insensitively():
    owner = uuid4()
    row = track_row()
    db = FakeDatabase()
    db.queue_fetchrow({"total": 1})
    db.queue_fetch([row])

    page, total = run(
        tracks.list_tracks(db, owner, q="aby", limit=2, offset=3, sort="title")
    )

    assert total == 1
    assert page == [row]  # rows echoed unchanged
    count_query, count_args = db.calls[0][1], db.calls[0][2]
    # Visibility and the search filter are independent of the sort order.
    assert "j.library_hidden = false" in count_query
    assert "ut.deleted_at is null" in count_query
    assert "a.status = 'ready'" in count_query
    assert count_args == (owner, "aby")

    page_query, page_args = db.calls[1][1], db.calls[1][2]
    assert (
        "order by lower(coalesce(nullif(ut.custom_title, ''), "
        "nullif(j.title, ''), a.title, '')) asc, ut.id asc"
    ) in page_query
    assert "limit $3 offset $4" in page_query
    assert page_args == (owner, "aby", 2, 3)


def test_list_tracks_rejects_an_unknown_sort_before_querying():
    db = FakeDatabase()

    with pytest.raises(ValueError, match="Invalid track sort"):
        run(tracks.list_tracks(db, uuid4(), sort="album"))

    assert db.calls == []


def _track_kind_queries(kind: str, **kwargs):
    """Run one list with ``kind`` and return its owner, queries, and args."""
    owner = uuid4()
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    run(tracks.list_tracks(db, owner, kind=kind, **kwargs))

    count_query, count_args = db.calls[0][1], db.calls[0][2]
    page_query, page_args = db.calls[1][1], db.calls[1][2]
    return owner, count_query, count_args, page_query, page_args


def _audio_extension_sql() -> str:
    return (
        "regexp_replace(lower(coalesce(a.output_ext, '')), '^\\.', '') "
        "= any(array['mp3', 'm4a', 'aac', 'wav', 'flac', 'ogg', 'opus'])"
    )


def _audio_intent_sql() -> str:
    return (
        "regexp_replace(lower(coalesce(j.format_selector, '')), '\\+subs$', '') "
        "= any(array['audio', 'mp3']) "
        "or lower(coalesce(j.format_selector, '')) like '%bestaudio%'"
    )


def test_list_tracks_audio_kind_filters_on_extension_or_job_intent():
    owner, count_query, count_args, page_query, page_args = (
        _track_kind_queries("audio", q="mix", limit=7, offset=14)
    )

    expected = f"and (({_audio_extension_sql()} or ({_audio_intent_sql()})))"
    assert expected in count_query
    assert expected in page_query
    assert "array['jpg'" not in count_query
    # The existing positional parameters keep their meaning and order.
    assert count_args == (owner, "mix")
    assert page_args == (owner, "mix", 7, 14)
    assert "limit $3 offset $4" in page_query


def test_list_tracks_image_kind_filters_on_the_image_extensions():
    owner, count_query, count_args, page_query, page_args = (
        _track_kind_queries("image")
    )

    expected = (
        "and (regexp_replace(lower(coalesce(a.output_ext, '')), '^\\.', '') "
        "= any(array['jpg', 'jpeg', 'png', 'webp', 'gif', 'avif', 'bmp']))"
    )
    assert expected in count_query
    assert expected in page_query
    assert "array['mp3'" not in count_query
    assert count_args == (owner, "")
    assert page_args == (owner, "", 50, 0)


def test_list_tracks_video_kind_is_the_complement_of_audio_and_image():
    owner, count_query, count_args, page_query, page_args = (
        _track_kind_queries("video")
    )

    expression = "regexp_replace(lower(coalesce(a.output_ext, '')), '^\\.', '')"
    audio = f"({_audio_extension_sql()} or ({_audio_intent_sql()}))"
    image = (
        f"{expression} = any(array['jpg', 'jpeg', 'png', 'webp', "
        "'gif', 'avif', 'bmp'])"
    )
    expected = f"and (not ({audio} or {image}))"
    assert expected in count_query
    assert expected in page_query
    # NULL/unknown extensions fall through COALESCE to '' and therefore match
    # the video complement instead of disappearing from every view.
    assert "coalesce(a.output_ext, '')" in page_query
    assert count_args == (owner, "")
    assert page_args == (owner, "", 50, 0)


def test_list_tracks_rejects_an_unknown_kind_before_querying():
    db = FakeDatabase()

    with pytest.raises(ValueError, match="Invalid track kind"):
        run(tracks.list_tracks(db, uuid4(), kind="music"))

    assert db.calls == []


def test_list_tracks_without_a_kind_keeps_every_media_type():
    db = FakeDatabase()
    db.queue_fetchrow({"total": 0})
    db.queue_fetch([])

    run(tracks.list_tracks(db, uuid4()))

    count_query = db.calls[0][1]
    assert "output_ext" not in count_query
    assert "not (" not in count_query
