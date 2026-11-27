"""Real-PostgreSQL tests for downloaded source playlists and their items.

Also covers the on-demand ZIP endpoint, which derives its candidate list from
the playlist items, the shared asset state, and the real files on disk.
"""
from __future__ import annotations

import io
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import create_app
from backend.app.services import assets, auth, playlists
from backend.app.services.signing import verify_media_token
from backend.tests.integration.conftest import (
    cleanup_test_data,
    create_profile,
    make_ready_asset,
    unique_email,
)

pytestmark = pytest.mark.integration


def test_upsert_playlist_is_scoped_by_owner_and_output_intent(db_run):
    async def scenario(db):
        owner = await create_profile(db)
        other = await create_profile(db)
        try:
            first = await playlists.upsert_playlist(
                db,
                user_id=owner["id"],
                canonical_id="youtube:PL1",
                source_url="https://example.test/playlist",
                title="Original",
                channel="Channel",
                item_count=2,
                options_hash="o" * 64,
                format_selector="best",
                thumbnail_path="playlists/cover.jpg",
            )
            refreshed = await playlists.upsert_playlist(
                db,
                user_id=owner["id"],
                canonical_id="youtube:PL1",
                source_url="https://example.test/playlist?v=2",
                title="Refreshed",
                channel="Channel 2",
                item_count=5,
                options_hash="o" * 64,
                format_selector="bestvideo",
                thumbnail_path=None,
            )
            assert refreshed["id"] == first["id"]
            assert refreshed["title"] == "Refreshed"
            assert refreshed["item_count"] == 5
            assert refreshed["format_selector"] == "bestvideo"
            # A missing thumbnail does not erase the stored one.
            assert refreshed["thumbnail_path"] == "playlists/cover.jpg"

            # A different output intent is a distinct playlist row.
            variant = await playlists.upsert_playlist(
                db,
                user_id=owner["id"],
                canonical_id="youtube:PL1",
                source_url="https://example.test/playlist",
                title="Audio",
                channel="Channel",
                item_count=2,
                options_hash="a" * 64,
                format_selector="bestaudio",
            )
            assert variant["id"] != first["id"]

            # Same source and intent for another owner is independent.
            foreign = await playlists.upsert_playlist(
                db,
                user_id=other["id"],
                canonical_id="youtube:PL1",
                source_url="https://example.test/playlist",
                title="Theirs",
                channel="Channel",
                item_count=2,
                options_hash="o" * 64,
                format_selector="best",
            )
            assert foreign["id"] != first["id"]

            owner_rows, owner_total = await playlists.list_playlists(db, owner["id"])
            assert owner_total == 2
            assert (await playlists.list_playlists(db, other["id"]))[1] == 1

            assert await playlists.get_playlist(db, first["id"], other["id"]) is None
            fetched = await playlists.get_playlist(db, first["id"], owner["id"])
            assert fetched["canonical_id"] == "youtube:PL1"

            with pytest.raises(ValueError):
                await playlists.upsert_playlist(
                    db,
                    user_id=owner["id"],
                    canonical_id="",
                    source_url="",
                    title="",
                    channel="",
                    item_count=0,
                    options_hash="o" * 64,
                    format_selector="",
                )
            with pytest.raises(ValueError):
                await playlists.upsert_playlist(
                    db,
                    user_id=owner["id"],
                    canonical_id="youtube:PL2",
                    source_url="",
                    title="",
                    channel="",
                    item_count=0,
                    options_hash="   ",
                    format_selector="",
                )
        finally:
            await cleanup_test_data(db, profiles=[owner, other])

    db_run(scenario)


def test_replace_items_reconciles_and_preserves_asset_links(db_run, media_storage):
    async def scenario(db):
        owner = await create_profile(db)
        try:
            playlist = await playlists.upsert_playlist(
                db,
                user_id=owner["id"],
                canonical_id="youtube:PLREPLACE",
                source_url="https://example.test/playlist",
                title="Source",
                channel="Channel",
                item_count=0,
                options_hash="r" * 64,
                format_selector="best",
            )
            entries = [
                {"canonical_id": "youtube:a", "title": "A", "duration": 10},
                {"canonical_id": "youtube:b", "title": "B", "duration": 20},
                {"canonical_id": "youtube:c", "title": "C", "duration": 30},
            ]
            created = await playlists.replace_items(db, playlist["id"], entries)
            assert [(item["position"], item["canonical_id"]) for item in created] == [
                (1, "youtube:a"),
                (2, "youtube:b"),
                (3, "youtube:c"),
            ]
            b_row = created[1]

            # Attach a ready shared asset to B.
            canonical = "youtube:replace-b"
            try:
                asset = await make_ready_asset(
                    db, media_storage, canonical_id=canonical
                )
                await playlists.update_item(
                    db,
                    playlist["id"],
                    2,
                    status="ready",
                    asset_id=asset["id"],
                )

                refreshed = await playlists.replace_items(
                    db,
                    playlist["id"],
                    [
                        {"canonical_id": "youtube:c", "title": "C2", "duration": 31},
                        {"canonical_id": "youtube:b", "title": "B2", "duration": 21},
                        {"canonical_id": "youtube:d", "title": "D", "duration": 40},
                    ],
                )
                assert [
                    (item["position"], item["canonical_id"], item["title"])
                    for item in refreshed
                ] == [
                    (1, "youtube:c", "C2"),
                    (2, "youtube:b", "B2"),
                    (3, "youtube:d", "D"),
                ]
                moved_b = refreshed[1]
                assert moved_b["id"] == b_row["id"]  # row survived the move
                assert moved_b["asset_id"] == asset["id"]
                assert moved_b["status"] == "ready"

                # C moved but is a different canonical id at position 1, so it
                # must not inherit the old row's asset/status.
                assert refreshed[0]["asset_id"] is None
                assert refreshed[0]["status"] == "pending"

                # Shrinking deletes the dropped rows, keeping the shared asset.
                final = await playlists.replace_items(
                    db, playlist["id"], [{"canonical_id": "youtube:b", "title": "B3"}]
                )
                assert [(item["position"], item["canonical_id"]) for item in final] == [
                    (1, "youtube:b")
                ]
                assert [item["canonical_id"] for item in await playlists.list_items(
                    db, playlist["id"]
                )] == ["youtube:b"]
                assert (await assets.get_asset(db, asset["id"]))["status"] == "ready"
            finally:
                await cleanup_test_data(db, canonical_ids=[canonical])
        finally:
            await cleanup_test_data(db, profiles=[owner])

    db_run(scenario)


def test_replace_items_dedupes_canonical_ids_but_keeps_anonymous_entries(
    db_run,
):
    async def scenario(db):
        owner = await create_profile(db)
        try:
            playlist = await playlists.upsert_playlist(
                db,
                user_id=owner["id"],
                canonical_id="youtube:PLDUP",
                source_url="",
                title="Duplicates",
                channel="",
                item_count=0,
                options_hash="d" * 64,
                format_selector="best",
            )
            items = await playlists.replace_items(
                db,
                playlist["id"],
                [
                    {"canonical_id": "youtube:a", "title": "first"},
                    {"canonical_id": "youtube:a", "title": "duplicate"},
                    {"canonical_id": "", "title": "anon one"},
                    {"canonical_id": "", "title": "anon two"},
                ],
            )
            assert [
                (item["position"], item["canonical_id"], item["title"])
                for item in items
            ] == [
                (1, "youtube:a", "first"),
                (2, "", "anon one"),
                (3, "", "anon two"),
            ]

            updated = await playlists.update_item(
                db, playlist["id"], 1, status="failed", error="nope"
            )
            assert updated["status"] == "failed"
            assert updated["error"] == "nope"
            with pytest.raises(ValueError):
                await playlists.update_item(
                    db, playlist["id"], 1, status="bogus"
                )

            playlist_row = await playlists.update_playlist(
                db, playlist["id"], status="partial", item_count=3
            )
            assert playlist_row["status"] == "partial"
            with pytest.raises(ValueError):
                await playlists.update_playlist(db, playlist["id"], status="bogus")
            with pytest.raises(ValueError):
                await playlists.update_playlist(db, playlist["id"], user_id=owner["id"])
        finally:
            await cleanup_test_data(db, profiles=[owner])

    db_run(scenario)


def test_delete_playlist_cascades_items_and_keeps_shared_assets(
    db_run, media_storage
):
    canonical = "youtube:delete-playlist"

    async def scenario(db):
        owner = await create_profile(db)
        other = await create_profile(db)
        try:
            asset = await make_ready_asset(
                db, media_storage, canonical_id=canonical
            )
            playlist = await playlists.upsert_playlist(
                db,
                user_id=owner["id"],
                canonical_id="youtube:PLDELETE",
                source_url="",
                title="Delete me",
                channel="",
                item_count=1,
                options_hash="x" * 64,
                format_selector="best",
            )
            await playlists.replace_items(
                db,
                playlist["id"],
                [{"canonical_id": canonical, "title": "A"}],
            )
            await playlists.update_item(
                db,
                playlist["id"],
                1,
                status="ready",
                asset_id=asset["id"],
            )

            assert not await playlists.delete_playlist(
                db, playlist["id"], other["id"]
            )
            assert await playlists.delete_playlist(db, playlist["id"], owner["id"])
            assert not await playlists.delete_playlist(
                db, playlist["id"], owner["id"]
            )
            assert await playlists.list_items(db, playlist["id"]) == []
            assert (await assets.get_asset(db, asset["id"]))["status"] == "ready"
        finally:
            await cleanup_test_data(
                db, profiles=[owner, other], canonical_ids=[canonical]
            )

    db_run(scenario)


def test_playlist_zip_includes_only_ready_items_with_real_files(
    database_url, db_run, media_storage
):
    email = unique_email("itest-zip")
    state: dict = {}

    async def seed(db):
        session = await auth.register(db, email, "zip-password-1")
        await db.execute(
            f"update {db.schema_sql}.profiles set is_approved = true where id = $1",
            session.profile["id"],
        )
        playlist = await playlists.upsert_playlist(
            db,
            user_id=session.profile["id"],
            canonical_id="youtube:PLZIP",
            source_url="https://example.test/playlist",
            title="Zip Me",
            channel="",
            item_count=3,
            options_hash="z" * 64,
            format_selector="best",
        )
        empty = await playlists.upsert_playlist(
            db,
            user_id=session.profile["id"],
            canonical_id="youtube:PLZIPEMPTY",
            source_url="",
            title="Empty",
            channel="",
            item_count=0,
            options_hash="y" * 64,
            format_selector="best",
        )
        await playlists.replace_items(
            db,
            playlist["id"],
            [
                {"canonical_id": "youtube:zip-a", "title": "Ready One"},
                {"canonical_id": "youtube:zip-b", "title": "Pending"},
                {"canonical_id": "youtube:zip-c", "title": "Missing file"},
            ],
        )
        first_asset = await make_ready_asset(
            db, media_storage, canonical_id="youtube:zip-a", payload=b"first-file"
        )
        third_asset = await make_ready_asset(
            db, media_storage, canonical_id="youtube:zip-c", payload=b"third-file"
        )
        await playlists.update_item(
            db, playlist["id"], 1, status="ready", asset_id=first_asset["id"]
        )
        await playlists.update_item(
            db, playlist["id"], 3, status="ready", asset_id=third_asset["id"]
        )
        # The third item's file disappears after the row was marked ready.
        media_storage.validate_relative_path(
            third_asset["file_path"]
        ).unlink()

        state.update(
            token=session.token,
            email=email,
            profile_id=session.profile["id"],
            playlist_id=playlist["id"],
            empty_id=empty["id"],
            canonical_ids=["youtube:zip-a", "youtube:zip-c"],
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
            response = client.get(
                f"/api/playlists/{state['playlist_id']}/zip", headers=headers
            )
            assert response.status_code == 200, response.text
            assert response.headers["content-type"] == "application/zip"
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                names = archive.namelist()
                assert names == ["001 - Ready One.mp4"]
                assert archive.read(names[0]) == b"first-file"

            # A playlist with no ready, on-disk items is a 404, not an empty zip.
            empty = client.get(
                f"/api/playlists/{state['empty_id']}/zip", headers=headers
            )
            assert empty.status_code == 404
            assert empty.json()["error"]["code"] == "playlist_empty"
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


def test_playlist_detail_signs_linked_asset_thumbnail(
    database_url, db_run, media_storage
):
    email = unique_email("itest-thumb")
    canonical = f"youtube:thumb-{uuid.uuid4().hex}"
    secret = "itest-playlist-media-secret"
    state: dict = {}
    thumbnail_bytes = b"\xff\xd8\xffplaylist-thumb"

    async def seed(db):
        session = await auth.register(db, email, "thumb-password-1")
        state.update(token=session.token, profile_id=session.profile["id"])
        await db.execute(
            f"update {db.schema_sql}.profiles "
            "set is_approved = true where id = $1",
            session.profile["id"],
        )
        playlist = await playlists.upsert_playlist(
            db,
            user_id=session.profile["id"],
            canonical_id=f"youtube:PLTHUMB-{uuid.uuid4().hex}",
            source_url="https://example.test/playlist",
            title="Thumbnails",
            channel="",
            item_count=2,
            options_hash="t" * 64,
            format_selector="best",
        )
        await playlists.replace_items(
            db,
            playlist["id"],
            [
                {"canonical_id": canonical, "title": "With thumbnail"},
                {"canonical_id": f"youtube:no-thumb-{uuid.uuid4().hex}", "title": "No thumbnail"},
            ],
        )
        asset = await make_ready_asset(
            db, media_storage, canonical_id=canonical, thumbnail=True
        )
        media_storage.validate_relative_path(asset["thumbnail_path"]).write_bytes(
            thumbnail_bytes
        )
        await playlists.update_item(
            db, playlist["id"], 1, status="ready", asset_id=asset["id"]
        )

        rows = await playlists.list_items_with_thumbnail_paths(db, playlist["id"])
        assert [row["position"] for row in rows] == [1, 2]
        assert rows[0]["asset_thumbnail_path"] == asset["thumbnail_path"]
        assert rows[1]["asset_thumbnail_path"] is None

        state.update(
            playlist_id=playlist["id"],
            asset_id=asset["id"],
            thumbnail_path=asset["thumbnail_path"],
        )

    try:
        db_run(seed)
        settings = Settings.from_env(
            {
                "ENVIRONMENT": "test",
                "DATABASE_URL": database_url,
                "MEDIA_TOKEN_SECRET": secret,
                "DOWNLOAD_DIR": str(media_storage.root),
            }
        )
        headers = {"Authorization": f"Bearer {state['token']}"}
        with TestClient(create_app(settings)) as client:
            response = client.get(
                f"/api/playlists/{state['playlist_id']}", headers=headers
            )
            assert response.status_code == 200, response.text
            items = response.json()["items"]
            signed = items[0]["thumbnail_url"]
            assert signed.startswith(
                f"/api/thumbnails/{state['asset_id']}?token="
            )
            claims = verify_media_token(signed.split("token=", 1)[1], secret)
            assert claims.asset_id == str(state["asset_id"])
            assert claims.user_id == str(state["profile_id"])
            assert items[1]["thumbnail_url"] is None
            assert all("asset_thumbnail_path" not in item for item in items)

            # The signed URL resolves to the cached thumbnail for this asset.
            thumbnail = client.get(signed)
            assert thumbnail.status_code == 200, thumbnail.text
            assert thumbnail.content == thumbnail_bytes
    finally:
        async def cleanup(db):
            if state.get("profile_id") is not None:
                await db.execute(
                    f"delete from {db.schema_sql}.profiles where id = $1",
                    state["profile_id"],
                )
            await cleanup_test_data(db, canonical_ids=[canonical])

        db_run(cleanup)