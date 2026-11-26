#!/usr/bin/env python3
"""Apply Vidfetch migrations through ``psycopg`` (PostgreSQL 16).

Usage:
    DATABASE_URL=postgresql://... python3 scripts/apply_migrations.py
    python3 scripts/apply_migrations.py \
        --database-url postgresql://... \
        --migrations-dir /tmp/vidfetch-migrations

Files are applied in filename order, each inside its own transaction. Migrations
are schema-agnostic here: schema names were validated and rendered by
``scripts/render_migrations.py`` before this script reads the SQL. This script
never interpolates identifiers. The SQL is plain PostgreSQL, so no placeholder
translation is needed.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"


def apply_migrations(database_url: str, migrations_dir: Path) -> int:
    paths = sorted(migrations_dir.glob("*.sql"))
    if not paths:
        print(f"No .sql migrations found in {migrations_dir}.", file=sys.stderr)
        return 1

    total = len(paths)
    # A parameterless ``execute`` uses the simple query protocol, which accepts
    # multiple statements per migration file (no client-side splitting).
    with psycopg.connect(database_url) as connection:
        for index, path in enumerate(paths, start=1):
            sql = path.read_text(encoding="utf-8")
            print(f"[{index}/{total}] applying {path.name}", flush=True)
            try:
                with connection.transaction():
                    connection.execute(sql)
            except psycopg.Error as exc:  # noqa: BLE001 - report the exact file
                print(
                    f"[{index}/{total}] failed {path.name}: {exc}",
                    file=sys.stderr,
                )
                return 1
            print(f"[{index}/{total}] applied {path.name}", flush=True)

    print(f"Applied {len(paths)} migrations from {migrations_dir}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply Vidfetch SQL migrations in filename order."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
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
        return apply_migrations(database_url, args.migrations_dir)
    except (OSError, psycopg.Error) as exc:
        print(f"Migration run failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
