"""Real-PostgreSQL tests for library visibility, track projection, and covers."""
from __future__ import annotations

import base64
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.services import assets, auth, jobs, library, tracks
from backend.tests.integration.conftest import (
    cleanup_test_data,
    create_profile,
    create_ready_job,
    make_ready_asset,
    unique_email,
)

pytestmark = pytest.mark.integration


def _jpeg() -> str:
    return base64.b64encode(b"\xff\xd8\xff\xe0" + b"cover" * 4).decode("ascii")


def _png() -> str:
    return base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"cover" * 4).decode("ascii")


def test_library_shows_only_ready_unhidden_jobs_over_ready_assets(
    db_run, media_storage
):
    async def scenario(db):
        owner = await create_profile(db)
        other = await create_profile(db)
        canonical_ids = ["youtube:lib-visible", "youtube:lib-processing"]
        try:
            visible_asset = await make_ready_asset(
                db, media_storage, canonical_id="youtube:lib-visible"
            )
            visible = await create_ready_job(
                db,
                user_id=owner["id"],
                asset_id=visible_asset["id"],
                title="Visible",
            )

            # A ready job whose asset is still processing is not library-ready.
            processing = await assets.claim_asset(
                db,
                media_storage,
                canonical_id="youtube:lib-processing",
                extractor_key="youtube",
                source_url="https://example.test/p",
                title="Processing",
                duration_seconds=1,
                options_hash="p" * 64,
                format_selector="best",
                lease_seconds=60,
            )
            await create_ready_job(
                db,
                user_id=owner["id"],
                asset_id=processing.asset["id"],
                title="Not ready",
            )

            # A queued job is history, not library.
            await jobs.create_job(
                db,
                user_id=owner["id"],
                source_url="https://example.test/queued",
                title="Queued",
                options_hash="q" * 64,
            )

            # Another owner's ready job never appears.
            other_asset = await make_ready_asset(
                db, media_storage, canonical_id="youtube:lib-visible"
            )
            await create_ready_job(
                db,
                user_id=other["id"],
                asset_id=other_asset["id"],
                title="Someone else",
            )

            rows, total = await library.list_library(db, owner["id"])
            assert total == 1
            assert [row["job_id"] for row in rows] == [visible["id"]]
            assert rows[0]["title"] == "Visible"
            assert rows[0]["file_size_bytes"] == 10

            # Hide the only entry: the library empties but history and the
            # shared asset/job survive.
            assert await library.hide_library_item(
                db, owner["id"], visible["id"]
            )
            assert (await library.list_library(db, owner["id"]))[1] == 0
            history, history_total = await library.list_history(db, owner["id"])
            assert history_total == 3  # ready, ready-over-processing, queued
            assert visible["id"] in {row["id"] for row in history}

            job_row = await jobs.get_job(db, visible["id"], owner["id"])
            assert job_row["status"] == "ready"
            hidden = await db.fetchrow(
                f"select library_hidden from {db.schema_sql}.download_jobs "
                "where id = $1",
                visible["id"],
            )
            assert hidden["library_hidden"] is True
            assert (await assets.get_asset(db, visible_asset["id"]))["status"] == "ready"

            # Hiding is idempotent for the owner, and never cross-owner.
            assert await library.hide_library_item(
                db, owner["id"], visible["id"]
            )
            assert not await library.hide_library_item(
                db, other["id"], visible["id"]
            )
        finally:
            await cleanup_test_data(
                db, profiles=[owner, other], canonical_ids=canonical_ids
            )

    db_run(scenario)


def test_tracks_project_metadata_and_order_by_download_date(db_run, media_storage):
    async def scenario(db):
        owner = await create_profile(db)
        canonical_ids = ["youtube:trk-old", "youtube:trk-new"]
        try:
            old_asset = await make_ready_asset(
                db, media_storage, canonical_id="youtube:trk-old", title="Old"
            )
            new_asset = await make_ready_asset(
                db,
                media_storage,
                canonical_id="youtube:trk-new",
                title="New",
                thumbnail=True,
            )
            old_job = await create_ready_job(
                db,
                user_id=owner["id"],
                asset_id=old_asset["id"],
                title="Old job title",
                completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            new_job = await create_ready_job(
                db,
                user_id=owner["id"],
                asset_id=new_asset["id"],
                title="New job title",
                completed_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            )

            rows, total = await tracks.list_tracks(db, owner["id"])
            assert total == 2
            assert [row["title"] for row in rows] == [
                "New job title",
                "Old job title",
            ]
            assert rows[0]["downloaded_at"] == datetime(
                2026, 2, 1, tzinfo=timezone.utc
            )
            assert rows[0]["thumbnail_path"].endswith("thumb.jpg")
            assert rows[0]["job_id"] == new_job["id"]

            # Custom metadata wins over the job title; artist/album drive search
            # and facets.
            await tracks.update_track(
                db,
                rows[0]["id"],
                owner["id"],
                {
                    "custom_title": "My New Song",
                    "custom_artist": "The Artist",
                    "custom_album": "The Album",
                },
            )
            updated = await tracks.get_track(db, rows[0]["id"], owner["id"])
            assert updated["title"] == "My New Song"
            assert updated["artist"] == "The Artist"
            assert updated["album"] == "The Album"

            assert (await tracks.list_tracks(db, owner["id"], q="my new"))[1] == 1
            assert (await tracks.list_tracks(db, owner["id"], q="artist"))[1] == 1
            assert (await tracks.list_tracks(db, owner["id"], q="album"))[1] == 1
            assert (await tracks.list_tracks(db, owner["id"], q="missing"))[1] == 0
            # Whitespace-only search is no filter.
            assert (await tracks.list_tracks(db, owner["id"], q="   "))[1] == 2

            facets = await tracks.list_facets(db, owner["id"], kind="artist")
            assert facets == [{"name": "The Artist", "track_count": 1}]
            album_facets = await tracks.list_facets(db, owner["id"], kind="album")
            assert album_facets == [{"name": "The Album", "track_count": 1}]

            # Requested id order is preserved, unknown ids are omitted.
            requested = await tracks.list_tracks_by_ids(
                db, owner["id"], [rows[1]["id"], rows[0]["id"], old_job["id"]]
            )
            assert [row["title"] for row in requested] == [
                "Old job title",
                "My New Song",
            ]
        finally:
            await cleanup_test_data(
                db, profiles=[owner], canonical_ids=canonical_ids
            )

    db_run(scenario)


def test_tracks_classify_native_audio_by_job_intent(db_run, media_storage):
    async def scenario(db):
        owner = await create_profile(db)
        canonical_ids = [
            "youtube:trk-webm-audio",
            "youtube:trk-webm-audio-subs",
            "youtube:trk-webm-legacy",
            "youtube:trk-webm-video",
        ]
        try:
            # Native audio keeps the source container (.webm), so the extension
            # alone would classify it as video.
            native = await make_ready_asset(
                db,
                media_storage,
                canonical_id="youtube:trk-webm-audio",
                title="Native audio",
                output_ext="webm",
            )
            await create_ready_job(
                db,
                user_id=owner["id"],
                asset_id=native["id"],
                title="Native audio",
                format_selector="audio",
            )

            with_subs = await make_ready_asset(
                db,
                media_storage,
                canonical_id="youtube:trk-webm-audio-subs",
                title="Audio with subs intent",
                output_ext="webm",
            )
            await create_ready_job(
                db,
                user_id=owner["id"],
                asset_id=with_subs["id"],
                title="Audio with subs intent",
                format_selector="audio+subs",
            )

            # Legacy jobs stored the raw yt-dlp selector.
            legacy = await make_ready_asset(
                db,
                media_storage,
                canonical_id="youtube:trk-webm-legacy",
                title="Legacy audio",
                output_ext="webm",
            )
            await create_ready_job(
                db,
                user_id=owner["id"],
                asset_id=legacy["id"],
                title="Legacy audio",
                format_selector="bestaudio/best",
            )

            video = await make_ready_asset(
                db,
                media_storage,
                canonical_id="youtube:trk-webm-video",
                title="Real video",
                output_ext="webm",
            )
            await create_ready_job(
                db,
                user_id=owner["id"],
                asset_id=video["id"],
                title="Real video",
                format_selector="best",
            )

            audio_rows, audio_total = await tracks.list_tracks(
                db, owner["id"], kind="audio"
            )
            assert audio_total == 3
            assert {row["format_selector"] for row in audio_rows} == {
                "audio",
                "audio+subs",
                "bestaudio/best",
            }

            video_rows, video_total = await tracks.list_tracks(
                db, owner["id"], kind="video"
            )
            assert video_total == 1
            assert [row["title"] for row in video_rows] == ["Real video"]

            assert (
                await tracks.list_tracks(db, owner["id"], kind="image")
            )[1] == 0
        finally:
            await cleanup_test_data(
                db, profiles=[owner], canonical_ids=canonical_ids
            )

    db_run(scenario)


def test_track_visibility_follows_the_library_and_asset_state(
    db_run, media_storage
):
    async def scenario(db):
        owner = await create_profile(db)
        canonical = "youtube:trk-visibility"
        try:
            asset = await make_ready_asset(
                db, media_storage, canonical_id=canonical
            )
            job_row = await create_ready_job(
                db, user_id=owner["id"], asset_id=asset["id"], title="Track"
            )
            track_id = (
                await db.fetchrow(
                    f"select id from {db.schema_sql}.user_tracks "
                    "where user_id = $1",
                    owner["id"],
                )
            )["id"]

            # Hiding the only ready job removes the track from every view.
            assert await library.hide_library_item(db, owner["id"], job_row["id"])
            assert (await tracks.list_tracks(db, owner["id"]))[1] == 0
            assert await tracks.get_track(db, track_id, owner["id"]) is None
            assert await tracks.update_track(
                db, track_id, owner["id"], {"custom_title": "Nope"}
            ) is None
            assert await tracks.list_tracks_by_ids(
                db, owner["id"], [track_id]
            ) == []
            assert await tracks.list_facets(db, owner["id"], kind="artist") == []

            # Restoring visibility brings it back with the stored metadata
            # untouched by the rejected update.
            await db.execute(
                f"update {db.schema_sql}.download_jobs "
                "set library_hidden = false where id = $1",
                job_row["id"],
            )
            restored = await tracks.get_track(db, track_id, owner["id"])
            assert restored is not None
            assert restored["title"] == "Track"

            # A shared asset that is no longer ready hides the track too.
            await db.execute(
                f"update {db.schema_sql}.media_assets set status = 'failed' "
                "where id = $1",
                asset["id"],
            )
            assert await tracks.get_track(db, track_id, owner["id"]) is None
        finally:
            await cleanup_test_data(
                db, profiles=[owner], canonical_ids=[canonical]
            )

    db_run(scenario)


def test_soft_deleted_tracks_disappear(db_run, media_storage):
    async def scenario(db):
        owner = await create_profile(db)
        canonical = "youtube:trk-deleted"
        try:
            asset = await make_ready_asset(
                db, media_storage, canonical_id=canonical
            )
            await create_ready_job(
                db, user_id=owner["id"], asset_id=asset["id"], title="Gone"
            )
            track_id = await db.fetchrow(
                f"select id from {db.schema_sql}.user_tracks where user_id = $1",
                owner["id"],
            )
            await db.execute(
                f"update {db.schema_sql}.user_tracks set deleted_at = now() "
                "where id = $1",
                track_id["id"],
            )
            assert (await tracks.list_tracks(db, owner["id"]))[1] == 0
            assert await tracks.get_track(db, track_id["id"], owner["id"]) is None
            assert (await tracks.list_facets(db, owner["id"], kind="artist")) == []
        finally:
            await cleanup_test_data(
                db, profiles=[owner], canonical_ids=[canonical]
            )

    db_run(scenario)


def test_cover_upload_replace_and_delete_lifecycle(db_run, media_storage):
    async def scenario(db):
        owner = await create_profile(db)
        other = await create_profile(db)
        canonical = "youtube:cover"
        try:
            asset = await make_ready_asset(
                db, media_storage, canonical_id=canonical
            )
            await create_ready_job(
                db, user_id=owner["id"], asset_id=asset["id"], title="Covered"
            )
            track_id = (
                await db.fetchrow(
                    f"select id from {db.schema_sql}.user_tracks "
                    "where user_id = $1",
                    owner["id"],
                )
            )["id"]

            with pytest.raises(tracks.CoverValidationError):
                await tracks.set_cover(
                    db,
                    media_storage,
                    track_id,
                    owner["id"],
                    content_type="image/png",
                    data=_jpeg(),  # declared type does not match magic bytes
                )

            jpg_path = await tracks.set_cover(
                db,
                media_storage,
                track_id,
                owner["id"],
                content_type="image/jpeg",
                data=_jpeg(),
            )
            assert jpg_path == f"covers/{owner['id']}/{track_id}.jpg"
            stored = media_storage.validate_relative_path(jpg_path)
            assert stored.is_file()
            assert stored.stat().st_size > 0

            resolved = await tracks.resolve_cover_path(
                db, media_storage, track_id, owner["id"]
            )
            assert resolved == stored

            # A different extension replaces the old file atomically.
            png_path = await tracks.set_cover(
                db,
                media_storage,
                track_id,
                owner["id"],
                content_type="image/png",
                data=_png(),
            )
            assert png_path == f"covers/{owner['id']}/{track_id}.png"
            assert media_storage.validate_relative_path(png_path).is_file()
            assert not stored.exists()

            row = await tracks.get_track(db, track_id, owner["id"])
            assert row["cover_path"] == png_path

            # Another user cannot write this track's cover.
            assert (
                await tracks.set_cover(
                    db,
                    media_storage,
                    track_id,
                    other["id"],
                    content_type="image/png",
                    data=_png(),
                )
                is None
            )
            assert not await tracks.delete_cover(
                db, media_storage, track_id, other["id"]
            )

            assert await tracks.delete_cover(
                db, media_storage, track_id, owner["id"]
            )
            assert not media_storage.validate_relative_path(png_path).exists()
            assert (
                await tracks.resolve_cover_path(
                    db, media_storage, track_id, owner["id"]
                )
                is None
            )
            cleared = await tracks.get_track(db, track_id, owner["id"])
            assert cleared["cover_path"] is None
        finally:
            await cleanup_test_data(
                db, profiles=[owner, other], canonical_ids=[canonical]
            )

    db_run(scenario)


def test_tracks_sort_by_download_date_or_resolved_title_across_pages(
    db_run, media_storage
):
    async def scenario(db):
        owner = await create_profile(db)
        canonical_ids: list[str] = []
        try:
            # Created oldest to newest with titles that order differently from
            # the download time.
            seeds = [
                ("delta", "2026-01-01"),
                ("Alpha", "2026-02-01"),
                ("charlie", "2026-03-01"),
                ("Bravo", "2026-04-01"),
                ("echo", "2026-05-01"),
            ]
            for index, (title, completed) in enumerate(seeds):
                canonical = f"youtube:sort-{index}"
                canonical_ids.append(canonical)
                asset = await make_ready_asset(
                    db, media_storage, canonical_id=canonical, title=title
                )
                await create_ready_job(
                    db,
                    user_id=owner["id"],
                    asset_id=asset["id"],
                    title=title,
                    completed_at=datetime.fromisoformat(completed).replace(
                        tzinfo=timezone.utc
                    ),
                )

            newest_first, total = await tracks.list_tracks(db, owner["id"])
            assert total == 5
            assert [row["title"] for row in newest_first] == [
                "echo",
                "Bravo",
                "charlie",
                "Alpha",
                "delta",
            ]

            by_title, total = await tracks.list_tracks(
                db, owner["id"], sort="title"
            )
            assert total == 5
            assert [row["title"] for row in by_title] == [
                "Alpha",
                "Bravo",
                "charlie",
                "delta",
                "echo",
            ]

            # Paging with a title sort visits every track exactly once.
            collected: list[str] = []
            for offset in (0, 2, 4):
                page, page_total = await tracks.list_tracks(
                    db, owner["id"], sort="title", limit=2, offset=offset
                )
                assert page_total == 5
                collected.extend(row["title"] for row in page)
            assert collected == [row["title"] for row in by_title]

            # The search filter composes with the sort.
            filtered, filtered_total = await tracks.list_tracks(
                db, owner["id"], q="a", sort="title", limit=10
            )
            assert filtered_total == 4
            assert [row["title"] for row in filtered] == [
                "Alpha",
                "Bravo",
                "charlie",
                "delta",
            ]

            # Equal resolved titles tie-break on the id, so paging stays stable.
            for row in by_title[:2]:
                await tracks.update_track(
                    db, row["id"], owner["id"], {"custom_title": "Same"}
                )
            all_rows, _ = await tracks.list_tracks(
                db, owner["id"], sort="title", limit=10
            )
            assert [row["title"] for row in all_rows] == [
                "charlie",
                "delta",
                "echo",
                "Same",
                "Same",
            ]
            same_ids = [
                row["id"] for row in all_rows if row["title"] == "Same"
            ]
            assert same_ids == sorted(same_ids)

            paged: list = []
            for offset in range(0, 8, 2):
                page, _ = await tracks.list_tracks(
                    db, owner["id"], sort="title", limit=2, offset=offset
                )
                paged.extend(row["id"] for row in page)
            assert paged == [row["id"] for row in all_rows]

            with pytest.raises(ValueError):
                await tracks.list_tracks(db, owner["id"], sort="album")
        finally:
            await cleanup_test_data(
                db, profiles=[owner], canonical_ids=canonical_ids
            )

    db_run(scenario)


def test_tracks_api_filters_by_media_kind_across_pages(
    database_url, db_run, media_storage
):
    """The server-side kind filter must page over one media type only."""
    email = unique_email("itest-kind")
    state: dict = {}

    async def seed(db):
        session = await auth.register(db, email, "kind-password-1")
        await db.execute(
            f"update {db.schema_sql}.profiles set is_approved = true "
            "where id = $1",
            session.profile["id"],
        )
        canonical_ids = [
            "youtube:kind-audio",
            "youtube:kind-video",
            "youtube:kind-image",
            "youtube:kind-unknown",
        ]
        seeds = [
            ("youtube:kind-audio", "Audio Song", "mp3", "2026-01-01"),
            ("youtube:kind-video", "Video Clip", "mp4", "2026-02-01"),
            ("youtube:kind-image", "Image Plate", "png", "2026-03-01"),
            # An unrecognised container must be treated as video, not dropped.
            ("youtube:kind-unknown", "Unknown Container", "mkv", "2026-04-01"),
        ]
        for canonical, title, extension, completed in seeds:
            asset = await make_ready_asset(
                db,
                media_storage,
                canonical_id=canonical,
                title=title,
                output_ext=extension,
            )
            await create_ready_job(
                db,
                user_id=session.profile["id"],
                asset_id=asset["id"],
                title=title,
                completed_at=datetime.fromisoformat(completed).replace(
                    tzinfo=timezone.utc
                ),
            )
        state.update(
            token=session.token,
            profile_id=session.profile["id"],
            canonical_ids=canonical_ids,
        )

    try:
        db_run(seed)
        settings = Settings.from_env(
            {
                "ENVIRONMENT": "test",
                "DATABASE_URL": database_url,
                "MEDIA_TOKEN_SECRET": "itest-media-secret",
                "DOWNLOAD_DIR": str(media_storage.root),
            }
        )
        headers = {"Authorization": f"Bearer {state['token']}"}
        with TestClient(create_app(settings)) as client:
            everything = client.get("/api/tracks?limit=50", headers=headers)
            assert everything.status_code == 200, everything.text
            assert everything.json()["total"] == 4

            audio = client.get(
                "/api/tracks", params={"kind": "audio"}, headers=headers
            )
            assert audio.status_code == 200, audio.text
            assert audio.json()["total"] == 1
            assert [item["output_ext"] for item in audio.json()["items"]] == [
                "mp3"
            ]

            image = client.get(
                "/api/tracks", params={"kind": "image"}, headers=headers
            )
            assert image.status_code == 200, image.text
            assert image.json()["total"] == 1
            assert [item["output_ext"] for item in image.json()["items"]] == [
                "png"
            ]

            video = client.get(
                "/api/tracks", params={"kind": "video"}, headers=headers
            )
            assert video.status_code == 200, video.text
            assert video.json()["total"] == 2
            assert [
                (item["title"], item["output_ext"])
                for item in video.json()["items"]
            ] == [
                ("Unknown Container", "mkv"),
                ("Video Clip", "mp4"),
            ]

            # The kind filter pages independently: two one-item pages cover the
            # video set in the same order as the full request, with no overlap.
            full = client.get(
                "/api/tracks",
                params={"kind": "video", "sort": "title", "limit": 10},
                headers=headers,
            )
            assert full.status_code == 200, full.text
            expected_ids = [item["id"] for item in full.json()["items"]]
            assert len(expected_ids) == 2

            pages: list[str] = []
            for offset in (0, 1):
                page = client.get(
                    "/api/tracks",
                    params={
                        "kind": "video",
                        "sort": "title",
                        "limit": 1,
                        "offset": offset,
                    },
                    headers=headers,
                )
                assert page.status_code == 200, page.text
                assert page.json()["total"] == 2
                assert page.json()["limit"] == 1
                assert page.json()["offset"] == offset
                pages.extend(item["id"] for item in page.json()["items"])
            assert pages == expected_ids
            assert len(set(pages)) == 2

            # Search composes with the kind filter instead of broadening it.
            searched = client.get(
                "/api/tracks",
                params={"kind": "video", "q": "audio"},
                headers=headers,
            )
            assert searched.status_code == 200, searched.text
            assert searched.json()["total"] == 0
    finally:
        async def cleanup(db):
            await db.execute(
                f"delete from {db.schema_sql}.profiles where id = $1",
                state["profile_id"],
            )
            await cleanup_test_data(
                db, canonical_ids=state.get("canonical_ids", [])
            )

        db_run(cleanup)
