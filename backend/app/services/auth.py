"""Local email/password authentication and opaque sessions.

Users are rows in ``profiles`` with an Argon2id ``password_hash``. Signing in
issues a random opaque token; only its SHA-256 hash is stored in
``auth_sessions``, so a database leak does not hand out usable sessions.

Authorization (approval and role) always comes from the profile row, never from
anything the client sends. An unapproved account can still sign in and read
``/api/me``; the approval guard decides what it may do next.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from ..core.config import DEFAULT_AUTH_SESSION_TTL_SECONDS
from ..core.db import DB_ERRORS, Database, is_unique_violation
from ..core.security import (
    dummy_verify_password,
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 200
MAX_EMAIL_LENGTH = 254

# Profile columns safe to hand to ``ProfileOut``. ``password_hash`` is never
# part of this list, so no response can leak it.
_PROFILE_COLUMNS = "id, email, is_approved, app_role, created_at, updated_at"
_SESSION_PROFILE_COLUMNS = (
    "p.id, p.email, p.is_approved, p.app_role, p.created_at, p.updated_at"
)

# Pragmatic address shape: a local part, then at least one dotted domain label.
_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)


class AuthServiceError(Exception):
    """Base for auth domain failures carrying a stable machine-readable code.

    Messages are safe to return to clients: they never include the submitted
    password, the stored hash, the session token, or database error text.
    """

    code = "auth_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidCredentialsError(AuthServiceError):
    """Wrong email/password. Deliberately does not say which one."""

    code = "invalid_credentials"

    def __init__(self, message: str = "Invalid email or password.") -> None:
        super().__init__(message)


class EmailTakenError(AuthServiceError):
    code = "email_taken"

    def __init__(self, message: str = "An account with this email already exists.") -> None:
        super().__init__(message)


class WeakPasswordError(AuthServiceError):
    code = "weak_password"

    def __init__(
        self, message: str = "Password must be at least 8 characters."
    ) -> None:
        super().__init__(message)


class InvalidPasswordError(AuthServiceError):
    code = "invalid_password"

    def __init__(self, message: str = "Password must be at most 200 characters.") -> None:
        super().__init__(message)


class InvalidEmailError(AuthServiceError):
    code = "invalid_email"

    def __init__(self, message: str = "Enter a valid email address.") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class AuthSession:
    """A freshly issued session: raw token (once), expiry, and profile."""

    token: str
    expires_at: datetime
    profile: dict[str, Any]


def _as_uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Invalid user id.") from exc


def normalize_email(email: Any) -> str:
    """Trim and lowercase an address, rejecting malformed ones.

    Raises :class:`InvalidEmailError`. The stored form is the normalized one;
    the unique index is on ``lower(email)`` so it matches regardless.
    """
    candidate = email.strip().lower() if isinstance(email, str) else ""
    if (
        not candidate
        or len(candidate) > MAX_EMAIL_LENGTH
        or not _EMAIL_RE.match(candidate)
    ):
        raise InvalidEmailError()
    return candidate


def validate_password(password: Any) -> str:
    """Return ``password`` when it meets the 8..200 character policy."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError()
    if len(password) > MAX_PASSWORD_LENGTH:
        raise InvalidPasswordError()
    return password


async def _create_session(
    db: Database,
    user_id: str | UUID,
    ttl_seconds: int,
) -> tuple[str, datetime]:
    """Insert a session row for ``user_id`` and return its raw token/expiry."""
    ttl = max(60, int(ttl_seconds))
    token = generate_session_token()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    owner = _as_uuid(user_id)
    # Lazy cleanup: expired rows for this user can never authenticate again.
    await db.execute(
        f"delete from {db.schema_sql}.auth_sessions "
        "where user_id = $1 and expires_at <= now()",
        owner,
    )
    await db.execute(
        f"insert into {db.schema_sql}.auth_sessions "
        "(user_id, token_hash, expires_at) values ($1, $2, $3)",
        owner,
        hash_session_token(token),
        expires_at,
    )
    return token, expires_at


async def register(
    db: Database,
    email: Any,
    password: Any,
    *,
    session_ttl_seconds: int = DEFAULT_AUTH_SESSION_TTL_SECONDS,
) -> AuthSession:
    """Create a pending profile and sign it in.

    The new account starts unapproved (``is_approved = false``, role ``user``);
    an administrator enables it later. A concurrent duplicate registration is
    reported as :class:`EmailTakenError` using the database's unique index.
    """
    address = normalize_email(email)
    validate_password(password)
    password_hash = await asyncio.to_thread(hash_password, password)

    try:
        record = await db.fetchrow(
            f"insert into {db.schema_sql}.profiles (email, password_hash) "
            f"values ($1, $2) returning {_PROFILE_COLUMNS}",
            address,
            password_hash,
        )
    except DB_ERRORS as exc:
        if is_unique_violation(exc):
            raise EmailTakenError() from exc
        raise
    if record is None:  # pragma: no cover - INSERT ... RETURNING always returns
        raise RuntimeError("Profile insert returned no row.")
    profile = dict(record)

    token, expires_at = await _create_session(
        db, profile["id"], session_ttl_seconds
    )
    return AuthSession(token=token, expires_at=expires_at, profile=profile)


async def login(
    db: Database,
    email: Any,
    password: Any,
    *,
    session_ttl_seconds: int = DEFAULT_AUTH_SESSION_TTL_SECONDS,
) -> AuthSession:
    """Check credentials and start a session, approved or not.

    Every failure (unknown email, malformed address, wrong password) raises the
    same :class:`InvalidCredentialsError`, and the unknown-email path still
    performs a password verification so response timing does not reveal whether
    an account exists.
    """
    secret = password if isinstance(password, str) else ""
    if len(secret) > MAX_PASSWORD_LENGTH:
        # Never feed an arbitrarily large value to Argon2 (or the database):
        # it can only ever fail, and no stored password is that long.
        raise InvalidCredentialsError()

    try:
        address = normalize_email(email)
    except InvalidEmailError as exc:
        await asyncio.to_thread(dummy_verify_password, secret)
        raise InvalidCredentialsError() from exc

    record = await db.fetchrow(
        f"select {_PROFILE_COLUMNS}, password_hash "
        f"from {db.schema_sql}.profiles where lower(email) = $1",
        address,
    )
    stored = record.get("password_hash") if record is not None else None
    if isinstance(stored, str) and stored:
        verified = await asyncio.to_thread(verify_password, stored, secret)
    else:
        await asyncio.to_thread(dummy_verify_password, secret)
        verified = False
    if record is None or not verified:
        raise InvalidCredentialsError()

    profile = {
        key: value
        for key, value in dict(record).items()
        if key != "password_hash"
    }
    token, expires_at = await _create_session(
        db, profile["id"], session_ttl_seconds
    )
    return AuthSession(token=token, expires_at=expires_at, profile=profile)


async def authenticate(
    db: Database, token: Any
) -> dict[str, Any] | None:
    """Return the profile behind an unexpired session, or ``None``.

    One statement both touches ``last_used_at`` and returns profile columns, so
    a successful authentication costs a single round trip and a failed one
    changes nothing.
    """
    if not isinstance(token, str) or not token:
        return None
    record = await db.fetchrow(
        f"with session as ("
        f"update {db.schema_sql}.auth_sessions set last_used_at = now() "
        "where token_hash = $1 and expires_at > now() "
        "returning user_id"
        ") "
        f"select {_SESSION_PROFILE_COLUMNS} from {db.schema_sql}.profiles p "
        "join session s on s.user_id = p.id",
        hash_session_token(token),
    )
    return None if record is None else dict(record)


async def revoke_session(db: Database, token: Any) -> None:
    """Delete one session by its raw token. Unknown tokens are a no-op."""
    if not isinstance(token, str) or not token:
        return
    await db.execute(
        f"delete from {db.schema_sql}.auth_sessions where token_hash = $1",
        hash_session_token(token),
    )


async def revoke_user_sessions(
    db: Database,
    user_id: str | UUID,
    keep_token: str | None = None,
) -> None:
    """Delete a user's sessions, optionally keeping the one that made the call."""
    owner = _as_uuid(user_id)
    if keep_token:
        await db.execute(
            f"delete from {db.schema_sql}.auth_sessions "
            "where user_id = $1 and token_hash <> $2",
            owner,
            hash_session_token(keep_token),
        )
    else:
        await db.execute(
            f"delete from {db.schema_sql}.auth_sessions where user_id = $1",
            owner,
        )


async def set_password(
    db: Database,
    user_id: str | UUID,
    password: Any,
    *,
    revoke_sessions: bool = False,
) -> bool:
    """Set a password without knowing the current one (admin reset).

    Returns ``False`` when no such profile exists. With ``revoke_sessions`` the
    hash change and the session cleanup commit together, so a reset can never
    leave old sessions alive against a new password.
    """
    validate_password(password)
    password_hash = await asyncio.to_thread(hash_password, password)
    owner = _as_uuid(user_id)

    if revoke_sessions:
        async with db.transaction() as connection:
            record = await connection.fetchrow(
                f"update {db.schema_sql}.profiles "
                "set password_hash = $2, updated_at = now() "
                "where id = $1 returning id",
                owner,
                password_hash,
            )
            if record is None:
                return False
            await connection.execute(
                f"delete from {db.schema_sql}.auth_sessions where user_id = $1",
                owner,
            )
        return True

    record = await db.fetchrow(
        f"update {db.schema_sql}.profiles "
        "set password_hash = $2, updated_at = now() "
        "where id = $1 returning id",
        owner,
        password_hash,
    )
    return record is not None


async def change_password(
    db: Database,
    user_id: str | UUID,
    current_password: Any,
    new_password: Any,
    *,
    keep_token: str | None = None,
) -> bool:
    """Change a password after verifying the current one.

    Raises :class:`InvalidCredentialsError` (mapped to 400, not 401, by the
    endpoint so a wrong current password is not mistaken for an expired
    session). Other sessions for the user are revoked; the caller's own session
    survives when ``keep_token`` is given.
    """
    owner = _as_uuid(user_id)
    validate_password(new_password)

    record = await db.fetchrow(
        f"select password_hash from {db.schema_sql}.profiles where id = $1",
        owner,
    )
    stored = record.get("password_hash") if record is not None else None
    current = current_password if isinstance(current_password, str) else ""
    if not isinstance(stored, str) or not stored:
        raise InvalidCredentialsError()
    verified = await asyncio.to_thread(verify_password, stored, current)
    if not verified:
        raise InvalidCredentialsError("The current password is incorrect.")

    password_hash = await asyncio.to_thread(hash_password, new_password)
    async with db.transaction() as connection:
        await connection.execute(
            f"update {db.schema_sql}.profiles "
            "set password_hash = $2, updated_at = now() where id = $1",
            owner,
            password_hash,
        )
        if keep_token:
            await connection.execute(
                f"delete from {db.schema_sql}.auth_sessions "
                "where user_id = $1 and token_hash <> $2",
                owner,
                hash_session_token(keep_token),
            )
        else:
            await connection.execute(
                f"delete from {db.schema_sql}.auth_sessions where user_id = $1",
                owner,
            )
    return True
