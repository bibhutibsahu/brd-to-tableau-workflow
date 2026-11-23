# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Each version matches one commit whose subject is exactly `vX.Y.Z`.

## v0.3.0 - 2026-11-23

### Added

- 3-step, 3-agent workflow (`modules/agents/`). Each agent reads the previous step's file and writes its own
  under `outputs/<project>/`:
  - Agent 1 · BRD Analyst: maps a customer BRD onto our standard BRD format, marks each field provided /
    inferred / missing with a question and a suggested default, applies pasted customer answers, and finalises
    the BRD (`.json`, `.md`, `.docx`) plus a gap report for the customer.
  - Agent 2 · Dashboard Designer: turns the finalised BRD into a dashboard spec (`dashboard_spec.json` / `.md`)
    with every KPI's SQL, Tableau and DAX formula, charts, filters, data model, tech stack and BRD
    traceability, and builds a single-file HTML dashboard mockup (ECharts, light / dark, table view,
    formulas and traceability tabs).
  - Agent 3 · BI Publisher: builds the approved spec in Tableau (packaged workbook) or as a Power BI hand-off
    pack (DAX measures, data model, page-by-page build guide). Platforms are pluggable adapters.
- One-go run of Steps 1 + 2: the app's **▶ Run** box and `python -m modules.workflow run <brd>` take a customer
  BRD straight to the HTML dashboard, filling gaps with AI suggestions marked *assumed*.
- Standard BRD template (`templates/brd_template.json`, with `.md` / `.docx` copies to send to customers).
- `python -m modules.workflow` CLI: `run`, `template`, `vendor`, `step1`, `step2`, `step3`, `demo`.
- Offline mockups: `python -m modules.workflow vendor` caches ECharts so new mockups embed it.
- Power BI DAX formula for every KPI in `templates/dashboard_config.json`.
- `.streamlit/config.toml` keeps the app on localhost, because the sidebar pre-fills the Gemini key.

### Changed

- The app is organised as the one-go Run box followed by Step 1 / Step 2 / Step 3 / LLM trace tabs. All
  earlier views (requirements, schema mapping, SQL & KPI logic, preview & review, Tableau export) remain.
- The pipeline's design stages are reusable (`pipeline.design_from_requirements`); `run_until_preview` and
  `python -m modules.pipeline` behave as before.
- BRD requirement ids (e.g. FR-1.1) are kept on visuals so charts trace back to the BRD.
- Gemini calls retry dropped connections and 5xx errors with backoff; bad keys and quota errors still fail
  immediately.
- Started with an older Streamlit from another Python, the app explains how to start it correctly instead
  of crashing.
- The `repo-baseline` Claude Code skill now expects `main` as the default branch (it said `master`), matching
  this repo, CI and `CLAUDE.md`.

## v0.2.0 - 2026-11-16

### Added

- uv project setup: `pyproject.toml`, `uv.lock`, `.python-version` (Python 3.12) and a `dev` dependency group
  with ruff and pre-commit.
- Ruff lint and format config in `pyproject.toml`.
- `.pre-commit-config.yaml` with general file checks, ruff, `uv-lock` and gitleaks, installed for both the
  pre-commit and pre-push stages.
- GitHub Actions `ci.yml`: pre-commit on all files, import check, gitleaks full-history scan, 5 MB large-file guard.
- `.github/dependabot.yml` for uv and GitHub Actions (weekly).
- `.gitattributes` to keep LF line endings across Windows and macOS / Linux.
- `CONTRIBUTING.md`, `CLAUDE.md`, this changelog, and a `/commit` Claude Code skill.

### Changed

- Code reformatted with ruff, plus small lint fixes (explicit `zip(strict=True)`, exception chaining).
- README setup and run commands now use `uv`, with separate macOS / Linux and Windows commands where they differ.
  Added a configuration table covering every environment variable.
- `.env.example` lists every variable `config.py` reads.
- `.gitignore` extended to cover secrets, keys, logs and OS / editor files.

### Removed

- `requirements.txt` (replaced by `pyproject.toml` + `uv.lock`).

## v0.1.0 - 2026-11-16

### Added

- Streamlit app that turns a BRD (PDF / DOCX / TXT / MD) into Tableau dashboards over an ecommerce star schema.
- Gemini steps: requirement extraction, schema mapping, visualization planning, AI insights and plain-English
  plan revisions, with an LLM trace tab.
- SQL and KPI generation from validated ids, a dashboard preview, and a Tableau workbook builder (`.twb` / `.twbx`).
- Sample ecommerce SQLite database and sample BRD generators.
