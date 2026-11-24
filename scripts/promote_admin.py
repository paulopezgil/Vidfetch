#!/usr/bin/env python3
"""Promote an existing Vidfetch profile to an approved administrator.

Usage:
    DATABASE_URL=postgresql://... python3 scripts/promote_admin.py \
        --email you@example.com

The account must already exist in the application ``profiles`` table. Create it
with ``scripts/create_admin.py`` (or the backend's ``create_admin`` module) and
then use this script to approve/promote an existing local account.

This script is intentionally separate from the application runtime. It never
prints the database URL or any token.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import psycopg

_SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_RESERVED = {
    "auth",
    "storage",
    "extensions",
    "graphql",
    "graphql_public",
    "information_schema",
    "pg_catalog",
    "pg_toast",
    "realtime",
    "vault",
}


def application_schema() -> str:
    schema = (os.getenv("DB_SCHEMA") or "public").strip()
    if (
        not _SCHEMA_RE.fullmatch(schema)
        or schema.startswith("pg_")
        or schema in _RESERVED
    ):
        raise SystemExit(
            "DB_SCHEMA must be a safe lowercase identifier such as public or vidfetch."
        )
    return schema


def promote(email: str) -> int:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print(
            "DATABASE_URL is not set.",
            file=sys.stderr,
        )
        return 2

    schema = application_schema()
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            f"""
            update "{schema}".profiles
               set is_approved = true,
                   app_role = 'admin',
                   approved_at = now(),
                   approved_by = id
             where lower(email) = lower(%s)
         returning id, email
            """,
            (email.strip(),),
        ).fetchone()

    if row is None:
        print(
            f"No profile found for {email!r}. Create the account first with "
            "scripts/create_admin.py, then run this command again.",
            file=sys.stderr,
        )
        return 1

    print(f"Promoted {row[1]} ({row[0]}) to approved administrator.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Account email")
    args = parser.parse_args(argv)
    try:
        return promote(args.email)
    except (OSError, psycopg.Error) as exc:
        print(f"Promotion failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
