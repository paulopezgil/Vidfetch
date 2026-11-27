# Vidfetch v2 — Implementation Status

| Field | Value |
| --- | --- |
| Status | **`v2.6.1` released** |
| Baseline | `v1.9.0` |
| Current released version | `v2.6.1` |
| Branch | `main` |
| Last updated | 2026-11-27 |

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
- [x] Removed the user-facing configuration screen.
- [x] Removed the user-facing history screen.
- [x] Vercel config (`frontend/vercel.json`).
- [x] Backend-only VPS stack (`docker-compose.prod.yml`).
- [x] Backend requirements moved into `backend/`.
- [x] Removed the all-in-one root Dockerfile/entrypoint.
- [x] Local and production setup documentation (`README.md`, `docs/V2_SETUP.md`).
- [x] Per-user track model with editable metadata, artist/album facets, and cover art.
- [x] Four-tab shell, persistent player, date-grouped Tracks search, and Artists/Albums views.
- [x] Curated playlists, playlist picker, reorder, play, and Add to playlist.
- [x] Offline metadata cache, queued edits, offline media cache, automatic two-phase transfers, and the production service worker.
- [x] Account menu with switch-account/sign-out and identity-scoped offline cleanup.
- [x] Release hardening: isolation/validation/ordering tests, storage overview, code splitting, and accessibility.

## Pending

- [x] Final release checks and `v2.1.0` release/tag from `main`.
- [x] Final release checks and `v2.2.0` release/tag from `main`.
- [x] Final release checks and `v2.2.1` release/tag from `main`.
- [x] Final release checks and `v2.3.0` release/tag from `main`.
- [x] Final release checks and `v2.4.0` release/tag from `main`.
- [x] Final release checks and `v2.4.1` release/tag from `main`.
- [x] Final release checks and `v2.4.2` release/tag from `main`.
- [x] Final release checks and `v2.4.3` release/tag from `main`.
- [x] Final release checks and `v2.5.0` release/tag from `main`.
- [x] Final release checks and `v2.5.1` release/tag from `main`.
- [x] Final release checks and `v2.5.2` release/tag from `main`.
- [x] Final release checks and `v2.5.3` release/tag from `main`.
- [x] Final release checks and `v2.5.4` release/tag from `main`.
- [x] Final release checks and `v2.6.0` release/tag from `main`.
- [x] Final release checks and `v2.6.1` release/tag from `main`.
- [ ] Live production smoke test on Vercel + VPS + Supabase Cloud.
- [ ] Playlist-item retry job creation.
- [ ] Playlist cover streaming endpoint.
- [ ] Cache eviction UI.
- [ ] v1 data backup/fresh-start confirmation.

## Verification log

| Check | Result |
| --- | --- |
| Backend pytest | 699 passed |
| Frontend production build | Passed; 24 lazy JS chunks |
| Offline media | Saved song played with the backend stopped and zero media requests |
| Offline metadata | Cached reads, queued edits, FIFO flush on reconnect |
| Account menu | Logout clears responses/queue and keeps saved media |
| Configuration tab removal | Nav, route, page, and legacy client deleted; build + serve 200 |
| History tab removal | Nav, route, page, and dead types deleted; build + serve 200 |
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
