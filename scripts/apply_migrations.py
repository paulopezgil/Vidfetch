#!/usr/bin/env python3
"""Apply rendered Vidfetch migrations through ``asyncpg``.

Usage:
    DATABASE_URL=postgresql://... python3 scripts/apply_migrations.py
    python3 scripts/apply_migrations.py \
        --database-url postgresql://... \
        --migrations-dir /tmp/vidfetch-migrations

Files are applied in filename order, each inside its own transaction. Migrations
are schema-agnostic here: schema names were validated and rendered by
``scripts/render_migrations.py`` before this script reads the SQL. This script
never interpolates identifiers.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"


async def apply_migrations(database_url: str, migrations_dir: Path) -> int:
    paths = sorted(migrations_dir.glob("*.sql"))
    if not paths:
        print(f"No .sql migrations found in {migrations_dir}.", file=sys.stderr)
        return 1

    connection = await asyncpg.connect(database_url)
    try:
        total = len(paths)
        for index, path in enumerate(paths, start=1):
            sql = path.read_text(encoding="utf-8")
            print(f"[{index}/{total}] applying {path.name}", flush=True)
            try:
                async with connection.transaction():
                    await connection.execute(sql)
            except Exception as exc:  # noqa: BLE001 - report the exact file
                print(
                    f"[{index}/{total}] failed {path.name}: {exc}",
                    file=sys.stderr,
                )
                return 1
            print(f"[{index}/{total}] applied {path.name}", flush=True)
    finally:
        await connection.close()

    print(f"Applied {len(paths)} migrations from {migrations_dir}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply Vidfetch SQL migrations in filename order."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL"),
        help="Postgres connection URL (defaults to DATABASE_URL).",
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=DEFAULT_MIGRATIONS_DIR,
        help=f"Directory containing .sql migrations (default: {DEFAULT_MIGRATIONS_DIR}).",
    )
    args = parser.parse_args(argv)

    database_url = (args.database_url or "").strip()
    if not database_url:
        print(
            "--database-url (or DATABASE_URL) is required.",
            file=sys.stderr,
        )
        return 2

    try:
        return asyncio.run(apply_migrations(database_url, args.migrations_dir))
    except (OSError, asyncpg.PostgresError) as exc:
        print(f"Migration run failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
