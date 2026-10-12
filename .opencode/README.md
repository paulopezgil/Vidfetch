# Project agents

These are repo-local OpenCode agents for the vidfetch project, discovered from
`.opencode/agents/`. Each Markdown file is one agent (frontmatter + system prompt).

| Agent | Mode | Where to run it | Purpose |
| --- | --- | --- | --- |
| `orchestrator` | primary | main checkout (`~/Projects/yt-dlp-frontend`, on `dev`) | Owns the Git workflow, verifies and merges work, drives to v1.0.0 |
| `backend` | all | backend worktree (`~/Projects/yt-dlp-frontend-backend`, on `dev-backend`) | FastAPI + yt-dlp backend, one commit per prompt, real tests |
| `frontend` | all | frontend worktree (`~/Projects/yt-dlp-frontend-frontend`, on `dev-frontend`) | Material Design 3 UI, one commit per prompt |

## Usage

Open OpenCode in the relevant directory and **select the agent** before (or
during) the session:

- `Ctrl+X` then `a` — list agents (`agent.list`); or
- `Shift+Tab` — cycle to the next agent (`agent.cycle`).

Examples:

```bash
# Orchestrator (from the main checkout)
cd ~/Projects/yt-dlp-frontend && opencode

# Backend agent (from the backend worktree)
cd ~/Projects/yt-dlp-frontend-backend && opencode

# Frontend agent (from the frontend worktree)
cd ~/Projects/yt-dlp-frontend-frontend && opencode
```

Because the two worktrees are separate checkouts, each needs this `.opencode/`
folder present in its working tree. After adding or changing agents here, sync
`dev` into the worktrees:

```bash
git -C ~/Projects/yt-dlp-frontend-backend merge dev
git -C ~/Projects/yt-dlp-frontend-frontend merge dev
```

## Workflow summary

- `main` = production/releases · `dev` = integration · `dev-backend` /
  `dev-frontend` = the two agents' branches (one per worktree).
- Agents work in scope, produce **one commit per prompt**, verify, and report.
- The orchestrator verifies (tests, build, mutation checks) and merges into
  `dev` with a version-named merge commit (`vX.Y.Z <summary>`), and finally
  merges `dev` → `main` as `v1.0.0`.

See `.opencode/agents/orchestrator.md` for the full procedure.
