# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Each version matches one commit whose subject is exactly `vX.Y.Z`.

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
