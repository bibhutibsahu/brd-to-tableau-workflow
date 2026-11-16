---
name: repo-baseline
description: Audit and set up the baseline hygiene of this project's Git repository, whatever its language or stack. Ensures a project-specific README, a tailored .gitignore that protects secrets and log files, secret-leak checks for environment variables, pre-commit hooks with the right linters (ruff for Python, sqlfluff for SQL, and so on), GitHub Actions workflows, and master as the default branch in Git and GitHub. Use this skill whenever the user asks to set up, initialise, bootstrap, tidy, audit, harden or "make production ready" a repository, mentions .gitignore, README, pre-commit, CI, GitHub workflows, linting setup, default branch or leaked secrets, or starts work in a repo that is missing any of these, even if they do not ask for a full audit.
---

# Repository Baseline

Bring this project's repository up to a consistent, secure baseline. Work for any project type: detect the stack first, then tailor every file to it. Never write generic boilerplate that ignores what is actually in the repo.

## Workflow

1. **Detect the project.** Inspect the repo root and subfolders for stack markers: `pyproject.toml`, `requirements*.txt`, `setup.py` (Python); `*.sql`, `dbt_project.yml` (SQL / dbt); `package.json` (Node / TypeScript); `go.mod`; `Cargo.toml`; `pom.xml` / `build.gradle`; `*.tf`; `Dockerfile`; `*.sh`. A repo can have several stacks; handle all of them. If the user states the project type, trust that and still check for others.
2. **Audit.** Check each item in the checklist below and record its status as present and correct, present but needs fixing, or missing.
3. **Report before changing.** Show the user a short audit summary and the planned changes. If a secret is found already committed, stop and raise it first (see Secrets).
4. **Apply fixes.** Create or update files. Preserve existing content the user wrote; merge rather than overwrite.
5. **Verify.** Run `pre-commit run --all-files` and the secret scan. Fix what fails, then give a final summary of what changed and anything the user must do manually (for example GitHub settings that need admin rights).

## Checklist

### 1. Default branch is `master`

- Local: `git config init.defaultBranch master`. If the repo uses another name, rename with `git branch -m <old> master`.
- Remote: if a GitHub remote exists, check with `gh repo view --json defaultBranchRef`. If it is not `master`, push `master` and run `gh repo edit --default-branch master`. Tell the user before deleting any old remote branch.
- Every workflow, branch protection rule and README badge must reference `master`, never `main`.

### 2. README.md populated for this project

The README must describe this specific project, using details discovered from the code. Include at least: project name and one-paragraph purpose; prerequisites and versions; installation and setup; configuration, listing every environment variable by name with a description (never real values) and pointing to `.env.example`; how to run, test and lint; project structure overview; contributing notes including pre-commit setup (`pre-commit install`); licence if one exists. Do not leave placeholder text such as "TODO" or "Describe your project here".

### 3. .gitignore tailored and protective

Build it from the detected stacks (for example `__pycache__/`, `.venv/`, `.pytest_cache/`, `.ruff_cache/` for Python; `node_modules/`, `dist/` for Node; `target/` for dbt; `.terraform/`, `*.tfstate*` for Terraform). Whatever the stack, it must always include:

```gitignore
# Secrets and environment
.env
.env.*
!.env.example
*.pem
*.key
*.p12
*.pfx
secrets/
credentials*.json
service-account*.json

# Logs
*.log
logs/
log/

# OS and editor
.DS_Store
Thumbs.db
.idea/
.vscode/*
!.vscode/extensions.json
```

After updating, check that no ignored file is still tracked: `git ls-files -ci --exclude-standard`. If any are, remove them from the index with `git rm --cached` (keeping them on disk) and tell the user.

### 4. Secrets and environment variables never reach Git or GitHub

- Provide `.env.example` with every variable name the code reads and empty or dummy values. Find names by searching for `os.environ`, `os.getenv`, `process.env`, `${{ secrets.` and similar.
- Add secret scanning in three layers: a `gitleaks` pre-commit hook, a gitleaks job in CI, and GitHub's own secret scanning with push protection (`gh api` or repo Settings > Code security; tell the user if it needs admin rights).
- Scan the full history once: `gitleaks git .` (or `gitleaks detect` on older versions). If anything real is found, **tell the user immediately**: the secret must be rotated or revoked first, because removing it from history does not make it safe again. Only then offer history rewriting (`git filter-repo`) as an optional extra step.
- GitHub Actions must read secrets only via `${{ secrets.NAME }}`; never echo them or hard-code values in workflow files.

### 5. Log files cannot leak

- Log files and folders are ignored (see section 3) and never committed or uploaded as CI artefacts unless the user asks.
- Check logging code for statements that print secrets, tokens, passwords, connection strings or full request headers. Flag them and suggest redaction or masking.

### 6. pre-commit configured for the stack

Create `.pre-commit-config.yaml`. Always include these general hooks:

- `pre-commit/pre-commit-hooks`: `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-json`, `check-toml`, `check-merge-conflict`, `check-added-large-files`, `detect-private-key`
- `gitleaks/gitleaks`: `gitleaks`

Then add hooks per detected stack:

| Stack                   | Tooling                                                                                                                                                |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Python                  | `astral-sh/ruff-pre-commit` with `ruff-check --fix` and `ruff-format`; config in `pyproject.toml` under `[tool.ruff]`                                  |
| SQL                     | `sqlfluff/sqlfluff` with `sqlfluff-lint` and `sqlfluff-fix`; a `.sqlfluff` file setting the correct `dialect` (and `templater = dbt` for dbt projects) |
| JavaScript / TypeScript | Prettier and ESLint                                                                                                                                    |
| Shell                   | `shellcheck`                                                                                                                                           |
| Dockerfile              | `hadolint`                                                                                                                                             |
| Terraform               | `antonbabenko/pre-commit-terraform` with `terraform_fmt`, `terraform_validate`, `terraform_tflint`                                                     |
| Markdown                | `markdownlint`                                                                                                                                         |
| Other                   | The established formatter and linter for that language                                                                                                 |

Never invent version numbers. Use any `rev`, then run `pre-commit autoupdate` to pin the latest releases. Finish with `pre-commit install` and `pre-commit run --all-files`.

### 7. GitHub Actions workflows

Create `.github/workflows/` with at minimum:

- `ci.yml`: triggers on `push` and `pull_request` to `master`; sets up the detected language runtime; installs dependencies; runs `pre-commit run --all-files`; runs the test suite if one exists.
- `secret-scan.yml` (or a job inside `ci.yml`): runs gitleaks on push and pull request with `fetch-depth: 0` so full history is scanned.

Use least-privilege `permissions:` (default `contents: read`), pin actions to a released major version or commit SHA, and enable dependency caching. Add `.github/dependabot.yml` for the detected package ecosystems plus `github-actions`.

### 8. Commit conventions

- The commit subject (first line) is **only** the version, in the form `vX.Y.Z` (for example `v0.1.0`). Nothing else goes on the subject line.
- Everything else (what changed, why, notes) goes in the commit description (the body), separated from the subject by a blank line.
- The project started at `v0.1.0`. For each new commit, bump from the previous commit's version using semantic versioning: patch (`v0.1.1`) for fixes and small changes, minor (`v0.2.0`) for new features, major (`v1.0.0`) for breaking changes. Keep `version` in `package.json` (or the stack's equivalent) in step with the commit subject.
- Keep a `CHANGELOG.md` in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format. Every version commit adds a `## vX.Y.Z - YYYY-MM-DD` section, newest first, grouped under Added / Changed / Fixed / Removed, in the same commit.
- The project's `/commit` skill (`.claude/skills/commit/SKILL.md`) applies these rules step by step; use it for every commit, and record the convention in `CLAUDE.md` and `CONTRIBUTING.md`.
- Never add an AI assistant (Claude or any other) as a co-author. Do not add `Co-Authored-By` trailers or "Generated with" lines to commits or pull requests.

## Final report

End with a short summary covering: the detected stacks; each checklist item and whether it was already fine, fixed or created; any secrets found and the action the user must take; manual steps remaining (for example enabling push protection or branch protection on `master` in GitHub settings).
