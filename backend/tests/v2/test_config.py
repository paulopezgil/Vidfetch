"""Tests for v2 environment configuration."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.core.config import (
    ConfigError,
    Settings,
    validate_schema_name,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_from_env_defaults_are_import_safe():
    settings = Settings.from_env({})

    assert settings.database_url == ""
    assert settings.db_schema == "public"
    assert settings.auth_session_ttl_seconds == 2_592_000
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
    assert settings.public_api_url == ""


def test_supabase_settings_are_gone_and_ignored():
    settings = Settings.from_env(
        {
            "SUPABASE_URL": "https://proj.supabase.co",
            "SUPABASE_JWKS_URL": "https://keys.example.test/jwks.json",
            "SUPABASE_JWT_SECRET": "legacy-secret",
            "SUPABASE_ANON_KEY": "anon",
            "SUPABASE_SERVICE_ROLE_KEY": "service",
            "SUPABASE_DB_URL": "postgresql://fallback/db",
        }
    )

    # Local auth has no Supabase settings left to read, including the old
    # database-URL fallback.
    for name in (
        "supabase_url",
        "supabase_jwks_url",
        "supabase_jwt_issuer",
        "supabase_jwt_audience",
        "supabase_jwt_secret",
        "supabase_anon_key",
        "supabase_service_role_key",
    ):
        assert not hasattr(settings, name)
    assert settings.database_url == ""


def test_auth_session_ttl_is_configurable_with_a_minimum():
    default = Settings.from_env({})
    custom = Settings.from_env({"AUTH_SESSION_TTL_SECONDS": "3600"})
    minimum = Settings.from_env({"AUTH_SESSION_TTL_SECONDS": "60"})

    assert default.auth_session_ttl_seconds == 2_592_000
    assert custom.auth_session_ttl_seconds == 3600
    assert minimum.auth_session_ttl_seconds == 60

    with pytest.raises(ConfigError) as excinfo:
        Settings.from_env({"AUTH_SESSION_TTL_SECONDS": "59"})
    assert "AUTH_SESSION_TTL_SECONDS" in str(excinfo.value)


def test_db_schema_defaults_to_public_and_reads_env():
    default = Settings.from_env({})
    custom = Settings.from_env({"DB_SCHEMA": "vidfetch"})

    assert default.db_schema == "public"
    assert custom.db_schema == "vidfetch"


@pytest.mark.parametrize(
    "value",
    [
        "public",
        "vidfetch",
        "my_schema",
        "_internal",
        "a",
        "a" * 63,
    ],
)
def test_validate_schema_name_accepts_application_schemas(value):
    assert validate_schema_name(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "Vidfetch",
        "vid-fetch",
        "1vidfetch",
        "vid fetch",
        "a" * 64,
        "public; drop table profiles",
        'vidfetch"',
        "vid.fetch",
    ],
)
def test_validate_schema_name_rejects_malformed_names(value):
    with pytest.raises(ConfigError):
        validate_schema_name(value)


@pytest.mark.parametrize(
    "value",
    [
        "pg_catalog",
        "pg_toast",
        "information_schema",
        "auth",
        "storage",
        "extensions",
        "graphql",
        "graphql_public",
        "realtime",
        "vault",
        "supabase_migrations",
    ],
)
def test_validate_schema_name_rejects_reserved_names(value):
    with pytest.raises(ConfigError):
        validate_schema_name(value)


def test_from_env_rejects_invalid_db_schema():
    with pytest.raises(ConfigError) as excinfo:
        Settings.from_env({"DB_SCHEMA": "not-a-schema"})

    assert "DB_SCHEMA" in str(excinfo.value)


def test_validate_runtime_rejects_invalid_db_schema():
    settings = Settings.from_env(
        {
            "DATABASE_URL": "postgresql://user:pass@pooler/db",
            "MEDIA_TOKEN_SECRET": "media-secret",
        }
    )
    settings.db_schema = "auth"

    with pytest.raises(ConfigError) as excinfo:
        settings.validate_runtime()

    assert "DB_SCHEMA" in str(excinfo.value)


def test_validate_runtime_rejects_invalid_public_api_url():
    settings = Settings.from_env(
        {
            "DATABASE_URL": "postgresql://user:pass@pooler/db",
            "MEDIA_TOKEN_SECRET": "media-secret",
        }
    )
    # Simulate a directly constructed Settings that bypassed from_env.
    settings.public_api_url = "ftp://api.vidfetch.example"

    with pytest.raises(ConfigError) as excinfo:
        settings.validate_runtime()

    assert "PUBLIC_API_URL" in str(excinfo.value)


def test_numeric_and_list_settings_parse():
    settings = Settings.from_env(
        {
            "DOWNLOAD_DIR": "/var/lib/vidfetch/media",
            "PUBLIC_API_URL": "https://api.vidfetch.example/",
            "MEDIA_TOKEN_TTL_SECONDS": "120",
            "AUTH_SESSION_TTL_SECONDS": "1200",
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
    assert settings.public_api_url == "https://api.vidfetch.example"
    assert settings.media_token_ttl_seconds == 120
    assert settings.auth_session_ttl_seconds == 1200
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


def test_public_api_url_defaults_to_empty_and_is_normalised():
    disabled = Settings.from_env({})
    enabled = Settings.from_env(
        {"PUBLIC_API_URL": "  https://api.vidfetch.example///  "}
    )
    with_path = Settings.from_env(
        {"PUBLIC_API_URL": "https://vidfetch.example/backend"}
    )

    assert disabled.public_api_url == ""
    assert enabled.public_api_url == "https://api.vidfetch.example"
    assert with_path.public_api_url == "https://vidfetch.example/backend"


@pytest.mark.parametrize(
    "value",
    [
        "ftp://api.vidfetch.example",
        "api.vidfetch.example",
        "https://user:secret-password@api.vidfetch.example",
        "https://api.vidfetch.example/?debug=1",
        "https://api.vidfetch.example/#frag",
        "https://",
        "https://api.vidfetch.example:notaport",
        "has space",
        "https://api.vidfetch.example/" + "a" * 2100,
    ],
)
def test_invalid_public_api_url_is_rejected_without_echoing_credentials(value):
    with pytest.raises(ConfigError) as excinfo:
        Settings.from_env({"PUBLIC_API_URL": value})

    message = str(excinfo.value)
    assert "PUBLIC_API_URL" in message
    assert "secret-password" not in message


@pytest.mark.parametrize(
    "name,value",
    [
        ("MEDIA_TOKEN_TTL_SECONDS", "soon"),
        ("AUTH_SESSION_TTL_SECONDS", "soon"),
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
    for expected in ("DATABASE_URL", "MEDIA_TOKEN_SECRET"):
        assert expected in message
    # Local auth needs no identity-provider configuration.
    assert "SUPABASE" not in message


def test_validate_runtime_accepts_database_and_media_secret():
    settings = Settings.from_env(
        {
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
