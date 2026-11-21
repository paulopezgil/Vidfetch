# Vidfetch v2 — Implementation Status

| Field | Value |
| --- | --- |
| Baseline | `v1.9.0` |
| Integration branch | `v2` |
| Target release | `v2.0.0` |
| Last updated | 2026-11-21 |

This is a working checklist, not a release note. The v1.9 `README.md` remains
the operator documentation until v2 ships.

## Branch layout

| Branch | Worktree | Purpose |
| --- | --- | --- |
| `v2` | `../yt-dlp-frontend-v2` | Integration branch |
| `v2-backend` | `../yt-dlp-frontend-v2-backend` | Backend agent |
| `v2-frontend` | `../yt-dlp-frontend-v2-frontend` | Frontend agent |
| `dev` | main checkout | Stable v1.9.x maintenance |

## Completed

- [x] Architecture specification approved (`docs/ARCHITECTURE_V2.md`).
- [x] `v2` integration branch and backend/frontend worktrees.
- [x] Supabase project config, seed, and initial migration:
  - `profiles`, `media_assets`, `download_jobs`, `playlists`,
    `playlist_items`, `admin_audit_log`
  - auth-user trigger, updated-at triggers, indexes, RLS
- [x] Follow-up migration for job progress, cancellation, and thumbnails.
- [x] First-admin promotion script (`scripts/promote_admin.py`).
- [x] Environment template (`.env.example`).
- [x] Single-origin Dockerfile, compose file, and entrypoint.
- [x] CI workflow for backend tests, frontend build, and migration SQL parsing.
- [x] Backend core:
  - config, asyncpg wrapper, JWT/JWKS verification
  - HMAC media signing, options hashing, path-safe storage
  - Pydantic v2 schemas
- [x] Backend authenticated API:
  - `/api/health`, `/api/me`
  - admin user list, approve, revoke, role change
  - last-admin guard and audit log
  - consistent error envelope
- [x] Frontend auth scaffold:
  - Supabase client and authenticated API helper
  - `AuthProvider`, route guards
  - login, pending, and admin pages
- [x] Setup/smoke-test guide (`docs/V2_SETUP.md`).

## In progress

- [ ] Backend video dedupe pipeline:
  - yt-dlp wrapper, canonical ids, options hashing
  - atomic asset claim and leases
  - durable job worker, progress, cancellation
  - `POST /api/info`, `POST /api/downloads`, list/get/cancel
- [ ] Frontend v2 download client and polling provider.

## Pending

- [ ] Playlist pipeline: per-item assets, retry, on-demand ZIP.
- [ ] Media streaming with signed URLs and range requests.
- [ ] Library/history endpoints and frontend page migration.
- [ ] Admin job/asset inventory and cache/disk visibility.
- [ ] Frontend dashboard/library/history/playlist migration to v2 API.
- [ ] Replace the v1 SSE `ActiveTasksProvider` with v2 polling (or optional
      signed-token SSE).
- [ ] Live Supabase integration tests (migrations, trigger, RLS, JWKS).
- [ ] Dedupe concurrency/crash-recovery tests against Postgres.
- [ ] Docker build and compose smoke test.
- [ ] Real video + playlist + ZIP smoke test.
- [ ] v1 data backup/fresh-start migration check.
- [ ] Release readiness and `v2.0.0` tag from `main`.

## Verification log

| Check | Result |
| --- | --- |
| Migration SQL parse (`pglast`) | 2 migrations parsed |
| Backend pytest | 268 passed (before the download pipeline) |
| Frontend build | 117 modules, zero TS errors |
| Mutation checks | media-token expiry, storage symlink escape, approval gate all failed as expected |
| Live Supabase | Not yet run |
| Docker build | Not yet run |
| Real download smoke test | Not yet run |

## Commands

From the `v2` worktree:

```bash
python3 -m pytest backend/tests -q
cd frontend && npm ci && npm run build
python3 - <<'PY'
from pathlib import Path
import pglast
for path in sorted(Path("supabase/migrations").glob("*.sql")):
    pglast.parse_sql(path.read_text())
    print("parsed", path)
PY
```

Or run the convenience script:

```bash
./scripts/check_v2.sh
```
