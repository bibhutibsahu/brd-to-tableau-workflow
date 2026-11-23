"""The 3-step, 3-agent workflow from the command line.

python -m modules.workflow run data/sample_brd.pdf           # ONE GO: Agent 1 + Agent 2 -> HTML dashboard
python -m modules.workflow template                         # write the blank BRD template (.md + .docx)
python -m modules.workflow vendor                            # cache ECharts so mockups work offline
python -m modules.workflow step1 data/sample_brd.pdf         # Agent 1: gap analysis -> brd_draft.*
python -m modules.workflow step1 data/sample_brd.pdf --accept-suggestions --finalize
python -m modules.workflow step2 outputs/<project>/step1_brd/brd_final.json      # Agent 2: spec + HTML
python -m modules.workflow step3 outputs/<project>/step2_mockup/dashboard_spec.json --platform tableau
python -m modules.workflow demo data/sample_brd.pdf          # Steps 1 + 2 end to end (for demos)

Steps 1 and 2 need GEMINI_API_KEY (env / .env). Step 3 does not use the LLM.
The one-click legacy pipeline is still available: python -m modules.pipeline <brd>.
"""

import argparse
import os
import sys
from pathlib import Path

from modules import brd_template
from modules.agents import PLATFORMS, BIPublisherAgent, BRDAnalystAgent, DashboardDesignerAgent
from modules.agents.base import read_json, write_text
from modules.llm_client import LLMClient, LLMError
from modules.pipeline import PipelineError


def run_step1(brd_path, llm, accept_suggestions=False, finalize=False, answers_file=None) -> tuple:
    agent = BRDAnalystAgent(llm)
    print(f"[{agent.name}] analysing {brd_path}")
    doc = agent.analyze(brd_path)
    _print_completeness(doc, "after gap analysis")
    if answers_file:
        doc, updated = agent.apply_customer_answers(doc, Path(answers_file).read_text(encoding="utf-8"))
        print(f"  customer answers filled {len(updated)} fields: {', '.join(updated) or '-'}")
    if accept_suggestions:
        agent.accept_suggestions(doc)
        agent.confirm_inferred(doc)
        _print_completeness(doc, "after accepting AI suggestions")
    if finalize:
        agent.finalize(doc, allow_open_items=True)
    paths = agent.save(doc)
    for kind, path in paths.items():
        print(f"  {kind:14} {path}")
    return doc, paths


def run_step2(doc, llm) -> dict:
    agent = DashboardDesignerAgent(llm)
    if doc.get("status") != "final":
        print("  note: this BRD is not finalised yet; designing from the draft")
    print(f"[{agent.name}] designing dashboards")
    state = agent.design(doc, log=lambda m: print("  " + m))
    out = agent.save(state)
    spec = out["spec"]
    charted = sum(1 for t in spec["traceability"] if t["status"] in ("charted", "kpi card"))
    print(
        f"  {len(spec['dashboards'])} dashboards, {sum(len(b['charts']) for b in spec['dashboards'])} charts, "
        f"{len(spec['kpis'])} KPIs · {charted}/{len(spec['traceability'])} BRD requirements in the mockup"
    )
    for kind, path in out["paths"].items():
        print(f"  {kind:14} {path}")
    return out


def run_brd_to_html(source, filename: str | None, llm, log=print) -> dict:
    """One go: Agent 1 + Agent 2. Customer BRD -> finalised BRD -> dashboard spec -> HTML mockup.

    Gaps are filled automatically: AI suggestions are accepted ('assumed'), inferred fields are confirmed,
    and anything still missing becomes an open question. The gap report keeps the original gaps so the
    customer can still answer them. Returns {"doc", "state", "mockup", "brd_paths", "gap_report"}.
    """
    analyst, designer = BRDAnalystAgent(llm), DashboardDesignerAgent(llm)
    log(f"1/2 {analyst.name}: mapping the customer BRD onto our format")
    doc = analyst.analyze(source, filename)
    comp = doc["completeness"]
    log(
        f"BRD completeness {comp['score'] * 100:.0f}% ({comp['required_filled']}/{comp['required_total']} required) · "
        f"{len(comp['missing'])} missing, {len(comp['to_confirm'])} inferred. Filling gaps with AI suggestions."
    )
    gap_report = brd_template.gap_report_markdown(doc)  # original gaps: questions for the customer
    analyst.accept_suggestions(doc)
    analyst.confirm_inferred(doc)
    analyst.finalize(doc, allow_open_items=True)
    brd_paths = analyst.save(doc)
    write_text(Path(brd_paths["gap_report"]), gap_report)

    log(f"2/2 {designer.name}: designing dashboards and building the HTML mockup")
    state = designer.design(doc, log=lambda m: log("    " + m))
    mockup = designer.save(state)
    return {"doc": doc, "state": state, "mockup": mockup, "brd_paths": brd_paths, "gap_report": gap_report}


def run_step3(spec, platform) -> dict:
    agent = BIPublisherAgent()
    print(f"[{agent.name}] building for {PLATFORMS[platform]['label']} ({PLATFORMS[platform]['status']})")
    result = agent.publish(spec, platform)
    for kind, path in result["files"].items():
        print(f"  {kind:14} {path}")
    return result


def _print_completeness(doc, when):
    comp = doc["completeness"]
    print(
        f"  BRD completeness {when}: {comp['score'] * 100:.0f}% "
        f"({comp['required_filled']}/{comp['required_total']} required) · "
        f"missing {len(comp['missing'])}, to confirm {len(comp['to_confirm'])}"
    )


def main():
    parser = argparse.ArgumentParser(description="BRD -> dashboard workflow (3 agents)")
    parser.add_argument("--model", default=None, help="Gemini model, default from GEMINI_MODEL")
    sub = parser.add_subparsers(dest="command", required=True)

    t = sub.add_parser("template", help="Write the blank BRD template to send to customers")
    t.add_argument("--out", default="templates", help="Output folder")

    sub.add_parser("vendor", help="Download ECharts once so HTML mockups work offline (inlined into the page)")

    s1 = sub.add_parser("step1", help="Agent 1: customer BRD -> our BRD format, with gaps")
    s1.add_argument("brd")
    s1.add_argument("--answers", help="Text file with the customer's answers to the gap questions")
    s1.add_argument("--accept-suggestions", action="store_true", help="Fill gaps with the AI suggestions")
    s1.add_argument("--finalize", action="store_true", help="Finalise the BRD (open items become open questions)")

    s2 = sub.add_parser("step2", help="Agent 2: finalised BRD -> dashboard spec + HTML mockup")
    s2.add_argument("brd_json")

    s3 = sub.add_parser("step3", help="Agent 3: dashboard spec -> BI platform build")
    s3.add_argument("spec_json")
    s3.add_argument("--platform", choices=list(PLATFORMS), default="tableau")

    for name, help_text in (
        ("run", "One go: Agent 1 + Agent 2, customer BRD -> HTML dashboard (gaps filled automatically)"),
        ("demo", "Same as run (kept for compatibility)"),
    ):
        d = sub.add_parser(name, help=help_text)
        d.add_argument("brd")
        d.add_argument("--platform", choices=list(PLATFORMS), help="Also run Step 3 for this platform")

    args = parser.parse_args()
    llm = LLMClient(model=args.model)
    try:
        if args.command == "template":
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            write_text(out / "brd_template.md", brd_template.to_markdown(blank=True))
            (out / "brd_template.docx").write_bytes(brd_template.to_docx(blank=True))
            print(f"Wrote {out / 'brd_template.md'} and {out / 'brd_template.docx'}")
        elif args.command == "vendor":
            from modules.html_mockup import download_echarts

            print(f"Saved {download_echarts()}. New mockups embed it and work offline.")
        elif args.command == "step1":
            run_step1(args.brd, llm, args.accept_suggestions, args.finalize, args.answers)
        elif args.command == "step2":
            run_step2(read_json(args.brd_json), llm)
        elif args.command == "step3":
            run_step3(read_json(args.spec_json), args.platform)
        elif args.command in ("run", "demo"):
            result = run_brd_to_html(args.brd, None, llm, log=print)
            spec, paths = result["mockup"]["spec"], result["mockup"]["paths"]
            charted = sum(1 for t in spec["traceability"] if t["status"] in ("charted", "kpi card"))
            print(
                f"\n{len(spec['dashboards'])} dashboards, {sum(len(b['charts']) for b in spec['dashboards'])} charts, "
                f"{len(spec['kpis'])} KPIs · {charted}/{len(spec['traceability'])} BRD requirements in the mockup"
            )
            print(f"Finalised BRD:  {result['brd_paths']['markdown']}")
            print(f"Gap report:     {result['brd_paths']['gap_report']}")
            print(f"Dashboard spec: {paths['spec_md']}")
            if args.platform:
                run_step3(spec, args.platform)
            print(f"\nOpen the HTML dashboard: {paths['html']}")
    except (PipelineError, LLMError, ValueError, FileNotFoundError) as error:
        raise SystemExit(f"\nERROR: {error}") from error
    if llm.calls:
        print(f"\nLLM calls: {len(llm.calls)} · tokens: {llm.total_tokens:,}")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
