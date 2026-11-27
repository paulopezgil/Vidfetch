# Verifying and merging subagent work

Do not merge blind, even when the agent reports success.

## 1. Bound the prompt

Every subagent prompt should include:

- one clear purpose and the allowed folder/worktree;
- the requirement to verify before committing;
- exactly one commit for the prompt;
- the standard report format: Task / Changed / Verified / Commit / Open items /
  scope confirmation.

## 2. Inspect the branch

```bash
git -C <worktree> status --short
git -C <worktree> log --oneline dev..dev-<name>
git -C <worktree> diff --stat dev..dev-<name>
git -C <worktree> diff --name-only dev..dev-<name>
```

The paths must be confined to the agent's scope (`backend/**` or `frontend/**`).
The tree must be clean.

## 3. Re-run the verification

- Backend: `python3 -m pytest backend/tests -q` and the real-PostgreSQL suite
  when available.
- Frontend: `npm run build` and a preview/curl route check.
- Migrations: `python3 scripts/render_migrations.py --check`.
- For critical behavior, run a mutation check: break it, confirm the specific
  test fails, then restore and confirm green. A test that cannot fail is a bug.

## 4. Check for overlap

```bash
comm -12 \
  <(git diff --name-only dev..dev-backend | sort) \
  <(git diff --name-only dev..dev-frontend | sort)
```

The output should be empty. If it is not, inspect the shared files before
merging.

## 5. Merge into `dev`

From the main checkout on `dev`:

```bash
git switch dev
git merge --no-ff dev-<name> -m "<type>(<scope>): <summary>"
```

No version number on `dev` merge commits.

## 6. Re-run integrated checks

After every merge, repeat the relevant tests/build on `dev`. If both sides
changed, run the full suite. Do not continue to the next agent until the
integrated tree is green.

## 7. Conflicts

Resolve conflicts in the branch that is checked out for the merge. Preserve both
features and the newest copy conventions. Re-run the build/tests after resolving.
Never commit conflict markers.

## 8. Report

Record the commit hashes, exact commands, test/build results and anything that
was not verified. The human should be able to reproduce the evidence.
