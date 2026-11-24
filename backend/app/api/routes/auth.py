"""Local email/password authentication endpoints.

Sign-in issues an opaque bearer token; every protected route accepts it as
``Authorization: Bearer <token>``. Responses never include password hashes or
another user's data, and failures use stable error codes so the UI can react.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from ...core.config import Settings
from ...core.db import DB_UNAVAILABLE, Database
from ...models.schemas import (
    AuthLogin,
    AuthRegister,
    AuthSessionOut,
    ChangePassword,
    ProfileOut,
)
from ...services import auth as auth_service
from ..deps import get_bearer_token, get_current_profile, get_db, get_settings
from ..errors import ApiError

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _unavailable() -> ApiError:
    return ApiError(
        503,
        "service_unavailable",
        "The service is temporarily unavailable.",
    )


def _domain_error(status_code: int, exc: auth_service.AuthServiceError) -> ApiError:
    """Expose a domain error's stable code with the endpoint's status."""
    return ApiError(status_code, exc.code, exc.message)


def _session_out(session: auth_service.AuthSession) -> AuthSessionOut:
    return AuthSessionOut(
        token=session.token,
        expires_at=session.expires_at,
        profile=ProfileOut.model_validate(session.profile),
    )


@router.post(
    "/register",
    response_model=AuthSessionOut,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: AuthRegister,
    db: Database | None = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthSessionOut:
    """Create a pending account and sign it in.

    Signing in immediately lets the UI show the "awaiting approval" screen
    instead of asking for the password again.
    """
    if db is None:
        raise _unavailable()
    try:
        session = await auth_service.register(
            db,
            payload.email,
            payload.password,
            session_ttl_seconds=settings.auth_session_ttl_seconds,
        )
    except auth_service.EmailTakenError as exc:
        raise _domain_error(409, exc) from exc
    except (
        auth_service.InvalidEmailError,
        auth_service.WeakPasswordError,
        auth_service.InvalidPasswordError,
    ) as exc:
        raise _domain_error(400, exc) from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return _session_out(session)


@router.post("/login", response_model=AuthSessionOut)
async def login(
    payload: AuthLogin,
    db: Database | None = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthSessionOut:
    """Check credentials and start a session (unapproved users included)."""
    if db is None:
        raise _unavailable()
    try:
        session = await auth_service.login(
            db,
            payload.email,
            payload.password,
            session_ttl_seconds=settings.auth_session_ttl_seconds,
        )
    except auth_service.InvalidCredentialsError as exc:
        raise _domain_error(401, exc) from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return _session_out(session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    token: str = Depends(get_bearer_token),
    db: Database | None = Depends(get_db),
) -> Response:
    """Revoke the caller's session. Unknown tokens still succeed."""
    if db is None:
        raise _unavailable()
    try:
        await auth_service.revoke_session(db, token)
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePassword,
    profile: ProfileOut = Depends(get_current_profile),
    token: str = Depends(get_bearer_token),
    db: Database | None = Depends(get_db),
) -> Response:
    """Change the caller's password and revoke their other sessions.

    A wrong current password is a 400 ``invalid_credentials`` rather than a 401:
    the session itself is still valid, and a 401 would make the UI sign the user
    out instead of showing the field error.
    """
    if db is None:
        raise _unavailable()
    try:
        await auth_service.change_password(
            db,
            profile.id,
            payload.current_password,
            payload.new_password,
            keep_token=token,
        )
    except auth_service.InvalidCredentialsError as exc:
        raise _domain_error(400, exc) from exc
    except (
        auth_service.WeakPasswordError,
        auth_service.InvalidPasswordError,
    ) as exc:
        raise _domain_error(400, exc) from exc
    except DB_UNAVAILABLE as exc:
        raise _unavailable() from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
