"""BRD text -> structured requirements JSON, extracted by Gemini."""

import config
from modules.llm_client import LLMClient, LLMError


def extract_requirements(brd_text: str, llm: LLMClient | None = None) -> dict:
    """Gemini reads the BRD and returns the normalized requirements JSON."""
    llm = llm or LLMClient()
    if not llm.available:
        raise LLMError("A Gemini API key is required to extract requirements.")
    prompt = (config.PROMPTS_DIR / "brd_extraction_prompt.txt").read_text(encoding="utf-8")
    raw = llm.generate_json(prompt.replace("{brd_text}", brd_text), purpose="brd_extraction")
    result = normalize_requirements(raw)
    result["extraction_method"] = f"llm:{llm.model}"
    return result


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
