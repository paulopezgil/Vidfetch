"""Supabase JWT verification and bearer-token extraction.

The backend trusts only cryptographically verified claims. In particular it
never reads approval or role information from ``user_metadata``: those live in
the ``profiles`` table and are loaded per request (see the architecture spec,
sections 6.2 and 6.3).

Tokens are verified with the project's HS256 secret when configured (tests and
legacy projects) and otherwise against the project JWKS with asymmetric
algorithms. The JWKS client is cached per URL so key fetches are reused.
"""
from __future__ import annotations

import threading
from typing import Any

import jwt
from jwt import PyJWKClient
from jwt.exceptions import (
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidTokenError,
    MissingRequiredClaimError,
    PyJWKClientError,
)

from .config import Settings

# Verification order matters: PyJWT's specific errors subclass InvalidTokenError.
_SYMMETRIC_ALGORITHMS = ["HS256"]
_ASYMMETRIC_ALGORITHMS = ["RS256", "ES256", "EdDSA"]

_JWKS_CLIENTS: dict[str, PyJWKClient] = {}
_JWKS_LOCK = threading.Lock()


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


def _jwks_client(url: str) -> PyJWKClient:
    """Return a process-wide cached JWKS client for ``url``."""
    with _JWKS_LOCK:
        client = _JWKS_CLIENTS.get(url)
        if client is None:
            client = PyJWKClient(url, cache_keys=True)
            _JWKS_CLIENTS[url] = client
        return client


def decode_supabase_token(token: str, settings: Settings) -> dict[str, Any]:
    """Verify a Supabase access token and return its claims.

    Raises :class:`AuthError` with a stable ``code`` on any failure.
    """
    if not isinstance(token, str) or not token.strip():
        raise AuthError("missing_token", "Authentication required.")

    if settings.supabase_jwt_secret:
        return _decode_claims(
            token,
            settings.supabase_jwt_secret,
            _SYMMETRIC_ALGORITHMS,
            settings,
        )

    if not settings.supabase_jwks_url:
        raise AuthError(
            "auth_not_configured",
            "Authentication is not configured on the server.",
        )

    try:
        signing_key = _jwks_client(settings.supabase_jwks_url).get_signing_key_from_jwt(token)
    except (PyJWKClientError, OSError) as exc:
        raise AuthError(
            "jwks_unavailable",
            "Unable to verify your session right now. Please try again.",
        ) from exc

    return _decode_claims(
        token,
        signing_key.key,
        _ASYMMETRIC_ALGORITHMS,
        settings,
    )


def _decode_claims(
    token: str,
    key: Any,
    algorithms: list[str],
    settings: Settings,
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "require": ["exp", "sub"],
        "verify_aud": bool(settings.supabase_jwt_audience),
        "verify_iss": bool(settings.supabase_jwt_issuer),
    }
    kwargs: dict[str, Any] = {"algorithms": algorithms, "options": options}
    if settings.supabase_jwt_audience:
        kwargs["audience"] = settings.supabase_jwt_audience
    if settings.supabase_jwt_issuer:
        kwargs["issuer"] = settings.supabase_jwt_issuer

    try:
        claims = jwt.decode(token, key, **kwargs)
    except ExpiredSignatureError as exc:
        raise AuthError(
            "token_expired", "Your session has expired. Please sign in again."
        ) from exc
    except InvalidAudienceError as exc:
        raise AuthError(
            "invalid_audience", "This token was not issued for this application."
        ) from exc
    except InvalidIssuerError as exc:
        raise AuthError(
            "invalid_issuer", "This token was not issued by the expected provider."
        ) from exc
    except MissingRequiredClaimError as exc:
        if "sub" in str(exc):
            raise AuthError(
                "missing_subject", "The token does not identify a user."
            ) from exc
        raise AuthError("invalid_token", "Invalid authentication token.") from exc
    except InvalidTokenError as exc:
        raise AuthError("invalid_token", "Invalid authentication token.") from exc

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise AuthError("missing_subject", "The token does not identify a user.")
    return claims
