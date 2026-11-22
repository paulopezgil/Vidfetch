# Project agents

These are repo-local OpenCode agents for the Vidfetch project, discovered from
`.opencode/agents/`. Each Markdown file is one agent (frontmatter + system prompt).

The canonical repo-wide rules (branches, versioning, v2 architecture guardrails,
and verification) live in the root [`AGENTS.md`](../AGENTS.md). Agent prompts add
scope and worktree details on top of those rules.

| Agent | Mode | Where to run it | Purpose |
| --- | --- | --- | --- |
| `orchestrator` | primary | main checkout (on `dev`) | Owns the Git workflow, verifies and merges work, ships releases from `main` |
| `backend` | all | backend worktree (on `dev-backend`) | Backend (FastAPI + yt-dlp), one commit per prompt, real tests |
| `frontend` | all | frontend worktree (on `dev-frontend`) | Material Design 3 UI, one commit per prompt |

## Usage

Open OpenCode in the relevant directory and **select the agent** before (or
during) the session:

- `Ctrl+X` then `a` — list agents (`agent.list`); or
- `Shift+Tab` — cycle to the next agent (`agent.cycle`).

Examples (the worktrees are conventionally sibling directories named
`<main-checkout>-backend` / `<main-checkout>-frontend`; find the real paths with
`git worktree list`):

```bash
# Orchestrator (from the main checkout, where `dev` is checked out)
cd <main-checkout> && opencode

# Backend agent (from the backend worktree, on `dev-backend`)
cd <backend-worktree> && opencode

# Frontend agent (from the frontend worktree, on `dev-frontend`)
cd <frontend-worktree> && opencode
```

Because the two worktrees are separate checkouts, each needs this `.opencode/`
folder present in its working tree. After adding or changing agents here, sync
`dev` into the worktrees:

```bash
git -C <backend-worktree> merge dev
git -C <frontend-worktree> merge dev
```

## Workflow summary

- `main` = production/releases · `dev` = integration · `dev-backend` /
  `dev-frontend` = the two agents' branches (one per worktree).
- Agents work in scope, produce **one commit per prompt**, verify, and report.
- The orchestrator verifies (tests, build, mutation checks) and merges into
  `dev` with conventional merge commits — **no version numbers on `dev`**.
- Releases happen only from `main`: merge `dev` → `main`, bump `APP_VERSION`,
  commit `release: vX.Y.Z`, tag `vX.Y.Z`, and push `main` plus tags.

See `.opencode/agents/orchestrator.md` for the full procedure.
