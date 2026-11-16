# CLAUDE.md

Guidance for Claude Code in this repository.

## Project

BRD → Tableau AI: a Streamlit app (`app.py`) that uses Gemini (`google-genai`) to turn a Business Requirements
Document into reviewed Tableau workbooks over a SQLite ecommerce star schema (`data/ecommerce.db`). It is an app
run from the repo root, not an installable package (`[tool.uv] package = false`).

- `config.py`: every setting and env var (`.env` overrides). Add new env vars here **and** to `.env.example`
  and the README configuration table.
- `modules/pipeline.py`: step runner and CLI. `modules/llm_client.py`: the only place that calls Gemini.
- `modules/sql_generator.py` builds SQL **only** from validated metric / dimension ids, with filter values as
  bound parameters on a read-only connection. Keep it that way: never interpolate LLM output into SQL.
- `templates/dashboard_config.json`: one definition per KPI (`sql` for the preview, `tableau` for the
  workbook). Change both together so the preview and the workbook show the same numbers.
- `prompts/*.txt`: LLM prompts. `scripts/`: data and sample-BRD generators.

## Tooling: uv only

- Use `uv` for everything: `uv sync`, `uv run ...`, `uv add <pkg>`, `uv add --dev <pkg>`. Never use `pip`,
  `python -m venv` or `requirements.txt`. That file was removed on purpose.
- Python version: `.python-version` (3.12). Commit `pyproject.toml` and `uv.lock` together.
- Run things with `uv run`, e.g. `uv run streamlit run app.py`, `uv run python -m modules.pipeline <brd>`.
- Contributors use macOS, Linux and Windows. When writing docs or scripts, give both shell variants where they
  differ (`cp` vs `Copy-Item`, `.venv/bin/` vs `.venv\Scripts\`), or prefer `uv run`, which is the same
  everywhere. Use `pathlib`, not hard-coded `/` separators, and open text files with `encoding="utf-8"`.

## Formatting and linting: ruff

- Ruff is the only linter and formatter. Config is in `pyproject.toml` (line length 120, py312).
- Before finishing any Python change: `uv run ruff check --fix .` and `uv run ruff format .`.

## pre-commit is mandatory

- Hooks must be installed in every clone: `uv run pre-commit install`. That installs both the **pre-commit
  and pre-push** hooks (`default_install_hook_types` in `.pre-commit-config.yaml`).
- Run `uv run pre-commit run --all-files` and make it pass before every commit and before every push.
- Never use `git commit --no-verify` or `git push --no-verify`, and never disable or weaken a hook to get a
  commit through. Fix the cause instead.
- CI (`.github/workflows/ci.yml`) re-runs the same hooks on every PR and push to `main`.

## Commit messages: `vX.Y.Z`

- The commit subject (first line) is **only** the version, e.g. `v0.2.1`. Nothing else on that line.
- All details (what changed, why) go in the commit body after a blank line.
- Bump from the latest `vX.Y.Z` subject in `git log`: patch for fixes, small changes and docs; minor for new
  features; major for breaking changes.
- In the same commit: set `version` in `pyproject.toml` (no `v`), run `uv lock`, and add a
  `## vX.Y.Z - YYYY-MM-DD` section at the top of `CHANGELOG.md` (Added / Changed / Fixed / Removed).
- Do **not** add `Co-Authored-By` trailers for Claude or any AI, and no "Generated with" lines in commits or PRs.
- The `/commit` skill (`.claude/skills/commit/SKILL.md`) does all of this. Use it when asked to commit.
- Only commit or push when the user asks.

## Git and GitHub

- Default branch: `main`. PRs target `main`.
- Never commit `.env`, keys, credentials, logs or `outputs/`. gitleaks runs in pre-commit and in CI.
- Files over 5 MB are blocked (pre-commit `check-added-large-files` and the CI large-file guard).
- Dependabot (`.github/dependabot.yml`) opens weekly PRs for uv and GitHub Actions.

## Tests

There is no test suite yet. If you add one, use pytest (`uv add --dev pytest`), put it in `tests/`, and add a
`uv run pytest` step to `ci.yml`.
