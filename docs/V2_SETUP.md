# Vidfetch v2.4 — Setup and Deployment Guide

This guide covers the two supported deployment modes:

- **Local development:** one `docker compose up` starts the Vite frontend, the
  FastAPI backend, and a bundled PostgreSQL 16 database.
- **Production:** the frontend is a static build (Vercel or any static host),
  the backend runs as a container with its own PostgreSQL database (bundled in
  Compose or external), and TLS is terminated in front of the API.

The application code, database migrations, and API are the same in both modes.

---

## Part A — Local development

### A1. Prerequisites

- Docker Engine / Docker Desktop
- Docker Compose v2+

Python, Node.js, `yt-dlp`, FFmpeg, and PostgreSQL run inside the images. No
hosted database or OAuth account is required.

### A2. Start the stack

From the repository root:

```bash
docker compose up --build
```

| Service | Purpose | Address |
| --- | --- | --- |
| `frontend` | Vite dev server, hot reload | <http://localhost:5173> |
| `backend` | FastAPI + worker + FFmpeg | <http://localhost:8000> |
| `db` | PostgreSQL 16 (no host port) | Compose network |
| `migrate` | One-shot migration runner | exits after applying |
| `bootstrap` | Creates the local approved admin | one-shot |

The first run builds images and initializes the database. Later runs are faster.

### A3. Local administrator

The `bootstrap` service creates:

```text
email:    admin@local.test
password: password123
```

Open <http://localhost:5173>, sign in, and approve other accounts at `/admin`.
New accounts created from the login screen start unapproved.

Recreate the development admin at any time:

```bash
docker compose run --rm bootstrap
```

### A4. Common local commands

```bash
# Logs
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f db

# Rebuild one service
docker compose up -d --build backend
docker compose up -d --build frontend

# Apply migrations without recreating the stack
docker compose run --rm migrate

# Backend health
curl -s http://localhost:8000/api/health

# Stop everything (data volumes stay)
docker compose down

# Full reset: database + media cache (destructive)
docker compose down -v
docker compose up --build
```

### A5. Local ports

| Port | Service |
| --- | --- |
| `5173` | Vite frontend |
| `8000` | FastAPI backend |

PostgreSQL is internal to the Compose network.

### A6. Local environment overrides

The local stack has development defaults; no `.env` is required. For frontend
development outside Compose, create `frontend/.env.local`:

```dotenv
VITE_API_BASE=http://localhost:8000/api
```

There are no authentication-provider keys. The backend uses the bundled
PostgreSQL database and the bootstrap admin.

---

## Part B — Production

Production is decoupled:

```text
Static frontend (Vercel or any static host)
        │  HTTPS + opaque bearer token
        ▼
Backend container (home server / VPS) ──► PostgreSQL 16
        │
        └── signed media URLs
```

### B1. Backend host

Use `docker-compose.backend.yml`. It bundles PostgreSQL, a migration runner, the
API/worker, and an optional bootstrap profile.

```bash
git clone https://github.com/paulopezgil/Vidfetch.git
cd Vidfetch
cp .env.example .env
```

Fill `.env`:

```dotenv
POSTGRES_PASSWORD=replace-with-a-long-random-password
DB_SCHEMA=public
AUTH_SESSION_TTL_SECONDS=2592000
MEDIA_TOKEN_SECRET=replace-with-a-long-random-secret
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

Important:

- `PUBLIC_API_URL` is the public **HTTPS** backend origin (no `/api` suffix).
- `CORS_ORIGINS` must exactly match the frontend origin.
- The `pgdata` and `vidfetch_downloads` volumes must be persistent and backed up.
- The backend runs as a single instance with a local media volume.
- The bundled `migrate` service applies `db/migrations` on every start.
- For an external PostgreSQL, point the backend at it, apply the migrations with
  `scripts/apply_migrations.py`, and override/disable the bundled `db` and
  `migrate` services.

Put a TLS reverse proxy in front of port `8000`:

```caddyfile
api.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

### B2. First administrator

No default account exists in production. Create one explicitly:

```bash
BOOTSTRAP_ADMIN_EMAIL=you@example.com \
BOOTSTRAP_ADMIN_PASSWORD='choose-a-strong-password' \
docker compose -f docker-compose.backend.yml --profile bootstrap run --rm bootstrap
```

Or, with an externally reachable database and backend dependencies installed:

```bash
DATABASE_URL=postgresql://... DB_SCHEMA=public \
  python3 scripts/create_admin.py --email you@example.com \
  --password 'choose-a-strong-password' --admin
```

`create_admin` is idempotent: it creates the account or updates its password,
approval, and role. `--admin` grants the administrator role; omitting it keeps an
existing admin role unchanged.

### B3. Frontend on Vercel

Create a Vercel project:

- **Root Directory:** `frontend`
- **Framework:** Vite (auto-detected)
- **Build command:** `npm run build`
- **Output directory:** `dist`
- `frontend/vercel.json` supplies the SPA rewrite.

Environment variables:

```dotenv
VITE_API_BASE=https://api.example.com/api
```

That is the only frontend setting. Never add `DATABASE_URL`,
`MEDIA_TOKEN_SECRET`, or any backend secret.

Add the production domain and make sure it matches `CORS_ORIGINS`.

### B4. Production checklist

- [ ] Backend `.env` has `POSTGRES_PASSWORD`, `MEDIA_TOKEN_SECRET`,
      `PUBLIC_API_URL`, `CORS_ORIGINS`, and `DB_SCHEMA`.
- [ ] TLS terminates in front of the backend.
- [ ] PostgreSQL and download volumes are persistent and backed up.
- [ ] Migrations applied (`migrate` service or `scripts/apply_migrations.py`).
- [ ] First administrator created explicitly.
- [ ] Vercel root directory is `frontend` and only `VITE_API_BASE` is set.
- [ ] `/api/health` returns `ok` over HTTPS.
- [ ] A real video, playlist, and ZIP work from the deployed frontend.
- [ ] Login, approval, logout, and password change work over HTTPS.

---

## Custom database schema

The default schema is `public`. A dedicated schema such as `vidfetch` is
supported: the backend reads the validated `DB_SCHEMA` variable and every query
targets that schema.

### Render and apply

```bash
DB_SCHEMA=vidfetch python3 scripts/render_migrations.py \
  --output /tmp/vidfetch-migrations

DATABASE_URL=postgresql://... \
  python3 scripts/apply_migrations.py \
  --migrations-dir /tmp/vidfetch-migrations
```

Then set `DB_SCHEMA=vidfetch` for the backend.

The first rendered file creates the schema and grants; the second creates the
tables. The committed `db/migrations/*.sql` files target `public`; the templates
live in `db/templates/`.

### Bundled Compose with a custom schema

The bundled `migrate` service mounts `db/migrations` (public). For a custom
schema, mount the rendered directory over `/migrations` with an override file
and set `DB_SCHEMA`, for example:

```yaml
# docker-compose.vidfetch.yml
services:
  migrate:
    volumes:
      - /tmp/vidfetch-migrations:/migrations:ro
```

```bash
docker compose -f docker-compose.backend.yml \
  -f docker-compose.vidfetch.yml up -d --build
```

Do not install both `public` and `vidfetch` in the same database.

### Verify

```sql
select table_name
  from information_schema.tables
 where table_schema = 'vidfetch'
 order by table_name;

select column_name
  from information_schema.columns
 where table_schema = 'vidfetch'
   and table_name = 'download_jobs'
 order by column_name;
```

Create the first admin in the same schema with `DB_SCHEMA=vidfetch`.

---

## Environment reference

### Backend / production

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection string |
| `POSTGRES_PASSWORD` | Bundled PostgreSQL password (Compose) |
| `DB_SCHEMA` | Application schema (`public` by default) |
| `AUTH_SESSION_TTL_SECONDS` | Opaque session lifetime (default 30 days) |
| `MEDIA_TOKEN_SECRET` | HMAC secret for signed media URLs |
| `MEDIA_TOKEN_TTL_SECONDS` | Signed URL lifetime |
| `PUBLIC_API_URL` | Absolute public backend origin |
| `CORS_ORIGINS` | Comma-separated browser origins |
| `DOWNLOAD_DIR` | Media root inside the container |
| `MAX_CONCURRENT_DOWNLOADS` | Global worker concurrency |
| `MAX_CONCURRENT_JOBS_PER_USER` | Per-user concurrency |
| `MAX_PLAYLIST_ITEMS` | Playlist item cap |
| `MAX_ASSET_BYTES` | Per-file size cap |
| `MIN_FREE_DISK_MB` | Disk-space safety floor |
| `JOB_LEASE_SECONDS` | Worker/asset lease duration |
| `ALLOW_PRIVATE_URLS` | Private URLs (local tests only) |
| `ENVIRONMENT` | Runtime mode |
| `LOG_LEVEL` | Log verbosity |

### Frontend

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE` | Absolute backend API URL, e.g. `https://api.example.com/api` |

---

## Local verification

```bash
# Backend unit tests
python3 -m pytest backend/tests -q

# Backend with a migrated throwaway PostgreSQL
TEST_DATABASE_URL=postgresql://... python3 -m pytest backend/tests -q

# Frontend
cd frontend && npm run build

# Backend + frontend + migration render/parse
./scripts/check_v2.sh
```

Integration tests are gated by `TEST_DATABASE_URL` and skip when it is absent.

---

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Local stack does not start | Docker running; ports 5173/8000 free |
| `bootstrap` failed | `docker compose logs bootstrap`; migrations may still be starting |
| Login invalid | Account exists; password; bootstrap output |
| `401 invalid_session` | Session expired or revoked; sign in again |
| `403 approval_required` | Approve the account at `/admin` |
| `relation "profiles" does not exist` | `DB_SCHEMA` differs from the migrated schema |
| Database unreachable | `DATABASE_URL`, `db` health, network/firewall |
| CORS error | `CORS_ORIGINS` must equal the frontend origin |
| Media URL fails | `PUBLIC_API_URL` must be the public HTTPS backend origin |
| Migration failure | `docker compose logs migrate`; apply files in filename order |
| Offline data missing | Browser storage/cache cleared or evicted |
| Port conflict | Stop the old stack before `docker compose up` |
