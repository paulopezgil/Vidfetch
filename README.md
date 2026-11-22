# Vidfetch

A self-hosted web frontend for [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) with
Google sign-in, administrator approval, per-user libraries, and a shared media
deduplication cache.

Built with **React + Vite + TypeScript + Tailwind CSS** (frontend),
**FastAPI + yt-dlp + FFmpeg** (backend), and **Supabase Auth + Postgres** for
identity, approval, and metadata. The application ships as one Docker image and
one origin.

> ⚠️ **Legal notice.** This tool is a frontend for yt-dlp. Only download content
> you are authorized to download. You are responsible for complying with
> applicable laws, platform terms of service, and the rights of content owners.

---

## Features

- **Google OAuth via Supabase** with a manual administrator approval gate.
- **Admin panel** for approving, revoking, and promoting users. Every change is
  audited and enforced by the backend, not just the UI.
- **Single video and playlist downloads** with progress, cancellation, and
  per-item status.
- **Global media deduplication** keyed by `(canonical_id, options_hash)`, so an
  identical video/format is downloaded once and shared from the cache.
- **Per-user library and history** without leaking other users’ jobs.
- **On-demand playlist ZIP** streaming; no archive is persisted.
- **Signed media URLs** with HTTP range support for preview and download.
- **Best / 720p / MP3** formats, optional subtitle embedding, and MP3 playlist
  album/cover tags.
- **Material Design 3** interface with light/dark schemes, adaptive navigation,
  and a PWA manifest.
- **Configurable database schema** via `DB_SCHEMA` (default `public`; dedicated
  schemas such as `vidfetch` are supported).
- **Docker-friendly** single-origin deployment with a persistent media volume.

---

## Architecture

```text
Browser (React SPA)
  ├─ Google OAuth ──────────────► Supabase Auth
  ├─ Bearer JWT ────────────────► FastAPI /api
  └─ signed media URLs ─────────► FastAPI media endpoints
                                      │
                                      ├─ Supabase Postgres (profiles, assets, jobs, playlists)
                                      ├─ yt-dlp + FFmpeg (worker)
                                      └─ persistent media volume
```

- **Frontend** handles the Supabase session, route guards, dashboard, library,
  history, playlist detail, and admin user management.
- **Backend** verifies the Supabase JWT, checks `profiles.is_approved` and
  `profiles.app_role`, claims/reuses the global media cache, and runs downloads
  through a durable Postgres-backed worker.
- **Supabase** provides Google OAuth and Postgres. Only the backend holds the
  database URL and service-role key.

The full design, security model, data model, and trade-offs are in
[`docs/ARCHITECTURE_V2.md`](docs/ARCHITECTURE_V2.md). Setup and smoke-test steps
are in [`docs/V2_SETUP.md`](docs/V2_SETUP.md).

---

## Prerequisites

- **Docker** and **Docker Compose** v2+.
- A **Supabase project** with the Google provider enabled.
- A Google Cloud OAuth 2.0 client.
- For local database tests: the Supabase CLI and Docker.

Everything else (Python 3.11, Node.js, FFmpeg) is provided by the image.

---

## Quick start

### 1. Configure

```bash
cp .env.example .env
```

Fill in the Supabase URL, anon key, service-role key, database URL, a random
`MEDIA_TOKEN_SECRET`, and the `VITE_SUPABASE_*` values. See the configuration
table below.

Generate a media token secret with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 2. Apply the database migrations

Default `public` schema:

```bash
npx supabase login
npx supabase link --project-ref <project-ref>
npx supabase db push
```

For a dedicated schema such as `vidfetch`, render and apply the schema-aware
migrations, then set `DB_SCHEMA=vidfetch` in `.env`:

```bash
DB_SCHEMA=vidfetch python scripts/render_migrations.py \
  --output /tmp/vidfetch-migrations

DATABASE_URL=postgresql://... \
  python scripts/apply_migrations.py \
  --migrations-dir /tmp/vidfetch-migrations
```

See [`docs/V2_SETUP.md`](docs/V2_SETUP.md) for local Supabase and Google OAuth
details.

### 3. Run

```bash
docker compose up --build
```

Open **http://localhost:8000**.

### 4. Bootstrap the first admin

1. Sign in with Google. The new account lands on `/pending`.
2. Promote it:

```bash
DATABASE_URL=... DB_SCHEMA=public \
  python scripts/promote_admin.py --email you@example.com
```

3. Refresh the app. The account can now approve other users at `/admin`.

---

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `SUPABASE_URL` | — | Supabase project URL |
| `SUPABASE_ANON_KEY` | — | Public Supabase key (frontend) |
| `SUPABASE_SERVICE_ROLE_KEY` | — | Backend-only Auth admin key |
| `SUPABASE_JWKS_URL` | derived | JWT verification key set |
| `SUPABASE_JWT_ISSUER` | derived | Expected JWT issuer |
| `SUPABASE_JWT_AUDIENCE` | `authenticated` | Expected JWT audience |
| `SUPABASE_JWT_SECRET` | — | Legacy/test HS256 secret |
| `DATABASE_URL` | — | Postgres connection string (pooler recommended) |
| `DB_SCHEMA` | `public` | Application table schema (`public`, `vidfetch`, …) |
| `DOWNLOAD_DIR` | `/app/downloads` | Persistent media root |
| `FRONTEND_DIST` | `/app/frontend-dist` | Built SPA assets |
| `MEDIA_TOKEN_SECRET` | — | HMAC secret for signed media URLs |
| `MEDIA_TOKEN_TTL_SECONDS` | `900` | Signed media URL lifetime |
| `MAX_CONCURRENT_DOWNLOADS` | `2` | Global download concurrency |
| `MAX_CONCURRENT_JOBS_PER_USER` | `2` | Per-user concurrency |
| `MAX_PLAYLIST_ITEMS` | `200` | Playlist item cap |
| `MAX_ASSET_BYTES` | `5368709120` | Per-file size cap |
| `MIN_FREE_DISK_MB` | `500` | Disk-space safety floor |
| `JOB_LEASE_SECONDS` | `300` | Worker/asset lease duration |
| `ALLOW_PRIVATE_URLS` | `false` | Allow private/loopback URLs (local tests only) |
| `CORS_ORIGINS` | empty | Explicit origins for split-origin deployments |
| `VITE_SUPABASE_URL` | — | Frontend build-time Supabase URL |
| `VITE_SUPABASE_ANON_KEY` | — | Frontend build-time anon key |
| `VITE_API_BASE` | `/api` | Frontend API base |

Never expose `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL`, or `MEDIA_TOKEN_SECRET`
to the frontend. The Vite variables are public by design.

### Persistent storage

- `./downloads` → media, thumbnails, and temporary work directories.
- Supabase Postgres → users, approval, jobs, cache registry, playlists.

Removing an item from a library hides the user’s job; it never deletes a shared
media file. Physical media is removed by admin action or cache eviction.

---

## How deduplication works

1. The backend resolves metadata and derives a canonical identity
   (`extractor:id`).
2. It hashes the requested output options (format, subtitles, MP3 behavior,
   etc.).
3. It atomically claims `(canonical_id, options_hash)`:
   - **ready + file valid** → return the cached asset;
   - **processing with a live lease** → wait;
   - **missing/failed/expired** → download once.
4. The worker finalizes the file and marks the asset ready.
5. A second user or request reuses the same file; progress is tracked in
   per-user jobs.

Concurrent requests cannot start duplicate downloads, and interrupted jobs are
recovered on restart.

---

## Development

### Backend

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn backend.app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Tests and checks

```bash
# Backend
python3 -m pytest backend/tests -q

# Frontend
cd frontend && npm run build

# Migrations + all local checks
./scripts/check_v2.sh
```

Supabase RLS/auth-trigger tests (local stack):

```bash
npx supabase start
npx supabase db reset
npx supabase test db
```

---

## Project structure

```text
backend/                 FastAPI application
  app/
    api/                 auth, downloads, media, playlists, library, admin
    core/                config, database, JWT security, URL validation
    models/              Pydantic schemas
    services/            yt-dlp, assets, jobs, worker, storage, playlists
  tests/                 v1 + v2 test suites
frontend/                React + Vite + TypeScript + Tailwind
  src/auth/              Supabase session and route guards
  src/pages/             Login, Pending, Dashboard, Library, History, Admin
  src/downloads/         polling provider
supabase/
  templates/             schema-templated migrations
  migrations/            generated public migrations
  tests/                 pgTAP RLS/auth-trigger tests
scripts/                 render/apply migrations, promote admin, checks
docs/                    architecture, setup, implementation status
Dockerfile               multi-stage frontend + backend image
docker-compose.yml       single-origin deployment + media volume
```

---

## Known limitations

- The backend is designed for a single instance with a local persistent volume.
  Horizontal scaling would require shared storage (for example S3/Supabase
  Storage) and a shared worker deployment.
- Playlist-item retry creates a new video job; per-item retry jobs and a
  playlist-cover streaming endpoint are not yet exposed.
- Playlist ZIP creation temporarily uses disk equal to the archive size and is
  deleted after streaming.
- yt-dlp extractor changes can require an image rebuild or a pinned upgrade.
- The custom-schema migration applier re-applies all files on a fresh database;
  it is not a ledger-based production migration runner.
- Hosted Supabase + Google OAuth must be configured with real credentials before
  production use.

---

## License

Released under the [MIT License](LICENSE). Provided as-is; you are responsible
for using it lawfully.
