#!/usr/bin/env python3
"""Render the Vidfetch Supabase migration templates for a configured schema.

The templates in ``db/templates`` contain a single ``{{schema}}``
placeholder. Rendering with the default ``public`` schema reproduces the
committed migrations byte for byte; rendering with e.g. ``vidfetch`` emits the
same SQL with every application table moved into that schema.

Usage:
    DB_SCHEMA=public python3 scripts/render_migrations.py
    python3 scripts/render_migrations.py --schema vidfetch --output /tmp/migrations
    DB_SCHEMA=public python3 scripts/render_migrations.py --check

``--check`` renders into a temporary directory and exits non-zero when the
committed output differs, which is what CI uses to detect edits made directly to
generated migrations.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

SCHEMA_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
RESERVED_SCHEMAS = frozenset(
    {
        "information_schema",
        "auth",
        "storage",
        "extensions",
        "graphql",
        "graphql_public",
        "realtime",
        "vault",
    }
)
RESERVED_PREFIXES = ("pg_", "supabase_")
PLACEHOLDER = "{{schema}}"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATES_DIR = REPO_ROOT / "db" / "templates"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "db" / "migrations"


def validate_schema(raw: str) -> str:
    """Validate a schema name using the same contract as the backend.

    The name must be a lowercase PostgreSQL identifier no longer than 63
    characters. Supabase-managed schemas and ``pg_*`` internals are rejected so
    a misconfigured deployment cannot overwrite platform objects.
    """
    schema = (raw or "").strip()
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError(
            f"Invalid DB_SCHEMA {raw!r}: expected ^[a-z_][a-z0-9_]{{0,62}}$."
        )
    if schema in RESERVED_SCHEMAS or schema.startswith(RESERVED_PREFIXES):
        raise ValueError(
            f"Invalid DB_SCHEMA {schema!r}: this schema is managed by Postgres "
            "or Supabase and cannot host application tables."
        )
    return schema


def quote_identifier(schema: str) -> str:
    """Return a safely quoted SQL identifier for an already validated schema."""
    return '"' + schema.replace('"', '""') + '"'


def template_name_to_migration(name: str) -> str:
    return name[: -len(".template")]


def render_templates(
    templates_dir: Path, output_dir: Path, schema: str
) -> dict[str, str]:
    """Render every template into ``output_dir`` and return the rendered texts."""
    templates = sorted(templates_dir.glob("*.sql.template"))
    if not templates:
        raise FileNotFoundError(f"No *.sql.template files found in {templates_dir}")

    quoted_schema = quote_identifier(schema)
    rendered: dict[str, str] = {}
    for template in templates:
        text = template.read_text(encoding="utf-8")
        unknown = sorted(
            {
                match
                for match in re.findall(r"\{\{[^}]*\}\}", text)
                if match != PLACEHOLDER
            }
        )
        if unknown:
            raise ValueError(
                f"{template} contains unsupported placeholders: {', '.join(unknown)}"
            )
        output = text.replace(PLACEHOLDER, quoted_schema)
        if "{{" in output:
            raise ValueError(f"{template} still contains an unreplaced placeholder")
        rendered[template_name_to_migration(template.name)] = output

    output_dir.mkdir(parents=True, exist_ok=True)
    for name, text in rendered.items():
        (output_dir / name).write_text(text, encoding="utf-8")
    return rendered


def compare_output(output_dir: Path, rendered: dict[str, str]) -> list[str]:
    """Return human-readable differences between ``output_dir`` and ``rendered``."""
    actual = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(output_dir.glob("*.sql"))
    }

    differences: list[str] = []
    for name in sorted(set(rendered) - set(actual)):
        differences.append(f"missing: {output_dir / name}")
    for name in sorted(set(actual) - set(rendered)):
        differences.append(f"unexpected: {output_dir / name}")
    for name in sorted(set(actual) & set(rendered)):
        if actual[name] != rendered[name]:
            differences.append(f"changed: {output_dir / name}")
    return differences


def resolve_schema(cli_schema: str | None) -> str:
    if cli_schema is not None:
        return validate_schema(cli_schema)
    return validate_schema(os.environ.get("DB_SCHEMA", "").strip() or "public")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render Vidfetch Supabase migrations for a configured schema."
    )
    parser.add_argument(
        "--schema",
        help="Application schema name (defaults to DB_SCHEMA or public).",
    )
    parser.add_argument(
        "--templates-dir",
        type=Path,
        default=DEFAULT_TEMPLATES_DIR,
        help=f"Template directory (default: {DEFAULT_TEMPLATES_DIR}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output migration directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Render to a temporary directory and fail if --output differs.",
    )
    args = parser.parse_args(argv)

    try:
        schema = resolve_schema(args.schema)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    try:
        if args.check:
            with tempfile.TemporaryDirectory(prefix="vidfetch-migrations-") as tmp:
                rendered = render_templates(
                    args.templates_dir, Path(tmp), schema
                )
                differences = compare_output(args.output, rendered)
                if differences:
                    print(
                        "Rendered migrations are out of date. Regenerate them with "
                        f"`DB_SCHEMA={schema} python3 scripts/render_migrations.py`.",
                        file=sys.stderr,
                    )
                    for difference in differences:
                        print(f"  {difference}", file=sys.stderr)
                    return 1
            print(
                f'Rendered migrations for schema "{schema}" match {args.output}.'
            )
            return 0

        rendered = render_templates(args.templates_dir, args.output, schema)
    except (OSError, ValueError) as exc:
        print(f"Failed to render migrations: {exc}", file=sys.stderr)
        return 1

    print(
        f'Rendered {len(rendered)} migrations for schema "{schema}" into '
        f"{args.output}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
