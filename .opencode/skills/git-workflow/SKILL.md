---
name: git-workflow
description: Vidfetch Git workflow for branches, worktrees, subagent merges, semantic versioning, version-prefixed main commits, releases and optional gh usage. Use before branching, merging agent work, choosing a version, cutting a release, tagging, pushing, or opening a GitHub issue/PR.
metadata:
  updated: 2026-11-27
  version: 1.0.0
---

# Vidfetch Git workflow

## Purpose

Keep the repository history predictable while several agents work in parallel.
This skill is the operational Git guide for the orchestrator and the subagents.

Read only the references needed for the task:

| Need | Reference |
| --- | --- |
| Branch model, release sequence, hotfixes | `references/branches-and-releases.md` |
| `MAJOR.MINOR.PATCH` meaning and version files | `references/versioning.md` |
| Creating, syncing and removing worktrees | `references/worktrees.md` |
| Allowed agent depth and leaf workers | `references/agent-delegation.md` |
| Verifying and merging subagent branches | `references/subagent-merges.md` |
| Permission and setup for the GitHub CLI | `references/gh.md` |

The human's explicit instruction always overrides this skill. Architecture,
security and coding rules still live in the root `AGENTS.md`.

## Branch model

| Branch | Role | Typical checkout |
| --- | --- | --- |
| `main` | Production only. Receives `dev` when a release is authorized. | Main checkout |
| `dev` | Active development and integration. Never carries release version numbers. | Main checkout |
| `dev-backend` / `dev-frontend` | Agent feature branches. One branch per worktree. | Worktrees |
| `dev-<feature>` | Optional extra worktree branch for parallel agent work. | Worktrees |

Rules:

- **`main` is production.** Do not merge into it unless the human has authorized
  a release (or explicitly asked for a direct main fix).
- **`dev` is integration.** Agent work lands there first with `--no-ff` merge
  commits.
- **One branch per worktree.** Never check out a branch that is active in another
  worktree.
- A subagent works in its own worktree and stays inside its folder (`backend/**`
  or `frontend/**`).

## Main commit names

Every commit created on `main` **must start with the version tag**, including
release, merge and direct-main maintenance commits:

```text
v2.6.3: release
v2.6.3: merge dev into main
v2.6.4: fix(frontend): keep the header below the iOS safe area
```

Tags keep the `v` prefix (`v2.6.3`).

Commits on `dev` and feature branches use Conventional Commits **without** a
version number:

```text
feat(frontend): add the quality menu
fix(backend): classify native audio by job intent
```

## Version semantics

| Segment | Meaning | Decision |
| --- | --- | --- |
| **MAJOR** | Exceptional, substantial app/architecture change, e.g. the multi-user server/client rewrite (`v2.0.0`) | Human only |
| **MINOR** | A group of related changes from an AI working session | Human normally decides; ask if not specified |
| **PATCH** | Individual change, fix or small feature | AI may choose the third number, supervised by the human |

The human can always override the choice. `backend/version.py:APP_VERSION` is the
single version source and is bumped only in the release commit on `main`.

## Standard flow

1. Discover the real state before acting:
   `git worktree list`, `git branch -vv`, `git status --short`,
   `git log --oneline --graph --all -20`.
2. Work on `dev` or a feature worktree. Keep each agent prompt bounded: one
   purpose, one commit, verify before committing.
3. Merge agent work into `dev` from the main checkout with `--no-ff` and a
   Conventional Commit message. Verify the diff, tests/build and scope first.
4. Release only when authorized:
   merge `dev` → `main` with a version-prefixed commit, bump
   `APP_VERSION`/package versions, update the changelog/docs, commit
   `vX.Y.Z: release`, tag `vX.Y.Z`, then push only when asked.
5. Never force-push, never rewrite published `main`, and never expose secrets or
   tokens in commits, logs or reports.

## Pushing and GitHub

Do not push, create issues, open pull requests or use `gh` unless the human
explicitly asks for that action. When they do, read
`references/gh.md` first and verify `gh auth status`.
