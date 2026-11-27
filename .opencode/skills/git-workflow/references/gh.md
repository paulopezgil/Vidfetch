# GitHub CLI (`gh`)

`gh` is optional. It is **not** allowed to push, create issues or open pull
requests unless the human explicitly asks for that action.

## Before using it

```bash
command -v gh
gh auth status
```

If `gh` is missing or not authenticated:

- do not install or log in silently;
- tell the human which command is needed;
- if they want it set up, ask them to run:

  ```bash
  gh auth login
  ```

Never print, commit or paste an auth token.

## Typical explicitly authorized actions

Push the current branch:

```bash
git push origin <branch>
```

Push a release branch and its tags:

```bash
git push origin main --tags
```

Create a pull request:

```bash
gh pr create --base main --head dev \
  --title "vX.Y.Z: <summary>" \
  --body "<what changed and how it was verified>"
```

Open an issue:

```bash
gh issue create --title "<title>" --body "<reproduction and evidence>"
```

## Safety

- A push to `main` is a production action. Confirm the human asked for it.
- Never force-push a shared branch.
- Keep secrets out of command lines, logs, commit messages and reports.
- After a push, report the remote commit/tag and whether any deployment was
  triggered.
