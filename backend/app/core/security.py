"""Password hashing, opaque session tokens, and bearer-token extraction.

Authentication is fully local: the backend stores Argon2id password hashes in
``profiles`` and SHA-256 hashes of opaque session tokens in ``auth_sessions``.
The raw session token only ever exists in the client's ``Authorization`` header
and in transit; the database never sees it.

Nothing here touches the network or reads configuration at import time.
"""
from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

# Session tokens are 256 bits of URL-safe randomness. They are only compared by
# their SHA-256 hash, so the database content cannot be replayed as a token.
SESSION_TOKEN_BYTES = 32

# Argon2id defaults (m=64 MiB, t=3, p=4) are the library's recommended
# password-hashing parameters.
_hasher = PasswordHasher()

# A fixed hash of a random, unused password. Verifying against it when an email
# is unknown keeps a failed login's timing similar to a wrong-password failure,
# so the endpoint does not reveal whether an account exists.
_DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$"
    "agz7LG9oHwLSRlF+LLlLmw$"
    "WQo5IQUT8LpOuoMAcG8H1GM/FNvfyWeH8g+46MmCK24"
)


class AuthError(Exception):
    """Authentication failure with a machine-readable code and safe message.

    Messages are deliberately generic and never contain the token, header, or
    upstream exception text, so they are safe to return to clients and log.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


def extract_bearer_token(authorization: str | None) -> str:
    """Return the token from an ``Authorization: Bearer <token>`` header.

    Raises :class:`AuthError` for missing or malformed headers.
    """
    if not isinstance(authorization, str) or not authorization.strip():
        raise AuthError("missing_token", "Authentication required.")

    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError(
            "invalid_authorization_header",
            "Use an Authorization: Bearer <token> header.",
        )

    token = parts[1].strip()
    if not token or any(char.isspace() for char in token):
        raise AuthError(
            "invalid_authorization_header",
            "Use an Authorization: Bearer <token> header.",
        )
    return token


def generate_session_token() -> str:
    """Return a new opaque session token (never stored in plaintext)."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """Return the lowercase SHA-256 hex digest used to look a session up."""
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def dummy_verify_password(password: str) -> bool:
    """Spend the same work as a real verification, always returning False."""
    verify_password(_DUMMY_PASSWORD_HASH, password)
    return False


def hash_password(password: str) -> str:
    """Hash ``password`` with Argon2id (salted; a fresh hash every call)."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Return True when ``password`` matches ``password_hash``.

    A corrupted/unknown hash is treated as a mismatch instead of raising, so a
    damaged row cannot turn a login attempt into a 500.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
