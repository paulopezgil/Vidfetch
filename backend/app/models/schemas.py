"""Pydantic v2 request/response models aligned with the Supabase schema.

Timestamps are timezone-aware ``datetime`` values and identifiers are UUIDs.
The models intentionally mirror the database columns so routers can hand
``dict(record)`` straight to Pydantic without ad-hoc reshaping.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.urls import validate_http_url

AppRole = Literal["user", "admin"]
AssetStatus = Literal["processing", "ready", "failed"]
JobKind = Literal["video", "playlist", "playlist_item"]
JobStatus = Literal[
    "queued",
    "resolving",
    "downloading",
    "processing",
    "ready",
    "failed",
    "cancelled",
]
HealthStatus = Literal["ok", "degraded", "unavailable"]
DownloadKind = Literal["video", "playlist"]
FormatName = Literal["best", "720p", "mp3"]


class _ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProfileOut(_ORMModel):
    """A user's application profile."""

    id: UUID
    email: str = ""
    is_approved: bool = False
    app_role: AppRole = "user"
    created_at: datetime
    updated_at: datetime


class MeOut(ProfileOut):
    """The caller's own profile (``GET /api/me``)."""


class StorageHealth(_ORMModel):
    free_bytes: int
    writable: bool


class HealthOut(_ORMModel):
    """Public health payload. Contains no secrets or user data."""

    status: HealthStatus
    version: str
    yt_dlp_version: str | None = None
    database: bool
    auth: bool
    storage: StorageHealth
    dependencies: dict[str, bool] = Field(default_factory=dict)


class MediaTokenOut(_ORMModel):
    """A short-lived signed media URL."""

    token: str
    url: str
    expires_at: datetime
    expires_in: int


class AdminUserList(_ORMModel):
    items: list[ProfileOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class RoleUpdate(BaseModel):
    app_role: AppRole


class DownloadJobOut(_ORMModel):
    """A per-user download job / history entry."""

    id: UUID
    user_id: UUID
    asset_id: UUID | None = None
    playlist_id: UUID | None = None
    kind: JobKind = "video"
    source_url: str = ""
    title: str = ""
    options_hash: str = ""
    format_selector: str = ""
    idempotency_key: str | None = None
    status: JobStatus = "queued"
    progress: float = 0
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed: float = 0
    eta_seconds: int | None = None
    error: str = ""
    attempts: int = 0
    cancel_requested: bool = False
    item_index: int = 0
    item_count: int = 0
    current_item_title: str = ""
    current_item_progress: float = 0
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class DownloadJobList(_ORMModel):
    """One page of the caller's download jobs."""

    items: list[DownloadJobOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class MediaAssetOut(_ORMModel):
    """A row from the global media deduplication cache."""

    id: UUID
    canonical_id: str
    extractor_key: str = ""
    source_url: str = ""
    title: str = ""
    duration_seconds: int | None = None
    options_hash: str
    options_schema_version: int = 1
    format_selector: str = ""
    output_ext: str | None = None
    file_path: str | None = None
    thumbnail_path: str | None = None
    file_size_bytes: int | None = None
    file_sha256: str | None = None
    status: AssetStatus = "processing"
    error: str = ""
    attempts: int = 0
    claimed_at: datetime | None = None
    lease_until: datetime | None = None
    created_at: datetime
    updated_at: datetime
    last_accessed_at: datetime


class InfoRequest(BaseModel):
    """Ask the backend to resolve metadata for a video or playlist URL."""

    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        return validate_http_url(value)


class DownloadRequest(BaseModel):
    """Create a download job (single video; playlists arrive later)."""

    url: str = Field(min_length=1, max_length=2048)
    kind: DownloadKind = "video"
    format: FormatName = "best"
    embed_subs: bool = False
    playlist_id: UUID | None = None
    idempotency_key: str | None = Field(default=None, max_length=200)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        return validate_http_url(value)


class InfoEntry(_ORMModel):
    """One flat playlist entry returned by yt-dlp metadata extraction."""

    id: str | None = None
    title: str = ""
    url: str | None = None
    duration: float | None = None
    thumbnail: str | None = None
    canonical_id: str = ""


class InfoOut(_ORMModel):
    """Normalized metadata for a single video or a playlist preview."""

    type: Literal["video", "playlist"]
    id: str | None = None
    title: str = ""
    canonical_id: str = ""
    extractor_key: str = ""
    duration: float | None = None
    thumbnail: str | None = None
    webpage_url: str | None = None
    channel: str | None = None
    formats: dict[str, Any] | None = None
    entries: list[InfoEntry] | None = None
    item_count: int = 0
    truncated: bool = False


class ErrorDetail(_ORMModel):
    code: str
    message: str


class ErrorResponse(_ORMModel):
    """Consistent error envelope from the API specification."""

    error: ErrorDetail
