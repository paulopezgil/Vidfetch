"""Create or update an administrator account from the command line.

Usage::

    python -m backend.app.cli.create_admin --email admin@example.com \\
        --password '...' [--admin]

The command is idempotent: an existing account gets the new password, is marked
approved, and receives the requested role. It reads ``DATABASE_URL`` and
``DB_SCHEMA`` from the environment and never prints the password, its hash, or
any connection string.
"""
from __future__ import annotations

import argparse
import sys
from typing import Sequence

import psycopg
from psycopg.rows import dict_row

from ..core.config import ConfigError, Settings
from ..core.security import hash_password
from ..services import auth as auth_service


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.app.cli.create_admin",
        description=(
            "Create an approved administrator account, or reset an existing "
            "account's password and role."
        ),
    )
    parser.add_argument("--email", required=True, help="Account email address.")
    parser.add_argument(
        "--password",
        required=True,
        help="Password to set (at least 8 characters).",
    )
    parser.add_argument(
        "--admin",
        action="store_true",
        help="Grant the admin application role (default: user).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command; returns a process exit code."""
    args = _build_parser().parse_args(argv)

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if not settings.database_url:
        print(
            "Configuration error: DATABASE_URL is not configured.",
            file=sys.stderr,
        )
        return 2

    try:
        email = auth_service.normalize_email(args.email)
        auth_service.validate_password(args.password)
    except auth_service.AuthServiceError as exc:
        print(f"Invalid input: {exc.message}", file=sys.stderr)
        return 2

    role = "admin" if args.admin else "user"
    password_hash = hash_password(args.password)
    schema_sql = f'"{settings.db_schema}"'

    try:
        with psycopg.connect(
            settings.database_url, row_factory=dict_row
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"select id from {schema_sql}.profiles "
                    "where lower(email) = %s",
                    (email,),
                )
                existing = cursor.fetchone()
                if existing is None:
                    cursor.execute(
                        f"insert into {schema_sql}.profiles "
                        "(email, password_hash, is_approved, app_role, "
                        "approved_at) "
                        "values (%s, %s, true, %s, now())",
                        (email, password_hash, role),
                    )
                    created = True
                else:
                    cursor.execute(
                        f"update {schema_sql}.profiles "
                        "set password_hash = %s, is_approved = true, "
                        "app_role = %s, "
                        "approved_at = coalesce(approved_at, now()), "
                        "updated_at = now() "
                        "where id = %s",
                        (password_hash, role, existing["id"]),
                    )
                    created = False
            connection.commit()
    except psycopg.Error:
        # Driver messages can include host/user details; keep them off stdout
        # (and out of logs that might be captured by a shell history).
        print("Database error: could not update the account.", file=sys.stderr)
        return 1

    verb = "Created" if created else "Updated"
    print(f"{verb} {role} account {email} (approved).")
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
