# Agent delegation and worktrees

The allowed depth is fixed:

```text
orchestrator
  ├─ backend ── backend-worker (leaf, cannot delegate)
  └─ frontend ─ frontend-worker (leaf, cannot delegate)
```

## Parent agents (`backend`, `frontend`)

- May spawn **multiple leaf workers** of their own domain using the `subagent`
  tool:
  - `agent: backend-worker`
  - `agent: frontend-worker`
- Must never delegate to a peer/primary agent (`backend`, `frontend`,
  `general`, `explore`) or to an `orchestrator`.
- Should split only independent file areas. Two workers must not edit the same
  files or share a worktree.
- Remains responsible for:
  - reviewing the leaf diff and scope;
  - re-running tests/build;
  - merging leaf branches back into its own integration branch
    (`dev-backend` / `dev-frontend`);
  - reporting one integrated result to the orchestrator.

## Leaf workers (`backend-worker`, `frontend-worker`)

- Work only in the assigned worktree/branch and folder.
- Produce exactly one commit for the assigned prompt.
- **Never call the `subagent` tool or spawn another agent.** There is no third
  level.
- Do not push, tag, release, or open GitHub issues/PRs.

## Worktree per worker

When parallel work is useful, the parent creates one worktree per independent
task:

```bash
git worktree add .worktrees/backend-<task> -b dev-backend-<task> dev-backend
git worktree add .worktrees/frontend-<task> -b dev-frontend-<task> dev-frontend
```

Give the worker:

- the absolute worktree path;
- the exact branch;
- the allowed folder/files;
- the verification command;
- the one-commit/report requirement.

The worker commits there; the parent merges the leaf branch into its own branch
from its own worktree:

```bash
git merge --no-ff dev-backend-<task> -m "feat(backend): <summary>"
git merge --no-ff dev-frontend-<task> -m "feat(frontend): <summary>"
```

The orchestrator then merges the parent branches into `dev` as usual.

For small tasks, skip the extra worktree and let the parent do the work
directly.
