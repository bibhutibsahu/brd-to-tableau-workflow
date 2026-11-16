"""BRD text -> structured requirements JSON.

The LLM reads the BRD. Without an API key, a keyword fallback finds catalog KPIs named in
the text and keeps the matching ecommerce dashboard templates.
"""

import re

import config
from modules.llm_client import LLMClient, LLMError
from modules.schema_mapper import load_dashboard_config, normalize


def extract_requirements(brd_text: str, llm: LLMClient | None = None) -> dict:
    llm = llm or LLMClient()
    if llm.available:
        prompt = (config.PROMPTS_DIR / "brd_extraction_prompt.txt").read_text(encoding="utf-8")
        try:
            raw = llm.generate_json(prompt.replace("{brd_text}", brd_text), purpose="brd_extraction")
            result = normalize_requirements(raw)
            result["extraction_method"] = f"llm:{llm.model}"
            return result
        except LLMError as error:
            result = rule_based_extraction(brd_text)
            result["assumptions"].insert(0, f"LLM extraction failed, used keyword fallback: {error}")
            return result
    return rule_based_extraction(brd_text)


def normalize_requirements(raw: dict) -> dict:
    """Fill defaults and coerce types so later steps can rely on the shape."""
    dashboards = []
    for index, board in enumerate(raw.get("dashboards") or [], start=1):
        if not isinstance(board, dict):
            continue
        kpis = []
        for kpi in board.get("kpis") or []:
            if isinstance(kpi, str):
                kpi = {"name": kpi}
            if isinstance(kpi, dict) and str(kpi.get("name", "")).strip():
                kpis.append({
                    "name": str(kpi["name"]).strip(),
                    "definition": str(kpi.get("definition") or "").strip(),
                    "priority": str(kpi.get("priority") or "medium").lower(),
                })
        visuals = []
        for visual in board.get("visuals") or []:
            if not isinstance(visual, dict) or not visual.get("metric"):
                continue
            top_n = visual.get("top_n")
            visuals.append({
                "title": str(visual.get("title") or "").strip(),
                "metric": str(visual.get("metric")).strip(),
                "dimension": str(visual.get("dimension") or "").strip(),
                "chart_hint": str(visual.get("chart_hint") or "").strip().lower(),
                "top_n": int(top_n) if isinstance(top_n, (int, float)) or str(top_n).isdigit() else None,
            })
        dashboards.append({
            "name": str(board.get("name") or f"Dashboard {index}").strip(),
            "purpose": str(board.get("purpose") or "").strip(),
            "audience": str(board.get("audience") or "").strip(),
            "kpis": kpis,
            "visuals": visuals,
        })
    if not dashboards:
        raise LLMError("No dashboards were extracted from the BRD")

    def strings(key):
        return [str(item).strip() for item in raw.get(key) or [] if str(item).strip()]

    return {
        "project_name": str(raw.get("project_name") or "BRD Dashboards").strip(),
        "business_objective": str(raw.get("business_objective") or "").strip(),
        "domain": str(raw.get("domain") or "ecommerce").strip().lower(),
        "stakeholders": strings("stakeholders"),
        "time_grain": str(raw.get("time_grain") or "month").strip().lower(),
        "global_filters": strings("global_filters"),
        "dashboards": dashboards,
        "assumptions": strings("assumptions"),
        "open_questions": strings("open_questions"),
    }


def rule_based_extraction(brd_text: str) -> dict:
    """Keyword fallback: find catalog KPIs mentioned in the BRD and keep matching templates."""
    settings = load_dashboard_config()
    text = " " + normalize(brd_text) + " "
    metric_by_id = {metric["id"]: metric for metric in settings["metrics"]}

    mentioned = set()
    for metric in settings["metrics"]:
        for phrase in [metric["label"], metric["id"].replace("_", " ")] + metric["synonyms"]:
            if f" {normalize(phrase)} " in text:
                mentioned.add(metric["id"])
                break

    dashboards = []
    for template in settings["fallback_dashboards"]:
        ids = set(template["kpis"]) | {visual["metric"] for visual in template["visuals"]}
        if mentioned & ids or normalize(template["name"]) in text:
            dashboards.append({
                "name": template["name"],
                "purpose": template["purpose"],
                "audience": "",
                "kpis": [{"name": metric_by_id[m]["label"], "definition": "", "priority": "high" if m in mentioned else "medium"}
                         for m in template["kpis"]],
                "visuals": [{"title": v["title"], "metric": metric_by_id[v["metric"]]["label"],
                             "dimension": v["dimension"], "chart_hint": "", "top_n": v.get("top_n")}
                            for v in template["visuals"]],
            })
    if not dashboards:
        template = settings["fallback_dashboards"][0]
        dashboards.append({
            "name": template["name"], "purpose": template["purpose"], "audience": "",
            "kpis": [{"name": metric_by_id[m]["label"], "definition": "", "priority": "medium"} for m in template["kpis"]],
            "visuals": [{"title": v["title"], "metric": metric_by_id[v["metric"]]["label"], "dimension": v["dimension"],
                         "chart_hint": "", "top_n": v.get("top_n")} for v in template["visuals"]],
        })

    title = next((line.strip("# ").strip() for line in brd_text.splitlines() if line.strip()), "BRD Dashboards")
    return {
        "project_name": re.sub(r"\s+", " ", title)[:80],
        "business_objective": "",
        "domain": "ecommerce",
        "stakeholders": [],
        "time_grain": "month",
        "global_filters": [],
        "dashboards": dashboards,
        "assumptions": [
            "No LLM key configured: requirements were matched by keyword against the ecommerce KPI catalog "
            f"({len(mentioned)} catalog KPIs found in the BRD). Set GEMINI_API_KEY for full extraction."
        ],
        "open_questions": [],
        "extraction_method": "rule-based",
    }
