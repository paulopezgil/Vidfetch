"""Pydantic v2 request/response models aligned with the Supabase schema.

Timestamps are timezone-aware ``datetime`` values and identifiers are UUIDs.
The models intentionally mirror the database columns so routers can hand
``dict(record)`` straight to Pydantic without ad-hoc reshaping.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


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


class ErrorDetail(_ORMModel):
    code: str
    message: str


class ErrorResponse(_ORMModel):
    """Consistent error envelope from the API specification."""

    error: ErrorDetail
