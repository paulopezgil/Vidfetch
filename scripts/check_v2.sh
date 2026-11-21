#!/usr/bin/env bash
# Local verification for the v2 branch.
#
# Usage (from the v2 worktree root):
#   ./scripts/check_v2.sh
#
# Requires Python deps from requirements.txt + requirements-dev.txt and a
# frontend `npm ci` (or an existing node_modules directory).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Backend tests"
python3 -m pytest backend/tests -q

echo "==> Frontend build"
(
  cd frontend
  if ! command -v npm >/dev/null 2>&1; then
    export PATH="/usr/share/nodejs/corepack/shims:$PATH"
  fi
  npm run build
)

echo "==> Migration SQL parse"
python3 - <<'PY'
from pathlib import Path
import pglast

paths = sorted(Path("supabase/migrations").glob("*.sql"))
if not paths:
    raise SystemExit("No migrations found")
for path in paths:
    pglast.parse_sql(path.read_text())
    print(f"parsed {path}")
PY

echo "==> All local checks passed"
