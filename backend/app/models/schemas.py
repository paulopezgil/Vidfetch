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
PlaylistStatus = Literal[
    "pending",
    "downloading",
    "ready",
    "partial",
    "failed",
    "cancelled",
]
PlaylistItemStatus = Literal[
    "pending",
    "downloading",
    "ready",
    "failed",
    "cancelled",
]
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
    thumbnail_url: str | None = None
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


class LibraryItemOut(_ORMModel):
    """A ready media asset from the caller's library.

    The row is keyed by the caller's job so a library entry can be hidden
    without deleting the shared asset or the download history.
    """

    job_id: UUID
    asset_id: UUID | None = None
    title: str = ""
    file_size_bytes: int | None = None
    output_ext: str | None = None
    thumbnail_path: str | None = None
    created_at: datetime
    status: JobStatus = "ready"
    format_selector: str = ""
    playlist_id: UUID | None = None


class LibraryList(_ORMModel):
    """One page of the caller's library."""

    items: list[LibraryItemOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class TrackOut(_ORMModel):
    """A per-user track over a shared media asset.

    ``title``/``artist``/``album`` are the user-editable track metadata; the
    remaining fields come from the representative ready job and the asset.
    """

    id: UUID
    asset_id: UUID
    job_id: UUID
    canonical_id: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    cover_path: str | None = None
    thumbnail_path: str | None = None
    duration_seconds: int | None = None
    file_size_bytes: int | None = None
    output_ext: str | None = None
    format_selector: str = ""
    playlist_id: UUID | None = None
    downloaded_at: datetime
    updated_at: datetime


class TrackList(_ORMModel):
    """One page of the caller's tracks."""

    items: list[TrackOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class AdminJobOut(DownloadJobOut):
    """An admin-wide job row, including the owner's email address."""

    user_email: str = ""


class AdminJobList(_ORMModel):
    """One page of all users' jobs for the admin inventory."""

    items: list[AdminJobOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class AdminAssetOut(MediaAssetOut):
    """A global media asset plus how many jobs and users reference it."""

    job_count: int = 0
    user_count: int = 0


class AdminAssetList(_ORMModel):
    """One page of the asset cache inventory and the current free space."""

    items: list[AdminAssetOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
    disk_free_bytes: int


class PlaylistItemOut(_ORMModel):
    """One row from the configured schema's ``playlist_items`` table.

    ``id``/``playlist_id`` and timestamps are optional so callers that only
    need the user-facing item fields can validate a partial mapping.
    """

    id: UUID | None = None
    playlist_id: UUID | None = None
    position: int
    canonical_id: str = ""
    source_url: str = ""
    title: str = ""
    duration_seconds: int | None = None
    asset_id: UUID | None = None
    job_id: UUID | None = None
    status: PlaylistItemStatus = "pending"
    error: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PlaylistOut(_ORMModel):
    """A per-user playlist row."""

    id: UUID
    user_id: UUID
    canonical_id: str
    source_url: str = ""
    title: str = ""
    channel: str = ""
    thumbnail_path: str | None = None
    item_count: int = 0
    options_hash: str
    format_selector: str = ""
    status: PlaylistStatus = "pending"
    created_at: datetime
    updated_at: datetime


class PlaylistDetailOut(PlaylistOut):
    """A playlist plus its ordered items."""

    items: list[PlaylistItemOut] = Field(default_factory=list)


class PlaylistList(_ORMModel):
    """One page of the caller's playlists."""

    items: list[PlaylistOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class InfoRequest(BaseModel):
    """Ask the backend to resolve metadata for a video or playlist URL."""

    url: str = Field(min_length=1, max_length=2048)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        return validate_http_url(value)


class DownloadRequest(BaseModel):
    """Create a video or playlist download job."""

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
