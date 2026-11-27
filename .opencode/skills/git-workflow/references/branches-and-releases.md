# Branches and releases

## Branch roles

- `main` — only production-ready releases. Version bumps, tags and the official
  release commit happen here and nowhere else.
- `dev` — integration branch for all completed agent work. No release version
  numbers in its commit messages.
- `dev-backend`, `dev-frontend`, `dev-<feature>` — short-lived agent branches,
  each checked out in its own worktree.

There is no separate `prod` branch.

## Normal release

Only when the human authorizes a production update:

1. Start from a clean main checkout on `dev`.
2. Run the release checks on `dev`:
   - backend tests, including real PostgreSQL when available;
   - frontend production build and route smoke check;
   - migration render check;
   - `docker compose` or deployment checks required by the release.
3. Choose the version from `references/versioning.md`.
4. Merge `dev` into `main` from the main checkout that has `main` checked out:

   ```bash
   git switch main
   git merge --no-ff dev -m "vX.Y.Z: merge dev into main"
   ```

5. Bump `backend/version.py:APP_VERSION`; update package versions, changelog and
   release docs.
6. Commit and tag:

   ```bash
   git add backend/version.py frontend/package.json frontend/package-lock.json \
     CHANGELOG.md docs/IMPLEMENTATION_STATUS.md AGENTS.md
   git commit -m "vX.Y.Z: release"
   git tag -a vX.Y.Z -m "vX.Y.Z <summary>"
   ```

7. Push only when the human asks:

   ```bash
   git push origin main --tags
   ```

The release commit and every other commit on `main` starts with the version.

## Direct main fix

Only when the human explicitly asks to bypass `dev`:

1. Apply the minimal fix on `main`.
2. Verify it.
3. Commit with the version prefix, e.g.
   `vX.Y.(Z+1): fix(frontend): ...`.
4. Bump the version, tag and push only if the human asked for a release/push.

Do not silently make product changes directly on `main`.

## After a release

- `main` stays at the release commit.
- `dev` remains the integration branch; do not put the release version number on
  routine `dev` commits.
- If the human asks to continue development, keep working on `dev`; the next
  version is chosen when the next release is authorized.
