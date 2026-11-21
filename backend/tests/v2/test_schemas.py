"""Tests for the v2 Pydantic response models."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from backend.app.models.schemas import (
    AdminUserList,
    DownloadJobOut,
    ErrorResponse,
    HealthOut,
    MediaAssetOut,
    MediaTokenOut,
    MeOut,
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
