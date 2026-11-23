# CLAUDE.md

Guidance for Claude Code in this repository.

## Project

BRD → Tableau AI: a Streamlit app (`app.py`) that uses Gemini (`google-genai`) to turn a Business Requirements
Document into reviewed Tableau workbooks over a SQLite ecommerce star schema (`data/ecommerce.db`). It is an app
run from the repo root, not an installable package (`[tool.uv] package = false`).

- The app runs a **3-step, 3-agent workflow** (`modules/agents/`, CLI `modules/workflow.py`). Each agent reads
  the previous step's file and writes its own under `outputs/<project>/step1_brd | step2_mockup | step3_<platform>`:
  1. `BRDAnalystAgent`: customer BRD → our BRD format (`templates/brd_template.json`, logic in
     `modules/brd_template.py`) with gaps flagged → finalised `brd_final.json`.
  2. `DashboardDesignerAgent`: `brd_final.json` → `dashboard_spec.json` / `.md` (KPI formulas, charts, tech stack,
     traceability) + `dashboard_mockup.html` (`modules/html_mockup.py`, `templates/mockup_template.html`). It reuses
     `pipeline.design_from_requirements`.
  3. `BIPublisherAgent`: `dashboard_spec.json` → Tableau (`twb_builder`) or the Power BI hand-off pack. Platforms are
     adapters in `PLATFORMS`; add a new platform there. No LLM in Step 3.
  The spec's `plan` key is the build contract for Step 3. Keep the spec backward compatible, or bump `SPEC_VERSION`.
- Current main path: Steps 1 + 2 in one go via `workflow.run_brd_to_html` (app "▶ Run" box, CLI
  `python -m modules.workflow run <brd>`). The separate step tabs stay for later review; keep both working.
- The original one-click flow (`pipeline.run_until_preview`, `python -m modules.pipeline`) must keep working.
- `llm_client` retries dropped connections / 5xx (`TRANSIENT_RETRY_WAITS`); bad keys and quota fail at once.
- `config.py`: every setting and env var (`.env` overrides). Add new env vars here **and** to `.env.example`
  and the README configuration table.
- `modules/pipeline.py`: step runner and CLI. `modules/llm_client.py`: the only place that calls Gemini.
- `modules/sql_generator.py` builds SQL **only** from validated metric / dimension ids, with filter values as
  bound parameters on a read-only connection. Keep it that way: never interpolate LLM output into SQL.
- `templates/dashboard_config.json`: one definition per KPI (`sql` for the preview and HTML mockup, `tableau` for
  the workbook, `dax` for Power BI). Change all three together so every output shows the same numbers.
- Changing `templates/brd_template.json`? Regenerate the shareable copies: `uv run python -m modules.workflow template`.
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
