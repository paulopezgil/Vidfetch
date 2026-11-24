# Vidfetch

**A self-hosted web app that makes [`yt-dlp`](https://github.com/yt-dlp/yt-dlp)
usable by real people.**

Vidfetch gives you a browser interface for importing videos and playlists into a
personal music library: tracks, curated playlists, artists and albums, a
persistent player, and an offline mode. Media files are cached once on the
server and shared, so the same video is never downloaded twice.

- **Local:** one `docker compose up` starts the Vite frontend, the FastAPI
  backend, and a PostgreSQL database. No cloud account is required.
- **Production:** the frontend is a static build on any static host (Vercel is
  the reference setup), and the backend runs as a container with its own
  PostgreSQL database, either bundled in Compose or external.

> ⚠️ **Use it responsibly.** Vidfetch is only a frontend for `yt-dlp`. Download
> content you are authorized to download, and follow the laws and terms of
> service that apply to you and your sources.

### Choose your path

| Goal | Start here | What you need |
| --- | --- | --- |
| Try it locally / develop | [Quick start — local](#quick-start--local) | Docker + Compose only |
| Run it for real | [Production deployment](#production-deployment) | A backend host with Docker, PostgreSQL, and a static frontend host |

Both modes use the same frontend, backend, database schema, migrations, and API.
Only packaging and hosting differ.

---

## Technologies

| Layer | Technology | Role |
| --- | --- | --- |
| **Frontend** | React 18, Vite, TypeScript, React Router | SPA shell, routes, type-safe UI |
| **UI system** | Tailwind CSS, Material Design 3 roles, Material Symbols | Themeable, accessible components (light/dark/system) |
| **Offline** | IndexedDB, Cache Storage, service worker | Cached library metadata, queued edits, saved media, offline app shell |
| **Backend** | FastAPI, Python 3.11, Uvicorn | JSON API, authentication, media streaming |
| **Database access** | psycopg 3 + `psycopg_pool`, SQL in a service/repository layer | Direct PostgreSQL access with pooled connections |
| **Authentication** | Argon2id password hashes, opaque bearer sessions stored as SHA-256 hashes | Local email/password login, approval, roles, revocation |
| **Media engine** | `yt-dlp`, FFmpeg, Node.js runtime | Metadata, downloads, merging, MP3 conversion |
| **Media delivery** | Shared filesystem cache, short-lived HMAC-signed URLs | Cross-user dedupe without exposing stored files |
| **Database** | PostgreSQL 16, SQL migrations in `db/` | Application data and durable job queue |
| **Packaging** | Docker Compose | Local stack and backend-only production stack |
| **Testing** | pytest, real-PostgreSQL integration tests, Vite build | Backend behavior and frontend type/build checks |

---

## Contents

- [Quick start — local](#quick-start--local)
- [Production deployment](#production-deployment)
- [The problem Vidfetch solves](#the-problem-vidfetch-solves)
- [How it works](#how-it-works)
- [Configuration](#configuration)
- [Development](#development)
- [Project layout](#project-layout)
- [Security notes](#security-notes)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)
- [Documentation](#documentation)

---

## Quick start — local

### What you need

- **Docker** and **Docker Compose** v2+
- That is it for the default local stack.

Python, Node.js, `yt-dlp`, FFmpeg, and PostgreSQL run inside the containers. You
do not need a hosted database or an OAuth account.

The local Compose stack provides:

| Service | Purpose | Address |
| --- | --- | --- |
| `frontend` | Vite dev server with hot reload | <http://localhost:5173> |
| `backend` | FastAPI + `yt-dlp` + FFmpeg + worker | <http://localhost:8000> |
| `db` | PostgreSQL 16 (no host port by default) | Compose network |
| `migrate` | One-shot migration runner (`db/migrations`) | exits after applying |
| `bootstrap` | Creates the local approved admin | one-shot container |

### Start everything

From the repository root:

```bash
docker compose up --build
```

The first run builds the backend and frontend images and initializes the
database. Later runs are faster.

Open **<http://localhost:5173>** and sign in with the development administrator:

```text
email:    admin@local.test
password: password123
```

Create additional accounts from the login screen; they start unapproved and land
on `/pending` until an administrator approves them at `/admin`.

### Local tips

- **Backend health:** <http://localhost:8000/api/health>
- **Logs:** `docker compose logs -f backend`
- **Stop everything:** `docker compose down`
- **Rebuild after dependency changes:** `docker compose up --build`
- **Apply new migrations without recreating containers:**
  ```bash
  docker compose run --rm migrate
  ```
- **Reset the database and media cache:** `docker compose down -v` (deletes the
  PostgreSQL and downloads volumes), then `docker compose up --build`.
- **Recreate the development admin:**
  ```bash
  docker compose run --rm bootstrap
  ```
- Docker may require `sudo` on Linux depending on how it is installed.

### What the local stack is doing

`db` stores profiles, sessions, jobs, the media cache registry, tracks, and
playlists. `migrate` applies the SQL files in `db/migrations` in filename order,
one transaction per file. `bootstrap` calls the admin CLI to create or update
`admin@local.test` as an approved administrator. `backend` serves the API and
runs the download worker; `frontend` is the Vite dev server.

There is no external authentication provider and no second database stack.

---

## Production deployment

Production is decoupled:

```text
Browser
  ├── static frontend (Vercel or any static host)
  ├── backend container (home server / VPS)  ──►  PostgreSQL
  └── signed media URLs from the backend origin
```

The backend owns downloads, media files, authentication, and the database. The
frontend is a static build and never receives database credentials.

### 1. Backend host

Use `docker-compose.backend.yml`, which bundles PostgreSQL 16, a migration
runner, the API/worker, and an optional first-admin profile.

```bash
git clone https://github.com/paulopezgil/Vidfetch.git
cd Vidfetch
cp .env.example .env
```

Fill `.env`:

```dotenv
# PostgreSQL container
POSTGRES_PASSWORD=replace-with-a-long-random-password

# Backend
DB_SCHEMA=public
MEDIA_TOKEN_SECRET=replace-with-a-long-random-secret
AUTH_SESSION_TTL_SECONDS=2592000
PUBLIC_API_URL=https://api.example.com
CORS_ORIGINS=https://app.example.com
DOWNLOAD_DIR=/app/downloads
MIN_FREE_DISK_MB=500
ALLOW_PRIVATE_URLS=false
ENVIRONMENT=production
LOG_LEVEL=INFO
```

Start it:

```bash
docker compose -f docker-compose.backend.yml up -d --build
curl -s https://api.example.com/api/health
```

Put a TLS reverse proxy (Caddy/nginx) in front of port `8000`. `PUBLIC_API_URL`
must be the public HTTPS backend origin; signed media URLs are built from it.
`CORS_ORIGINS` must exactly match the frontend origin.

Create the first administrator explicitly — no default account is created:

```bash
BOOTSTRAP_ADMIN_EMAIL=you@example.com \
BOOTSTRAP_ADMIN_PASSWORD='choose-a-strong-password' \
docker compose -f docker-compose.backend.yml --profile bootstrap run --rm bootstrap
```

The bundled stack runs migrations automatically before the backend. To use an
**external PostgreSQL** instead, point the backend `DATABASE_URL` at it, apply
`db/migrations` with `scripts/apply_migrations.py`, and disable/override the
bundled `db` and `migrate` services.

### 2. Frontend

Build `frontend/` as a static Vite app and host it anywhere. On Vercel:

- **Root Directory:** `frontend`
- **Framework:** Vite
- **Build command:** `npm run build`
- **Output directory:** `dist`

Environment variable:

```dotenv
VITE_API_BASE=https://api.example.com/api
```

That is the only frontend setting. Never expose database credentials, session
secrets, or `MEDIA_TOKEN_SECRET`.

After deploying, add the final domain and make sure it matches
`CORS_ORIGINS` on the backend.

### Production checklist

- [ ] Backend `.env` has `POSTGRES_PASSWORD`, `MEDIA_TOKEN_SECRET`,
      `PUBLIC_API_URL`, `CORS_ORIGINS`, and `DB_SCHEMA`.
- [ ] TLS terminates in front of the backend.
- [ ] PostgreSQL and download volumes are persistent and backed up.
- [ ] Migrations applied (`migrate` service or `scripts/apply_migrations.py`).
- [ ] First administrator created explicitly.
- [ ] Vercel has `VITE_API_BASE` only; no secrets.
- [ ] `/api/health` returns `ok` over HTTPS.
- [ ] A real video, playlist, and ZIP work from the deployed frontend.
- [ ] Login, approval, and logout work over HTTPS.

---

## The problem Vidfetch solves

If you want to share downloading with other people on a server, you quickly need
things `yt-dlp` does not provide:

- a friendly web interface
- accounts and access control
- a way to stop the same popular video being downloaded repeatedly
- a personal library with tracks, curated playlists, and offline playback
- safe in-browser preview and download links
- a queue that survives restarts and reports progress

Vidfetch wraps `yt-dlp` in a small, opinionated application that provides those
pieces. It is deliberately self-hosted: you own the server, the storage, and the
accounts.

---

## How it works

```text
Browser (React + Vite)
  │  HTTPS + opaque bearer token
  ▼
FastAPI backend ──► PostgreSQL 16
  │                   profiles, auth_sessions, download_jobs,
  │                   media_assets, user_tracks, user_playlists
  ▼
DOWNLOAD_DIR volume
  media files + thumbnails + covers
  │
  └── signed media URLs ──► browser player / offline cache
```

### The main pieces

| Layer | Responsibility |
| --- | --- |
| **Frontend** | Login/register, route guards, Home, Tracks, Playlists, Artists & Albums, Settings, player, admin panel |
| **Offline layer** | IndexedDB metadata cache, queued mutations, Cache Storage media, service-worker shell |
| **Backend API** | Session auth, approval/role guards, jobs, tracks, curated playlists, media tokens, admin |
| **Worker** | Claims durable jobs, runs `yt-dlp`/FFmpeg, updates progress, repairs/fills the shared cache |
| **Database** | Local users/sessions, per-user jobs/library/playlists, global media registry |

### Authentication flow

1. A visitor registers with email and password, or an administrator creates the
   account. Passwords are stored as **Argon2id** hashes; new self-service accounts
   start unapproved.
2. `POST /api/auth/login` verifies the password and issues a random opaque
   session token. Only its **SHA-256 hash** is stored in `auth_sessions`, with an
   expiry and optional user-agent.
3. The browser keeps the token and sends `Authorization: Bearer <token>` on every
   JSON API call. `/api/me` and protected endpoints resolve the session in
   PostgreSQL; approval and role always come from the `profiles` row.
4. Logout deletes the session. Password changes revoke other sessions; an admin
   password reset revokes all sessions for that account.

### Download lifecycle

1. The Home tab resolves a URL and creates a `download_jobs` row.
2. The worker claims the job, resolves metadata, and claims a global
   `media_assets` row keyed by `(canonical_id, options_hash)`. A cache hit
   completes immediately; a miss downloads once.
3. Ready jobs create/update the user's `user_tracks` entry. The library, artist,
   and album views read those per-user rows.
4. Media is served through short-lived HMAC-signed URLs. The player uses the
   local copy first when a song is saved for offline use.
5. Completed audio jobs are copied to the browser's media cache automatically;
   saved songs are permanent and play without the backend.

---

## Configuration

### Local

The local Compose file contains development defaults and a fixed
`admin@local.test` bootstrap. No `.env` is required.

### Backend environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | — | PostgreSQL connection string (compose builds it) |
| `POSTGRES_PASSWORD` | — | Bundled PostgreSQL password (compose) |
| `DB_SCHEMA` | `public` | Application table schema |
| `AUTH_SESSION_TTL_SECONDS` | `2592000` | Session lifetime (30 days) |
| `MEDIA_TOKEN_SECRET` | — | HMAC secret for signed media URLs |
| `MEDIA_TOKEN_TTL_SECONDS` | `900` | Signed URL lifetime |
| `PUBLIC_API_URL` | — | Absolute backend origin for media URLs |
| `CORS_ORIGINS` | — | Comma-separated frontend origins |
| `DOWNLOAD_DIR` | `/app/downloads` | Media storage root |
| `MAX_CONCURRENT_DOWNLOADS` | `2` | Global worker concurrency |
| `MAX_CONCURRENT_JOBS_PER_USER` | `2` | Per-user concurrency |
| `MAX_PLAYLIST_ITEMS` | `200` | Playlist item cap |
| `MAX_ASSET_BYTES` | `5368709120` | Per-file size cap |
| `MIN_FREE_DISK_MB` | `500` | Disk-space safety floor |
| `JOB_LEASE_SECONDS` | `300` | Worker/asset lease duration |
| `ALLOW_PRIVATE_URLS` | `false` | Private/loopback URLs (tests only) |
| `ENVIRONMENT` | `development` | Runtime mode |
| `LOG_LEVEL` | `INFO` | Log verbosity |

### Frontend

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE` | Absolute backend API URL, e.g. `https://api.example.com/api` |

There are no authentication-provider keys in the frontend.

### Database schema

The default schema is `public`. A dedicated schema such as `vidfetch` is
supported; the backend reads `DB_SCHEMA` and every query targets that schema.

```bash
DB_SCHEMA=vidfetch python3 scripts/render_migrations.py \
  --output /tmp/vidfetch-migrations

DATABASE_URL=postgresql://... \
  python3 scripts/apply_migrations.py \
  --migrations-dir /tmp/vidfetch-migrations
```

Then set `DB_SCHEMA=vidfetch` for the backend. The committed
`db/migrations/*.sql` files target `public`; templates live in `db/templates/`.
When using the bundled Compose stack, it applies the committed public
migrations. For a custom schema, mount the rendered directory over
`/migrations` in an override file or apply them manually before starting the
backend.

`scripts/render_migrations.py --check` verifies the committed public output.

### Persistent data

- Docker volume `pgdata` → PostgreSQL data.
- Docker volume `vidfetch_downloads` → media, thumbnails, covers, temporary work.
- Browser IndexedDB/Cache Storage → optional offline library and saved media.

Removing an item from a library only hides the user's entry. It never deletes a
shared media file that another user may still need.

---

## Development

### Local full stack

```bash
docker compose up --build
# frontend: http://localhost:5173
# backend:  http://localhost:8000
```

Vite runs with the source directory bind-mounted, so frontend edits hot reload.
The backend image does not auto-reload; rebuild it after backend changes:

```bash
docker compose up -d --build backend
```

### Backend without Docker

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
uvicorn backend.app.main:app --reload --port 8000
```

Set `DATABASE_URL` (and `MEDIA_TOKEN_SECRET`) to a PostgreSQL database with
`db/migrations` applied.

### Frontend without Docker

```bash
cd frontend
npm install
npm run dev
```

Set `VITE_API_BASE` in `frontend/.env.local` when running outside Compose.

### Tests and checks

```bash
# Backend unit tests
python3 -m pytest backend/tests -q

# Backend with a real migrated PostgreSQL (never the production database)
TEST_DATABASE_URL=postgresql://... python3 -m pytest backend/tests -q

# Frontend
cd frontend && npm run build

# Backend + frontend + migration render/parse
./scripts/check_v2.sh
```

Integration tests are gated by `TEST_DATABASE_URL`; when it is unset they skip.

### Docker images

```bash
docker build -t vidfetch-backend ./backend
docker build -t vidfetch-frontend ./frontend
docker compose config -q
docker compose -f docker-compose.backend.yml config -q
```

---

## Project layout

```text
backend/
  app/
    api/               auth, jobs, library, media, playlists, tracks, admin
    cli/               create/update administrator accounts
    core/              config, psycopg pool, password/session helpers
    models/            Pydantic schemas
    services/          query/repository layer and worker
  tests/
    v2/                unit/API tests with fakes
    integration/       gated real-PostgreSQL tests
  Dockerfile           backend-only image
  requirements.txt

db/
  templates/           schema-aware SQL templates ({{schema}})
  migrations/          rendered public migrations

frontend/
  Dockerfile           local Vite dev-server image
  vercel.json          Vercel/Vite + SPA rewrite
  src/
    auth/              local session provider and route guards
    components/        M3 components, player bar, dialogs
    offline/           IndexedDB, media cache, sync queue
    pages/             Login, Pending, Home, Tracks, Playlists,
                       Artists/Albums, Settings, Admin
    player/            persistent media player and queue
    theme/             light/dark/system preference
    lib/               API client, session token storage, helpers

docker-compose.yml           local frontend + backend + PostgreSQL
docker-compose.backend.yml   backend-only production stack (bundled PostgreSQL)
scripts/                     migrations, admin CLI wrapper, checks
```

---

## Security notes

- Passwords use Argon2id. Raw session tokens exist only in the browser header;
  the database stores SHA-256 hashes. Expired sessions cannot authenticate.
- Approval and roles are read from `profiles` on every request, never from
  client-supplied claims.
- `DATABASE_URL`, `MEDIA_TOKEN_SECRET`, password hashes, and session tokens must
  never reach the frontend, logs, or error messages.
- The backend is the only database client; there is no public database API.
- Media paths are validated under `DOWNLOAD_DIR`; traversal, absolute paths, and
  symlink escapes are rejected.
- Private/loopback download URLs are rejected unless `ALLOW_PRIVATE_URLS=true`
  (trusted local tests only; never in production).
- Use HTTPS for the frontend and backend. Signed media URLs are short-lived.
- Keep the PostgreSQL and downloads volumes backed up.

---

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Local stack does not start | Docker is running; ports 5173 and 8000 are free |
| `bootstrap` failed | `docker compose logs bootstrap`; database/migrations may still be starting |
| Login says invalid credentials | Email/password; the account exists; bootstrap output |
| `401 invalid_session` | Session expired or revoked; sign in again |
| `403 approval_required` | An administrator must approve the account at `/admin` |
| `relation "profiles" does not exist` | `DB_SCHEMA` differs from the schema that received migrations |
| Database connection refused | `DATABASE_URL`, PostgreSQL health, network/pooler |
| CORS error | `CORS_ORIGINS` must exactly match the browser origin |
| Media URL fails | `PUBLIC_API_URL` must be the public HTTPS backend origin |
| Migration failed | Inspect `docker compose logs migrate`; apply files in filename order |
| Ports already in use | Stop the old stack before `docker compose up` |
| Offline data missing | Browser storage/cache may have been cleared or evicted |

---

## Known limitations

- The backend is designed for **one instance with a persistent volume**.
  Horizontal scaling would need shared storage and a shared worker deployment.
- There is no email verification, self-service password reset, or login rate
  limiting yet. Administrators can reset passwords from the API/CLI.
- Offline media is stored per browser origin; clearing site data or browser
  eviction removes it. The UI keeps saved songs permanent, so it does not offer
  an un-download action.
- The interface is currently Catalan only; the Settings language control is a
  placeholder for future locales.
- Large playlists consume disk until the media cache is managed.
- `yt-dlp` extractors change over time; keep the backend image updated.

---

## Documentation

- [`docs/ARCHITECTURE_V2.md`](docs/ARCHITECTURE_V2.md) — architecture and data model
- [`docs/V2_SETUP.md`](docs/V2_SETUP.md) — detailed local and production setup
- [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) — status and checks
- [`CHANGELOG.md`](CHANGELOG.md) — release notes

---

## License

See the repository license file.
