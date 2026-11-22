# Vidfetch v2 — Setup and Smoke-Test Guide

Status: draft for the v2 implementation. Update this document as the
implementation lands.

This guide covers a hosted Supabase project and a local application. The
production deployment uses the same values with production redirect URLs.

---

## 1. Create the Supabase project

1. Create a project at <https://supabase.com>.
2. Note the project URL and keys under **Project Settings → API**:
   - Project URL → `SUPABASE_URL`
   - `anon` public key → `SUPABASE_ANON_KEY`
   - `service_role` key → `SUPABASE_SERVICE_ROLE_KEY` (backend only)
3. Note the Postgres connection string under **Project Settings → Database**.
   Use the **pooler** connection string for `DATABASE_URL` in production.
   For local development, the direct connection string is fine.

## 2. Enable Google OAuth

1. Create a Google Cloud OAuth 2.0 client (Web application).
2. Add authorized redirect URIs:
   - Hosted Supabase callback:
     `https://<project-ref>.supabase.co/auth/v1/callback`
   - Local Supabase callback (if using `supabase start`):
     `http://127.0.0.1:54321/auth/v1/callback`
3. In Supabase: **Authentication → Providers → Google**, enable it and paste
   the client ID and secret.
4. In Supabase: **Authentication → URL Configuration**:
   - Site URL: `http://localhost:8000` for local production-like testing
   - Additional redirect URLs:
     - `http://localhost:8000`
     - `http://localhost:5173` (Vite dev server)

## 3. Apply the database migrations

The committed `supabase/migrations/*.sql` target `public` and are generated from
`supabase/templates/*.sql.template`. `DB_SCHEMA` selects the application schema.

### Hosted project — default `public`

```bash
npx supabase login
npx supabase link --project-ref <project-ref>
npx supabase db push
```

Or run the committed migrations in the Supabase SQL editor.

### Local Supabase — default `public`

```bash
npx supabase start
npx supabase db reset
```

The local API URL and keys are printed by `supabase status`. The local database
is disposable; `db reset` reapplies the public migrations and `seed.sql`.

### Dedicated schema such as `vidfetch`

Render the templates for the schema and apply them. The backend must use the
same `DB_SCHEMA` value.

```bash
DB_SCHEMA=vidfetch python scripts/render_migrations.py \
  --output /tmp/vidfetch-migrations

DATABASE_URL=postgresql://... \
  python scripts/apply_migrations.py \
  --migrations-dir /tmp/vidfetch-migrations
```

For local Supabase, reset the stack from a temporary workdir that contains the
rendered migrations. This replaces the public tables with the dedicated schema:

```bash
mkdir -p /tmp/vidfetch-supabase/supabase
cp supabase/config.toml supabase/seed.sql /tmp/vidfetch-supabase/supabase/
DB_SCHEMA=vidfetch python scripts/render_migrations.py \
  --output /tmp/vidfetch-supabase/supabase/migrations

# start the stack once from the repo (pinned CLI 3.2.0)
npx supabase --version
npx supabase start

# apply the custom-schema migrations to the local database
npx supabase --workdir /tmp/vidfetch-supabase db reset
```

Then set `DB_SCHEMA=vidfetch` in `.env` before starting the backend. Verify:

```bash
curl -s http://127.0.0.1:8000/api/health
```

The migration renderer validates the schema with the same rules as the backend
and rejects Supabase-managed schemas (`auth`, `storage`, `pg_*`, etc.).

> The repository intentionally does not seed an administrator. See section 5.

## 4. Configure the application

```bash
cp .env.example .env
```

Fill in at least:

```dotenv
SUPABASE_URL=...
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...
DATABASE_URL=...
DB_SCHEMA=public   # or vidfetch when using rendered custom migrations
MEDIA_TOKEN_SECRET=<long random string>
VITE_SUPABASE_URL=...
VITE_SUPABASE_ANON_KEY=...
```

Generate a media token secret with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Never commit `.env`. The frontend only receives the `VITE_*` values at build
time; it must never receive `SUPABASE_SERVICE_ROLE_KEY` or `DATABASE_URL`.

## 5. First admin bootstrap

1. Start the backend and frontend.
2. Sign in with Google.
3. The account lands on `/pending` because `is_approved = false`.
4. Promote the first account:

```bash
DATABASE_URL=... python3 scripts/promote_admin.py --email you@example.com
```

5. Refresh the app or wait for the pending page to refresh. The account is now
   an approved admin and can open `/admin`.

Do not commit real admin emails or UUIDs to `supabase/seed.sql`.

## 6. Run locally

### Backend

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn backend.app.main:app --reload --port 8000
```

The v2 backend entry point is `backend.app.main:app`. The v1 backend remains on
`dev` until the v2 branch reaches parity.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The Vite dev server should proxy `/api` to the
backend, or `VITE_API_BASE` can point at `http://localhost:8000/api`.

## 7. Smoke test

- [ ] Anonymous visit redirects to `/login`.
- [ ] Google sign-in creates a `profiles` row.
- [ ] New account is sent to `/pending` and cannot call download endpoints.
- [ ] `scripts/promote_admin.py` promotes the first account.
- [ ] Admin can approve a second account.
- [ ] Approved user can fetch video metadata.
- [ ] Approved user can start a video download.
- [ ] A second request for the same media/options reuses the cached asset.
- [ ] Approved user can start and complete a playlist download.
- [ ] Playlist ZIP downloads.
- [ ] Progress polling updates and cancellation works.
- [ ] Media preview works through signed URLs.
- [ ] Revoking the second account blocks API and media access.
- [ ] Backend restart recovers stale jobs without duplicate downloads.
- [ ] `GET /api/health` reports database/auth/storage status.

## 8. Docker

The v2 image is a single application origin with a persistent media volume.

### Build and test without live Supabase

The Vite build only needs the **public** Supabase URL and anon key. This smoke
test deliberately runs with `ENVIRONMENT=test` so the container starts without
a database, and verifies the entrypoint, SPA serving, and health endpoint:

```bash
sudo docker build \
  --build-arg VITE_SUPABASE_URL=https://example.supabase.co \
  --build-arg VITE_SUPABASE_ANON_KEY=test-anon-key \
  -t vidfetch-v2-test .

sudo docker run --rm -d --name vidfetch-v2-test \
  -p 18000:8000 \
  -e ENVIRONMENT=test \
  -e DOWNLOAD_DIR=/app/downloads \
  -e FRONTEND_DIST=/app/frontend-dist \
  vidfetch-v2-test

curl -s http://127.0.0.1:18000/api/health
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18000/
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18000/login

sudo docker rm -f vidfetch-v2-test
```

Expected during this offline smoke test: `/api/health` returns `200` with
`status: degraded` and `database: false`; `/` and `/login` return `200`.

### Real run

```bash
cp .env.example .env   # fill in the real Supabase values
docker compose up --build
```

Then open <http://localhost:8000>. The application container must receive the
Supabase and database values from `.env` or the host environment; the service
role key must never be baked into the frontend build. The Docker build may warn
about the public `VITE_SUPABASE_ANON_KEY` build argument; that key is public by
design, unlike the service-role key.

## 9. Troubleshooting

| Symptom | Check |
| --- | --- |
| `401` on every API call | Supabase URL/keys, JWT issuer/audience, clock skew |
| `403 approval_required` | `profiles.is_approved`; promote the first admin |
| Google login redirects to an error | Supabase redirect URLs and Google OAuth client URIs |
| Database connection refused | Supabase project running; pooler vs direct URL; SSL mode |
| `relation "profiles" does not exist` | Migrations not applied or wrong database |
| Media URL `401` | Signed URL expired; request a new token |
| Downloads fail with 403 from YouTube | Update yt-dlp; see v1 README troubleshooting |
