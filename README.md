# BRD → Tableau AI

A Gemini-powered app that turns a customer's Business Requirements Document into a finalised BRD, an HTML
dashboard mockup, and then reviewed, approved Tableau (or Power BI) dashboards over an ecommerce star schema.

## The 3-step workflow (3 agents)

| Step | Agent | Input | What it does | Output (`outputs/<project>/…`) |
| --- | --- | --- | --- | --- |
| 1 · BRD | **BRD Analyst** (Gemini) | customer BRD (PDF / DOCX / TXT / MD) | Maps the customer BRD onto **our BRD format** (`templates/brd_template.json`), marks every field *provided / inferred / missing*, writes a question and a suggested default for each gap. The analyst fills gaps by hand, pastes the customer's answers (Gemini applies them), or accepts suggestions (marked *assumed*), then finalises. | `step1_brd/brd_final.json`, `.md`, `.docx`, `gap_report.md` |
| 2 · Mockup | **Dashboard Designer** (Gemini + SQL) | `brd_final.json` | Maps the BRD to the star schema, computes every KPI with SQL, plans the dashboards and AI insights, and writes the **dashboard spec**: every KPI's SQL / Tableau / DAX formula, charts, filters, data model, tech stack and BRD traceability. Builds a **single-file HTML dashboard** for the demo. | `step2_mockup/dashboard_spec.json`, `dashboard_spec.md`, `dashboard_mockup.html` |
| 3 · BI platform | **BI Publisher** (no LLM) | approved `dashboard_spec.json` | Builds the approved design in the chosen platform. **Tableau:** packaged workbook. **Power BI:** hand-off pack (DAX measures, model and relationships, page-by-page build guide, CSV data) until the platform is confirmed. | `step3_tableau/…/*.twbx`, or `step3_powerbi/measures.dax`, `model.json`, `build_guide.md` |

**For now, Steps 1 and 2 run in one go**: the app's **▶ Run** button (or `python -m modules.workflow run <brd>`)
takes the customer BRD straight to the HTML dashboard. Gaps are filled with the AI suggestions (marked
*assumed* in the finalised BRD), and `gap_report.md` keeps the original gaps as questions for the customer.
The step-by-step tabs below the Run box are there for reviewing or changing each step.

Each agent reads the previous step's file and writes its own, so any step can be re-run, reviewed, or handed
to someone else. For demos, Steps 1 and 2 are the deliverable (finalised BRD + HTML mockup). Step 3 runs once
the dashboarding platform is decided.

The HTML mockup has dashboard tabs, KPI tiles, charts with tooltips and a table view, AI insights, a
**KPI formulas** tab (SQL / Tableau / DAX) and a **BRD traceability** tab, in light and dark themes. It loads
Apache ECharts from cdnjs. Run `uv run python -m modules.workflow vendor` once to cache the library, and later
mockups embed it so they work offline.

The original one-click flow is still available (Step 2 › "One-click", or `python -m modules.pipeline`):

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
`.venv\Scripts\Activate.ps1` (Windows PowerShell). Then `streamlit run app.py` works directly. In VS Code,
select `.venv` as the Python interpreter and new terminals activate it for you. Started with another
Python's Streamlit (e.g. a global Anaconda install), the app shows how to start it correctly instead of
crashing.

`.streamlit/config.toml` keeps the app on http://localhost:8501, reachable from this computer only, because
the sidebar pre-fills the Gemini key from `.env`.

## Gemini API key

Get a key at https://aistudio.google.com/apikey, then either:

- paste it into **Gemini API key** in the app sidebar and click **Connect**. The app makes one test call to
  check the key and model. The key stays in that browser session's memory and is never saved; or
- put it in `.env` (copy `.env.example`), and the sidebar field is pre-filled. `.env` is git-ignored.

Choose the model in the sidebar, or set `GEMINI_MODEL` in `.env`.

Command line (uses the key from `.env` / environment):

```bash
# one go: customer BRD -> finalised BRD -> HTML dashboard (Agent 1 + Agent 2)
uv run python -m modules.workflow run data/sample_brd.pdf

# 3-step workflow, one step at a time
uv run python -m modules.workflow template                       # blank BRD template (.md + .docx) for customers
uv run python -m modules.workflow step1 data/sample_brd.pdf      # Agent 1: gap analysis -> brd_draft.* + gap_report.md
uv run python -m modules.workflow step1 data/sample_brd.pdf --answers answers.txt --accept-suggestions --finalize
uv run python -m modules.workflow step2 outputs/<project>/step1_brd/brd_final.json
uv run python -m modules.workflow step3 outputs/<project>/step2_mockup/dashboard_spec.json --platform tableau
uv run python -m modules.workflow demo data/sample_brd.pdf       # same as run (kept for compatibility)

# original one-click flow
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
| Step 1 gap analysis | `agents/brd_analyst.py` | maps the customer BRD onto our format, writes questions and suggestions (`prompts/brd_gap_prompt.txt`); applies pasted customer answers | values coerced to each field's type; names, dates and owners not in the BRD stay *missing* (ideas go to `suggestion`); finalising is blocked while required fields are missing unless open items are allowed |
| Step 2 spec + mockup | `agents/dashboard_designer.py`, `html_mockup.py` | – (reuses the stages below) | formulas copied from the KPI catalog, never written by the LLM; LLM text is HTML-escaped in the mockup |
| Step 3 build | `agents/bi_publisher.py` | – | the spec's plan is re-validated against the database before building |
| BRD → text | `brd_parser.py` | – | PDF (pypdf), DOCX incl. tables, TXT/MD |
| Requirements JSON | `requirement_extractor.py` | reads the BRD (`prompts/brd_extraction_prompt.txt`) | JSON shape normalised |
| Schema mapping | `schema_mapper.py` | maps business names → metric / dimension ids | every id checked against the schema; invented ids repaired or listed as unmapped |
| SQL & KPI logic | `sql_generator.py` | – | SQL built only from validated ids; filter values are bound parameters; read-only DB connection |
| Visual plan | `visualization_planner.py` | designs dashboards (`prompts/visualization_prompt.txt`) | `validate_plan`: unknown ids dropped, chart types checked, titles unique |
| Insights | `dashboard_generator.generate_insights` | headline, insights, actions (`prompts/insights_prompt.txt`) | Gemini sees only the computed numbers and is told to use only those |
| Modify | `visualization_planner.revise_plan` | applies plain-English edits | re-validated; any change resets approval |
| Tableau workbook | `twb_builder.py` | – | XML well-formedness and zone/field reference checks before writing |

Each KPI has one definition in `templates/dashboard_config.json`, with a `sql` form for the preview and the
HTML mockup, a `tableau` formula for the workbook, and a `dax` formula for Power BI, so all of them show the
same numbers.

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
app.py                     Streamlit UI: Step 1 BRD → Step 2 mockup → Step 3 BI platform → LLM trace
config.py                  paths, model, limits (.env overrides)
modules/
  agents/                  the three agents: brd_analyst.py, dashboard_designer.py, bi_publisher.py (+ base.py)
  brd_template.py          our BRD format: gap scoring, finalise, Markdown / DOCX rendering, Step 2 hand-off
  html_mockup.py           single-file HTML dashboard (ECharts) for the Step 2 demo
  workflow.py              3-step CLI (template, vendor, step1, step2, step3, demo)
  brd_parser.py            requirement_extractor.py   schema_mapper.py
  sql_generator.py         visualization_planner.py   dashboard_generator.py
  twb_builder.py           Tableau XML writer
  llm_client.py            Gemini JSON client: retries, error messages, token/latency trace
  pipeline.py              step runner + one-click CLI (design stages shared with Step 2)
prompts/                   BRD gap analysis, extraction, visualization and insights prompts
templates/dashboard_config.json   KPI catalog (sql, tableau, dax formulas), chart rules, default filters
templates/brd_template.*   our standard BRD format (.json is the source; .md / .docx to send to customers)
templates/mockup_template.html    HTML mockup page (data is injected by html_mockup.py)
scripts/                   database and sample BRD builders
data/                      ecommerce.db, sample_brd.pdf / .docx
.github/                   CI workflow and Dependabot config
pyproject.toml, uv.lock    dependencies (uv) and ruff config
```

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). In short: run `uv run pre-commit install` once per clone, and make
every commit subject just the version (`vX.Y.Z`), with the details in the commit body and in
[CHANGELOG.md](CHANGELOG.md).
