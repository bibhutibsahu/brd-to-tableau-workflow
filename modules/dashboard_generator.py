"""Dashboard preview (data + Altair charts) and the final Tableau workbook export."""

import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

import config
from modules import twb_builder
from modules.schema_mapper import connect, load_dashboard_config
from modules.sql_generator import SQLGenerator, execute


# ------------------------------------------------------------------ preview

def build_preview(plan: dict, schema: dict, semantic: dict, filters: dict | None = None) -> list:
    """Run every KPI and chart query in the plan. Returns one entry per dashboard."""
    generator = SQLGenerator(schema, semantic)
    metrics = {m["id"]: m for m in semantic["metrics"]}
    preview = []
    for board in plan["dashboards"]:
        kpis = []
        if board["kpis"]:
            sql, params = generator.kpi_query(board["kpis"], filters)
            result = execute(sql, params)
            row = result["data"].iloc[0].to_dict() if result["rows"] else {}
            kpis = [{"metric": m, "label": metrics[m]["label"], "value": row.get(m),
                     "display": format_value(row.get(m), metrics[m]["format"]), "sql": sql, "error": result["error"]}
                    for m in board["kpis"]]
        charts = []
        for chart in board["charts"]:
            sql, params = generator.chart_query(chart["metric"], chart["dimension"], filters, chart["sort"], chart["top_n"])
            charts.append({**chart, "sql": sql, **execute(sql, params)})
        preview.append({"name": board["name"], "purpose": board.get("purpose", ""), "kpis": kpis, "charts": charts})
    return preview


def format_value(value, fmt: str) -> str:
    if value is None or value != value:  # None or NaN
        return "–"
    currency = load_dashboard_config().get("currency_symbol", "₹")
    if fmt == "percent":
        return f"{value * 100:.1f}%"
    if fmt == "decimal":
        return f"{value:,.2f}"
    if fmt == "currency":
        for limit, suffix in ((1e7, " Cr"), (1e5, " L")):
            if abs(value) >= limit:
                return f"{currency}{value / limit:,.2f}{suffix}"
        return f"{currency}{value:,.0f}"
    return f"{value:,.0f}"


def altair_chart(chart: dict, semantic: dict):
    """Altair spec matching the Tableau chart type, for the Streamlit preview."""
    import altair as alt

    data = chart["data"]
    dim = next(d for d in semantic["dimensions"] if d["id"] == chart["dimension"])
    metric = next(m for m in semantic["metrics"] if m["id"] == chart["metric"])
    x_field, y_field = dim["column"], chart["metric"]
    axis_format = {"percent": ".1%", "decimal": ",.2f"}.get(metric["format"], ",.0f")
    measure = alt.Y(y_field, title=metric["label"], axis=alt.Axis(format=axis_format))
    tooltip = [alt.Tooltip(x_field, title=dim["label"]), alt.Tooltip(y_field, title=metric["label"], format=axis_format)]
    base = alt.Chart(data).properties(height=280)

    if chart["chart"] == "line":
        return base.mark_line(point=True).encode(x=alt.X(x_field, title=dim["label"], sort=None), y=measure, tooltip=tooltip)
    if chart["chart"] == "pie":
        return base.mark_arc(innerRadius=50).encode(theta=alt.Theta(y_field, type="quantitative"),
                                                   color=alt.Color(x_field, title=dim["label"]), tooltip=tooltip)
    if chart["chart"] == "horizontal_bar":
        return base.mark_bar().encode(y=alt.Y(x_field, title=None, sort="-x" if chart["sort"] != "asc" else "x"),
                                      x=alt.X(y_field, title=metric["label"], axis=alt.Axis(format=axis_format)),
                                      tooltip=tooltip)
    if chart["chart"] == "table":
        return None  # rendered as a dataframe by the app
    sort = None if chart["sort"] == "none" else ("-y" if chart["sort"] == "desc" else "y")
    return base.mark_bar().encode(x=alt.X(x_field, title=dim["label"], sort=sort), y=measure, tooltip=tooltip)


def filter_values(dimension_id: str, semantic: dict) -> list:
    """Distinct values of a dimension, for preview filter widgets."""
    dim = next(d for d in semantic["dimensions"] if d["id"] == dimension_id)
    with connect() as conn:
        rows = conn.execute(f'SELECT DISTINCT "{dim["column"]}" FROM "{dim["table"]}" '
                            f'WHERE "{dim["column"]}" IS NOT NULL ORDER BY 1').fetchall()
    return [row[0] for row in rows]


def star_schema_dot(schema: dict) -> str:
    """Graphviz DOT for the star schema diagram in the app."""
    fact = schema["fact_table"]
    lines = ["digraph G {", "rankdir=LR; bgcolor=transparent;",
             "node [shape=box, style='rounded,filled', fontname=Helvetica, fontsize=11];",
             f'"{fact}" [fillcolor="#1f3a5f", fontcolor=white, label="{fact}\\n{schema["tables"][fact]["row_count"]:,} rows"];']
    for join in schema["joins"]:
        table = schema["tables"][join["dim_table"]]
        lines.append(f'"{table["name"]}" [fillcolor="#dbe7f5", label="{table["name"]}\\n{table["row_count"]:,} rows"];')
        lines.append(f'"{fact}" -> "{table["name"]}" [label="{join["fact_column"]}", fontsize=9, arrowhead=none];')
    lines.append("}")
    return "\n".join(lines).replace("'", '"')


# ------------------------------------------------------------------ Tableau export

def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_") or "workbook"


def export_star_schema(schema: dict, data_dir: Path) -> list:
    """Write the fact and joined dimension tables to CSV for the workbook's Data folder."""
    import pandas as pd

    data_dir.mkdir(parents=True, exist_ok=True)
    tables = [schema["fact_table"]] + [j["dim_table"] for j in schema["joins"]]
    paths = []
    with connect(schema["database"]) as conn:
        for table in tables:
            path = data_dir / f"{table}.csv"
            pd.read_sql_query(f'SELECT * FROM "{table}"', conn).to_csv(path, index=False)
            paths.append(path)
    return paths


def generate_tableau_workbook(plan: dict, schema: dict, semantic: dict, output_dir: Path | None = None) -> dict:
    """Write outputs/<name>/<name>.twb + Data/*.csv, a packaged .twbx and the approved plan JSON."""
    currency = load_dashboard_config().get("currency_symbol", "₹")
    twb, index = twb_builder.build_twb(plan, schema, semantic, currency)
    problems = twb_builder.validate_twb(twb)
    if problems:
        raise ValueError("Generated workbook failed validation:\n" + "\n".join(problems))

    name = slug(plan["title"])
    folder = Path(output_dir or config.OUTPUT_DIR) / name
    folder.mkdir(parents=True, exist_ok=True)
    twb_path = folder / f"{name}.twb"
    twb_path.write_text(twb, encoding="utf-8")
    csv_paths = export_star_schema(schema, folder / "Data")

    twbx_path = folder / f"{name}.twbx"
    with zipfile.ZipFile(twbx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(twb_path.name, twb)
        for path in csv_paths:
            archive.write(path, f"Data/{path.name}")

    plan_path = folder / "approved_plan.json"
    plan_path.write_text(json.dumps({**plan, "approved_at": datetime.now().isoformat(timespec="seconds")}, indent=2),
                         encoding="utf-8")
    return {"twb_path": str(twb_path), "twbx_path": str(twbx_path), "plan_path": str(plan_path),
            "data_files": [str(p) for p in csv_paths], **index}
