"""Shared FastAPI dependencies for authentication and database access."""
from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import Depends, Header, Request
from starlette.concurrency import run_in_threadpool

from ..core.config import Settings
from ..core.db import Database
from ..core.security import AuthError, decode_supabase_token, extract_bearer_token
from ..models.schemas import ProfileOut
from ..services import profiles
from ..services.storage import Storage

# Database failures that mean "try again later" rather than "bad request".
_DB_UNAVAILABLE = (asyncpg.PostgresError, OSError, ConnectionError)


def get_settings(request: Request) -> Settings:
    """Return the settings attached to the running application."""
    return request.app.state.settings


def get_db(request: Request) -> Database | None:
    """Return the application's database wrapper, if one is configured."""
    return getattr(request.app.state, "db", None)


def get_storage(request: Request) -> Storage:
    """Return the application's path-safe media storage."""
    return request.app.state.storage


async def get_current_profile(
    request: Request,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    db: Database | None = Depends(get_db),
) -> ProfileOut:
    """Verify the bearer token and load the caller's profile.

    JWT verification may fetch JWKS over the network synchronously, so it runs
    in a threadpool. The returned profile is always read from ``public.profiles``;
    approval and role claims from the token are never trusted.

    The token is validated before the database is consulted so an anonymous
    request is always a 401, even while the database is unavailable.
    """
    token = extract_bearer_token(authorization)
    claims = await run_in_threadpool(decode_supabase_token, token, settings)

    subject = claims.get("sub")
    try:
        user_id = UUID(str(subject))
    except (AttributeError, TypeError, ValueError) as exc:
        raise AuthError(
            "invalid_token", "Invalid authentication token."
        ) from exc

    if db is None:
        raise AuthError(
            "service_unavailable",
            "The service is temporarily unavailable.",
        )

    try:
        row = await profiles.get_profile(db, user_id)
    except _DB_UNAVAILABLE as exc:
        raise AuthError(
            "service_unavailable",
            "The service is temporarily unavailable.",
        ) from exc

    if row is None:
        raise AuthError(
            "profile_missing",
            "No profile exists for this account. Please sign in again.",
        )
    return ProfileOut.model_validate(row)


def require_approved(
    profile: ProfileOut = Depends(get_current_profile),
) -> ProfileOut:
    """Allow only approved users (``/api/me`` is deliberately exempt)."""
    if not profile.is_approved:
        raise AuthError(
            "approval_required",
            "Your account is awaiting administrator approval.",
        )
    return profile


def require_admin(
    profile: ProfileOut = Depends(require_approved),
) -> ProfileOut:
    """Allow only approved administrators.

    Pending users receive ``approval_required`` (from ``require_approved``)
    before the role check, matching the endpoint access matrix.
    """
    if profile.app_role != "admin":
        raise AuthError(
            "admin_required",
            "Administrator access is required.",
        )
    return profile
