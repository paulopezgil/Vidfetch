# Vidfetch v2 — Implementation Status

| Field | Value |
| --- | --- |
| Status | **`v2.1.0` deployment refactor in progress** |
| Baseline | `v1.9.0` |
| Current released version | `v2.0.2` |
| Branch | `dev` (main checkout) |
| Last updated | 2026-11-22 |

This is the implementation checklist for the current development cycle. The root
`README.md` documents the shipped application; `docs/V2_SETUP.md` has the
step-by-step local and production setup.

## Branch layout

Worktrees live inside the main checkout under `.worktrees/`:

| Branch | Worktree | Purpose |
| --- | --- | --- |
| `main` | main checkout, during releases | Production releases |
| `dev` | main checkout | Active development |
| `dev-backend` | `.worktrees/backend` | Backend agent |
| `dev-frontend` | `.worktrees/frontend` | Frontend agent |

The long-lived `v2` branch was merged and deleted after the v2.0.x releases.

## Completed

- [x] Architecture specification approved (`docs/ARCHITECTURE_V2.md`).
- [x] Supabase schema, auth trigger, RLS, and migrations.
- [x] Backend core: config, async DB, JWT/JWKS, media signing, storage.
- [x] Authenticated API, admin user management, audit log.
- [x] Video dedupe pipeline and durable job worker.
- [x] Playlist downloads, partial failure, cancellation, on-demand ZIP.
- [x] Signed media/thumbnail streaming with range support.
- [x] Library, history, and admin job/asset inventory.
- [x] Frontend auth, route guards, dashboard, library, history, playlists, admin.
- [x] Local email/password auth gated by `VITE_ENABLE_LOCAL_AUTH`.
- [x] Configurable database schema (`DB_SCHEMA`, default `public`).
- [x] Templated migrations and schema renderer/applier.
- [x] Split **`backend/Dockerfile`** and **`frontend/Dockerfile`**.
- [x] Local `docker-compose.yml` with frontend + backend + local Supabase.
- [x] Supabase CLI wrapper and local administrator bootstrap.
- [x] Absolute media URLs via `PUBLIC_API_URL`.
- [x] Vercel config (`frontend/vercel.json`).
- [x] Backend-only VPS stack (`docker-compose.prod.yml`).
- [x] Backend requirements moved into `backend/`.
- [x] Removed the all-in-one root Dockerfile/entrypoint.
- [x] Local and production setup documentation (`README.md`, `docs/V2_SETUP.md`).

## Pending

- [ ] Final release checks and `v2.1.0` release/tag from `main`.
- [ ] Live production smoke test on Vercel + VPS + Supabase Cloud.
- [ ] Playlist-item retry job creation.
- [ ] Playlist cover streaming endpoint.
- [ ] Cache eviction UI.
- [ ] v1 data backup/fresh-start confirmation.

## Verification log

| Check | Result |
| --- | --- |
| Backend pytest | 521 passed |
| Frontend production build | Passed |
| Frontend local Docker image | Built; Vite dev server serves 200 |
| Backend Docker image | Built; non-root; `/api/health` 200; no frontend/tests in image |
| Local Compose stack | Frontend, backend, Supabase, local bootstrap started successfully |
| Local admin bootstrap | `admin@local.test` created and approved |
| Local auth | Email/password sign-in returned an ES256 token |
| Local API auth | `/api/me` returned 200 with JWKS verification |
| CORS | Preflight from `http://localhost:5173` allowed |
| Local real download | YouTube video reached `ready` |
| Absolute media URL | `PUBLIC_API_URL` produced `http://localhost:8000/api/media/...` |
| Compose cleanup | `down` stopped the wrapper and local Supabase containers |
| Supabase migrations | Applied cleanly |
| Supabase pgTAP/RLS | 56 assertions passed |
| Custom schema (`vidfetch`) | Migrations, trigger, API, download, dedupe, media, library, history passed |
| Real playlist + ZIP | 2-item playlist and 72.9 MB ZIP passed |
| Mutation checks | Token expiry, path traversal, approval gate, cache repair, media approval, library visibility, and schema qualification all failed as expected |

## Commands

From the repository root:

```bash
python3 -m pytest backend/tests -q
(cd frontend && npm run build)
./scripts/check_v2.sh
docker compose config
docker compose up --build
```

Local Supabase reset:

```bash
docker compose exec supabase supabase db reset
docker compose up local-bootstrap
```

Production backend:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```
