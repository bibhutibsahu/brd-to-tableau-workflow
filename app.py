"""BRD -> Dashboard AI: Streamlit app for the 3-step, 3-agent workflow.

    streamlit run app.py

Main path: one "Run" does Agent 1 + Agent 2 and shows the HTML dashboard. The step tabs below it let you
review or change each step on its own.

Step 1  Agent 1 · BRD Analyst         customer BRD -> our BRD format -> fill gaps -> finalised BRD
Step 2  Agent 2 · Dashboard Designer  finalised BRD -> KPIs, charts, formulas (spec .json/.md) -> HTML mockup
Step 3  Agent 3 · BI Publisher        approved spec -> Tableau workbook / Power BI hand-off pack

The original one-click flow (customer BRD -> requirements -> preview -> Tableau) is still available in Step 2.
"""

import copy
import io
import json
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from modules import brd_template
from modules.agents import PLATFORMS, BIPublisherAgent, BRDAnalystAgent, DashboardDesignerAgent
from modules.dashboard_generator import (
    altair_chart,
    build_preview,
    filter_values,
    generate_insights,
    star_schema_dot,
)
from modules.llm_client import LLMClient, LLMError
from modules.pipeline import PipelineError, run_until_preview
from modules.visualization_planner import revise_plan, validate_plan
from modules.workflow import run_brd_to_html

if not hasattr(st, "iframe"):  # older Streamlit, e.g. a global Anaconda install instead of the project's .venv
    st.error(
        f"This app needs the project's Streamlit (1.67), but this is Streamlit {st.__version__} from a different "
        "Python. Stop it (Ctrl+C) and start it with:\n\n"
        "`uv run streamlit run app.py`\n\n"
        "or activate the project environment first (`.venv\\Scripts\\Activate.ps1` on Windows, "
        "`source .venv/bin/activate` on macOS / Linux), then `streamlit run app.py`."
    )
    st.stop()

st.set_page_config(page_title="BRD to Dashboard AI", page_icon="📊", layout="wide")

CHART_LABELS = {"line": "Line", "bar": "Bar", "horizontal_bar": "Horizontal bar", "pie": "Pie", "table": "Table"}
MODELS = ["gemini-3.5-flash", "gemini-3.5-pro", "gemini-2.5-flash", "gemini-2.5-pro"]
STATUS_LABELS = {s: f"{brd_template.STATUS_ICONS[s]} {s}" for s in brd_template.STATUSES}

ss = st.session_state


def current_llm() -> LLMClient | None:
    return ss.get("llm")


def set_plan(plan: dict):
    """Store a new plan, rebuild the preview, clear stale insights, approval and mockup."""
    state = ss["state"]
    state["plan"] = validate_plan(plan, state["semantic"])
    state["preview"] = build_preview(state["plan"], state["schema"], state["semantic"], ss.get("filters"))
    state["insights"] = {}
    ss["approved"], ss["export"], ss["mockup_stale"] = False, None, True


def build_mockup():
    """Agent 2 writes dashboard_spec.json / .md and dashboard_mockup.html for the current design."""
    designer = DashboardDesignerAgent(current_llm())
    ss["mockup"] = designer.save(ss["state"], ss.get("filters"))
    ss["mockup_stale"] = False


def zip_folder(folder: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(folder))
    return buffer.getvalue()


# ------------------------------------------------------------------ sidebar: API key + progress

with st.sidebar:
    st.title("📊 BRD → Dashboard AI")

    st.subheader("Connect Gemini")
    api_key = st.text_input(
        "Gemini API key",
        value=config.GEMINI_API_KEY,
        type="password",
        help="Get one at https://aistudio.google.com/apikey. Kept in this browser session's memory "
        "only; never saved to disk.",
    )
    default_model = config.GEMINI_MODEL if config.GEMINI_MODEL in MODELS else MODELS[0]
    model_choice = st.selectbox("Model", [*MODELS, "Custom…"], index=[*MODELS, "Custom…"].index(default_model))
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
        st.caption("🔴 Not connected. Steps 1 and 2 need Gemini; Step 3 does not.")

    st.subheader("Progress")
    doc = ss.get("brd_doc")
    st.markdown(
        f"{'✅' if doc and doc['status'] == 'final' else ('🟡' if doc else '⬜')} **Step 1** · BRD "
        + (f"({doc['completeness']['score'] * 100:.0f}% complete, {doc['status']})" if doc else "")
    )
    st.markdown(
        f"{'✅' if ss.get('mockup') and not ss.get('mockup_stale') else ('🟡' if ss.get('state') else '⬜')} "
        f"**Step 2** · Mockup{' (approved)' if ss.get('approved') else ''}"
    )
    st.markdown(f"{'✅' if ss.get('publish') else '⬜'} **Step 3** · BI platform")
    st.caption(f"Database: `{config.DATABASE_PATH.name}` · Outputs: `{config.OUTPUT_DIR.name}/<project>/`")


st.header("BRD → Dashboard AI")

# ------------------------------------------------------------------ one go: Agent 1 + Agent 2 -> HTML

with st.container(border=True):
    st.subheader("▶ Customer BRD → HTML dashboard")
    st.caption(
        "One run: Agent 1 maps the BRD onto our format and fills the gaps automatically (AI suggestions are "
        "marked *assumed*), then Agent 2 designs the dashboards and builds the HTML."
    )
    left, right = st.columns([3, 1])
    with left:
        run_upload = st.file_uploader("Customer BRD", type=["pdf", "docx", "txt", "md"], key="run_upload")
        run_sample_path = config.DATA_DIR / "sample_brd.pdf"
        run_sample = (
            run_upload is None
            and run_sample_path.exists()
            and st.checkbox("Use the included sample BRD", value=True, key="run_sample")
        )
    with right:
        go = st.button(
            "▶ Run",
            type="primary",
            width="stretch",
            disabled=llm is None or (run_upload is None and not run_sample),
        )
        if llm is None:
            st.caption("Connect Gemini in the sidebar first.")
    if go:
        source, name = (
            (run_upload.getvalue(), run_upload.name)
            if run_upload is not None
            else (run_sample_path, run_sample_path.name)
        )
        with st.status("Running Agent 1 + Agent 2…", expanded=True) as status:
            try:
                result = run_brd_to_html(source, name, llm, log=st.write)
                ss["brd_doc"], ss["state"], ss["mockup"] = result["doc"], result["state"], result["mockup"]
                ss["approved"], ss["export"], ss["filters"], ss["publish"] = False, None, {}, None
                ss["mockup_stale"] = False
                ss["run_result"] = {"gap_report": result["gap_report"], "brd_paths": result["brd_paths"]}
                status.update(label="Done. The HTML dashboard is below.", state="complete", expanded=False)
            except PipelineError as error:
                status.update(label=f"Failed at: {error.step}", state="error")
                st.error(str(error.cause))
            except (LLMError, ValueError) as error:
                status.update(label="Run failed", state="error")
                st.error(str(error))

    run_result, mockup = ss.get("run_result"), ss.get("mockup")
    if run_result and mockup:
        spec, paths = mockup["spec"], mockup["paths"]
        trace_rows = spec["traceability"]
        charted = sum(1 for t in trace_rows if t["status"] in ("charted", "kpi card"))
        m = st.columns(4)
        m[0].metric("Dashboards", len(spec["dashboards"]))
        m[1].metric("Charts", sum(len(b["charts"]) for b in spec["dashboards"]))
        m[2].metric("KPIs", len(spec["kpis"]))
        m[3].metric("BRD requirements shown", f"{charted}/{len(trace_rows)}")
        if ss.get("mockup_stale"):
            st.warning("The design was changed below. Regenerate the mockup in Step 2 › Spec & HTML mockup.")
        project_folder = Path(paths["html"]).parents[1]
        d = st.columns(5)
        d[0].download_button("⬇ HTML dashboard", mockup["html"], "dashboard_mockup.html", type="primary")
        d[1].download_button(
            "Finalised BRD (.docx)", Path(run_result["brd_paths"]["docx"]).read_bytes(), "brd_final.docx"
        )
        d[2].download_button("Gap report (for customer)", run_result["gap_report"], "gap_report.md")
        d[3].download_button("Dashboard spec (.md)", Path(paths["spec_md"]).read_bytes(), "dashboard_spec.md")
        d[4].download_button("Everything (.zip)", zip_folder(project_folder), f"{project_folder.name}.zip")
        st.caption(f"Saved in `{project_folder}`")
        st.iframe(mockup["html"], height=980)

with st.expander("How it works: the 3 agents"):
    cards = st.columns(3)
    for col, agent in zip(cards, (BRDAnalystAgent, DashboardDesignerAgent, BIPublisherAgent), strict=True):
        with col.container(border=True):
            info = agent.card()
            st.markdown(f"**Step {info['step']} · {info['name'].split('· ')[-1]}**")
            st.caption(f"{info['role']}\n\nIn: {info['inputs']}  \nOut: {info['outputs']}")

st.markdown("#### Step-by-step review")
st.caption(
    "The run above fills both steps. Use these tabs to review or change the BRD and the design, or to build "
    "Step 3 once the BI platform is chosen."
)
step1, step2, step3, trace = st.tabs(["Step 1 · BRD", "Step 2 · Dashboard mockup", "Step 3 · BI platform", "LLM trace"])


# ================================================================== STEP 1: BRD


def field_editor(field: dict, value, key: str):
    """Widget for one BRD field. Returns the edited value in the field's type."""
    if field["type"] == "text":
        return st.text_area(field["label"], value or "", key=key, height=80)
    if field["type"] == "list":
        text = st.text_area(f"{field['label']} (one per line)", "\n".join(value or []), key=key, height=110)
        return [line.strip() for line in text.splitlines() if line.strip()]
    columns = [c["id"] for c in field["columns"]]
    frame = pd.DataFrame(value or [], columns=columns).fillna("")
    edited = st.data_editor(
        frame,
        key=key,
        num_rows="dynamic",
        width="stretch",
        column_config={c["id"]: st.column_config.TextColumn(c["label"]) for c in field["columns"]},
        hide_index=True,
    )
    return edited.fillna("").astype(str).to_dict("records")


def show_value(field: dict, value):
    if brd_template.is_empty(value):
        st.caption("— empty —")
    elif field["type"] == "table":
        st.dataframe(
            pd.DataFrame(value, columns=[c["id"] for c in field["columns"]]).rename(
                columns={c["id"]: c["label"] for c in field["columns"]}
            ),
            hide_index=True,
            width="stretch",
        )
    elif field["type"] == "list":
        st.markdown("\n".join(f"- {item}" for item in value))
    else:
        st.write(value)


with step1:
    st.subheader("Step 1 · Finalise the BRD")
    st.caption(
        "Agent 1 maps the customer's BRD onto our standard BRD format, flags what is missing or only implied, "
        "and suggests answers. Fill the gaps (or send the gap report to the customer), then finalise."
    )

    with st.expander("📄 Our BRD format (blank template to send to customers)"):
        left, right = st.columns(2)
        left.download_button(
            "Download template (.docx)", brd_template.to_docx(blank=True), "brd_template.docx", width="stretch"
        )
        right.download_button(
            "Download template (.md)", brd_template.to_markdown(blank=True), "brd_template.md", width="stretch"
        )
        rows = [
            {
                "section": f["section_title"],
                "field": f["label"],
                "type": f["type"],
                "required": f["required"],
                "guidance": f["guidance"],
            }
            for f in brd_template.fields()
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    source_col, resume_col = st.columns([3, 2])
    with source_col:
        upload = st.file_uploader("Customer BRD", type=["pdf", "docx", "txt", "md"], key="brd_upload")
        sample = config.DATA_DIR / "sample_brd.pdf"
        use_sample = upload is None and sample.exists() and st.checkbox("Use the included sample BRD", value=True)
        if st.button(
            "▶ Run Agent 1 · analyse BRD",
            type="primary",
            disabled=llm is None or (upload is None and not use_sample),
        ):
            source, name = (upload.getvalue(), upload.name) if upload is not None else (sample, sample.name)
            with st.spinner("Agent 1 is mapping the customer BRD onto our format…"):
                try:
                    ss["brd_doc"] = BRDAnalystAgent(llm).analyze(source, name)
                    BRDAnalystAgent.save(ss["brd_doc"])
                    st.rerun()
                except (LLMError, ValueError) as error:
                    st.error(str(error))
        if llm is None:
            st.caption("Connect Gemini in the sidebar to run Agent 1.")
    with resume_col:
        saved = st.file_uploader("…or resume a saved BRD (brd_draft.json / brd_final.json)", type=["json"])
        if saved is not None and st.button("Load saved BRD"):
            try:
                ss["brd_doc"] = brd_template.load_document(json.loads(saved.getvalue()))
                st.rerun()
            except (ValueError, json.JSONDecodeError) as error:
                st.error(str(error))

    doc = ss.get("brd_doc")
    if doc:
        fmap = brd_template.field_map()
        comp = doc["completeness"]
        st.divider()
        project = doc["fields"]["project_name"]["value"] or "Untitled project"
        st.markdown(f"### {project}  ·  _{doc['status']}_")
        m = st.columns(5)
        m[0].metric("Completeness", f"{comp['score'] * 100:.0f}%", help="Required fields that have a value")
        m[1].metric("Required filled", f"{comp['required_filled']}/{comp['required_total']}")
        m[2].metric("Missing", len(comp["missing"]), f"{len(comp['missing_required'])} required", delta_color="off")
        m[3].metric("To confirm", len(comp["to_confirm"]), help="Inferred by the AI, not stated in the BRD")
        m[4].metric("Provided by customer", comp["counts"]["provided"])
        st.progress(comp["score"])
        if doc.get("agent_summary"):
            st.info(f"**Agent 1:** {doc['agent_summary']}")
        for issue in brd_template.consistency_issues(doc):
            st.warning(issue)

        gap_tab, all_tab, answers_tab, doc_tab = st.tabs(
            ["Gaps to fill", "All fields", "Apply customer answers", "BRD document"]
        )

        with gap_tab:
            open_ids = comp["missing"] + comp["to_confirm"]
            a, b, _ = st.columns([1, 1, 2])
            if a.button("Accept all AI suggestions", disabled=not comp["missing"], help="Missing fields → 'assumed'"):
                BRDAnalystAgent.accept_suggestions(doc)
                st.rerun()
            if b.button("Confirm all inferred", disabled=not comp["to_confirm"]):
                BRDAnalystAgent.confirm_inferred(doc)
                st.rerun()
            if not open_ids:
                st.success("No gaps left. Review the document and finalise.")
            only_required = st.toggle("Required fields only", value=False)
            for field_id in open_ids:
                field, entry = fmap[field_id], doc["fields"][field_id]
                if only_required and not field["required"]:
                    continue
                title = (
                    f"{STATUS_LABELS[entry['status']]} · **{field['label']}**"
                    f"{' (required)' if field['required'] else ''} — {field['section_title']}"
                )
                with st.expander(title, expanded=field["required"] and entry["status"] == "missing"):
                    if entry.get("question"):
                        st.markdown(f"**Question for the customer:** {entry['question']}")
                    if entry.get("note"):
                        st.caption(f"Agent note: {entry['note']}")
                    if entry["status"] == "missing" and not brd_template.is_empty(entry.get("suggestion")):
                        st.markdown("**AI suggestion:**")
                        show_value(field, entry["suggestion"])
                    with st.form(f"gap_{field_id}"):
                        start = entry["value"] if entry["status"] != "missing" else entry.get("suggestion")
                        value = field_editor(field, start, f"gap_editor_{field_id}")
                        if st.form_submit_button("Save answer"):
                            BRDAnalystAgent.set_answer(doc, field_id, value, note="Entered by analyst")
                            st.rerun()

        with all_tab:
            for section in brd_template.load_template()["sections"]:
                st.markdown(f"#### {section['title']}")
                for field in section["fields"]:
                    entry = doc["fields"][field["id"]]
                    with st.expander(f"{STATUS_LABELS[entry['status']]} · {field['label']}"):
                        if entry.get("source"):
                            st.caption(f"Source: {entry['source']}")
                        with st.form(f"edit_{field['id']}"):
                            value = field_editor(field, entry["value"], f"all_editor_{field['id']}")
                            if st.form_submit_button("Save"):
                                BRDAnalystAgent.set_answer(doc, field["id"], value, note="Edited by analyst")
                                st.rerun()

        with answers_tab:
            st.caption(
                "Paste the customer's reply (email, meeting notes, filled questionnaire). Agent 1 fills the "
                "matching missing / to-confirm fields."
            )
            answers = st.text_area("Customer answers", height=180, key="customer_answers")
            if st.button("✨ Apply with Agent 1", disabled=llm is None or not answers.strip()):
                with st.spinner("Agent 1 is reading the answers…"):
                    try:
                        _, updated = BRDAnalystAgent(llm).apply_customer_answers(doc, answers)
                        st.success(
                            f"Updated {len(updated)} fields: " + ", ".join(fmap[f]["label"] for f in updated)
                            if updated
                            else "The answers did not match any open field."
                        )
                    except LLMError as error:
                        st.error(str(error))

        with doc_tab:
            st.markdown(brd_template.to_markdown(doc))
            if doc.get("customer_brd_text"):
                with st.expander("Customer BRD text"):
                    st.text(doc["customer_brd_text"][:20000])

        st.divider()
        st.markdown("#### Finalise")
        allow_open = st.checkbox(
            "Allow finalising with open items (missing fields become open questions)",
            value=False,
            disabled=comp["ready"],
        )
        f1, f2, _ = st.columns([1, 1, 2])
        if f1.button("💾 Save draft"):
            paths = BRDAnalystAgent.save(doc)
            st.success(f"Saved in `{Path(paths['json']).parent}`")
        if f2.button("✅ Finalise BRD", type="primary", disabled=not (comp["ready"] or allow_open)):
            try:
                BRDAnalystAgent.finalize(doc, allow_open_items=allow_open)
                ss["brd_paths"] = BRDAnalystAgent.save(doc)
                st.rerun()
            except ValueError as error:
                st.error(str(error))
        stem = "brd_final" if doc["status"] == "final" else "brd_draft"
        d = st.columns(4)
        public = {k: v for k, v in doc.items() if k != "customer_brd_text"}
        d[0].download_button(f"{stem}.json", json.dumps(public, indent=2, ensure_ascii=False), f"{stem}.json")
        d[1].download_button(f"{stem}.md", brd_template.to_markdown(doc), f"{stem}.md")
        d[2].download_button(f"{stem}.docx", brd_template.to_docx(doc), f"{stem}.docx")
        d[3].download_button("gap_report.md (for customer)", brd_template.gap_report_markdown(doc), "gap_report.md")
        if doc["status"] == "final":
            st.success(f"BRD finalised {doc['finalized_at']}. Continue with **Step 2 · Dashboard mockup**.")


# ================================================================== STEP 2: design + mockup


def render_requirements(state):
    req = state["requirements"]
    brd = state.get("brd") or {}
    st.caption(
        f"Source: {brd.get('source', '-')} · {brd.get('char_count', 0):,} characters"
        f"{' (truncated)' if brd.get('truncated') else ''} · extracted by {req.get('extraction_method')}"
    )
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
        st.text(brd.get("text", "")[:20000])


def render_mapping(state):
    mapped = state["mapped"]
    left, right = st.columns(2)
    with left:
        st.subheader("Star schema")
        st.graphviz_chart(star_schema_dot(state["schema"]))
    with right:
        st.subheader("Semantic layer")
        st.write(
            f"{len(state['semantic']['metrics'])} metrics, {len(state['semantic']['dimensions'])} dimensions. "
            f"Mapping: `{mapped['method']}`"
        )
        st.dataframe(
            pd.DataFrame(state["semantic"]["dimensions"])[["id", "label", "distinct_count", "temporal"]],
            hide_index=True,
            width="stretch",
            height=260,
        )
    rows = []
    for board in mapped["dashboards"]:
        rows += [
            {
                "dashboard": board["name"],
                "type": "KPI",
                "ref": "",
                "requirement": k["name"],
                "metric": k["metric_id"],
                "dimension": "",
                "confidence": k["confidence"],
                "matched by": k["matched_by"],
            }
            for k in board["kpis"]
        ]
        rows += [
            {
                "dashboard": board["name"],
                "type": "Visual",
                "ref": v.get("ref", ""),
                "requirement": v["title"] or v["metric"],
                "metric": v["metric_id"],
                "dimension": v["dimension_id"],
                "confidence": v["confidence"],
                "matched by": v["matched_by"],
            }
            for v in board["visuals"]
        ]
    st.subheader("Requirement → schema mapping")
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={"confidence": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")},
    )
    if mapped["unmapped"]:
        st.warning("Requirements the database cannot answer yet:")
        st.dataframe(pd.DataFrame(mapped["unmapped"]), hide_index=True, width="stretch")


def render_sql(state):
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


def render_preview(state):
    req, plan = state["requirements"], state["plan"]
    semantic = state["semantic"]
    metric_ids = [m["id"] for m in semantic["metrics"]]
    metric_label = {m["id"]: m["label"] for m in semantic["metrics"]}
    dim_ids = [d["id"] for d in semantic["dimensions"]]
    dim_label = {d["id"]: f"{d['label']} ({d['table']})" for d in semantic["dimensions"]}

    if plan["filters"]:
        chosen = {}
        for col, dim_id in zip(st.columns(len(plan["filters"])), plan["filters"], strict=True):
            chosen[dim_id] = col.multiselect(dim_label[dim_id], filter_values(dim_id, semantic), key=f"flt_{dim_id}")
        chosen = {k: v for k, v in chosen.items() if v}
        if chosen != ss.get("filters", {}):
            ss["filters"] = chosen
            state["preview"] = build_preview(plan, state["schema"], semantic, chosen)
            state["insights"] = {}
            ss["mockup_stale"] = True

    top_left, top_right = st.columns([3, 1])
    for warning in plan.get("warnings", []):
        top_left.caption(f"⚠️ {warning}")
    if top_right.button("✨ Refresh AI insights", disabled=llm is None, width="stretch"):
        with st.spinner("Gemini is reading the numbers…"):
            try:
                state["insights"] = generate_insights(
                    state["preview"], semantic, llm, req["business_objective"], ss.get("filters")
                )
                ss["mockup_stale"] = True
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
            for col, kpi in zip(st.columns(len(board["kpis"])), board["kpis"], strict=True):
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
                with st.expander("Modify chart"), st.form(f"edit_{b_index}_{chart['id']}"):
                    kind = st.selectbox(
                        "Chart type",
                        list(CHART_LABELS),
                        format_func=CHART_LABELS.get,
                        index=list(CHART_LABELS).index(chart["chart"]),
                    )
                    metric = st.selectbox(
                        "Metric", metric_ids, format_func=metric_label.get, index=metric_ids.index(chart["metric"])
                    )
                    dimension = st.selectbox(
                        "Dimension", dim_ids, format_func=dim_label.get, index=dim_ids.index(chart["dimension"])
                    )
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
                            charts[position].update(
                                {
                                    "chart": kind,
                                    "metric": metric,
                                    "dimension": dimension,
                                    "title": title,
                                    "top_n": top_n or None,
                                }
                            )
                        set_plan(new_plan)
                        st.rerun()
        st.divider()

    st.subheader("Review")
    instruction = st.text_area(
        "Ask Gemini for changes in plain English",
        placeholder="e.g. Make Net Revenue by Region a horizontal bar, and add Return Rate by "
        "Brand to Product Performance",
    )
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
        build_mockup()
        st.success("Approved. The spec and HTML mockup are regenerated; Step 3 is unlocked.")


def render_mockup():
    mockup = ss.get("mockup")
    if st.button(
        "🔄 Regenerate spec + HTML mockup" if mockup else "🧩 Generate spec + HTML mockup",
        type="primary" if (not mockup or ss.get("mockup_stale")) else "secondary",
    ):
        build_mockup()
        mockup = ss["mockup"]
    if not mockup:
        st.info("Generate the spec and the HTML mockup for the current design.")
        return
    if ss.get("mockup_stale"):
        st.warning("The design changed since the mockup was generated. Regenerate it to include the changes.")
    spec, paths = mockup["spec"], mockup["paths"]
    status = "approved" if ss.get("approved") else "draft (approve in Preview & review)"
    st.caption(f"Status: {status} · saved in `{Path(paths['html']).parent}`")
    d = st.columns(4)
    d[0].download_button("dashboard_mockup.html", mockup["html"], "dashboard_mockup.html", type="primary")
    d[1].download_button("dashboard_spec.json", Path(paths["spec_json"]).read_bytes(), "dashboard_spec.json")
    d[2].download_button("dashboard_spec.md", Path(paths["spec_md"]).read_bytes(), "dashboard_spec.md")
    d[3].download_button("All Step 2 files (.zip)", zip_folder(Path(paths["html"]).parent), "step2_mockup.zip")

    view, formulas, stack, tracing = st.tabs(["HTML mockup", "KPI formulas", "Tech stack", "BRD traceability"])
    with view:
        # LLM text in the page is HTML-escaped by the template's JS and the JSON escapes "</".
        st.iframe(mockup["html"], height=980)
    with formulas:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "KPI": k["label"],
                        "BRD definition": k["brd_definition"] or k["business_definition"],
                        "SQL (mockup)": k["formulas"]["sql"],
                        "Tableau": k["formulas"]["tableau"],
                        "Power BI (DAX)": k["formulas"]["dax"],
                        "format": k["format"],
                    }
                    for k in spec["kpis"]
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    with stack:
        st.json(spec["tech_stack"])
    with tracing:
        frame = pd.DataFrame(spec["traceability"])
        st.dataframe(frame, hide_index=True, width="stretch")
        done = int(frame["status"].isin(["charted", "kpi card"]).sum()) if not frame.empty else 0
        st.caption(f"{done} of {len(frame)} BRD requirements appear in the mockup.")


with step2:
    st.subheader("Step 2 · Dashboard mockup")
    st.caption(
        "Agent 2 designs KPIs and charts from the finalised BRD, stores every formula and the tech stack in "
        "dashboard_spec.json / .md, and builds a single-file HTML dashboard for the demo."
    )
    doc = ss.get("brd_doc")
    src_left, src_right = st.columns([3, 2])
    with src_left:
        if doc:
            st.markdown(
                f"**Input:** BRD from Step 1 — _{doc['fields']['project_name']['value'] or 'untitled'}_ "
                f"({doc['status']}, {doc['completeness']['score'] * 100:.0f}% complete)"
            )
            if doc["status"] != "final":
                st.warning("The BRD is not finalised yet. Finalise it in Step 1, or design from the draft.")
        else:
            st.markdown("**Input:** no BRD yet. Run Step 1, or load a finalised BRD here.")
        if st.button(
            "▶ Run Agent 2 · design dashboards",
            type="primary",
            disabled=llm is None or not doc,
        ):
            with st.status("Agent 2 is designing the dashboards…", expanded=True) as status:
                try:
                    ss["state"] = DashboardDesignerAgent(llm).design(doc, log=st.write)
                    ss["approved"], ss["export"], ss["filters"], ss["publish"] = False, None, {}, None
                    build_mockup()
                    status.update(label="Design ready. Review it, then approve.", state="complete")
                except PipelineError as error:
                    status.update(label=f"Failed at: {error.step}", state="error")
                    st.error(str(error.cause))
                except LLMError as error:
                    status.update(label="Design failed", state="error")
                    st.error(str(error))
    with src_right:
        saved_brd = st.file_uploader("Load a finalised BRD (brd_final.json)", type=["json"], key="step2_brd")
        if saved_brd is not None and st.button("Use this BRD"):
            try:
                ss["brd_doc"] = brd_template.load_document(json.loads(saved_brd.getvalue()))
                st.rerun()
            except (ValueError, json.JSONDecodeError) as error:
                st.error(str(error))
        with st.expander("One-click (original flow): use the customer BRD as-is, skip Step 1"):
            quick = st.file_uploader("Customer BRD", type=["pdf", "docx", "txt", "md"], key="quick_upload")
            sample = config.DATA_DIR / "sample_brd.pdf"
            quick_sample = quick is None and sample.exists() and st.checkbox("Use the included sample", True, key="qs")
            if st.button("▶ Run pipeline", disabled=llm is None or (quick is None and not quick_sample)):
                source, name = (quick.getvalue(), quick.name) if quick is not None else (sample, sample.name)
                with st.status("Running pipeline…", expanded=True) as status:
                    try:
                        ss["state"] = run_until_preview(source, name, llm, log=st.write)
                        ss["approved"], ss["export"], ss["filters"], ss["publish"] = False, None, {}, None
                        build_mockup()
                        status.update(label="Pipeline complete. Review the preview, then approve.", state="complete")
                    except PipelineError as error:
                        status.update(label=f"Failed at: {error.step}", state="error")
                        st.error(str(error.cause))
                    except (LLMError, FileNotFoundError) as error:
                        status.update(label="Pipeline failed", state="error")
                        st.error(str(error))

    if "state" in ss:
        state = ss["state"]
        plan, mapped = state["plan"], state["mapped"]
        st.divider()
        st.markdown(f"### {plan['title'] or state['requirements']['project_name']}")
        cols = st.columns(5)
        cols[0].metric("Dashboards", len(plan["dashboards"]))
        cols[1].metric("Charts", sum(len(b["charts"]) for b in plan["dashboards"]))
        cols[2].metric("KPIs", len({k for b in plan["dashboards"] for k in b["kpis"]}))
        cols[3].metric(
            "SQL queries",
            len(state["results"]),
            f"{sum(1 for r in state['results'] if r['error'])} failed",
            delta_color="inverse",
        )
        cols[4].metric("Unmapped requirements", len(mapped["unmapped"]))
        tabs = st.tabs(
            [
                "Requirements",
                "Schema mapping",
                "SQL & KPI logic",
                "Preview & review",
                "Spec & HTML mockup",
            ]
        )
        with tabs[0]:
            render_requirements(state)
        with tabs[1]:
            render_mapping(state)
        with tabs[2]:
            render_sql(state)
        with tabs[3]:
            render_preview(state)
        with tabs[4]:
            render_mockup()


# ================================================================== STEP 3: BI platform

with step3:
    st.subheader("Step 3 · Build in the BI platform")
    target = (ss.get("brd_doc") or {}).get("fields", {}).get("target_platform", {}).get("value") or "not decided"
    st.info(
        f"Target platform in the BRD: **{target}**. Until the platform is confirmed, the Step 2 HTML mockup is the "
        "demo deliverable. Agent 3 builds the approved design in the chosen platform from dashboard_spec.json."
    )
    mockup = ss.get("mockup")
    spec = mockup["spec"] if mockup else None
    spec_upload = st.file_uploader("…or load an approved dashboard_spec.json", type=["json"], key="spec_upload")
    if spec_upload is not None:
        try:
            spec = json.loads(spec_upload.getvalue())
            if "plan" not in spec or "kpis" not in spec:
                raise ValueError("Not a dashboard spec: 'plan' and 'kpis' are required.")
            st.caption(f"Using uploaded spec: {spec['project']['name']} (generated {spec['generated_at']})")
        except (ValueError, json.JSONDecodeError, KeyError) as error:
            st.error(str(error))
            spec = None

    from_session = spec is not None and spec_upload is None
    if spec is None:
        st.warning("No design yet. Complete Step 2 (or load a dashboard_spec.json).")
    elif from_session and not ss.get("approved"):
        st.warning("Approve the dashboards in Step 2 › Preview & review first.")
    else:
        if from_session and ss.get("mockup_stale"):
            st.warning("The design changed after the spec was generated. Regenerate it in Step 2 first.")
        options = list(PLATFORMS)
        platform = st.radio(
            "Platform",
            options,
            format_func=lambda p: f"{PLATFORMS[p]['label']} — {PLATFORMS[p]['status']}",
            horizontal=False,
        )
        st.caption(f"Output: {PLATFORMS[platform]['output']}")
        if st.button(f"📦 Run Agent 3 · build for {PLATFORMS[platform]['label']}", type="primary"):
            try:
                ss["publish"] = BIPublisherAgent().publish(spec, platform)
                if platform == "tableau":
                    ss["export"] = ss["publish"]["details"]
            except Exception as error:
                st.exception(error)
        result = ss.get("publish")
        if result:
            folder = Path(result["folder"])
            st.success(f"{result['label']} build written to `{folder}`")
            if result["platform"] == "tableau":
                export = result["details"]
                st.caption(
                    f"Workbook: {len(export['dashboards'])} dashboards, {len(export['worksheets'])} worksheets. "
                    "XML validation passed."
                )
                twbx, twb = Path(export["twbx_path"]), Path(export["twb_path"])
                c1, c2, c3 = st.columns(3)
                c1.download_button("Download .twbx (with data)", twbx.read_bytes(), twbx.name, type="primary")
                c2.download_button("Download .twb (XML)", twb.read_bytes(), twb.name)
                c3.download_button("Download plan JSON", Path(export["plan_path"]).read_bytes(), "approved_plan.json")
                st.dataframe(pd.DataFrame(export["worksheets"]), hide_index=True, width="stretch")
            else:
                files = result["files"]
                c1, c2, c3, c4 = st.columns(4)
                c1.download_button("Power BI pack (.zip)", zip_folder(folder), "powerbi_pack.zip", type="primary")
                c2.download_button("measures.dax", Path(files["measures"]).read_bytes(), "measures.dax")
                c3.download_button("model.json", Path(files["model"]).read_bytes(), "model.json")
                c4.download_button("build_guide.md", Path(files["guide"]).read_bytes(), "build_guide.md")
                with st.expander("Build guide", expanded=True):
                    st.markdown(Path(files["guide"]).read_text(encoding="utf-8"))
            with st.expander("Approved plan"):
                st.json(spec["plan"])


# ================================================================== LLM trace

with trace:
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
