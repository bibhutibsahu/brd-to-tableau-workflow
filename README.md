# BRD → Tableau AI

A Gemini-powered app that turns a Business Requirements Document into reviewed, approved Tableau
dashboards over an ecommerce star schema.

```
Upload BRD (PDF/DOCX) → Gemini extracts requirements → structured JSON → Gemini maps them to the schema
→ SQL & KPI logic → execute SQL → Gemini plans the visuals → dashboard preview + AI insights
→ user review → approve / modify (by hand or in plain English) → generate Tableau workbook (.twbx / .twb)
```

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (manages Python 3.12, the virtual environment and dependencies)
- Git
- A Gemini API key

Install uv:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh      # or: brew install uv
```

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   # or: winget install astral-sh.uv
```

## Setup

The `uv` commands are the same on macOS, Linux and Windows. `uv run` uses the project's `.venv`, so you do
not need to activate it.

```bash
uv sync                                          # installs Python 3.12 (from .python-version) + all dependencies
uv run pre-commit install                        # mandatory: installs the pre-commit and pre-push hooks
uv run python scripts/generate_ecommerce_db.py   # builds data/ecommerce.db (star schema)
uv run python scripts/make_sample_brd.py         # builds data/sample_brd.pdf + .docx
uv run streamlit run app.py
```

Copy the environment template:

```bash
cp .env.example .env               # macOS / Linux
```

```powershell
Copy-Item .env.example .env        # Windows (PowerShell)
```

If you prefer to activate the environment yourself: `source .venv/bin/activate` (macOS / Linux) or
`.venv\Scripts\Activate.ps1` (Windows PowerShell).

## Gemini API key

Get a key at https://aistudio.google.com/apikey, then either:

- paste it into **Gemini API key** in the app sidebar and click **Connect**. The app makes one test call to
  check the key and model. The key stays in that browser session's memory and is never saved; or
- put it in `.env` (copy `.env.example`), and the sidebar field is pre-filled. `.env` is git-ignored.

Choose the model in the sidebar, or set `GEMINI_MODEL` in `.env`.

Command line (uses the key from `.env` / environment):

```bash
uv run python -m modules.pipeline data/sample_brd.pdf --approve --model gemini-3.5-flash
```

## Configuration

All settings are read in `config.py` from the environment or `.env` (see `.env.example`). Never commit `.env`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | – | Gemini API key. Optional if entered in the sidebar. |
| `GOOGLE_API_KEY` | – | Fallback name for the Gemini key. |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Default model. |
| `LLM_TEMPERATURE` | `0.1` | Sampling temperature for every LLM call. |
| `DATABASE_PATH` | `data/ecommerce.db` | SQLite star schema the BRD is mapped onto. |
| `MAX_BRD_CHARS` | `60000` | BRD text beyond this is cut before it is sent to the LLM. |
| `PREVIEW_ROW_LIMIT` | `500` | Rows returned per preview query. |

## Lint and format

[Ruff](https://docs.astral.sh/ruff/) is the linter and formatter (config in `pyproject.toml`). The pre-commit
hooks run it automatically. To run it by hand:

```bash
uv run ruff check --fix .
uv run ruff format .
uv run pre-commit run --all-files    # everything CI runs
```

There is no automated test suite yet. CI runs the pre-commit hooks, an import check, a gitleaks scan of the
full history and a 5 MB file-size guard (`.github/workflows/ci.yml`).

## What Gemini does, and what code guarantees

| Step | Module | Gemini | Guardrail |
| --- | --- | --- | --- |
| BRD → text | `brd_parser.py` | – | PDF (pypdf), DOCX incl. tables, TXT/MD |
| Requirements JSON | `requirement_extractor.py` | reads the BRD (`prompts/brd_extraction_prompt.txt`) | JSON shape normalised |
| Schema mapping | `schema_mapper.py` | maps business names → metric / dimension ids | every id checked against the schema; invented ids repaired or listed as unmapped |
| SQL & KPI logic | `sql_generator.py` | – | SQL built only from validated ids; filter values are bound parameters; read-only DB connection |
| Visual plan | `visualization_planner.py` | designs dashboards (`prompts/visualization_prompt.txt`) | `validate_plan`: unknown ids dropped, chart types checked, titles unique |
| Insights | `dashboard_generator.generate_insights` | headline, insights, actions (`prompts/insights_prompt.txt`) | Gemini sees only the computed numbers and is told to use only those |
| Modify | `visualization_planner.revise_plan` | applies plain-English edits | re-validated; any change resets approval |
| Tableau workbook | `twb_builder.py` | – | XML well-formedness and zone/field reference checks before writing |

Each KPI has one definition in `templates/dashboard_config.json`, with a `sql` form for the preview and a
`tableau` formula for the workbook, so both show the same numbers.

The **LLM trace** tab lists every Gemini call: step, model, latency, tokens, prompt and response.

## Data model (`data/ecommerce.db`)

`fact_sales` (order-line grain) joins to `dim_date`, `dim_customer`, `dim_product`, `dim_geography`,
`dim_channel` and `dim_promotion`. Joins come from declared foreign keys, or failing that from fact columns
named like a dimension's primary key.

To use your own SQLite star schema, set `DATABASE_PATH` in `.env`, and edit the metrics in
`templates/dashboard_config.json` (`columns`, `sql`, `tableau`). Metrics whose columns are missing are
disabled automatically.

## The generated workbook

`outputs/<title>/` holds `<title>.twbx` (open in Tableau), `<title>.twb` (the XML), `Data/*.csv` and
`approved_plan.json`. Inside it:

- one data source: the fact CSV LEFT JOINed to each dimension CSV on its key
- each metric as a calculated field (AOV, Gross Margin %, Return Rate, …) with ₹ / % formats
- one dashboard per planned dashboard: title, KPI cards, a two-column chart grid, and filter dropdowns
  that apply to every sheet
- top-N filters, sorted bars, line trends, pies and text tables

## Project layout

```
app.py                     Streamlit UI (connect → upload → review → approve → download)
config.py                  paths, model, limits (.env overrides)
modules/
  brd_parser.py            requirement_extractor.py   schema_mapper.py
  sql_generator.py         visualization_planner.py   dashboard_generator.py
  twb_builder.py           Tableau XML writer
  llm_client.py            Gemini JSON client: retries, error messages, token/latency trace
  pipeline.py              step runner + CLI
prompts/                   extraction, visualization and insights prompts
templates/dashboard_config.json   KPI catalog, chart rules, default filters
scripts/                   database and sample BRD builders
data/                      ecommerce.db, sample_brd.pdf / .docx
.github/                   CI workflow and Dependabot config
pyproject.toml, uv.lock    dependencies (uv) and ruff config
```

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). In short: run `uv run pre-commit install` once per clone, and make
every commit subject just the version (`vX.Y.Z`), with the details in the commit body and in
[CHANGELOG.md](CHANGELOG.md).
