---
name: commit
description: Commit changes in this repo using its versioned commit convention. The subject line is only the version (vX.Y.Z), details go in the body, the version is bumped in pyproject.toml and uv.lock, and CHANGELOG.md gets a new section, all after pre-commit passes. Use whenever the user asks to commit, make a commit, cut a version, bump the version or release, or invokes /commit.
---

# Versioned commit

Every commit in this repo is a version. Follow these steps in order.

## 1. Check the state

- `git status` and `git diff` (staged and unstaged). Work out what is changing. If nothing is, stop and say so.
- Find the current version: the latest subject in `git log --format=%s` that matches `^v\d+\.\d+\.\d+$`. If
  none exists, use `version` from `pyproject.toml`.
- Make sure the hooks are installed: if `.git/hooks/pre-commit` or `.git/hooks/pre-push` is missing, run
  `uv run pre-commit install`.

## 2. Choose the new version

Use semantic versioning from the current version:

- **patch** (`v0.2.0` → `v0.2.1`): bug fixes, small changes, docs, dependency bumps, refactors
- **minor** (`v0.2.1` → `v0.3.0`): new features, backwards compatible
- **major** (`v0.3.0` → `v1.0.0`): breaking changes, such as removed config, changed CLI or changed output format

If the user named a version or a bump level, use that. If it is genuinely unclear between minor and major, ask.

## 3. Update the version files

1. Set `version = "X.Y.Z"` in `pyproject.toml` (no `v` prefix).
2. Run `uv lock` so `uv.lock` records the new project version.
3. Add a section at the **top** of `CHANGELOG.md`, below the intro, in Keep a Changelog format:

   ```markdown
   ## vX.Y.Z - YYYY-MM-DD

   ### Added
   - ...
   ### Changed
   - ...
   ### Fixed
   - ...
   ### Removed
   - ...
   ```

   Use today's date and include only the groups that apply. Describe the changes for a reader, not file by file.

## 4. Run pre-commit

- Stage the intended files explicitly by name. Never stage `.env`, keys, logs or `outputs/`.
- Run `uv run pre-commit run --all-files`. If hooks modify files, review them, stage them, and run again until
  everything passes.
- If a hook fails and cannot be auto-fixed, fix the cause. Never use `--no-verify` and never edit
  `.pre-commit-config.yaml` to skip a check.

## 5. Commit

The subject is **only** `vX.Y.Z`. Put a summary and bullet details in the body:

```bash
git commit -F - <<'EOF'
vX.Y.Z

One-sentence summary of the change.

- detail
- detail
EOF
```

Windows PowerShell has no heredoc. Use repeated `-m` instead (each `-m` becomes its own paragraph):

```powershell
git commit -m "vX.Y.Z" -m "One-sentence summary." -m "- detail`n- detail"
```

Rules:

- Nothing on the subject line except the version.
- No `Co-Authored-By` trailers for Claude or any AI, and no "Generated with" lines.
- `pyproject.toml`, `uv.lock` and `CHANGELOG.md` go in the same commit as the change.

## 6. Verify

- `git log -1 --format='%s%n---%n%b'`: the subject must match `^v\d+\.\d+\.\d+$`.
- Push only if the user asked. The pre-push hook runs the same checks again.
