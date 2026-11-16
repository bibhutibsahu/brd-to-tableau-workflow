# Contributing

Contributors work on macOS, Linux and Windows. Commands are given for each where they differ. Every `uv ...`
command works the same everywhere.

## 1. One-time setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh      # or: brew install uv
```

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   # or: winget install astral-sh.uv
```

Clone, install, and **install the git hooks (mandatory)**:

```bash
git clone git@github.com:bibhutibhusan-ada/brd-to-tableau-agent.git
cd brd-to-tableau-agent
uv sync                       # Python 3.12 + runtime and dev dependencies into .venv
uv run pre-commit install     # installs BOTH the pre-commit and pre-push hooks
```

Then create your `.env`:

```bash
cp .env.example .env               # macOS / Linux
```

```powershell
Copy-Item .env.example .env        # Windows (PowerShell)
```

Windows only: set `git config core.autocrlf false`. `.gitattributes` already keeps files at LF line endings.

## 2. pre-commit is mandatory

Do not commit or push without the hooks installed. They run on every `git commit` and again on every `git push`:

- whitespace, end-of-file, line-ending, YAML / JSON / TOML, merge-conflict and large-file checks
- private-key detection and **gitleaks** secret scanning
- **ruff** lint (`--fix`) and **ruff format**
- **uv-lock**, which fails if `uv.lock` is out of date with `pyproject.toml`

If a hook changes files, the commit stops. Review the changes, `git add` them and commit again.

Run every hook by hand:

```bash
uv run pre-commit run --all-files
```

Never bypass the hooks with `--no-verify`. CI (`.github/workflows/ci.yml`) runs the same hooks on every pull
request and push to `main`, so a bypassed commit fails there anyway.

## 3. Day-to-day commands

```bash
uv run streamlit run app.py                                   # run the app
uv run python -m modules.pipeline data/sample_brd.pdf --approve   # CLI pipeline
uv run ruff check --fix .                                     # lint
uv run ruff format .                                          # format
uv add <package>                                              # add a runtime dependency
uv add --dev <package>                                        # add a dev-only dependency
uv lock --upgrade-package <package>                           # bump one dependency
```

Always commit `pyproject.toml` and `uv.lock` together. Do not add a `requirements.txt`.

## 4. Commit messages and versions

The commit subject (first line) is **only** the version: `vX.Y.Z`. Put everything else in the commit body,
after a blank line.

```text
v0.2.1

Fix KPI card rounding for Gross Margin %.

- dashboard_generator: round percentages to 1 dp before formatting
- CHANGELOG: v0.2.1 entry
```

How to choose the version (bump from the latest `vX.Y.Z` in `git log`):

| Change | Bump | Example |
| --- | --- | --- |
| Bug fix, small change, docs, dependency bump | patch | `v0.2.0` → `v0.2.1` |
| New feature, backwards compatible | minor | `v0.2.1` → `v0.3.0` |
| Breaking change | major | `v0.3.0` → `v1.0.0` |

In the **same commit**:

1. Set `version` in `pyproject.toml` to the new version (without the `v`).
2. Run `uv lock` so `uv.lock` picks up the version.
3. Add a `## vX.Y.Z - YYYY-MM-DD` section at the top of `CHANGELOG.md`, grouped under Added / Changed / Fixed /
   Removed.

To write a multi-line message from the terminal:

```bash
git commit -m "v0.2.1" -m "Fix KPI card rounding for Gross Margin %." -m "- detail one
- detail two"
```

Or run `git commit` with no `-m` to write the message in your editor.

Do not add AI co-author trailers (`Co-Authored-By: Claude ...`) or "Generated with" lines to commits or PRs.

Dependabot pull requests use their own commit messages. Squash-merge them with a `vX.Y.Z` subject and a
CHANGELOG entry.

## 5. Pull requests

- Branch from `main`, open a PR into `main`.
- CI must pass: pre-commit, import check, gitleaks full-history scan, 5 MB file-size guard.
- Never commit `.env`, keys, credentials, logs or `outputs/`. They are git-ignored; keep it that way.
- Files over 5 MB are rejected. Use git-lfs for large binaries.
