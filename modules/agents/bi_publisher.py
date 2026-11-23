"""Step 3 - BI Publisher agent.

Builds the approved Step 2 design (dashboard_spec.json) in the BI platform the customer chooses.
Each platform is an adapter in PLATFORMS, so a new one can be added without touching Steps 1 and 2.

  tableau  packaged workbook (.twbx + .twb + Data/*.csv), via the existing twb_builder
  powerbi  hand-off pack: DAX measures, data model and relationships, page-by-page build guide, CSV data

No LLM is used here on purpose: formulas and layout come straight from the approved spec.
"""

from modules.agents.base import Agent, step_dir, write_json, write_text
from modules.dashboard_generator import export_star_schema, generate_tableau_workbook
from modules.schema_mapper import build_semantic_layer, introspect_schema
from modules.visualization_planner import validate_plan

POWERBI_VISUALS = {
    "line": "Line chart",
    "bar": "Clustered column chart",
    "horizontal_bar": "Clustered bar chart",
    "pie": "Donut chart",
    "table": "Table",
}
POWERBI_FORMATS = {"currency": "₹#,##0", "percent": "0.0%", "decimal": "#,##0.00", "number": "#,##0"}


def _tableau(spec, plan, schema, semantic, folder) -> dict:
    export = generate_tableau_workbook(plan, schema, semantic, output_dir=folder)
    return {
        "files": {"twbx": export["twbx_path"], "twb": export["twb_path"], "plan": export["plan_path"]},
        "details": export,
    }


def _measure_name(kpi: dict) -> str:
    return kpi["label"].replace("[", "(").replace("]", ")")


def _powerbi(spec, plan, schema, semantic, folder) -> dict:
    kpis = {k["id"]: k for k in spec["kpis"]}
    dims = {d["id"]: d for d in semantic["dimensions"]}
    fact = schema["fact_table"]

    measures = [f"// DAX measures for {spec['project']['name']} - generated from dashboard_spec.json", ""]
    measures.append(f"// Create these in the '{fact}' table (or a dedicated _Measures table).")
    for k in spec["kpis"]:
        measures += [
            "",
            f"// {k['brd_definition'] or k['business_definition']}",
            f"// Format string: {POWERBI_FORMATS.get(k['format'], '#,##0')}",
            f"{_measure_name(k)} = {k['formulas']['dax'] or 'BLANK()  // TODO: no DAX formula in dashboard_config.json'}",
        ]

    model = {
        "tables": [
            {
                "name": name,
                "role": "fact" if name == fact else "dimension",
                "source": f"Data/{name}.csv",
                "rows": table["row_count"],
                "columns": [{"name": c["name"], "type": c["type"]} for c in table["columns"]],
            }
            for name, table in schema["tables"].items()
            if name == fact or name in {j["dim_table"] for j in schema["joins"]}
        ],
        "relationships": [
            {
                "from": f"{fact}[{j['fact_column']}]",
                "to": f"{j['dim_table']}[{j['dim_column']}]",
                "cardinality": "many-to-one",
                "cross_filter": "single",
            }
            for j in schema["joins"]
        ],
        "measures": [
            {
                "name": _measure_name(k),
                "expression": k["formulas"]["dax"],
                "format_string": POWERBI_FORMATS.get(k["format"], "#,##0"),
            }
            for k in spec["kpis"]
        ],
    }

    guide = [
        f"# Power BI build guide - {spec['project']['name']}",
        "",
        "Built from the approved Step 2 design (`dashboard_spec.json`). Steps:",
        "",
        "1. **Get data → Text/CSV**: load every file in `Data/`.",
        "2. **Model view**: create the relationships in `model.json` (many-to-one, single direction).",
        "3. **Measures**: paste each measure from `measures.dax` and set its format string.",
        "4. **Pages**: one page per dashboard below. KPI tiles are *Card* visuals across the top; charts follow "
        "in a two-column grid, in the order listed.",
        "5. **Slicers**: add the global filters below to every page and sync them (View → Sync slicers).",
        "",
        "## Global slicers",
        "",
    ]
    guide += [
        f"- {dims[f]['label']}: `{dims[f]['table']}[{dims[f]['column']}]`" for f in plan["filters"] if f in dims
    ] or ["- none"]
    for board in spec["dashboards"]:
        guide += ["", f"## Page: {board['name']}", "", board["purpose"] or "", ""]
        guide.append(
            "**Cards:** " + (", ".join(f"[{_measure_name(kpis[m])}]" for m in board["kpis"] if m in kpis) or "-")
        )
        guide += [
            "",
            "| # | Visual | Power BI visual | Axis / Category | Values | Sort / Top N | BRD ref |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for i, c in enumerate(board["charts"], start=1):
            field = c["dimension_field"]
            top = f"Top N filter: {c['top_n']} by [{c['metric_label']}]" if c["top_n"] else ""
            sort = {"desc": "descending by value", "asc": "ascending by value", "none": "by axis"}.get(
                c["sort"], c["sort"]
            )
            guide.append(
                f"| {i} | {c['title']} | {POWERBI_VISUALS.get(c['chart'], c['chart'])} | `{field['table']}[{field['column']}]` | "
                f"[{c['metric_label']}] | {sort}{'; ' + top if top else ''} | {', '.join(c['brd_refs']) or '-'} |"
            )
    guide += [
        "",
        "## Theme",
        "",
        "Series colours (light): "
        + ", ".join(spec["design_tokens"]["series_light"])
        + ". Single-series charts use the first.",
    ]

    csvs = export_star_schema(schema, folder / "Data")
    files = {
        "measures": write_text(folder / "measures.dax", "\n".join(measures) + "\n"),
        "model": write_json(folder / "model.json", model),
        "guide": write_text(folder / "build_guide.md", "\n".join(guide) + "\n"),
    }
    return {
        "files": {k: str(v) for k, v in files.items()},
        "details": {
            "measures": len(model["measures"]),
            "pages": len(spec["dashboards"]),
            "data_files": [str(p) for p in csvs],
        },
    }


PLATFORMS = {
    "tableau": {
        "label": "Tableau",
        "status": "adapter ready",
        "output": ".twbx packaged workbook (+ .twb XML, Data/*.csv)",
        "build": _tableau,
    },
    "powerbi": {
        "label": "Power BI",
        "status": "hand-off pack (automated .pbix / PBIP build planned once the platform is confirmed)",
        "output": "measures.dax, model.json, build_guide.md, Data/*.csv",
        "build": _powerbi,
    },
}


class BIPublisherAgent(Agent):
    step = 3
    name = "Agent 3 · BI Publisher"
    role = "Builds the approved mockup design in the chosen BI platform (Tableau or Power BI)."
    inputs = "dashboard_spec.json (Step 2)"
    outputs = "Tableau .twbx, or the Power BI hand-off pack"
    uses_llm = False

    def publish(self, spec: dict, platform: str, root=None) -> dict:
        if platform not in PLATFORMS:
            raise ValueError(f"Unknown platform '{platform}'. Choose one of: {', '.join(PLATFORMS)}")
        schema = introspect_schema()
        semantic = build_semantic_layer(schema)
        plan = validate_plan(spec["plan"], semantic)  # the spec may come from another machine: re-check ids
        folder = step_dir(spec["project"]["brd_project_name"] or spec["project"]["name"], 3, platform, root=root)
        result = PLATFORMS[platform]["build"](spec, plan, schema, semantic, folder)
        return {"platform": platform, "label": PLATFORMS[platform]["label"], "folder": str(folder), **result}
