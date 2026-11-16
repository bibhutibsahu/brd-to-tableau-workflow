# BRD → Tableau AI

Turns a Business Requirements Document into reviewed, approved Tableau dashboards over an
ecommerce star schema.

```
Upload BRD (PDF/DOCX) → LLM: extract requirements → structured JSON → map database schema
→ generate SQL & KPI logic → execute SQL → AI visualization planner → dashboard preview
→ user review → approve / modify → generate Tableau workbook (.twbx / .twb)
```

## Quick start

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python scripts/generate_ecommerce_db.py   # data/ecommerce.db (star schema)
.venv/bin/python scripts/make_sample_brd.py         # data/sample_brd.pdf + .docx
cp .env.example .env                                 # add GEMINI_API_KEY
.venv/bin/streamlit run app.py
```

Headless run:

```bash
.venv/bin/python -m modules.pipeline data/sample_brd.pdf --approve
.venv/bin/python -m pytest -q
```

Without `GEMINI_API_KEY`, the app runs in **rule-based mode**. It matches catalog KPIs named in the
BRD and uses the ecommerce dashboard templates. A key enables full BRD extraction, LLM schema mapping,
LLM chart planning and plain-English plan edits.

## Where the AI sits, and where it does not

| Step | Module | AI | Guardrail |
| --- | --- | --- | --- |
| BRD → text | `brd_parser.py` | – | PDF (pypdf), DOCX incl. tables, TXT/MD |
| Requirements JSON | `requirement_extractor.py` | Gemini, `prompts/brd_extraction_prompt.txt` | Shape normalised; keyword fallback |
| Schema mapping | `schema_mapper.py` | Gemini maps business names → ids | Ids checked against the catalog; fuzzy fallback; unmapped items listed, never invented |
| SQL & KPI logic | `sql_generator.py` | **none** | SQL built from validated ids; filter values are bound parameters; read-only connection |
| Visual plan | `visualization_planner.py` | Gemini, `prompts/visualization_prompt.txt` | Rule-based baseline; `validate_plan` drops unknown ids, fixes bad pies, makes titles unique |
| Preview | `dashboard_generator.py` | – | Same SQL as step 4; Altair charts mirror the Tableau chart types |
| Modify | `visualization_planner.revise_plan` | Gemini edits the plan JSON | Re-validated before use; approval resets on any change |
| Tableau workbook | `twb_builder.py` | **none** | XML well-formedness + zone/field reference checks before writing |

Each KPI has one definition in `templates/dashboard_config.json`, with a `sql` form for the preview and a
`tableau` formula for the workbook. The two use the same logic.

## Data model (`data/ecommerce.db`)

`fact_sales` (order-line grain) joins to `dim_date`, `dim_customer`, `dim_product`,
`dim_geography`, `dim_channel`, `dim_promotion`. Joins come from declared foreign keys, or failing
that from fact columns named like a dimension's primary key. To point at another SQLite star schema, set
`DATABASE_PATH`, and edit the `columns`, `sql` and `tableau` fields of the metrics in
`templates/dashboard_config.json`. Metrics whose columns are missing are disabled automatically.

## The generated workbook

`outputs/<title>/` holds `<title>.twbx` (open in Tableau), `<title>.twb` (the XML), `Data/*.csv`
and `approved_plan.json`. Inside it:

- one data source: the fact CSV LEFT JOINed to each dimension CSV on its key
- each metric as a calculated field (AOV, Gross Margin %, Return Rate, …) with ₹ / % formats
- one dashboard per planned dashboard: title, KPI cards, a two-column chart grid, and filter
  dropdowns that apply across every sheet
- top-N filters, sorted bars, line trends, pies and text tables

## Project layout

```
app.py                     Streamlit UI (upload → review → approve → download)
config.py                  paths, model, limits (.env overrides)
modules/
  brd_parser.py            requirement_extractor.py   schema_mapper.py
  sql_generator.py         visualization_planner.py   dashboard_generator.py
  twb_builder.py           Tableau XML writer
  llm_client.py            Gemini JSON wrapper
  pipeline.py              step runner + CLI
prompts/                   extraction and visualization prompts
templates/dashboard_config.json   KPI catalog, chart rules, fallback dashboards
scripts/                   sample database and sample BRD generators
tests/                     end-to-end tests (fake LLM, no key needed)
```
