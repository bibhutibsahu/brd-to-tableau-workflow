"""BRD -> Tableau AI: Streamlit app.

    streamlit run app.py

Upload BRD -> extract requirements -> map schema -> SQL & KPI logic -> execute ->
plan visuals -> preview -> review / modify -> approve -> generate Tableau workbook.
"""

import copy
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from modules.dashboard_generator import (altair_chart, build_preview, filter_values,
                                         generate_tableau_workbook, star_schema_dot)
from modules.llm_client import LLMClient, LLMError
from modules.pipeline import run_until_preview
from modules.visualization_planner import revise_plan, validate_plan

st.set_page_config(page_title="BRD to Tableau AI", page_icon="📊", layout="wide")

CHART_LABELS = {"line": "Line", "bar": "Bar", "horizontal_bar": "Horizontal bar", "pie": "Pie", "table": "Table"}


@st.cache_resource
def get_llm() -> LLMClient:
    return LLMClient()


def ss():
    return st.session_state


def set_plan(plan: dict):
    """Store a new plan, rebuild the preview, and clear any earlier approval."""
    state = ss()["state"]
    state["plan"] = validate_plan(plan, state["semantic"])
    state["preview"] = build_preview(state["plan"], state["schema"], state["semantic"], ss().get("filters"))
    ss()["approved"] = False
    ss()["export"] = None


# ------------------------------------------------------------------ sidebar

llm = get_llm()
with st.sidebar:
    st.title("📊 BRD → Tableau AI")
    if llm.available:
        st.success(f"LLM: {llm.model}")
    else:
        st.warning("No GEMINI_API_KEY: rule-based mode. Requirements are matched to the KPI catalog by keyword.")
    upload = st.file_uploader("Upload BRD", type=["pdf", "docx", "txt", "md"])
    sample = config.DATA_DIR / "sample_brd.pdf"
    use_sample = st.checkbox("Use sample ecommerce BRD", value=upload is None and sample.exists())
    st.caption(f"Database: `{config.DATABASE_PATH.name}`")
    run = st.button("▶ Run pipeline", type="primary", width="stretch",
                    disabled=upload is None and not use_sample)

if run:
    source, name = (upload.getvalue(), upload.name) if upload is not None and not use_sample else (sample, sample.name)
    with st.status("Running pipeline…", expanded=True) as status:
        try:
            ss()["state"] = run_until_preview(source, name, llm, log=st.write)
            ss()["approved"], ss()["export"], ss()["filters"] = False, None, {}
            status.update(label="Pipeline complete. Review the preview, then approve.", state="complete")
        except FileNotFoundError as error:
            status.update(label="Database missing", state="error")
            st.error(str(error))
        except Exception as error:
            status.update(label="Pipeline failed", state="error")
            st.exception(error)

if "state" not in ss():
    st.header("BRD → Tableau dashboards")
    st.markdown(
        "Upload a Business Requirements Document (PDF/DOCX), or tick **Use sample ecommerce BRD**, then **Run pipeline**.\n\n"
        "1. **Extract** KPIs, visuals and filters from the BRD (LLM)\n"
        "2. **Map** them to the ecommerce star schema\n"
        "3. **Generate and run SQL** for every KPI and chart\n"
        "4. **Plan** the chart types and layout\n"
        "5. **Preview**, modify, and approve\n"
        "6. **Generate** a Tableau workbook (.twbx)")
    st.stop()

state = ss()["state"]
req, mapped, plan = state["requirements"], state["mapped"], state["plan"]

st.header(req["project_name"])
cols = st.columns(5)
cols[0].metric("Dashboards", len(plan["dashboards"]))
cols[1].metric("Charts", sum(len(b["charts"]) for b in plan["dashboards"]))
cols[2].metric("KPIs", len({k for b in plan["dashboards"] for k in b["kpis"]}))
cols[3].metric("SQL queries", len(state["results"]), f"{sum(1 for r in state['results'] if r['error'])} failed",
               delta_color="inverse")
cols[4].metric("Unmapped", len(mapped["unmapped"]))

tabs = st.tabs(["1 · Requirements", "2 · Schema mapping", "3 · SQL & KPI logic", "4 · Preview & review", "5 · Tableau export"])

# ------------------------------------------------------------------ 1 requirements
with tabs[0]:
    st.caption(f"Source: {state['brd']['source']} · {state['brd']['char_count']:,} characters · "
               f"extracted by {req.get('extraction_method')}")
    if req["business_objective"]:
        st.info(req["business_objective"])
    left, right = st.columns(2)
    left.markdown("**Stakeholders:** " + (", ".join(req["stakeholders"]) or "—"))
    left.markdown("**Time grain:** " + req["time_grain"])
    right.markdown("**Global filters:** " + (", ".join(req["global_filters"]) or "—"))
    for board in req["dashboards"]:
        with st.expander(f"{board['name']} — {len(board['kpis'])} KPIs, {len(board['visuals'])} visuals"):
            st.write(board["purpose"])
            st.dataframe(pd.DataFrame(board["kpis"]), hide_index=True, width="stretch")
            st.dataframe(pd.DataFrame(board["visuals"]), hide_index=True, width="stretch")
    for title, items in (("Assumptions", req["assumptions"]), ("Open questions", req["open_questions"])):
        if items:
            st.markdown(f"**{title}**\n" + "\n".join(f"- {item}" for item in items))
    with st.expander("Structured JSON"):
        st.json(req)
    with st.expander("BRD text"):
        st.text(state["brd"]["text"][:20000])

# ------------------------------------------------------------------ 2 schema mapping
with tabs[1]:
    left, right = st.columns([1, 1])
    with left:
        st.subheader("Star schema")
        st.graphviz_chart(star_schema_dot(state["schema"]))
    with right:
        st.subheader("Semantic layer")
        st.write(f"{len(state['semantic']['metrics'])} metrics, {len(state['semantic']['dimensions'])} dimensions. "
                 f"Mapping method: `{mapped['method']}`")
        st.dataframe(pd.DataFrame(state["semantic"]["dimensions"])[["id", "label", "distinct_count", "temporal"]],
                     hide_index=True, width="stretch", height=260)
    rows = []
    for board in mapped["dashboards"]:
        rows += [{"dashboard": board["name"], "type": "KPI", "requirement": k["name"], "metric": k["metric_id"],
                  "dimension": "", "confidence": k["confidence"], "matched by": k["matched_by"]} for k in board["kpis"]]
        rows += [{"dashboard": board["name"], "type": "Visual", "requirement": v["title"] or v["metric"],
                  "metric": v["metric_id"], "dimension": v["dimension_id"], "confidence": v["confidence"],
                  "matched by": v["matched_by"]} for v in board["visuals"]]
    st.subheader("Requirement → schema mapping")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"confidence": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")})
    if mapped["unmapped"]:
        st.warning("Requirements the database cannot answer yet:")
        st.dataframe(pd.DataFrame(mapped["unmapped"]), hide_index=True, width="stretch")

# ------------------------------------------------------------------ 3 SQL & KPI logic
with tabs[2]:
    st.subheader("KPI logic")
    st.dataframe(pd.DataFrame(state["kpi_logic"]), hide_index=True, width="stretch")
    st.subheader("Generated SQL")
    for result in state["results"]:
        icon = "❌" if result["error"] else "✅"
        with st.expander(f"{icon} {result['dashboard']} · {result['name']} — {result['rows']} rows, {result['ms']} ms"):
            st.code(result["sql"], language="sql")
            if result["error"]:
                st.error(result["error"])
            else:
                st.dataframe(result["data"].head(50), hide_index=True, width="stretch")

# ------------------------------------------------------------------ 4 preview & review
with tabs[3]:
    semantic = state["semantic"]
    metric_ids = [m["id"] for m in semantic["metrics"]]
    metric_label = {m["id"]: m["label"] for m in semantic["metrics"]}
    dim_ids = [d["id"] for d in semantic["dimensions"]]
    dim_label = {d["id"]: f"{d['label']} ({d['table']})" for d in semantic["dimensions"]}

    if plan["filters"]:
        filter_cols = st.columns(len(plan["filters"]))
        chosen = {}
        for col, dim_id in zip(filter_cols, plan["filters"]):
            chosen[dim_id] = col.multiselect(dim_label[dim_id], filter_values(dim_id, semantic), key=f"flt_{dim_id}")
        chosen = {k: v for k, v in chosen.items() if v}
        if chosen != ss().get("filters", {}):
            ss()["filters"] = chosen
            state["preview"] = build_preview(plan, state["schema"], semantic, chosen)

    for warning in plan.get("warnings", []):
        st.caption(f"⚠️ {warning}")

    for b_index, board in enumerate(state["preview"]):
        st.markdown(f"### {board['name']}")
        if board["purpose"]:
            st.caption(board["purpose"])
        if board["kpis"]:
            for col, kpi in zip(st.columns(len(board["kpis"])), board["kpis"]):
                col.metric(kpi["label"], kpi["display"])
        chart_cols = st.columns(2)
        for c_index, chart in enumerate(board["charts"]):
            with chart_cols[c_index % 2]:
                st.markdown(f"**{chart['title']}** · _{CHART_LABELS[chart['chart']]}_")
                if chart["error"]:
                    st.error(chart["error"])
                elif chart["chart"] == "table":
                    st.dataframe(chart["data"], hide_index=True, width="stretch", height=280)
                else:
                    st.altair_chart(altair_chart(chart, semantic), width="stretch")
                with st.expander("Modify chart"):
                    with st.form(f"edit_{b_index}_{chart['id']}"):
                        kind = st.selectbox("Chart type", list(CHART_LABELS), format_func=CHART_LABELS.get,
                                            index=list(CHART_LABELS).index(chart["chart"]))
                        metric = st.selectbox("Metric", metric_ids, format_func=metric_label.get,
                                              index=metric_ids.index(chart["metric"]))
                        dimension = st.selectbox("Dimension", dim_ids, format_func=dim_label.get,
                                                 index=dim_ids.index(chart["dimension"]))
                        title = st.text_input("Title", chart["title"])
                        top_n = st.number_input("Top N (0 = all)", 0, 100, chart["top_n"] or 0)
                        remove = st.checkbox("Remove this chart")
                        if st.form_submit_button("Apply"):
                            new_plan = copy.deepcopy(plan)
                            charts = new_plan["dashboards"][b_index]["charts"]
                            position = next(i for i, c in enumerate(charts) if c["id"] == chart["id"])
                            if remove:
                                charts.pop(position)
                            else:
                                charts[position].update({"chart": kind, "metric": metric, "dimension": dimension,
                                                         "title": title, "top_n": top_n or None})
                            set_plan(new_plan)
                            st.rerun()
        st.divider()

    st.subheader("Review")
    instruction = st.text_area("Ask for changes in plain English",
                               placeholder="e.g. Make Net Revenue by Region a horizontal bar and add a chart of "
                                           "Return Rate by Brand to Product Performance")
    left, right = st.columns(2)
    if left.button("✨ Apply with AI", disabled=not instruction.strip()):
        try:
            set_plan(revise_plan(plan, instruction, semantic, llm))
            st.rerun()
        except LLMError as error:
            st.error(str(error))
    if right.button("✅ Approve dashboards", type="primary"):
        ss()["approved"] = True
        st.success("Approved. Open the Tableau export tab.")

# ------------------------------------------------------------------ 5 export
with tabs[4]:
    if not ss().get("approved"):
        st.info("Approve the dashboards in the Preview & review tab first.")
    else:
        if st.button("📦 Generate Tableau workbook", type="primary"):
            try:
                ss()["export"] = generate_tableau_workbook(plan, state["schema"], state["semantic"])
            except Exception as error:
                st.exception(error)
        export = ss().get("export")
        if export:
            st.success(f"Workbook written: {len(export['dashboards'])} dashboards, "
                       f"{len(export['worksheets'])} worksheets. XML validation passed.")
            twbx, twb = Path(export["twbx_path"]), Path(export["twb_path"])
            c1, c2, c3 = st.columns(3)
            c1.download_button("Download .twbx (with data)", twbx.read_bytes(), twbx.name, type="primary")
            c2.download_button("Download .twb (XML)", twb.read_bytes(), twb.name)
            c3.download_button("Download plan JSON", Path(export["plan_path"]).read_bytes(), "approved_plan.json")
            st.caption(f"Saved in `{twbx.parent}`")
            st.dataframe(pd.DataFrame(export["worksheets"]), hide_index=True, width="stretch")
            with st.expander("Approved plan"):
                st.json(plan)
