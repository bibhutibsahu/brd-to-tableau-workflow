"""Step 2 - Dashboard Designer agent.

Reads the finalised BRD, maps it to the star schema, computes every KPI with SQL, lets Gemini design
the dashboards and write insights, and produces:

  dashboard_spec.json   the platform-neutral design: KPIs with SQL / Tableau / DAX formulas, charts,
                        filters, data model, tech stack and BRD traceability. Step 3 builds from this.
  dashboard_spec.md     the same spec for people to review.
  dashboard_mockup.html a single-file interactive HTML dashboard for the customer demo.
"""

from datetime import datetime
from pathlib import Path

from modules import brd_template
from modules.agents.base import Agent, step_dir, write_json, write_text
from modules.dashboard_generator import build_preview
from modules.html_mockup import ECHARTS_LOCAL, ECHARTS_URL, ECHARTS_VERSION, render_mockup
from modules.pipeline import design_from_requirements
from modules.schema_mapper import load_dashboard_config

SPEC_VERSION = "1.0"
CHART_DESCRIPTIONS = {
    "line": "Line chart (trend over time)",
    "bar": "Vertical bar chart (compare a few categories)",
    "horizontal_bar": "Sorted horizontal bar chart (ranking)",
    "pie": "Donut chart (share of total, few parts)",
    "table": "Table",
}


class DashboardDesignerAgent(Agent):
    step = 2
    name = "Agent 2 · Dashboard Designer"
    role = "Designs KPIs and charts from the finalised BRD and builds the HTML dashboard mockup."
    inputs = "brd_final.json (Step 1)"
    outputs = "dashboard_spec.json, dashboard_spec.md, dashboard_mockup.html"

    # ------------------------------------------------------------ design

    def design(self, brd_doc: dict, log=print) -> dict:
        """Finalised BRD -> design state (requirements, mapping, SQL, plan, preview, insights)."""
        llm = self.require_llm()
        requirements = brd_template.to_requirements(brd_doc)
        markdown = brd_template.to_markdown(brd_doc)
        brd = {
            "text": markdown,
            "source": f"Finalised BRD ({brd_doc.get('source') or 'Step 1'})",
            "pages": None,
            "char_count": len(markdown),
            "truncated": False,
        }
        state = design_from_requirements(requirements, llm, log, brd=brd)
        state["brd_document"] = brd_doc
        return state

    @staticmethod
    def refresh_preview(state: dict, filters: dict | None = None) -> dict:
        state["preview"] = build_preview(state["plan"], state["schema"], state["semantic"], filters)
        return state

    # ------------------------------------------------------------ spec

    def build_spec(self, state: dict, filters: dict | None = None) -> dict:
        from modules.agents.bi_publisher import PLATFORMS

        settings = load_dashboard_config()
        semantic, plan, mapped, schema = state["semantic"], state["plan"], state["mapped"], state["schema"]
        metrics = {m["id"]: m for m in semantic["metrics"]}
        dims = {d["id"]: d for d in semantic["dimensions"]}
        req = state["requirements"]
        sql_by_chart = {c["id"]: c["sql"] for board in state.get("preview", []) for c in board["charts"]}
        kpi_sql = {
            board["name"]: (board["kpis"][0]["sql"] if board["kpis"] else "") for board in state.get("preview", [])
        }

        # BRD wording for each metric, from the mapped KPI requirements
        brd_names, brd_defs = {}, {}
        for board in mapped["dashboards"]:
            for kpi in board["kpis"]:
                if kpi["metric_id"]:
                    brd_names.setdefault(kpi["metric_id"], kpi["name"])
                    if kpi.get("definition"):
                        brd_defs.setdefault(kpi["metric_id"], kpi["definition"])

        # BRD requirement ids for each (metric, dimension) pair
        refs = {}
        for board in mapped["dashboards"]:
            for visual in board["visuals"]:
                if visual["metric_id"] and visual["dimension_id"]:
                    refs.setdefault((visual["metric_id"], visual["dimension_id"]), []).append(
                        visual.get("ref") or visual["title"]
                    )

        used = list(
            dict.fromkeys(
                [m for b in plan["dashboards"] for m in b["kpis"]]
                + [c["metric"] for b in plan["dashboards"] for c in b["charts"]]
            )
        )
        kpis = [
            {
                "id": m,
                "label": metrics[m]["label"],
                "brd_name": brd_names.get(m, ""),
                "brd_definition": brd_defs.get(m, ""),
                "business_definition": metrics[m]["description"],
                "format": metrics[m]["format"],
                "formulas": {
                    "sql": metrics[m]["sql"],
                    "tableau": metrics[m]["tableau"],
                    "dax": metrics[m].get("dax", ""),
                },
                "source_columns": metrics[m]["columns"],
            }
            for m in used
        ]

        dashboards = []
        for board in plan["dashboards"]:
            charts = []
            for chart in board["charts"]:
                dim = dims[chart["dimension"]]
                charts.append(
                    {
                        **chart,
                        "chart_description": CHART_DESCRIPTIONS.get(chart["chart"], chart["chart"]),
                        "metric_label": metrics[chart["metric"]]["label"],
                        "dimension_label": dim["label"],
                        "dimension_field": {"table": dim["table"], "column": dim["column"]},
                        "brd_refs": refs.get((chart["metric"], chart["dimension"]), []),
                        "sql": sql_by_chart.get(chart["id"], ""),
                    }
                )
            dashboards.append(
                {
                    "name": board["name"],
                    "purpose": board["purpose"],
                    "kpis": board["kpis"],
                    "kpi_sql": kpi_sql.get(board["name"], ""),
                    "layout": {"kpi_row": "top, one tile per KPI", "charts": "two-column grid, in list order"},
                    "charts": charts,
                }
            )

        return {
            "spec_version": SPEC_VERSION,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "generated_by": f"{self.name} ({state['mode']})",
            "project": {
                "name": plan["title"] or req["project_name"],
                "brd_project_name": req["project_name"],
                "objective": req["business_objective"],
                "domain": req["domain"],
                "stakeholders": req["stakeholders"],
                "time_grain": req["time_grain"],
                "source_brd": (state.get("brd") or {}).get("source", ""),
                "brd_status": (state.get("brd_document") or {}).get("status", "not from Step 1"),
            },
            "tech_stack": self.tech_stack(state, PLATFORMS),
            "data_model": {
                "database": schema["database"],
                "fact_table": schema["fact_table"],
                "joins": schema["joins"],
                "tables": {name: t["row_count"] for name, t in schema["tables"].items()},
            },
            "formatting": {
                "currency_symbol": settings.get("currency_symbol", "₹"),
                "number_style": "Indian (lakh / crore)",
                "formats": {"currency": "₹ with L / Cr", "percent": "0.0%", "decimal": "0.00", "number": "#,##0"},
            },
            "design_tokens": {
                "chart_library": f"Apache ECharts {ECHARTS_VERSION}",
                "series_light": [
                    "#2a78d6",
                    "#eb6834",
                    "#1baf7a",
                    "#eda100",
                    "#e87ba4",
                    "#008300",
                    "#6250d6",
                    "#e34948",
                ],
                "series_dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#0ca30c", "#9085e9", "#e66767"],
                "surface_light": "#fcfcfb",
                "surface_dark": "#1a1a19",
                "rules": "single-series charts use series 1; categorical colours in fixed order; max 8 then 'Other'",
            },
            "filters": [
                {"id": f, "label": dims[f]["label"], "distinct_values": dims[f]["distinct_count"]}
                for f in plan["filters"]
            ],
            "filters_applied": {
                dims[k]["label"]: [str(v) for v in vals] for k, vals in (filters or {}).items() if k in dims
            },
            "kpis": kpis,
            "dashboards": dashboards,
            "traceability": self.traceability(mapped, plan),
            "unmapped": mapped["unmapped"],
            "assumptions": req["assumptions"],
            "open_questions": req["open_questions"],
            "warnings": plan.get("warnings", []),
            "plan": plan,  # the validated plan: Step 3's build contract
        }

    @staticmethod
    def tech_stack(state: dict, platforms: dict) -> dict:

        return {
            "mockup": {
                "output": "dashboard_mockup.html (single file, data embedded)",
                "markup": "HTML5 + CSS custom properties (light / dark theme)",
                "charting": f"Apache ECharts {ECHARTS_VERSION}",
                "charting_source": "inlined (offline)" if ECHARTS_LOCAL.exists() else ECHARTS_URL,
                "interaction": "dashboard tabs, tooltips, chart / table toggle, KPI formula and traceability tabs",
            },
            "data": {
                "engine": "SQLite",
                "database": Path(state["schema"]["database"]).name,
                "model": "star schema",
                "fact_table": state["schema"]["fact_table"],
                "dimension_tables": [j["dim_table"] for j in state["schema"]["joins"]],
                "query_safety": "SQL built from validated metric / dimension ids only; read-only connection",
            },
            "semantic_layer": "templates/dashboard_config.json (one definition per KPI: sql, tableau, dax)",
            "ai": {"provider": "Google Gemini", "model": state["mode"].removeprefix("llm:")},
            "app": "Python 3.12, Streamlit, pandas, Altair (in-app preview)",
            "target_platforms": {
                key: {"label": p["label"], "status": p["status"], "output": p["output"]} for key, p in platforms.items()
            },
        }

    @staticmethod
    def traceability(mapped: dict, plan: dict) -> list:
        charted = {}
        for board in plan["dashboards"]:
            for chart in board["charts"]:
                charted.setdefault((chart["metric"], chart["dimension"]), []).append(
                    f"{board['name']} › {chart['title']}"
                )
        kpi_cards = {}
        for board in plan["dashboards"]:
            for metric_id in board["kpis"]:
                kpi_cards.setdefault(metric_id, []).append(board["name"])
        unmapped = {(u["dashboard"], u["type"], u["name"]): u["reason"] for u in mapped["unmapped"]}
        rows = []
        for board in mapped["dashboards"]:
            for kpi in board["kpis"]:
                where = kpi_cards.get(kpi["metric_id"], [])
                status = "kpi card" if where else ("mapped, not charted" if kpi["metric_id"] else "unmapped")
                rows.append(
                    {
                        "ref": "",
                        "type": "KPI",
                        "requirement": kpi["name"],
                        "brd_dashboard": board["name"],
                        "metric_id": kpi["metric_id"],
                        "status": status,
                        "where": ", ".join(where),
                        "reason": unmapped.get((board["name"], "kpi", kpi["name"]), ""),
                    }
                )
            for visual in board["visuals"]:
                key = (visual["metric_id"], visual["dimension_id"])
                where = charted.get(key, []) if all(key) else []
                status = "charted" if where else ("mapped, not charted" if all(key) else "unmapped")
                name = visual["title"] or visual["metric"]
                rows.append(
                    {
                        "ref": visual.get("ref", ""),
                        "type": "Visual",
                        "requirement": name,
                        "brd_dashboard": board["name"],
                        "metric_id": visual["metric_id"],
                        "dimension_id": visual["dimension_id"],
                        "status": status,
                        "where": ", ".join(where),
                        "reason": unmapped.get((board["name"], "visual", name), ""),
                    }
                )
        return rows

    # ------------------------------------------------------------ outputs

    @staticmethod
    def spec_markdown(spec: dict) -> str:
        p, ts = spec["project"], spec["tech_stack"]
        lines = [
            f"# Dashboard specification - {p['name']}",
            "",
            f"Spec v{spec['spec_version']} · generated {spec['generated_at']} by {spec['generated_by']}",
            f"Source: {p['source_brd']} (BRD status: {p['brd_status']})",
            "",
            f"**Objective:** {p['objective'] or '-'}",
            "",
            f"**Stakeholders:** {', '.join(p['stakeholders']) or '-'} · **Time grain:** {p['time_grain']}",
            "",
            "## Tech stack",
            "",
            "| Layer | Choice |",
            "| --- | --- |",
            f"| Mockup | {ts['mockup']['markup']}; charts: {ts['mockup']['charting']} |",
            f"| Data | {ts['data']['engine']} `{ts['data']['database']}`, {ts['data']['model']} "
            f"(fact `{ts['data']['fact_table']}`; dims {', '.join(f'`{d}`' for d in ts['data']['dimension_tables'])}) |",
            f"| Semantic layer | {ts['semantic_layer']} |",
            f"| AI | {ts['ai']['provider']} `{ts['ai']['model']}` |",
            f"| App | {ts['app']} |",
        ]
        for platform in ts["target_platforms"].values():
            lines.append(f"| Step 3: {platform['label']} | {platform['status']} → {platform['output']} |")
        lines += ["", "## Global filters", ""]
        lines += [f"- {f['label']} (`{f['id']}`, {f['distinct_values']} values)" for f in spec["filters"]] or ["- none"]
        lines += [
            "",
            "## KPI catalogue and formulas",
            "",
            "| KPI | BRD definition | SQL | Tableau | Power BI (DAX) | Format |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for k in spec["kpis"]:
            cell = lambda s: str(s).replace("|", "\\|")  # noqa: E731
            lines.append(
                f"| **{k['label']}** (`{k['id']}`) | {cell(k['brd_definition'] or k['business_definition'])} | "
                f"`{cell(k['formulas']['sql'])}` | `{cell(k['formulas']['tableau'])}` | `{cell(k['formulas']['dax'])}` | {k['format']} |"
            )
        labels = {k["id"]: k["label"] for k in spec["kpis"]}
        for board in spec["dashboards"]:
            lines += ["", f"## Dashboard: {board['name']}", "", board["purpose"] or "", ""]
            lines.append("**KPI tiles:** " + (", ".join(labels.get(m, m) for m in board["kpis"]) or "-"))
            lines += [
                "",
                "| # | Chart | Type | Measure | Breakdown | Sort / Top N | BRD ref | Why |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
            for i, c in enumerate(board["charts"], start=1):
                lines.append(
                    f"| {i} | {c['title']} | {c['chart']} | {c['metric_label']} | {c['dimension_label']} | "
                    f"{c['sort']}{' / top ' + str(c['top_n']) if c['top_n'] else ''} | {', '.join(c['brd_refs']) or '-'} | {c['rationale']} |"
                )
        lines += [
            "",
            "## BRD traceability",
            "",
            "| Req. | Type | Requirement | Status | Where |",
            "| --- | --- | --- | --- | --- |",
        ]
        for t in spec["traceability"]:
            lines.append(
                f"| {t['ref'] or '-'} | {t['type']} | {t['requirement']} | {t['status']} | {t['where'] or t['reason']} |"
            )
        for title, items in (
            ("Assumptions", spec["assumptions"]),
            ("Open questions", spec["open_questions"]),
            ("Warnings", spec["warnings"]),
        ):
            if items:
                lines += ["", f"## {title}", ""] + [f"- {i}" for i in items]
        return "\n".join(lines) + "\n"

    def save(self, state: dict, filters: dict | None = None, root=None) -> dict:
        """Write dashboard_spec.json / .md and dashboard_mockup.html. Returns {"spec": spec, "paths": {...}}."""
        spec = self.build_spec(state, filters)
        folder = step_dir(spec["project"]["brd_project_name"] or spec["project"]["name"], 2, root=root)
        html = render_mockup(spec, state["preview"], state.get("insights", {}), state["semantic"])
        paths = {
            "spec_json": write_json(folder / "dashboard_spec.json", spec),
            "spec_md": write_text(folder / "dashboard_spec.md", self.spec_markdown(spec)),
            "html": write_text(folder / "dashboard_mockup.html", html),
        }
        return {"spec": spec, "html": html, "paths": {k: str(v) for k, v in paths.items()}}
