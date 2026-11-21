"""Runtime configuration for the v2 backend.

Configuration is read from environment variables only. Importing this module
must never require environment variables to be present: tests import it, and
tools import it without a database or Supabase project. Call
:meth:`Settings.validate_runtime` from application startup to fail fast with a
clear message when required values are missing.

The v1 settings in :mod:`backend.config` are intentionally left alone; v2 code
uses the dataclass below so a bad environment cannot break v1 imports.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

DEFAULT_JWT_AUDIENCE = "authenticated"
DEFAULT_MEDIA_TOKEN_TTL_SECONDS = 900
DEFAULT_MAX_CONCURRENT_DOWNLOADS = 2
DEFAULT_MAX_CONCURRENT_JOBS_PER_USER = 2
DEFAULT_MAX_PLAYLIST_ITEMS = 200
DEFAULT_MAX_ASSET_BYTES = 5 * 1024 * 1024 * 1024
DEFAULT_MIN_FREE_DISK_MB = 500
DEFAULT_JOB_LEASE_SECONDS = 300


class ConfigError(RuntimeError):
    """Raised when configuration is missing or malformed."""


def _env_int(
    env: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int | None = None,
) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw.strip())
        except ValueError:
            raise ConfigError(
                f"Invalid integer for {name}: {raw!r}"
            ) from None
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} must be >= {minimum} (got {value}).")
    return value


def _split_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _clean_url(raw: str | None) -> str:
    return (raw or "").strip().rstrip("/")


@dataclass
class Settings:
    """All v2 runtime settings with safe, import-time-free defaults."""

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwks_url: str = ""
    supabase_jwt_issuer: str = ""
    supabase_jwt_audience: str = DEFAULT_JWT_AUDIENCE
    supabase_jwt_secret: str = ""

    database_url: str = ""
    download_dir: Path = field(default_factory=lambda: (Path.cwd() / "downloads").resolve())
    frontend_dist: Path = field(
        default_factory=lambda: (Path.cwd() / "frontend-dist").resolve()
    )

    media_token_secret: str = ""
    media_token_ttl_seconds: int = DEFAULT_MEDIA_TOKEN_TTL_SECONDS

    max_concurrent_downloads: int = DEFAULT_MAX_CONCURRENT_DOWNLOADS
    max_concurrent_jobs_per_user: int = DEFAULT_MAX_CONCURRENT_JOBS_PER_USER
    max_playlist_items: int = DEFAULT_MAX_PLAYLIST_ITEMS
    max_asset_bytes: int = DEFAULT_MAX_ASSET_BYTES
    min_free_disk_mb: int = DEFAULT_MIN_FREE_DISK_MB
    job_lease_seconds: int = DEFAULT_JOB_LEASE_SECONDS

    cors_origins: list[str] = field(default_factory=list)
    environment: str = "development"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        """Build settings from ``environ`` (defaults to ``os.environ``).

        Never raises for absent variables. Malformed integers do raise
        :class:`ConfigError`, because silently substituting a default would
        hide an operator typo in a limit that protects the disk or workers.
        """
        env = os.environ if environ is None else environ

        supabase_url = _clean_url(env.get("SUPABASE_URL"))
        derived_jwks = (
            f"{supabase_url}/auth/v1/.well-known/jwks.json" if supabase_url else ""
        )
        derived_issuer = f"{supabase_url}/auth/v1" if supabase_url else ""

        database_url = (
            env.get("DATABASE_URL", "").strip()
            or env.get("SUPABASE_DB_URL", "").strip()
        )

        download_raw = env.get("DOWNLOAD_DIR", "").strip()
        download_dir = (
            Path(download_raw).expanduser().resolve()
            if download_raw
            else (Path.cwd() / "downloads").resolve()
        )

        frontend_raw = env.get("FRONTEND_DIST", "").strip()
        frontend_dist = (
            Path(frontend_raw).expanduser().resolve()
            if frontend_raw
            else (Path.cwd() / "frontend-dist").resolve()
        )

        cors_raw = env.get("CORS_ORIGINS")
        if cors_raw is not None and cors_raw.strip() == "*":
            cors_origins = ["*"]
        else:
            cors_origins = _split_csv(cors_raw)

        return cls(
            supabase_url=supabase_url,
            supabase_anon_key=env.get("SUPABASE_ANON_KEY", "").strip(),
            supabase_service_role_key=env.get(
                "SUPABASE_SERVICE_ROLE_KEY", ""
            ).strip(),
            supabase_jwks_url=env.get("SUPABASE_JWKS_URL", "").strip()
            or derived_jwks,
            supabase_jwt_issuer=env.get("SUPABASE_JWT_ISSUER", "").strip()
            or derived_issuer,
            supabase_jwt_audience=env.get(
                "SUPABASE_JWT_AUDIENCE", DEFAULT_JWT_AUDIENCE
            ).strip()
            or DEFAULT_JWT_AUDIENCE,
            supabase_jwt_secret=env.get("SUPABASE_JWT_SECRET", "").strip(),
            database_url=database_url,
            download_dir=download_dir,
            frontend_dist=frontend_dist,
            media_token_secret=env.get("MEDIA_TOKEN_SECRET", "").strip(),
            media_token_ttl_seconds=_env_int(
                env,
                "MEDIA_TOKEN_TTL_SECONDS",
                DEFAULT_MEDIA_TOKEN_TTL_SECONDS,
                minimum=1,
            ),
            max_concurrent_downloads=_env_int(
                env,
                "MAX_CONCURRENT_DOWNLOADS",
                DEFAULT_MAX_CONCURRENT_DOWNLOADS,
                minimum=1,
            ),
            max_concurrent_jobs_per_user=_env_int(
                env,
                "MAX_CONCURRENT_JOBS_PER_USER",
                DEFAULT_MAX_CONCURRENT_JOBS_PER_USER,
                minimum=1,
            ),
            max_playlist_items=_env_int(
                env,
                "MAX_PLAYLIST_ITEMS",
                DEFAULT_MAX_PLAYLIST_ITEMS,
                minimum=1,
            ),
            max_asset_bytes=_env_int(
                env,
                "MAX_ASSET_BYTES",
                DEFAULT_MAX_ASSET_BYTES,
                minimum=1,
            ),
            min_free_disk_mb=_env_int(
                env,
                "MIN_FREE_DISK_MB",
                DEFAULT_MIN_FREE_DISK_MB,
                minimum=0,
            ),
            job_lease_seconds=_env_int(
                env,
                "JOB_LEASE_SECONDS",
                DEFAULT_JOB_LEASE_SECONDS,
                minimum=1,
            ),
            cors_origins=cors_origins,
            environment=env.get("ENVIRONMENT", "development").strip()
            or "development",
            log_level=(env.get("LOG_LEVEL", "INFO").strip() or "INFO").upper(),
        )

    def validate_runtime(self) -> None:
        """Raise :class:`ConfigError` when startup-required values are absent.

        Called from the application lifespan, never at import time.
        """
        missing: list[str] = []
        if not self.supabase_url:
            missing.append("SUPABASE_URL")
        if not self.database_url:
            missing.append("DATABASE_URL (or SUPABASE_DB_URL)")
        if not self.media_token_secret:
            missing.append("MEDIA_TOKEN_SECRET")
        if not self.supabase_jwt_secret and not self.supabase_jwks_url:
            missing.append("SUPABASE_JWKS_URL (or SUPABASE_JWT_SECRET)")
        if missing:
            raise ConfigError(
                "Missing required configuration: " + ", ".join(missing)
            )
