# Versioning

Versions use `MAJOR.MINOR.PATCH`. Tags are `vMAJOR.MINOR.PATCH` (for example
`v2.6.3`).

## Segment meanings for this project

| Segment | Use it for | Who decides |
| --- | --- | --- |
| **MAJOR** | Substantial app or architecture rewrites, incompatible changes, or a new product shape. Example: the multi-user server/client rewrite that became `v2.0.0`. | Human |
| **MINOR** | A group of related changes delivered in one AI working session. | Human normally says; if not, ask before bumping |
| **PATCH** | One individual change, bug fix, copy fix or small feature. | AI may choose the third number under supervision |

The human's explicit version or instruction always wins.

## Files to keep in sync at release time

- `backend/version.py` → `APP_VERSION` is the single source of truth.
- `frontend/package.json` and `frontend/package-lock.json` root version.
- `CHANGELOG.md` release heading and release notes.
- `docs/IMPLEMENTATION_STATUS.md` current released version and release checklist.
- `AGENTS.md` current release line.

Do not bump these files on `dev` or feature branches as routine work.

## Main commit naming

All commits created on `main` start with the version tag:

```text
v2.6.3: release
v2.6.3: merge dev into main
v2.6.4: fix(frontend): keep the header below the iOS safe area
```

The version in a direct-main commit is the version that the commit belongs to
(usually the next patch), even if the tag is created in a following commit.

## Dev and feature commit naming

No version numbers:

```text
feat(frontend): add the quality menu
fix(backend): classify native audio by job intent
refactor(frontend): extract the row actions
```
