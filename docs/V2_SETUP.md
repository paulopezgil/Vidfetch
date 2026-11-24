# Vidfetch v2 — Setup and Deployment Guide

This guide covers both supported deployment modes:

- **Local development:** one `docker compose up` starts the Vite frontend, the
  FastAPI backend, and a complete local Supabase stack. No cloud account is
  required.
- **Production:** the frontend is deployed natively to **Vercel**, the backend
  runs as a container on a **VPS**, and both use **Supabase Cloud**.

The application code, database migrations, and API are the same in both modes.

---

## Part A — Local development

### A1. Prerequisites

- Docker Engine / Docker Desktop
- Docker Compose v2+
- Optional: the Supabase CLI, only if you want to run database commands from the
  host instead of through the Compose Supabase wrapper

Python, Node.js, `yt-dlp`, and FFmpeg are inside the images. You do **not** need
a Supabase Cloud project or Google OAuth credentials for local work.

### A2. Start the stack

From the repository root:

```bash
docker compose up --build
```

This starts:

| Service | Purpose | Address |
| --- | --- | --- |
| `frontend` | Vite dev server, hot reload | <http://localhost:5173> |
| `backend` | FastAPI + worker + FFmpeg | <http://localhost:8000> |
| `supabase` | Official Supabase CLI local stack | API `:54321`, DB `:54322` |
| `local-bootstrap` | Creates/approves the local admin | one-shot |
| Studio | Supabase web UI | <http://localhost:54323> |
| Mailpit | Local mail catcher | <http://localhost:54324> |

The first run pulls images and can take several minutes. Later runs are faster.

### A3. Local admin account

The `local-bootstrap` service creates:

```text
email:    admin@local.test
password: password123
```

Open <http://localhost:5173> and use the **local development** sign-in form.
Local email/password auth is enabled only because `docker-compose.yml` sets
`VITE_ENABLE_LOCAL_AUTH=true`. Production builds do not set this flag.

If the bootstrap service failed, inspect it:

```bash
docker compose logs local-bootstrap
docker compose up local-bootstrap
```

### A4. How the local Supabase service works

`docker/supabase` is a small wrapper around the official Supabase CLI:

- It runs the pinned Supabase CLI and the static Docker CLI.
- It mounts the host Docker socket, so the CLI can start the official local
  Supabase containers.
- It uses host networking so the CLI’s own health checks can reach the
  host-published Postgres/Auth ports.
- The repository is mounted at the same absolute path inside and outside the
  wrapper, so Docker path references remain valid.
- On `docker compose down`, the wrapper’s signal handler runs
  `supabase stop --no-backup` to stop the local stack.

Local development is therefore a four-service Compose stack, but only one
command:

```bash
docker compose up --build
```

### A5. Common local commands

```bash
# Logs
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f supabase

# Rebuild one service
docker compose up -d --build backend
docker compose up -d --build frontend

# Stop everything (the Supabase wrapper stops the CLI stack too)
docker compose down

# Reset the local database and reapply migrations
docker compose exec supabase supabase db reset
docker compose up local-bootstrap

# Check backend health
curl -s http://localhost:8000/api/health
```

If Supabase containers remain after a forced stop, run:

```bash
npx supabase stop --no-backup
```

### A6. Local ports

| Port | Service |
| --- | --- |
| `5173` | Vite frontend |
| `8000` | FastAPI backend |
| `54321` | Supabase API / Auth gateway |
| `54322` | Supabase Postgres |
| `54323` | Supabase Studio |
| `54324` | Mailpit |

If a port is already in use, stop the old stack before starting Compose.

### A7. Local environment overrides

The local stack uses development defaults from `docker-compose.yml`; no `.env`
is required. The fixed local Supabase keys are public, disposable values.

For frontend development outside Docker, copy `frontend/.env.example` to
`frontend/.env.local` and set:

```dotenv
VITE_SUPABASE_URL=http://127.0.0.1:54321
VITE_SUPABASE_ANON_KEY=<local anon key>
VITE_API_BASE=http://localhost:8000/api
VITE_ENABLE_LOCAL_AUTH=true
```

Never set `VITE_ENABLE_LOCAL_AUTH` in a production build.

---

## Part B — Production

Production uses three independently managed pieces:

```text
Vercel (frontend)  ──►  VPS (backend container)  ──►  Supabase Cloud
```

### B1. Supabase Cloud

1. Create a project at <https://supabase.com>.
2. Copy from **Project Settings → API**:
   - Project URL → `SUPABASE_URL`
   - `anon` key → `SUPABASE_ANON_KEY`
   - `service_role` key → `SUPABASE_SERVICE_ROLE_KEY` (backend only)
3. Copy the **pooler** connection string from
   **Project Settings → Database** → `DATABASE_URL`.
4. Create a Google Cloud OAuth 2.0 client and add the Supabase callback:
   `https://<project-ref>.supabase.co/auth/v1/callback`
5. Enable **Authentication → Providers → Google** in Supabase.
6. Configure **Authentication → URL Configuration**:
   - Site URL: `https://your-app.vercel.app`
   - Redirect URLs: `https://your-app.vercel.app` and
     `http://localhost:5173`

### B2. Apply migrations

Choose **one** schema per database.

**Default `public` schema:**

```bash
npx supabase login
npx supabase link --project-ref <project-ref>
npx supabase db push
```

You can also run the committed SQL files from `supabase/migrations/` in the
Supabase SQL editor.

**Dedicated schema (`vidfetch`):** do **not** run `db push` — the committed
migrations target `public`. Render the templates for `vidfetch` and apply the
rendered files instead. See [Custom database schema](#custom-database-schema).
Set `DB_SCHEMA=vidfetch` on the backend.

Do not install both schemas in the same database: the auth trigger would be
repointed and you would have two sets of tables.

### B3. Frontend on Vercel

Create a Vercel project:

- **Root Directory:** `frontend`
- **Framework:** Vite (auto-detected)
- **Build command:** `npm run build`
- **Output directory:** `dist`
- `frontend/vercel.json` supplies the SPA rewrite

Environment variables:

```dotenv
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-key
VITE_API_BASE=https://api.example.com/api
```

Do **not** add `VITE_ENABLE_LOCAL_AUTH`, `SUPABASE_SERVICE_ROLE_KEY`, or
`DATABASE_URL` to Vercel.

### B4. Backend on the VPS

Copy the repository to the VPS and create `.env` from `.env.example`:

```dotenv
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
DATABASE_URL=postgresql://...
DB_SCHEMA=public

PUBLIC_API_URL=https://api.example.com
CORS_ORIGINS=https://your-app.vercel.app
MEDIA_TOKEN_SECRET=<long random secret>
```

Start the backend-only stack:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

The backend image is built from `backend/Dockerfile` with the `backend/`
directory as its build context. It does not contain the frontend.

Put a TLS reverse proxy in front of port 8000. Example Caddyfile:

```caddyfile
api.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Important:

- `PUBLIC_API_URL` must be the public **HTTPS** backend origin. It is used for
  absolute signed media/thumbnail URLs.
- `CORS_ORIGINS` must include the exact Vercel origin.
- The media volume (`vidfetch_downloads`) must be persistent and backed up.
- The backend runs as a single instance with a local media volume.

### B5. First administrator

Sign in with Google once. The account is created with `is_approved=false` and
lands on `/pending`. Promote it from the Supabase SQL editor:

```sql
update public.profiles
   set is_approved = true,
       app_role = 'admin',
       approved_at = now(),
       approved_by = id
 where lower(email) = lower('you@example.com');
```

Or use the helper:

```bash
DATABASE_URL=... DB_SCHEMA=public \
  python3 scripts/promote_admin.py --email you@example.com
```

Refresh the app and approve other users at `/admin`.

### B6. Production checklist

- [ ] Supabase project created and Google provider enabled.
- [ ] Google OAuth callback and Supabase redirect URLs configured.
- [ ] Migrations applied (`public` or the chosen `DB_SCHEMA`).
- [ ] Backend `DB_SCHEMA` matches the schema that received the migrations.
- [ ] Dedicated schema: rendered migrations applied and `vidfetch` not exposed in the Data API.
- [ ] Vercel root directory is `frontend` and env values are set.
- [ ] Vercel does **not** contain backend secrets.
- [ ] VPS `.env` has `PUBLIC_API_URL`, `CORS_ORIGINS`, and backend secrets.
- [ ] TLS reverse proxy terminates HTTPS in front of the backend.
- [ ] `vidfetch_downloads` volume is persistent and backed up.
- [ ] First admin promoted.
- [ ] `/api/health` returns `ok` over HTTPS.
- [ ] A real video, playlist, and ZIP work from the Vercel origin.

---

## Custom database schema

The default schema is `public`, so forks work without extra configuration. A
deployment can use a dedicated schema such as `vidfetch`; the backend reads the
validated schema name from **`DB_SCHEMA`** and routes every query there.

Pick one schema per database. Do not apply both `public` and `vidfetch` in the
same project.

### 1. Render the migrations

```bash
DB_SCHEMA=vidfetch python3 scripts/render_migrations.py \
  --schema vidfetch \
  --output /tmp/vidfetch-migrations
```

The first rendered file creates the schema, grants usage, and sets default
privileges for `service_role`. The rest create the tables, RLS, and the
`auth.users` trigger. Confirm the files reference `"vidfetch"`.

Do **not** use `npx supabase db push` for a custom schema: the committed
`supabase/migrations/` files target `public`.

### 2. Apply them

**Supabase SQL Editor (cloud):** paste the rendered files in filename order
(`00000000000000_schema.sql` first).

**Or from the terminal**, using a direct/session connection on port `5432`
(not the `6543` transaction pooler):

```bash
DATABASE_URL='postgresql://postgres:<password>@db.<ref>.supabase.co:5432/postgres' \
  python3 scripts/apply_migrations.py \
  --migrations-dir /tmp/vidfetch-migrations
```

### 3. Point the backend at it

```dotenv
DB_SCHEMA=vidfetch
# the running backend can keep the transaction pooler on 6543
DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
```

Restart the backend. If `DB_SCHEMA` is missing or does not match the applied
migrations, requests fail with `relation "profiles" does not exist`.

### 4. Supabase UI settings

- Keep the **Data API disabled** and “Grant API access to new tables
  automatically” **off**.
- Keep “Enable RLS on new tables automatically” **on**. It mainly protects
  `public`; the migrations enable RLS explicitly in `vidfetch`.
- Do **not** add `vidfetch` to the Data API’s exposed schemas. The backend
  connects directly with `DATABASE_URL`.
- Auth URL Configuration and the Google provider are unchanged by the schema
  choice.

### 5. Verify

```sql
select table_name
  from information_schema.tables
 where table_schema = 'vidfetch'
 order by table_name;

select tgname
  from pg_trigger
 where tgrelid = 'auth.users'::regclass
   and not tgisinternal;
```

Expect the nine application tables and `on_auth_user_created`. Promote the first
admin in the same schema:

```sql
update vidfetch.profiles
   set is_approved = true,
       app_role = 'admin',
       approved_at = now(),
       approved_by = id
 where lower(email) = lower('you@example.com');
```

Or `DATABASE_URL=... DB_SCHEMA=vidfetch python3 scripts/promote_admin.py
--email you@example.com`.

### Notes

- `scripts/render_migrations.py --check` only verifies the committed `public`
  output; render custom schemas to a temporary directory.
- The pgTAP RLS tests in `supabase/tests/` are public-only.
- If the project already applied the public migrations, reset the database or
  start a fresh project before switching; otherwise two table sets exist and the
  auth trigger moves to the second one.

---

## Environment reference

### Backend / production

| Variable | Purpose |
| --- | --- |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Public Supabase key |
| `SUPABASE_SERVICE_ROLE_KEY` | Backend-only Auth admin key |
| `SUPABASE_JWKS_URL` | Optional JWT key-set override |
| `SUPABASE_JWT_ISSUER` | Optional JWT issuer override |
| `SUPABASE_JWT_AUDIENCE` | Optional JWT audience override |
| `DATABASE_URL` | Postgres connection string |
| `DB_SCHEMA` | Application schema (`public` by default) |
| `PUBLIC_API_URL` | Absolute public backend origin |
| `CORS_ORIGINS` | Comma-separated browser origins |
| `MEDIA_TOKEN_SECRET` | HMAC secret for signed media URLs |
| `MEDIA_TOKEN_TTL_SECONDS` | Signed URL lifetime |
| `DOWNLOAD_DIR` | Media root inside the container |
| `MAX_CONCURRENT_DOWNLOADS` | Global worker concurrency |
| `MAX_CONCURRENT_JOBS_PER_USER` | Per-user concurrency |
| `MAX_PLAYLIST_ITEMS` | Playlist item cap |
| `MAX_ASSET_BYTES` | Per-file size cap |
| `MIN_FREE_DISK_MB` | Disk-space safety floor |
| `JOB_LEASE_SECONDS` | Worker/asset lease duration |
| `ALLOW_PRIVATE_URLS` | Private URLs (local tests only) |

### Frontend / Vercel

| Variable | Purpose |
| --- | --- |
| `VITE_SUPABASE_URL` | Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | Public anon key |
| `VITE_API_BASE` | Absolute backend API URL |
| `VITE_ENABLE_LOCAL_AUTH` | Local development only; omit in production |

---

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Local stack does not start | Docker is running; ports 5173/8000/54321/54322/54323 are free |
| `local-bootstrap` failed | `docker compose logs local-bootstrap`; Auth may still be starting |
| Local login form is missing | `VITE_ENABLE_LOCAL_AUTH=true` in the frontend container env |
| `401` after local login | Backend must use the local JWKS URL, not the legacy HS256 secret |
| `401` in production | Supabase URL/keys, JWKS/issuer/audience, clock skew |
| `403 approval_required` | `profiles.is_approved` |
| `403 admin_required` | `profiles.app_role` |
| CORS error from Vercel | `CORS_ORIGINS` must exactly match the Vercel origin |
| Media URL fails from Vercel | `PUBLIC_API_URL` must be the public HTTPS backend origin |
| `relation "profiles" does not exist` | Migrations not applied or `DB_SCHEMA` mismatch |
| Custom schema fails after switching | Do not mix `public` and `vidfetch`; reset and apply one set |
| Google redirect error | Google callback and Supabase Site/Redirect URLs |
