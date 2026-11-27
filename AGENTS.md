# Vidfetch — Agent Rules

This file is the canonical repo-wide rulebook for OpenCode agents. Agent-specific
scope and worktree details live in `.opencode/agents/*.md`.

## Current state

- `main` — stable production releases only. Current release: `v2.5.1`.
- `dev` — active development and integration for the next release.
- The v2 rewrite is released; there is no long-lived `v2` branch anymore.
- v2 stack: React + FastAPI + **PostgreSQL** + **local email/password sessions**
  + shared media cache. Supabase and Google OAuth are gone.

The v2 design is `docs/ARCHITECTURE_V2.md`. `docs/V2_SETUP.md` explains
local/production setup, and `docs/IMPLEMENTATION_STATUS.md` tracks progress.
The root `README.md` documents the shipped application.

## Branches and worktrees

Worktrees live inside the main checkout under `.worktrees/` (gitignored).

| Branch | Worktree | Owner |
| --- | --- | --- |
| `main` | main checkout, during release only | Orchestrator |
| `dev` | main checkout | Orchestrator |
| `dev-backend` | `.worktrees/backend` | Backend agent |
| `dev-frontend` | `.worktrees/frontend` | Frontend agent |

- One branch per worktree.
- Merge into a branch from the worktree that has it checked out.
- Backend agent edits only `backend/**`; frontend agent edits only
  `frontend/**`. Database migrations (`db/`), root Docker/CI, and docs are
  orchestrated at the `dev` level.
- After changing agent files on `dev`, sync the worktrees with
  `git -C .worktrees/backend merge dev` and
  `git -C .worktrees/frontend merge dev`.

## Versioning and commits

- `MAJOR.MINOR.PATCH`, chosen only at release time from `main`.
- Tags keep the `v` prefix (`v2.0.0`).
- `backend/version.py:APP_VERSION` is the single version source; bump it only in
  the `release:` commit on `main`.
- Conventional Commits: `feat:`, `fix:`, `refactor:`, `chore:`, `docs:`,
  `test:`, `build:`, `ci:`. `release: vX.Y.Z` is only for `main`.
- Never put version numbers in development or merge commit messages.
- One commit per bounded agent prompt; leave the tree clean.
- Merge feature branches into `dev` with `--no-ff` and a conventional message.

## v2 architecture guardrails

- PostgreSQL is the application database (psycopg 3 pool, repository/service
  layer). Local SQLite is v1 only. Supabase is not a dependency.
- All application tables live in the schema named by `DB_SCHEMA` (default
  `public`; a dedicated schema such as `vidfetch` is supported). Backend SQL
  must use the validated schema helper, never a hardcoded `public.` prefix.
  Migrations are rendered from `db/templates/` with the same schema.
- Authentication is local: Argon2id `profiles.password_hash` plus opaque bearer
  tokens whose SHA-256 hashes live in `auth_sessions`. `/api/auth/register`,
  `/api/auth/login`, `/api/auth/logout`, and `/api/auth/password` are the auth
  surface. Never log raw tokens or password hashes.
- `profiles.is_approved` and `profiles.app_role` are the authorization source of
  truth. Pending users may call `/api/me`, `/api/health`, logout, and their own
  password change only.
- Media files are a global cache; users own jobs/library entries, not shared
  files. User deletion must not delete shared media.
- Dedupe key is `(canonical_id, options_hash)`; claims are atomic with leases.
- The queue is the `download_jobs` table; use `FOR UPDATE SKIP LOCKED`.
- Progress is polled. Media uses short-lived HMAC-signed URLs; JSON API uses
  opaque Bearer session tokens.
- Store relative media paths and resolve them under `DOWNLOAD_DIR`; reject
  traversal, symlinks, and absolute paths.
- Reject SSRF/private URLs unless `ALLOW_PRIVATE_URLS=true` (trusted local tests
  only). Never enable it in production.
- Never expose `DATABASE_URL`, `MEDIA_TOKEN_SECRET`, password hashes, or session
  tokens in the frontend, logs, or errors.

## Verification

From the relevant worktree:

```bash
# Backend
python3 -m pytest backend/tests -q
python3 -c "import backend.app.main"

# Backend with real PostgreSQL (migrated throwaway DB)
TEST_DATABASE_URL=postgresql://... python3 -m pytest backend/tests -q

# Frontend
cd frontend && npm run build
# serve-check: npm run preview + curl -> 200

# Integrated v2
./scripts/check_v2.sh
```

- Tests must be real. No `xfail`, `assert True`, or “did not raise” tests.
- Integration tests are gated by `TEST_DATABASE_URL`; the DB must have
  `db/migrations` applied and must not be the production database.
- Run a mutation check for new behavior: break it, confirm the specific test
  fails, then revert.
- Do not merge unverified work. Report exact commands and results.
