"""Single source of truth for the application version.

Kept separate from :mod:`backend.config` because that module holds runtime
configuration read from environment variables; the version is a static,
build-time value.
"""
from __future__ import annotations

APP_VERSION = "1.9.0"
