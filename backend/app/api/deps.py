"""Shared FastAPI dependencies for authentication and database access."""
from __future__ import annotations

from fastapi import Depends, Header, Request

from ..core.config import Settings
from ..core.db import DB_UNAVAILABLE, Database
from ..core.security import AuthError, extract_bearer_token
from ..models.schemas import ProfileOut
from ..services import auth
from ..services.storage import Storage


def get_settings(request: Request) -> Settings:
    """Return the settings attached to the running application."""
    return request.app.state.settings


def get_db(request: Request) -> Database | None:
    """Return the application's database wrapper, if one is configured."""
    return getattr(request.app.state, "db", None)


def get_storage(request: Request) -> Storage:
    """Return the application's path-safe media storage."""
    return request.app.state.storage


async def get_bearer_token(
    authorization: str | None = Header(default=None),
) -> str:
    """Extract the opaque session token from the Authorization header."""
    return extract_bearer_token(authorization)


async def get_current_profile(
    token: str = Depends(get_bearer_token),
    db: Database | None = Depends(get_db),
) -> ProfileOut:
    """Resolve the caller's profile from their opaque session token.

    Approval and role always come from the ``profiles`` row, never from client
    input. The token is validated before any other work, so an anonymous
    request is a 401 even while the database is unavailable.
    """
    if db is None:
        raise AuthError(
            "service_unavailable",
            "The service is temporarily unavailable.",
        )

    try:
        row = await auth.authenticate(db, token)
    except DB_UNAVAILABLE as exc:
        raise AuthError(
            "service_unavailable",
            "The service is temporarily unavailable.",
        ) from exc

    if row is None:
        raise AuthError(
            "invalid_session",
            "Your session is invalid or has expired. Please sign in again.",
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
