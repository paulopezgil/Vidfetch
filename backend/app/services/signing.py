"""Short-lived HMAC-signed media tokens.

Browsers cannot attach an ``Authorization`` header to ``<video>``, ``<img>``, or
plain download links, so media and thumbnails are protected by signed URLs
instead. The token is a URL-safe payload plus an HMAC-SHA256 signature over
``(asset_id, user_id, expiry)``.

Format::

    base64url({"a": asset_id, "e": expiry, "u": user_id}) "." hex(hmac)

The signature is compared in constant time. Tokens never include the secret and
should never be logged.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass

_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class MediaTokenError(Exception):
    """Raised when a media token is malformed, forged, or expired."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


@dataclass(frozen=True)
class MediaToken:
    """Verified media token contents."""

    asset_id: str
    user_id: str
    expires_at: int


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _signature(secret: str, payload_b64: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def sign_media_token(
    secret: str,
    asset_id: str,
    user_id: str,
    ttl_seconds: int,
    *,
    now: int | None = None,
) -> str:
    """Create a signed token for ``asset_id`` and ``user_id``.

    ``ttl_seconds`` must be positive. ``now`` is an override for tests; it is a
    Unix timestamp in seconds.
    """
    if not isinstance(secret, str) or not secret:
        raise ValueError("A media token secret is required.")
    if not isinstance(asset_id, str) or not asset_id.strip():
        raise ValueError("asset_id is required.")
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id is required.")
    if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool):
        raise ValueError("ttl_seconds must be an integer.")
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive.")

    issued_at = int(time.time() if now is None else now)
    payload = {
        "a": asset_id,
        "e": issued_at + ttl_seconds,
        "u": user_id,
    }
    payload_b64 = _b64url_encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return f"{payload_b64}.{_signature(secret, payload_b64)}"


def verify_media_token(
    token: str,
    secret: str,
    *,
    now: int | None = None,
) -> MediaToken:
    """Verify a media token, raising :class:`MediaTokenError` on failure."""
    if not isinstance(secret, str) or not secret:
        raise ValueError("A media token secret is required.")
    if not isinstance(token, str) or not token:
        raise MediaTokenError("invalid_token", "Invalid media token.")

    parts = token.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise MediaTokenError("invalid_token", "Invalid media token.")

    payload_b64, provided_signature = parts
    expected_signature = _signature(secret, payload_b64)
    if not hmac.compare_digest(expected_signature, provided_signature):
        raise MediaTokenError("invalid_token", "Invalid media token.")

    if not _B64URL_RE.fullmatch(payload_b64):
        raise MediaTokenError("invalid_token", "Invalid media token.")
    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise MediaTokenError("invalid_token", "Invalid media token.") from exc

    if not isinstance(payload, dict):
        raise MediaTokenError("invalid_token", "Invalid media token.")
    asset_id = payload.get("a")
    user_id = payload.get("u")
    expires_at = payload.get("e")
    if (
        not isinstance(asset_id, str)
        or not asset_id
        or not isinstance(user_id, str)
        or not user_id
        or not isinstance(expires_at, int)
        or isinstance(expires_at, bool)
    ):
        raise MediaTokenError("invalid_token", "Invalid media token.")

    current = int(time.time() if now is None else now)
    if current >= expires_at:
        raise MediaTokenError("expired_token", "This media link has expired.")

    return MediaToken(asset_id=asset_id, user_id=user_id, expires_at=expires_at)
