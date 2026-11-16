"""Runs the BRD -> Tableau steps in order. Used by app.py and from the command line:

    python -m modules.pipeline data/sample_brd.pdf            # plan + preview, no TWB
    python -m modules.pipeline data/sample_brd.pdf --approve  # also writes the Tableau workbook
"""

import argparse
import json

from modules.brd_parser import parse_brd
from modules.dashboard_generator import build_preview, generate_tableau_workbook
from modules.llm_client import LLMClient
from modules.requirement_extractor import extract_requirements
from modules.schema_mapper import build_semantic_layer, introspect_schema, map_requirements
from modules.sql_generator import SQLGenerator, execute_queries, generate_queries
from modules.visualization_planner import plan_visualizations


def run_until_preview(source, filename: str | None = None, llm: LLMClient | None = None, log=print) -> dict:
    llm = llm or LLMClient()
    state = {"llm_mode": f"llm:{llm.model}" if llm.available else "rule-based (no GEMINI_API_KEY)"}

    log("1/7 Parsing BRD")
    state["brd"] = parse_brd(source, filename)
    log("2/7 Extracting requirements")
    state["requirements"] = extract_requirements(state["brd"]["text"], llm)
    log("3/7 Mapping database schema")
    state["schema"] = introspect_schema()
    state["semantic"] = build_semantic_layer(state["schema"])
    state["mapped"] = map_requirements(state["requirements"], state["semantic"], llm)
    log("4/7 Generating SQL and KPI logic")
    generator = SQLGenerator(state["schema"], state["semantic"])
    state["queries"] = generate_queries(state["mapped"], generator)
    used = sorted({m for q in state["queries"] for m in q["metric_ids"]})
    state["kpi_logic"] = generator.kpi_logic(used)
    log("5/7 Executing SQL")
    state["results"] = execute_queries(state["queries"])
    log("6/7 Planning visualizations")
    state["plan"] = plan_visualizations(state["mapped"], state["semantic"], state["requirements"]["project_name"],
                                        state["results"], llm)
    log("7/7 Building dashboard preview")
    state["preview"] = build_preview(state["plan"], state["schema"], state["semantic"])
    return state


def approve(state: dict) -> dict:
    return generate_tableau_workbook(state["plan"], state["schema"], state["semantic"])


def main():
    parser = argparse.ArgumentParser(description="BRD -> Tableau dashboard pipeline")
    parser.add_argument("brd", help="Path to the BRD (.pdf, .docx, .txt, .md)")
    parser.add_argument("--approve", action="store_true", help="Write the Tableau workbook after planning")
    args = parser.parse_args()

    state = run_until_preview(args.brd)
    print(f"\nMode: {state['llm_mode']}")
    print(f"Requirements: {len(state['requirements']['dashboards'])} dashboards "
          f"({state['requirements'].get('extraction_method')})")
    failed = [r for r in state["results"] if r["error"]]
    print(f"SQL: {len(state['results'])} queries, {len(failed)} failed")
    for item in state["mapped"]["unmapped"]:
        print(f"  unmapped {item['type']}: {item['name']} - {item['reason']}")
    for board in state["preview"]:
        print(f"\n== {board['name']}")
        for kpi in board["kpis"]:
            print(f"   {kpi['label']}: {kpi['display']}")
        for chart in board["charts"]:
            print(f"   [{chart['chart']}] {chart['title']} ({chart['rows']} rows){' ERROR ' + chart['error'] if chart['error'] else ''}")
    for warning in state["plan"]["warnings"]:
        print(f"warning: {warning}")
    if args.approve:
        print("\n" + json.dumps(approve(state), indent=2))


if __name__ == "__main__":
    main()
