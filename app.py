"""BRD -> Tableau AI: Streamlit app.

    streamlit run app.py

Upload BRD -> Gemini extracts requirements -> map schema -> SQL & KPI logic -> execute ->
Gemini plans visuals -> preview + AI insights -> review / modify -> approve -> Tableau workbook.
"""

import copy
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from modules.dashboard_generator import (altair_chart, build_preview, filter_values, generate_insights,
                                         generate_tableau_workbook, star_schema_dot)
from modules.llm_client import LLMClient, LLMError
from modules.pipeline import PipelineError, run_until_preview
from modules.visualization_planner import revise_plan, validate_plan

st.set_page_config(page_title="BRD to Tableau AI", page_icon="📊", layout="wide")

CHART_LABELS = {"line": "Line", "bar": "Bar", "horizontal_bar": "Horizontal bar", "pie": "Pie", "table": "Table"}
MODELS = ["gemini-3.5-flash", "gemini-3.5-pro", "gemini-2.5-flash", "gemini-2.5-pro"]

ss = st.session_state


def current_llm() -> LLMClient | None:
    return ss.get("llm")


def set_plan(plan: dict):
    """Store a new plan, rebuild the preview, clear stale insights and any earlier approval."""
    state = ss["state"]
    state["plan"] = validate_plan(plan, state["semantic"])
    state["preview"] = build_preview(state["plan"], state["schema"], state["semantic"], ss.get("filters"))
    state["insights"] = {}
    ss["approved"], ss["export"] = False, None


# ------------------------------------------------------------------ sidebar: API key + run

with st.sidebar:
    st.title("📊 BRD → Tableau AI")

    st.subheader("1. Connect Gemini")
    api_key = st.text_input("Gemini API key", value=config.GEMINI_API_KEY, type="password",
                            help="Get one at https://aistudio.google.com/apikey. Kept in this browser session's memory "
                                 "only; never saved to disk.")
    default_model = config.GEMINI_MODEL if config.GEMINI_MODEL in MODELS else MODELS[0]
    model_choice = st.selectbox("Model", MODELS + ["Custom…"], index=(MODELS + ["Custom…"]).index(default_model))
    model = st.text_input("Custom model id", config.GEMINI_MODEL) if model_choice == "Custom…" else model_choice

    if st.button("Connect", width="stretch", disabled=not api_key.strip()):
        candidate = LLMClient(api_key=api_key, model=model)
        with st.spinner(f"Testing {model}…"):
            try:
                info = candidate.ping()
                ss["llm"] = candidate
                st.success(f"Connected to {info['model']} ({info['latency_ms']} ms)")
            except LLMError as error:
                ss.pop("llm", None)
                st.error(str(error))

    llm = current_llm()
    if llm and (llm.api_key != api_key.strip() or llm.model != model):
        ss.pop("llm", None)
        llm = None
    if llm:
        st.caption(f"🟢 {llm.model} · {len(llm.calls)} calls · {llm.total_tokens:,} tokens")
    else:
        st.caption("🔴 Not connected")

    st.subheader("2. BRD")
    upload = st.file_uploader("Upload BRD", type=["pdf", "docx", "txt", "md"])
    sample = config.DATA_DIR / "sample_brd.pdf"
    use_sample = upload is None and sample.exists() and st.checkbox("Use the included ecommerce BRD", value=True)
    st.caption(f"Database: `{config.DATABASE_PATH.name}`")

    run = st.button("▶ Run pipeline", type="primary", width="stretch",
                    disabled=llm is None or (upload is None and not use_sample))
    if llm is None:
        st.caption("Connect Gemini to run.")

if run:
    source, name = (upload.getvalue(), upload.name) if upload is not None else (sample, sample.name)
    with st.status("Running pipeline…", expanded=True) as status:
        try:
            ss["state"] = run_until_preview(source, name, llm, log=st.write)
            ss["approved"], ss["export"], ss["filters"] = False, None, {}
            status.update(label="Pipeline complete. Review the preview, then approve.", state="complete")
        except PipelineError as error:
            status.update(label=f"Failed at: {error.step}", state="error")
            st.error(str(error.cause))
        except (LLMError, FileNotFoundError) as error:
            status.update(label="Pipeline failed", state="error")
            st.error(str(error))

if "state" not in ss:
    st.header("BRD → Tableau dashboards")
    st.markdown(
        "1. **Connect Gemini** in the sidebar with your API key\n"
        "2. **Upload a BRD** (PDF / DOCX / TXT), or use the included ecommerce BRD\n"
        "3. **Run pipeline**: Gemini extracts the requirements, maps them to the star schema, and plans the "
        "dashboards; SQL computes every KPI\n"
        "4. **Review** the preview and AI insights, modify charts by hand or in plain English, then **approve**\n"
        "5. **Download** the Tableau workbook (.twbx)")
    st.stop()

state = ss["state"]
req, mapped, plan = state["requirements"], state["mapped"], state["plan"]

st.header(req["project_name"])
cols = st.columns(5)
cols[0].metric("Dashboards", len(plan["dashboards"]))
cols[1].metric("Charts", sum(len(b["charts"]) for b in plan["dashboards"]))
cols[2].metric("KPIs", len({k for b in plan["dashboards"] for k in b["kpis"]}))
cols[3].metric("SQL queries", len(state["results"]), f"{sum(1 for r in state['results'] if r['error'])} failed",
               delta_color="inverse")
cols[4].metric("Unmapped requirements", len(mapped["unmapped"]))

tabs = st.tabs(["1 · Requirements", "2 · Schema mapping", "3 · SQL & KPI logic", "4 · Preview & review",
                "5 · Tableau export", "LLM trace"])

# ------------------------------------------------------------------ 1 requirements
with tabs[0]:
    st.caption(f"Source: {state['brd']['source']} · {state['brd']['char_count']:,} characters"
               f"{' (truncated)' if state['brd']['truncated'] else ''} · extracted by {req.get('extraction_method')}")
    if req["business_objective"]:
        st.info(req["business_objective"])
    left, right = st.columns(2)
    left.markdown("**Stakeholders:** " + (", ".join(req["stakeholders"]) or "—"))
    left.markdown("**Time grain:** " + req["time_grain"])
    right.markdown("**Global filters:** " + (", ".join(req["global_filters"]) or "—"))
    for board in req["dashboards"]:
        with st.expander(f"{board['name']} — {len(board['kpis'])} KPIs, {len(board['visuals'])} visuals"):
            st.write(board["purpose"])
            if board.get("audience"):
                st.caption(f"Audience: {board['audience']}")
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
    left, right = st.columns(2)
    with left:
        st.subheader("Star schema")
        st.graphviz_chart(star_schema_dot(state["schema"]))
    with right:
        st.subheader("Semantic layer")
        st.write(f"{len(state['semantic']['metrics'])} metrics, {len(state['semantic']['dimensions'])} dimensions. "
                 f"Mapping: `{mapped['method']}`")
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
        chosen = {}
        for col, dim_id in zip(st.columns(len(plan["filters"])), plan["filters"]):
            chosen[dim_id] = col.multiselect(dim_label[dim_id], filter_values(dim_id, semantic), key=f"flt_{dim_id}")
        chosen = {k: v for k, v in chosen.items() if v}
        if chosen != ss.get("filters", {}):
            ss["filters"] = chosen
            state["preview"] = build_preview(plan, state["schema"], semantic, chosen)
            state["insights"] = {}

    top_left, top_right = st.columns([3, 1])
    for warning in plan.get("warnings", []):
        top_left.caption(f"⚠️ {warning}")
    if top_right.button("✨ Refresh AI insights", disabled=llm is None, width="stretch"):
        with st.spinner("Gemini is reading the numbers…"):
            try:
                state["insights"] = generate_insights(state["preview"], semantic, llm, req["business_objective"],
                                                      ss.get("filters"))
            except LLMError as error:
                st.error(str(error))

    for b_index, board in enumerate(state["preview"]):
        st.markdown(f"### {board['name']}")
        if board["purpose"]:
            st.caption(board["purpose"])
        insight = state.get("insights", {}).get(board["name"])
        if insight:
            with st.container(border=True):
                st.markdown(f"**✨ {insight['headline']}**")
                for line in insight["insights"]:
                    st.markdown(f"- {line}")
                if insight["recommendations"]:
                    st.markdown("**Recommended actions:** " + " · ".join(insight["recommendations"]))
        if board["kpis"]:
            for col, kpi in zip(st.columns(len(board["kpis"])), board["kpis"]):
                col.metric(kpi["label"], kpi["display"])
        chart_cols = st.columns(2)
        for c_index, chart in enumerate(board["charts"]):
            with chart_cols[c_index % 2]:
                st.markdown(f"**{chart['title']}** · _{CHART_LABELS[chart['chart']]}_")
                if chart.get("rationale"):
                    st.caption(chart["rationale"])
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
    instruction = st.text_area("Ask Gemini for changes in plain English",
                               placeholder="e.g. Make Net Revenue by Region a horizontal bar, and add Return Rate by "
                                           "Brand to Product Performance")
    left, right = st.columns(2)
    if left.button("✨ Apply with Gemini", disabled=llm is None or not instruction.strip()):
        with st.spinner("Gemini is revising the plan…"):
            try:
                set_plan(revise_plan(plan, instruction, semantic, llm))
                st.rerun()
            except LLMError as error:
                st.error(str(error))
    if right.button("✅ Approve dashboards", type="primary"):
        ss["approved"] = True
        st.success("Approved. Open the Tableau export tab.")

# ------------------------------------------------------------------ 5 export
with tabs[4]:
    if not ss.get("approved"):
        st.info("Approve the dashboards in the Preview & review tab first.")
    else:
        if st.button("📦 Generate Tableau workbook", type="primary"):
            try:
                ss["export"] = generate_tableau_workbook(plan, state["schema"], state["semantic"])
            except Exception as error:
                st.exception(error)
        export = ss.get("export")
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

# ------------------------------------------------------------------ LLM trace
with tabs[5]:
    calls = llm.calls if llm else []
    if not calls:
        st.info("No Gemini calls in this session yet.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Calls", len(calls))
        c2.metric("Total tokens", f"{llm.total_tokens:,}")
        c3.metric("Total latency", f"{sum(c['latency_ms'] for c in calls) / 1000:.1f} s")
        table = pd.DataFrame(calls)[["purpose", "model", "ok", "latency_ms", "prompt_tokens", "output_tokens", "error"]]
        st.dataframe(table, hide_index=True, width="stretch")
        for i, call in enumerate(calls, start=1):
            with st.expander(f"{i}. {call['purpose']} — {'ok' if call['ok'] else 'failed'}, {call['latency_ms']} ms"):
                st.markdown("**Prompt**")
                st.code(call["prompt"], language="text")
                st.markdown("**Response**")
                st.code(call["response"] or call.get("error") or "", language="json")
