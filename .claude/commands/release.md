---
description: Gitflow release — bump version on dev, promote dev to master with --no-ff, tag
allowed-tools: PowerShell, Read, Edit, Bash
---

Release Canlytics following gitflow: only finished and tested work in `dev` reaches `master`.

## Argument

`$ARGUMENTS` is the bump type: `patch`, `minor`, or `major` (default `patch`). See the SemVer policy in `AGENTS.md`.

## Steps

### 1 — Preconditions (stop and report if any fails)

- `git status` is clean and the current branch is `dev`. Every finished branch is already merged into `dev` with `--no-ff`.
- The full suite is green: `.venv/Scripts/python.exe -m unittest discover -s tests -t . -v`.
- `CHANGELOG.md` has entries under `## Unreleased`. A release with nothing listed there is a mistake.
- The user has approved this release. Never release on your own initiative.

### 2 — Bump on `dev`

1. Read `config/version.py` (`APP_VERSION`) and compute the new version. Bumping resets the lower parts: `0.4.0` → patch `0.4.1`, minor `0.5.0`, major `1.0.0`.
2. Edit `config/version.py`. It is the only source of the version.
3. In `CHANGELOG.md`, rename `## Unreleased` to `## X.Y.Z (YYYY-MM-DD)` and add a fresh empty `## Unreleased` above it.
4. Commit on `dev`:

```powershell
git add config/version.py CHANGELOG.md
git commit -m "chore(release): bump version to X.Y.Z"
```

### 3 — Promote `dev` → `master` and tag

```powershell
git checkout master
git merge --no-ff dev -m "release: merge dev into master (vX.Y.Z)"
git tag "vX.Y.Z"
git checkout dev
git log --oneline --graph -5 master
```

Never use `--squash`. A squash leaves no ancestry, so `git log master..dev` stops meaning anything.

### 4 — Report

Report the old and new version, the tag, and `git log --oneline -3 master`.

**NEVER** add `Co-Authored-By` or any AI signature. **No push**: the remote has SSL issues, so the user pushes manually (`git push origin master dev --follow-tags`).
