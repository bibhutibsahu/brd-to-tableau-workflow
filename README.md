# BRD → Tableau AI

A Gemini-powered app that turns a Business Requirements Document into reviewed, approved Tableau
dashboards over an ecommerce star schema.

```
Upload BRD (PDF/DOCX) → Gemini extracts requirements → structured JSON → Gemini maps them to the schema
→ SQL & KPI logic → execute SQL → Gemini plans the visuals → dashboard preview + AI insights
→ user review → approve / modify (by hand or in plain English) → generate Tableau workbook (.twbx / .twb)
```

## Setup

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python scripts/generate_ecommerce_db.py   # builds data/ecommerce.db (star schema)
.venv/bin/python scripts/make_sample_brd.py         # builds data/sample_brd.pdf + .docx
.venv/bin/streamlit run app.py
```

## Gemini API key

Get a key at https://aistudio.google.com/apikey, then either:

- paste it into **Gemini API key** in the app sidebar and click **Connect**. The app makes one test call to
  check the key and model. The key stays in that browser session's memory and is never saved; or
- put it in `.env` (copy `.env.example`), and the sidebar field is pre-filled. `.env` is git-ignored.

Choose the model in the sidebar, or set `GEMINI_MODEL` in `.env`.

Command line (uses the key from `.env` / environment):

```bash
.venv/bin/python -m modules.pipeline data/sample_brd.pdf --approve --model gemini-3.5-flash
```

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
```
