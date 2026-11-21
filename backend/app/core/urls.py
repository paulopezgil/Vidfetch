"""Reusable HTTP(S) URL validation.

This module performs *syntactic* validation only: scheme, hostname, port, and
embedded credentials. It is safe to import from Pydantic models and from code
that cannot resolve DNS. Network-level (SSRF) validation lives in
:func:`backend.app.services.ytdlp.validate_media_url`, which builds on this
helper.

Validation is deliberately strict: media URLs are either ``http`` or ``https``
and may never carry userinfo (``user:password@``), because credentials would end
up in logs, history rows, and error messages.
"""
from __future__ import annotations

from urllib.parse import urlsplit

MAX_URL_LENGTH = 2048


class UrlValidationError(ValueError):
    """Raised when a URL is not an acceptable http(s) media URL."""


def validate_http_url(url: str) -> str:
    """Validate ``url`` and return it stripped.

    Raises :class:`UrlValidationError` with a user-safe message on failure.
    """
    if not isinstance(url, str):
        raise UrlValidationError("A URL is required.")
    candidate = url.strip()
    if not candidate:
        raise UrlValidationError("A URL is required.")
    if len(candidate) > MAX_URL_LENGTH:
        raise UrlValidationError("The URL is too long.")
    if any(character.isspace() or ord(character) < 0x20 for character in candidate):
        raise UrlValidationError("The URL contains invalid characters.")

    try:
        parts = urlsplit(candidate)
        # Accessing ``port`` validates it; a malformed port raises ValueError.
        parts.port
    except ValueError as exc:
        raise UrlValidationError("A valid http(s) URL is required.") from exc

    if parts.scheme.lower() not in ("http", "https"):
        raise UrlValidationError("Only http and https URLs are supported.")
    if not parts.hostname:
        raise UrlValidationError("The URL must include a hostname.")
    if parts.username is not None or parts.password is not None:
        raise UrlValidationError("URLs with embedded credentials are not allowed.")
    if "@" in parts.netloc:
        # Catches malformed userinfo that ``urlsplit`` could not parse.
        raise UrlValidationError("URLs with embedded credentials are not allowed.")
    if parts.port is not None and not 1 <= parts.port <= 65535:
        raise UrlValidationError("The URL contains an invalid port.")

    return candidate
