"""Tests for v2 environment configuration."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.core.config import ConfigError, Settings

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_from_env_defaults_are_import_safe():
    settings = Settings.from_env({})

    assert settings.supabase_url == ""
    assert settings.supabase_jwks_url == ""
    assert settings.supabase_jwt_issuer == ""
    assert settings.supabase_jwt_audience == "authenticated"
    assert settings.database_url == ""
    assert settings.media_token_secret == ""
    assert settings.media_token_ttl_seconds == 900
    assert settings.max_concurrent_downloads == 2
    assert settings.max_concurrent_jobs_per_user == 2
    assert settings.max_playlist_items == 200
    assert settings.max_asset_bytes > 0
    assert settings.min_free_disk_mb == 500
    assert settings.job_lease_seconds == 300
    assert settings.allow_private_urls is False
    assert settings.cors_origins == []
    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert isinstance(settings.download_dir, Path)
    assert settings.frontend_dist == (Path.cwd() / "frontend-dist").resolve()


def test_supabase_url_derives_jwks_and_issuer():
    settings = Settings.from_env({"SUPABASE_URL": "https://proj.supabase.co/"})

    assert settings.supabase_url == "https://proj.supabase.co"
    assert (
        settings.supabase_jwks_url
        == "https://proj.supabase.co/auth/v1/.well-known/jwks.json"
    )
    assert settings.supabase_jwt_issuer == "https://proj.supabase.co/auth/v1"


def test_explicit_supabase_values_override_derived_defaults():
    settings = Settings.from_env(
        {
            "SUPABASE_URL": "https://proj.supabase.co",
            "SUPABASE_JWKS_URL": "https://keys.example.test/jwks.json",
            "SUPABASE_JWT_ISSUER": "https://issuer.example.test",
            "SUPABASE_JWT_AUDIENCE": "custom-aud",
            "SUPABASE_JWT_SECRET": "legacy-secret",
            "SUPABASE_ANON_KEY": "anon",
            "SUPABASE_SERVICE_ROLE_KEY": "service",
        }
    )

    assert settings.supabase_jwks_url == "https://keys.example.test/jwks.json"
    assert settings.supabase_jwt_issuer == "https://issuer.example.test"
    assert settings.supabase_jwt_audience == "custom-aud"
    assert settings.supabase_jwt_secret == "legacy-secret"
    assert settings.supabase_anon_key == "anon"
    assert settings.supabase_service_role_key == "service"


def test_database_url_prefers_database_url_then_supabase_db_url():
    preferred = Settings.from_env(
        {
            "DATABASE_URL": "postgresql://primary/db",
            "SUPABASE_DB_URL": "postgresql://fallback/db",
        }
    )
    fallback = Settings.from_env({"SUPABASE_DB_URL": "postgresql://fallback/db"})

    assert preferred.database_url == "postgresql://primary/db"
    assert fallback.database_url == "postgresql://fallback/db"


def test_numeric_and_list_settings_parse():
    settings = Settings.from_env(
        {
            "DOWNLOAD_DIR": "/var/lib/vidfetch/media",
            "FRONTEND_DIST": "/srv/vidfetch/frontend-dist",
            "MEDIA_TOKEN_TTL_SECONDS": "120",
            "MAX_CONCURRENT_DOWNLOADS": "4",
            "MAX_CONCURRENT_JOBS_PER_USER": "3",
            "MAX_PLAYLIST_ITEMS": "50",
            "MAX_ASSET_BYTES": "12345",
            "MIN_FREE_DISK_MB": "0",
            "JOB_LEASE_SECONDS": "45",
            "ALLOW_PRIVATE_URLS": "true",
            "CORS_ORIGINS": "https://a.test, https://b.test ,",
            "ENVIRONMENT": "production",
            "LOG_LEVEL": "debug",
        }
    )

    assert settings.download_dir == Path("/var/lib/vidfetch/media").resolve()
    assert settings.frontend_dist == Path("/srv/vidfetch/frontend-dist").resolve()
    assert settings.media_token_ttl_seconds == 120
    assert settings.max_concurrent_downloads == 4
    assert settings.max_concurrent_jobs_per_user == 3
    assert settings.max_playlist_items == 50
    assert settings.max_asset_bytes == 12345
    assert settings.min_free_disk_mb == 0
    assert settings.job_lease_seconds == 45
    assert settings.allow_private_urls is True
    assert settings.cors_origins == ["https://a.test", "https://b.test"]
    assert settings.environment == "production"
    assert settings.log_level == "DEBUG"


def test_cors_wildcard_is_preserved():
    assert Settings.from_env({"CORS_ORIGINS": "*"}).cors_origins == ["*"]


def test_frontend_dist_defaults_to_cwd_and_reads_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    default = Settings.from_env({})
    explicit = Settings.from_env({"FRONTEND_DIST": "static-ui"})

    assert default.frontend_dist == (tmp_path / "frontend-dist").resolve()
    assert explicit.frontend_dist == (tmp_path / "static-ui").resolve()


@pytest.mark.parametrize(
    "name,value",
    [
        ("MEDIA_TOKEN_TTL_SECONDS", "soon"),
        ("MAX_CONCURRENT_DOWNLOADS", "0"),
        ("MAX_CONCURRENT_JOBS_PER_USER", "-1"),
        ("MAX_PLAYLIST_ITEMS", "zero"),
        ("MIN_FREE_DISK_MB", "-5"),
        ("JOB_LEASE_SECONDS", "1.5"),
        ("ALLOW_PRIVATE_URLS", "maybe"),
    ],
)
def test_invalid_numeric_settings_raise_config_error(name, value):
    with pytest.raises(ConfigError):
        Settings.from_env({name: value})


def test_validate_runtime_lists_every_missing_requirement():
    settings = Settings.from_env({})

    with pytest.raises(ConfigError) as excinfo:
        settings.validate_runtime()

    message = str(excinfo.value)
    for expected in (
        "SUPABASE_URL",
        "DATABASE_URL",
        "MEDIA_TOKEN_SECRET",
        "SUPABASE_JWKS_URL",
    ):
        assert expected in message


def test_validate_runtime_accepts_jwks_configuration():
    settings = Settings.from_env(
        {
            "SUPABASE_URL": "https://proj.supabase.co",
            "DATABASE_URL": "postgresql://user:pass@pooler/db",
            "MEDIA_TOKEN_SECRET": "media-secret",
        }
    )

    settings.validate_runtime()


def test_validate_runtime_accepts_legacy_shared_secret():
    settings = Settings.from_env(
        {
            "SUPABASE_URL": "https://proj.supabase.co",
            "SUPABASE_JWT_SECRET": "shared-secret",
            "DATABASE_URL": "postgresql://user:pass@pooler/db",
            "MEDIA_TOKEN_SECRET": "media-secret",
        }
    )

    settings.validate_runtime()


def test_import_does_not_require_environment():
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", "/tmp"),
        "PYTHONPATH": str(REPO_ROOT),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import backend.app.core.config, backend.app.core.security, "
            "backend.app.services.storage",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
