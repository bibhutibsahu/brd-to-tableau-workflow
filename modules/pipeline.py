"""Runs the BRD -> Tableau steps in order. Used by app.py and from the command line:

python -m modules.pipeline data/sample_brd.pdf             # Gemini (GEMINI_API_KEY in env/.env)
python -m modules.pipeline data/sample_brd.pdf --approve   # also writes the Tableau workbook
"""

import argparse
import json
import os

from modules.brd_parser import parse_brd
from modules.dashboard_generator import build_preview, generate_insights, generate_tableau_workbook
from modules.llm_client import LLMClient, LLMError
from modules.requirement_extractor import extract_requirements
from modules.schema_mapper import build_semantic_layer, introspect_schema, map_requirements
from modules.sql_generator import SQLGenerator, execute_queries, generate_queries
from modules.visualization_planner import plan_visualizations

STEPS = 8


class PipelineError(RuntimeError):
    """A step failed. .step names it so the UI can say where."""

    def __init__(self, step: str, error: Exception):
        super().__init__(f"{step} failed: {error}")
        self.step, self.cause = step, error


def run_until_preview(source, filename: str | None = None, llm: LLMClient | None = None, log=print) -> dict:
    llm = llm or LLMClient()
    if not llm.available:
        raise LLMError("No Gemini API key. Enter it in the sidebar or set GEMINI_API_KEY in .env.")
    state = {"mode": f"llm:{llm.model}"}

    def step(number, label, fn):
        log(f"{number}/{STEPS} {label}")
        try:
            return fn()
        except Exception as error:
            raise PipelineError(label, error) from error

    state["brd"] = step(1, "Parsing BRD", lambda: parse_brd(source, filename))
    state["requirements"] = step(
        2, "Extracting requirements with Gemini", lambda: extract_requirements(state["brd"]["text"], llm)
    )
    state["schema"] = step(3, "Reading database schema", introspect_schema)
    state["semantic"] = build_semantic_layer(state["schema"])
    state["mapped"] = step(
        3, "Mapping requirements to the schema", lambda: map_requirements(state["requirements"], state["semantic"], llm)
    )
    generator = SQLGenerator(state["schema"], state["semantic"])
    state["queries"] = step(4, "Generating SQL and KPI logic", lambda: generate_queries(state["mapped"], generator))
    used = sorted({m for q in state["queries"] for m in q["metric_ids"]})
    state["kpi_logic"] = generator.kpi_logic(used)
    state["results"] = step(5, "Executing SQL", lambda: execute_queries(state["queries"]))
    state["plan"] = step(
        6,
        "Planning visualizations",
        lambda: plan_visualizations(
            state["mapped"], state["semantic"], state["requirements"]["project_name"], state["results"], llm
        ),
    )
    state["preview"] = step(
        7, "Building dashboard preview", lambda: build_preview(state["plan"], state["schema"], state["semantic"])
    )
    state["insights"] = step(
        8,
        "Writing AI insights",
        lambda: generate_insights(
            state["preview"], state["semantic"], llm, state["requirements"]["business_objective"]
        ),
    )
    return state


def approve(state: dict) -> dict:
    return generate_tableau_workbook(state["plan"], state["schema"], state["semantic"])


def main():
    parser = argparse.ArgumentParser(description="BRD -> Tableau dashboard pipeline")
    parser.add_argument("brd", help="Path to the BRD (.pdf, .docx, .txt, .md)")
    parser.add_argument("--approve", action="store_true", help="Write the Tableau workbook after planning")
    parser.add_argument("--model", default=None, help="Gemini model, default from GEMINI_MODEL")
    args = parser.parse_args()

    llm = LLMClient(model=args.model)
    try:
        state = run_until_preview(args.brd, llm=llm)
    except (PipelineError, LLMError) as error:
        raise SystemExit(f"\nERROR: {error}") from error
    print(f"\nMode: {state['mode']}   LLM calls: {len(llm.calls)}   tokens: {llm.total_tokens:,}")
    print(f"Requirements: {len(state['requirements']['dashboards'])} dashboards")
    failed = [r for r in state["results"] if r["error"]]
    print(f"SQL: {len(state['results'])} queries, {len(failed)} failed")
    for item in state["mapped"]["unmapped"]:
        print(f"  unmapped {item['type']}: {item['name']} - {item['reason']}")
    for board in state["preview"]:
        print(f"\n== {board['name']}")
        insight = state["insights"].get(board["name"])
        if insight:
            print(f"   >> {insight['headline']}")
        for kpi in board["kpis"]:
            print(f"   {kpi['label']}: {kpi['display']}")
        for chart in board["charts"]:
            print(
                f"   [{chart['chart']}] {chart['title']} ({chart['rows']} rows){' ERROR ' + chart['error'] if chart['error'] else ''}"
            )
    for warning in state["plan"]["warnings"]:
        print(f"warning: {warning}")
    if args.approve:
        print("\n" + json.dumps(approve(state), indent=2))


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
