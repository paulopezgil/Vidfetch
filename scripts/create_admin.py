#!/usr/bin/env python3
"""Create a local Vidfetch account from the host, without the backend image.

Usage:
    DATABASE_URL=postgresql://... python3 scripts/create_admin.py \
        --email you@example.com --password '...' --admin

This is a thin wrapper around ``backend.app.cli.create_admin``: the CLI owns the
Argon2id hashing and the ``profiles`` insert, so the host and the container can
never drift apart. It is what a home server uses to bootstrap the first account
without building or running the backend container.

``DB_SCHEMA`` is honoured the same way as the backend (defaults to ``public``).
Requires the backend runtime dependencies in the active environment (psycopg
and argon2-cffi). Run from the repository root or any directory; the repo root
is added to ``sys.path`` below.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    try:
        from backend.app.cli.create_admin import main as cli_main
    except ImportError as exc:
        print(
            "Could not import backend.app.cli.create_admin "
            f"({exc}). Install the backend requirements first: "
            "pip install -r backend/requirements.txt",
            file=sys.stderr,
        )
        return 2

    args = list(sys.argv[1:] if argv is None else argv)
    # The CLI accepts an optional argv argument; call it plainly if it does not.
    parameters = inspect.signature(cli_main).parameters
    result = cli_main(args) if parameters else cli_main()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
