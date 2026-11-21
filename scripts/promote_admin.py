#!/usr/bin/env python3
"""Promote an existing Vidfetch profile to an approved administrator.

Usage:
    DATABASE_URL=postgresql://... python3 scripts/promote_admin.py \
        --email you@example.com

The user must have signed in with Google at least once so that the
``auth.users`` trigger has created their ``public.profiles`` row.

This script is intentionally separate from the application runtime. It never
prints the database URL or any token.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

import asyncpg


async def promote(email: str) -> int:
    database_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")
    if not database_url:
        print(
            "DATABASE_URL (or SUPABASE_DB_URL) is not set.",
            file=sys.stderr,
        )
        return 2

    connection = await asyncpg.connect(database_url)
    try:
        row = await connection.fetchrow(
            """
            update public.profiles
               set is_approved = true,
                   app_role = 'admin',
                   approved_at = now(),
                   approved_by = id
             where lower(email) = lower($1)
         returning id, email
            """,
            email.strip(),
        )
    finally:
        await connection.close()

    if row is None:
        print(
            f"No profile found for {email!r}. Sign in with Google first, then "
            "run this command again.",
            file=sys.stderr,
        )
        return 1

    print(f"Promoted {row['email']} ({row['id']}) to approved administrator.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Google account email")
    args = parser.parse_args()
    return asyncio.run(promote(args.email))


if __name__ == "__main__":
    raise SystemExit(main())
