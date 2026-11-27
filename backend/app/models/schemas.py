"""Pydantic v2 request/response models aligned with the database schema.

Timestamps are timezone-aware ``datetime`` values and identifiers are UUIDs.
The models intentionally mirror the database columns so routers can hand
``dict(record)`` straight to Pydantic without ad-hoc reshaping.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

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


class AuthRegister(BaseModel):
    """Email/password sign-up payload."""

    email: str = ""
    password: str = ""


class AuthLogin(BaseModel):
    """Email/password sign-in payload."""

    email: str = ""
    password: str = ""


class AuthSessionOut(_ORMModel):
    """A new session plus the profile it belongs to.

    ``token`` is the only time the raw opaque token exists; only its SHA-256
    hash is stored server-side.
    """

    token: str
    expires_at: datetime
    profile: ProfileOut


class ChangePassword(BaseModel):
    """Self-service password change for the signed-in user."""

    current_password: str = ""
    new_password: str = ""


class AdminPasswordReset(BaseModel):
    """Administrator password reset for another account."""

    password: str = ""


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
    cover_url: str | None = None
    thumbnail_path: str | None = None
    thumbnail_url: str | None = None
    duration_seconds: int | None = None
    file_size_bytes: int | None = None
    output_ext: str | None = None
    format_selector: str = ""
    playlist_id: UUID | None = None
    status: JobStatus = "ready"
    downloaded_at: datetime
    updated_at: datetime


class TrackUpdate(BaseModel):
    """Editable per-user track metadata.

    Every field is optional, but an empty body is invalid. Values are trimmed
    and limited to 200 characters; an empty string deliberately clears a field.
    """

    custom_title: str | None = None
    custom_artist: str | None = None
    custom_album: str | None = None

    @field_validator(
        "custom_title", "custom_artist", "custom_album", mode="before"
    )
    @classmethod
    def _validate_metadata(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Track metadata values must be strings.")
        trimmed = value.strip()
        if len(trimmed) > 200:
            raise ValueError(
                "Track metadata values must be at most 200 characters."
            )
        return trimmed

    @model_validator(mode="after")
    def _require_a_field(self) -> "TrackUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one track metadata field is required.")
        return self


class TrackList(_ORMModel):
    """One page of the caller's tracks."""

    items: list[TrackOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class FacetItem(BaseModel):
    """A distinct artist or album name and how many tracks use it."""

    name: str
    track_count: int


class FacetList(BaseModel):
    """Autocomplete choices for a track metadata field."""

    items: list[FacetItem] = Field(default_factory=list)


CoverContentType = Literal["image/jpeg", "image/png", "image/webp"]


class CoverUpload(BaseModel):
    """A base64-encoded cover image and its declared media type."""

    content_type: CoverContentType
    data: str = Field(min_length=1)


class CoverOut(_ORMModel):
    """The stored path and a freshly signed URL for a track cover."""

    cover_path: str
    cover_url: str


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
    channel: str = ""
    duration_seconds: int | None = None
    asset_id: UUID | None = None
    job_id: UUID | None = None
    status: PlaylistItemStatus = "pending"
    error: str = ""
    thumbnail_url: str | None = None
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


USER_PLAYLIST_NAME_MAX = 200
USER_PLAYLIST_DESCRIPTION_MAX = 500
USER_PLAYLIST_SHARE_EMAIL_MAX = 254

# The same pragmatic address shape used for sign-up: a local part plus at least
# one dotted domain label. The service still resolves the address against the
# profiles table; this only rejects obvious garbage before a database round-trip.
_SHARE_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)


def _trim_playlist_name(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Playlist name must be a string.")
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("Playlist name is required.")
    if len(trimmed) > USER_PLAYLIST_NAME_MAX:
        raise ValueError(
            "Playlist name must be at most "
            f"{USER_PLAYLIST_NAME_MAX} characters."
        )
    return trimmed


def _trim_playlist_description(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Playlist description must be a string.")
    trimmed = value.strip()
    if len(trimmed) > USER_PLAYLIST_DESCRIPTION_MAX:
        raise ValueError(
            "Playlist description must be at most "
            f"{USER_PLAYLIST_DESCRIPTION_MAX} characters."
        )
    return trimmed


class UserPlaylistOut(_ORMModel):
    """A per-user curated playlist with a count of its visible tracks.

    ``is_owner`` is ``False`` for a playlist shared with the caller, and
    ``owner_email`` names the account that owns it.
    """

    id: UUID
    user_id: UUID
    name: str
    description: str = ""
    cover_path: str | None = None
    track_count: int = 0
    owner_email: str = ""
    is_owner: bool = True
    created_at: datetime
    updated_at: datetime


class UserPlaylistDetailOut(UserPlaylistOut):
    """A curated playlist plus its visible tracks in playlist order."""

    items: list[TrackOut] = Field(default_factory=list)


class UserPlaylistList(_ORMModel):
    """One page of the caller's curated playlists."""

    items: list[UserPlaylistOut] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class UserPlaylistCreate(BaseModel):
    """Create a curated playlist. The name and description are trimmed."""

    name: str
    description: str = ""

    @field_validator("name", mode="before")
    @classmethod
    def _validate_name(cls, value: Any) -> str:
        return _trim_playlist_name(value)

    @field_validator("description", mode="before")
    @classmethod
    def _validate_description(cls, value: Any) -> str:
        return _trim_playlist_description(value)


class UserPlaylistUpdate(BaseModel):
    """Edit a curated playlist. An empty body is invalid."""

    name: str | None = None
    description: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _validate_name(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _trim_playlist_name(value)

    @field_validator("description", mode="before")
    @classmethod
    def _validate_description(cls, value: Any) -> str | None:
        if value is None:
            return None
        return _trim_playlist_description(value)

    @model_validator(mode="after")
    def _require_a_field(self) -> "UserPlaylistUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one playlist field is required.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Playlist name cannot be null.")
        return self


class UserPlaylistAddTrack(BaseModel):
    """Add one of the caller's tracks to a curated playlist."""

    track_id: UUID


class UserPlaylistOrder(BaseModel):
    """A complete, new ordering of a curated playlist's tracks."""

    track_ids: list[UUID] = Field(default_factory=list)


class UserPlaylistShareCreate(BaseModel):
    """Share a curated playlist with the account behind ``email``."""

    email: str

    @field_validator("email", mode="before")
    @classmethod
    def _validate_email(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("Enter a valid email address.")
        candidate = value.strip().lower()
        if (
            not candidate
            or len(candidate) > USER_PLAYLIST_SHARE_EMAIL_MAX
            or not _SHARE_EMAIL_RE.match(candidate)
        ):
            raise ValueError("Enter a valid email address.")
        return candidate


class UserPlaylistShareOut(_ORMModel):
    """One account a curated playlist is shared with."""

    user_id: UUID
    email: str
    created_at: datetime


class UserPlaylistShareList(_ORMModel):
    """Every account a curated playlist is shared with."""

    items: list[UserPlaylistShareOut] = Field(default_factory=list)


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
