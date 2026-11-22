"""Tests for the v2 Pydantic response models."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from backend.app.models.schemas import (
    AdminAssetList,
    AdminAssetOut,
    AdminJobList,
    AdminJobOut,
    AdminUserList,
    DownloadJobList,
    DownloadJobOut,
    DownloadRequest,
    ErrorResponse,
    HealthOut,
    InfoOut,
    LibraryItemOut,
    LibraryList,
    MediaAssetOut,
    MediaTokenOut,
    MeOut,
    PlaylistDetailOut,
    PlaylistItemOut,
    PlaylistList,
    PlaylistOut,
    ProfileOut,
    RoleUpdate,
    StorageHealth,
)

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


def _profile_dict() -> dict:
    return {
        "id": str(uuid4()),
        "email": "user@example.test",
        "is_approved": True,
        "app_role": "admin",
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }


def test_profile_out_parses_schema_row():
    raw = _profile_dict()

    profile = ProfileOut.model_validate(raw)

    assert isinstance(profile.id, UUID)
    assert profile.email == "user@example.test"
    assert profile.is_approved is True
    assert profile.app_role == "admin"
    assert profile.created_at == NOW

    dumped = profile.model_dump(mode="json")
    assert dumped["id"] == raw["id"]
    assert dumped["created_at"] == "2026-11-21T12:00:00Z"


def test_profile_out_defaults():
    profile = ProfileOut(
        id=uuid4(), created_at=NOW, updated_at=NOW
    )

    assert profile.email == ""
    assert profile.is_approved is False
    assert profile.app_role == "user"


def test_profile_out_rejects_invalid_role():
    raw = _profile_dict()
    raw["app_role"] = "superuser"

    with pytest.raises(ValidationError):
        ProfileOut.model_validate(raw)


def test_me_out_is_the_profile_shape():
    profile = MeOut.model_validate(_profile_dict())

    assert isinstance(profile, ProfileOut)
    assert profile.app_role == "admin"


@pytest.mark.parametrize("role", ["user", "admin"])
def test_role_update_accepts_known_roles(role: str):
    assert RoleUpdate(app_role=role).app_role == role


def test_role_update_rejects_unknown_role():
    with pytest.raises(ValidationError):
        RoleUpdate(app_role="owner")


def test_admin_user_list_shape():
    items = [ProfileOut.model_validate(_profile_dict())]

    listing = AdminUserList(items=items, total=1, limit=50, offset=0)

    assert listing.items == items
    assert listing.total == 1


def test_health_out_shape():
    health = HealthOut(
        status="ok",
        version="2.0.0",
        yt_dlp_version="2026.11.1",
        database=True,
        auth=True,
        storage=StorageHealth(free_bytes=123456, writable=True),
        dependencies={"ffmpeg": True, "node": False},
    )

    assert health.status == "ok"
    assert health.dependencies["node"] is False

    with pytest.raises(ValidationError):
        HealthOut(
            status="exploded",
            version="2.0.0",
            database=True,
            auth=True,
            storage=StorageHealth(free_bytes=0, writable=False),
        )


def test_media_token_out_shape():
    token = MediaTokenOut(
        token="payload.signature",
        url="/api/media/abc?token=payload.signature",
        expires_at=NOW,
        expires_in=900,
    )

    assert token.expires_in == 900


def test_download_job_out_aligns_with_schema():
    job = DownloadJobOut(
        id=uuid4(),
        user_id=uuid4(),
        kind="video",
        status="downloading",
        progress=42.5,
        downloaded_bytes=1024,
        total_bytes=2048,
        speed=512.0,
        source_url="https://example.test/v",
        options_hash="a" * 64,
        created_at=NOW,
        updated_at=NOW,
    )

    assert job.progress == 42.5
    assert job.asset_id is None
    assert job.eta_seconds is None

    with pytest.raises(ValidationError):
        DownloadJobOut(
            id=uuid4(),
            user_id=uuid4(),
            status="exploded",
            created_at=NOW,
            updated_at=NOW,
        )


def test_media_asset_out_aligns_with_schema():
    asset = MediaAssetOut(
        id=uuid4(),
        canonical_id="youtube:dQw4w9WgXcQ",
        options_hash="b" * 64,
        status="ready",
        output_ext="mp4",
        file_path="assets/abc/file.mp4",
        file_size_bytes=98765,
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=NOW,
    )

    assert asset.canonical_id == "youtube:dQw4w9WgXcQ"
    assert asset.file_path == "assets/abc/file.mp4"
    assert asset.options_schema_version == 1

    with pytest.raises(ValidationError):
        MediaAssetOut(
            id=uuid4(),
            canonical_id="x",
            options_hash="c" * 64,
            status="gone",
            created_at=NOW,
            updated_at=NOW,
            last_accessed_at=NOW,
        )


def test_download_job_out_has_progress_and_cancel_fields():
    job = DownloadJobOut(
        id=uuid4(),
        user_id=uuid4(),
        status="downloading",
        created_at=NOW,
        updated_at=NOW,
    )

    assert job.cancel_requested is False
    assert job.item_index == 0
    assert job.item_count == 0
    assert job.current_item_title == ""
    assert job.current_item_progress == 0

    parsed = DownloadJobOut(
        id=uuid4(),
        user_id=uuid4(),
        status="downloading",
        cancel_requested=True,
        item_index=2,
        item_count=5,
        current_item_title="Second",
        current_item_progress=40.5,
        created_at=NOW,
        updated_at=NOW,
    )
    assert parsed.cancel_requested is True
    assert parsed.current_item_progress == 40.5


def test_media_asset_out_thumbnail_path_is_optional():
    asset = MediaAssetOut(
        id=uuid4(),
        canonical_id="youtube:abc",
        options_hash="d" * 64,
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=NOW,
    )
    assert asset.thumbnail_path is None

    with_thumb = MediaAssetOut(
        id=uuid4(),
        canonical_id="youtube:abc",
        options_hash="d" * 64,
        thumbnail_path="thumbnails/abc.jpg",
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=NOW,
    )
    assert with_thumb.thumbnail_path == "thumbnails/abc.jpg"


def test_download_request_validates_url_kind_format_and_key():
    request = DownloadRequest(url="https://example.test/v")
    assert request.kind == "video"
    assert request.format == "best"
    assert request.embed_subs is False
    assert request.idempotency_key is None

    with pytest.raises(ValidationError):
        DownloadRequest(url="ftp://example.test/v")
    with pytest.raises(ValidationError):
        DownloadRequest(url="https://user:pass@example.test/v")
    with pytest.raises(ValidationError):
        DownloadRequest(url="https://example.test/v", format="4k")
    with pytest.raises(ValidationError):
        DownloadRequest(url="https://example.test/v", kind="book")
    with pytest.raises(ValidationError):
        DownloadRequest(url="https://example.test/v", idempotency_key="k" * 201)


def test_info_out_parses_video_and_playlist_payloads():
    video = InfoOut.model_validate(
        {
            "type": "video",
            "id": "abc",
            "title": "Clip",
            "canonical_id": "youtube:abc",
            "extractor_key": "youtube",
            "duration": 12,
            "thumbnail": "https://img.example.test/t.jpg",
            "formats": {"heights": [720], "has_720p": True, "has_audio": True},
            "entries": None,
            "item_count": 1,
            "truncated": False,
        }
    )
    assert video.canonical_id == "youtube:abc"
    assert video.entries is None
    assert video.formats["heights"] == [720]

    playlist = InfoOut.model_validate(
        {
            "type": "playlist",
            "id": "PL1",
            "title": "List",
            "canonical_id": "youtube:PL1",
            "entries": [
                {
                    "id": "one",
                    "title": "One",
                    "url": "https://example.test/one",
                    "canonical_id": "youtube:one",
                }
            ],
            "item_count": 1,
            "truncated": True,
        }
    )
    assert playlist.type == "playlist"
    assert playlist.entries[0].canonical_id == "youtube:one"
    assert playlist.truncated is True

    with pytest.raises(ValidationError):
        InfoOut.model_validate({"type": "stream"})


def test_download_job_list_shape():
    item = DownloadJobOut(
        id=uuid4(),
        user_id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
    )

    listing = DownloadJobList(items=[item], total=1, limit=50, offset=0)

    assert listing.items[0].id == item.id
    assert listing.total == 1


def test_media_token_out_accepts_thumbnail_url():
    token = MediaTokenOut(
        token="payload.signature",
        url="/api/media/abc?token=payload.signature",
        thumbnail_url="/api/thumbnails/abc?token=payload.signature",
        expires_at=NOW,
        expires_in=900,
    )
    assert token.thumbnail_url.endswith("payload.signature")

    without_thumbnail = MediaTokenOut(
        token="payload.signature",
        url="/api/media/abc?token=payload.signature",
        expires_at=NOW,
        expires_in=900,
    )
    assert without_thumbnail.thumbnail_url is None


def test_playlist_models_parse_schema_rows():
    playlist_id = uuid4()
    user_id = uuid4()
    playlist = PlaylistOut.model_validate(
        {
            "id": playlist_id,
            "user_id": user_id,
            "canonical_id": "youtube:PL1",
            "source_url": "https://example.test/list",
            "title": "List",
            "channel": "Channel",
            "thumbnail_path": "playlists/cover.jpg",
            "item_count": 1,
            "options_hash": "a" * 64,
            "format_selector": "best",
            "status": "ready",
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    item = PlaylistItemOut.model_validate(
        {
            "id": uuid4(),
            "playlist_id": playlist_id,
            "position": 1,
            "canonical_id": "youtube:vid1",
            "source_url": "https://example.test/v1",
            "title": "One",
            "duration_seconds": 12,
            "asset_id": uuid4(),
            "job_id": None,
            "status": "ready",
            "error": "",
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    detail = PlaylistDetailOut.model_validate(
        {**playlist.model_dump(), "items": [item.model_dump()]}
    )

    assert detail.items[0].position == 1
    assert detail.items[0].duration_seconds == 12
    assert PlaylistList(
        items=[playlist], total=1, limit=50, offset=0
    ).items[0].item_count == 1

    with pytest.raises(ValidationError):
        PlaylistOut.model_validate(
            {
                **playlist.model_dump(),
                "status": "exploded",
            }
        )


def test_error_envelope_shape():
    error = ErrorResponse.model_validate(
        {
            "error": {
                "code": "approval_required",
                "message": "Your account is awaiting administrator approval.",
            }
        }
    )

    assert error.error.code == "approval_required"
    assert "approval" in error.error.message


def test_library_models_parse_a_ready_item():
    job_id = uuid4()
    asset_id = uuid4()
    item = LibraryItemOut.model_validate(
        {
            "job_id": job_id,
            "asset_id": asset_id,
            "title": "Clip",
            "file_size_bytes": 2048,
            "output_ext": "mp4",
            "thumbnail_path": "thumbnails/a.jpg",
            "created_at": NOW,
            "status": "ready",
            "format_selector": "best",
            "playlist_id": None,
        }
    )

    assert item.job_id == job_id
    assert item.asset_id == asset_id
    assert item.file_size_bytes == 2048
    assert item.playlist_id is None

    listing = LibraryList(items=[item], total=1, limit=50, offset=0)
    assert listing.items[0].title == "Clip"
    assert listing.total == 1

    with pytest.raises(ValidationError):
        LibraryItemOut.model_validate(
            {
                "job_id": job_id,
                "created_at": NOW,
                "status": "exploded",
            }
        )


def test_admin_job_out_adds_the_owner_email():
    base = {
        "id": uuid4(),
        "user_id": uuid4(),
        "created_at": NOW,
        "updated_at": NOW,
    }

    default = AdminJobOut(**base)
    labelled = AdminJobOut(**base, user_email="owner@example.test")
    listing = AdminJobList(items=[labelled], total=1, limit=50, offset=0)

    assert default.user_email == ""
    assert listing.items[0].user_email == "owner@example.test"
    assert isinstance(listing.items[0], DownloadJobOut)


def test_admin_asset_out_adds_usage_counts():
    asset = AdminAssetOut(
        id=uuid4(),
        canonical_id="youtube:abc",
        options_hash="d" * 64,
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=NOW,
    )
    counted = AdminAssetOut(
        id=uuid4(),
        canonical_id="youtube:def",
        options_hash="e" * 64,
        job_count=3,
        user_count=2,
        created_at=NOW,
        updated_at=NOW,
        last_accessed_at=NOW,
    )
    listing = AdminAssetList(
        items=[counted], total=1, limit=50, offset=0, disk_free_bytes=1234
    )

    assert asset.job_count == 0
    assert asset.user_count == 0
    assert counted.job_count == 3
    assert counted.user_count == 2
    assert listing.disk_free_bytes == 1234
