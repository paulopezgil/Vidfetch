# Worktrees

Worktrees let several agents work on one repository at the same time. Each
worktree has exactly one checked-out branch.

## Discover reality first

Never assume paths or branch state:

```bash
git worktree list
git branch -vv
git status --short
```

## Create one

```bash
git worktree add .worktrees/<name> -b dev-<name> <base-branch>
```

Examples:

```bash
git worktree add .worktrees/backend -b dev-backend dev
git worktree add .worktrees/frontend -b dev-frontend dev
git worktree add .worktrees/frontend-biblioteca -b dev-frontend-biblioteca dev
```

`<base-branch>` is normally `dev`. Use `main` only for an explicitly authorized
maintenance branch.

## Agent scope

- Backend worktree: edits only `backend/**`.
- Frontend worktree: edits only `frontend/**`.
- Database migrations (`db/**`), root Docker/CI, docs and version files are
  coordinated from the main checkout.

## Sync a worktree

When `dev` has moved, bring it into the worktree before starting:

```bash
git -C .worktrees/<name> merge dev
```

Do not check out a branch that is already active in another worktree.

## Merge back

Merge the feature branch into `dev` from the main checkout that has `dev`
checked out:

```bash
git switch dev
git merge --no-ff dev-<name> -m "<type>(<scope>): <summary>"
```

The merge commit on `dev` carries no version number.

## Remove a finished worktree

After its branch has been merged and is no longer needed:

```bash
git worktree remove .worktrees/<name>
git branch -d dev-<name>
```

Use `git worktree remove --force` only after the human confirms that any
uncommitted work can be discarded.
