# Vidfetch v2 — Implementation Status

| Field | Value |
| --- | --- |
| Status | **`v2.0.2` released** |
| Baseline | `v1.9.0` |
| Integration branch | `v2` |
| Release | `v2.0.2` (CI dependency patch) |
| Last updated | 2026-11-22 |

This is the implementation checklist for the v2 release. The root `README.md`
now documents the shipped v2 application.

## Branch layout

| Branch | Worktree | Purpose |
| --- | --- | --- |
| `v2` | `../yt-dlp-frontend-v2` | Integration branch |
| `v2-backend` | `../yt-dlp-frontend-v2-backend` | Backend agent |
| `v2-frontend` | `../yt-dlp-frontend-v2-frontend` | Frontend agent |
| `dev` | main checkout | Active development for the next release |

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
- [x] Backend video dedupe pipeline:
  - SSRF-aware yt-dlp wrapper, canonical ids, options hashing
  - atomic asset claim and leases
  - durable job worker, progress, cancellation
  - `POST /api/info`, `POST /api/downloads`, list/get/cancel
- [x] Frontend v2 download client and polling provider.
- [x] Dashboard migrated to v2 info/create/cancel and active job polling.
- [x] Playlist download pipeline: per-item assets, progress, partial failure,
      cancellation, on-demand ZIP.
- [x] Signed media and thumbnail streaming with range support.
- [x] Playlist list/detail/delete endpoints.
- [x] History page migrated to v2 jobs.
- [x] Backend library/history endpoints and admin job/asset inventory.
- [x] Frontend Library and PlaylistDetail migration to v2.
- [x] Removed the v1 SSE `ActiveTasksProvider` and unused v1 task card.
- [x] Backend `DB_SCHEMA` support: validated schema, schema-aware queries,
      default `public`.
- [x] Supabase RLS and auth-trigger pgTAP coverage (56 assertions passing
      against local Supabase).
- [x] Templated Supabase migrations with renderer/applier tooling:
      default `public`, custom schemas such as `vidfetch`.
- [x] End-to-end custom-schema validation (`DB_SCHEMA=vidfetch`):
      migrations, auth trigger, backend API, real download, dedupe, media
      streaming, library, and history.
- [x] Setup/smoke-test guide (`docs/V2_SETUP.md`).

## Pending

- [ ] Playlist-item retry job creation.
- [ ] Playlist cover streaming and cache eviction UI.
- [ ] Hosted Supabase + Google OAuth setup and live smoke test.
- [ ] v1 data backup/fresh-start confirmation.
- [ ] Release readiness and `v2.0.0` tag from `main`.
- [ ] Live Supabase integration tests (migrations, trigger, RLS, JWKS).
- [ ] Dedupe concurrency/crash-recovery tests against Postgres.
- [x] Docker image build and container startup smoke test.
- [ ] `docker compose up` with a real Supabase project.
- [ ] Real video + playlist + ZIP smoke test.
- [ ] v1 data backup/fresh-start migration check.
- [ ] Release readiness and `v2.0.0` tag from `main`.

## Verification log

| Check | Result |
| --- | --- |
| Migration SQL parse (`pglast`) | 2 migrations parsed |
| Backend pytest | 508 passed |
| Frontend build | 119 modules, zero TS errors |
| Mutation checks | media-token expiry, storage symlink escape, approval gate, cache repair, media approval re-check, library-hidden filtering, and schema qualification all failed as expected |
| Local Supabase migrations | Applied cleanly (`supabase db reset`) |
| Supabase pgTAP/RLS | 56 assertions passed |
| Local auth/API integration | Health, profile trigger, JWT `/api/me`, pending 403, admin approval, admin 403, and real YouTube `/api/info` passed |
| Custom schema (`vidfetch`) | Migrations applied; trigger wrote `vidfetch.profiles`; backend health/me/admin/info passed |
| Real video download | `ready`, 21 MB MP4 on disk |
| Dedupe | Second identical job reused the same asset; one file on disk |
| Media streaming | Full 200, range 206, thumbnail JPEG, download disposition |
| Library/history | Both returned the ready jobs with asset metadata |
| Real playlist download | 2-item channel playlist reached `ready`; both assets on disk |
| Playlist detail/list | Returned the playlist and both ready items |
| Playlist ZIP | Streamed 72.9 MB archive containing both MP4s |
| Docker build | Passed (`vidfetch-v2-test`) |
| Container startup | `/api/health` 200 degraded (test env), `/` 200, `/login` 200 |
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
