"""Dashboard plan: which charts, which chart types, which filters.

Plan shape (the contract between preview, review and Tableau export):
{
  "title": "...",
  "filters": ["table.column", ...],
  "dashboards": [{"name", "purpose", "kpis": [metric ids],
                  "charts": [{"id", "title", "chart", "metric", "dimension", "sort", "top_n", "rationale"}]}],
  "warnings": [...], "planned_by": "llm:<model>"
}
"""

import json

import config
from modules.schema_mapper import load_dashboard_config

REVISION_PROMPT = """You edit a Tableau dashboard plan. Apply the user's instruction and return the FULL updated plan
as JSON in exactly the same shape. Use only these metric ids: {metrics}
and only these dimension ids: {dimensions}. Allowed chart types: {chart_types}.
If the instruction asks for something not available, keep the plan and explain in "warnings".

Instruction: {instruction}

Current plan:
{plan}
"""


def _rules(settings: dict) -> dict:
    return settings["chart_rules"]


def choose_chart(metric: dict, dimension: dict, hint: str = "", top_n: int | None = None) -> tuple:
    """Rule-based chart choice. Returns (chart, sort, top_n, rationale)."""
    settings = load_dashboard_config()
    rules = _rules(settings)
    allowed = settings["chart_types"]
    hint = (hint or "").lower().replace(" chart", "").replace(" ", "_")
    hint = {"column": "bar", "donut": "pie", "trend": "line", "area": "line", "hbar": "horizontal_bar"}.get(hint, hint)
    count = dimension["distinct_count"]
    ratio = metric["format"] in ("percent", "decimal") or metric["id"].startswith(("aov", "avg"))

    if hint in allowed and hint != "kpi" and not (hint == "pie" and (ratio or count > rules["share_max_categories"] * 2)):
        return hint, "none" if dimension["temporal"] else "desc", top_n, f"BRD asked for a {hint} chart."
    if dimension["temporal"]:
        return "line", "none", None, "Time dimension: a line shows the trend."
    if count > rules["horizontal_bar_min_categories"] * 3 and not top_n:
        top_n = rules["default_top_n"]
    if count >= rules["horizontal_bar_min_categories"] or top_n:
        return "horizontal_bar", "desc", top_n, f"{count} categories: a sorted horizontal bar ranks them with readable labels."
    if not ratio and count <= rules["share_max_categories"] and metric["format"] in ("currency", "number"):
        return "pie", "desc", None, f"{count} categories of an additive measure: a pie shows the share of total."
    return "bar", "desc", None, "Few categories: bars compare values side by side."


def plan_visualizations(mapped: dict, semantic: dict, title: str, results: list | None = None, llm=None) -> dict:
    """Gemini designs the dashboards from the mapped requirements and the data profile.

    The result always passes validate_plan (unknown ids dropped, chart types checked, titles unique).
    """
    if llm is None or not llm.available:
        from modules.llm_client import LLMError

        raise LLMError("A Gemini API key is required for visualization planning .")
    settings = load_dashboard_config()
    rules = _rules(settings)
    profile = [{"dashboard": r["dashboard"], "visual": r["name"], "dimension": r.get("dimension_id"),
                "rows": r["rows"], "distinct_values": next((d["distinct_count"] for d in semantic["dimensions"]
                                                            if d["id"] == r.get("dimension_id")), None)}
               for r in results or [] if r["kind"] == "visual"]
    prompt = (config.PROMPTS_DIR / "visualization_prompt.txt").read_text(encoding="utf-8").format(
        metrics=", ".join(f"{m['id']} ({m['label']}, {m['format']})" for m in semantic["metrics"]),
        dimensions=", ".join(f"{d['id']} ({d['label']}, {d['distinct_count']} values{', time' if d['temporal'] else ''})"
                             for d in semantic["dimensions"]),
        chart_types=", ".join(c for c in settings["chart_types"] if c != "kpi"),
        share_max=rules["share_max_categories"], hbar_min=rules["horizontal_bar_min_categories"],
        requirements=json.dumps(_compact(mapped), indent=1), profile=json.dumps(profile, indent=1),
    )
    plan = llm.generate_json(prompt, purpose="visualization_planning")
    plan.setdefault("title", title)
    plan["planned_by"] = f"llm:{llm.model}"
    checked = validate_plan(plan, semantic)
    if not checked["dashboards"]:
        from modules.llm_client import LLMError

        raise LLMError("Gemini's dashboard plan used no valid metrics or dimensions: " + "; ".join(checked["warnings"][:5]))
    return checked


def _compact(mapped: dict) -> list:
    return [{"name": b["name"], "purpose": b.get("purpose", ""),
             "kpis": [k["metric_id"] for k in b["kpis"] if k["metric_id"]],
             "visuals": [{"title": v["title"], "metric": v["metric_id"], "dimension": v["dimension_id"],
                          "chart_hint": v.get("chart_hint", ""), "top_n": v.get("top_n")}
                         for v in b["visuals"] if v["metric_id"] and v["dimension_id"]]}
            for b in mapped["dashboards"]]


def validate_plan(plan: dict, semantic: dict) -> dict:
    """Drop unknown ids, fix chart types, make titles unique. Never raises on LLM output."""
    settings = load_dashboard_config()
    metrics = {m["id"]: m for m in semantic["metrics"]}
    dims = {d["id"]: d for d in semantic["dimensions"]}
    allowed = [c for c in settings["chart_types"] if c != "kpi"]
    warnings = list(plan.get("warnings") or [])
    clean = {"title": str(plan.get("title") or "BRD Dashboards").strip()[:100], "filters": [], "dashboards": [],
             "planned_by": plan.get("planned_by", "rules"), "warnings": warnings}

    for dim_id in plan.get("filters") or []:
        if dim_id in dims and dim_id not in clean["filters"] and len(clean["filters"]) < 4:
            clean["filters"].append(dim_id)
        elif dim_id not in dims:
            warnings.append(f"Filter {dim_id} removed: not a dimension in the schema.")

    titles, names, counter = set(), set(), 1
    for board in plan.get("dashboards") or []:
        name = str(board.get("name") or "Dashboard").strip()[:60]
        while name in names:
            name += " (2)"
        names.add(name)
        kpis = []
        for metric_id in board.get("kpis") or []:
            if metric_id in metrics and metric_id not in kpis:
                kpis.append(metric_id)
            elif metric_id not in metrics:
                warnings.append(f"{name}: KPI {metric_id} removed (unknown metric).")
        charts = []
        for chart in board.get("charts") or []:
            metric_id, dim_id = chart.get("metric"), chart.get("dimension")
            if metric_id not in metrics or dim_id not in dims:
                warnings.append(f"{name}: chart '{chart.get('title')}' removed (unknown metric or dimension).")
                continue
            kind = chart.get("chart") if chart.get("chart") in allowed else None
            metric, dim = metrics[metric_id], dims[dim_id]
            if kind is None:
                kind, *_ = choose_chart(metric, dim)
            if kind == "pie" and (metric["format"] in ("percent", "decimal") or dim["distinct_count"] > 12):
                warnings.append(f"{name}: '{chart.get('title')}' changed from pie to bar (pie needs a few parts of a sum).")
                kind = "bar" if dim["distinct_count"] <= 8 else "horizontal_bar"
            if dim["temporal"] and kind in ("pie",):
                kind = "line"
            if kind == "pie" and any(c["chart"] == "pie" for c in charts):
                kind = "bar" if dim["distinct_count"] <= 8 else "horizontal_bar"  # one pie per dashboard
            top_n = chart.get("top_n")
            top_n = int(top_n) if isinstance(top_n, (int, float)) and top_n > 0 else None
            sort = chart.get("sort") if chart.get("sort") in ("asc", "desc", "none") else ("none" if dim["temporal"] else "desc")
            title = str(chart.get("title") or f"{metric['label']} by {dim['label']}").strip()[:80]
            base, n = title, 2
            while title in titles or title in names:  # Tableau sheet names must be unique
                title, n = f"{base} ({n})", n + 1
            titles.add(title)
            charts.append({"id": f"c{counter}", "title": title, "chart": kind, "metric": metric_id, "dimension": dim_id,
                           "sort": sort, "top_n": top_n, "rationale": str(chart.get("rationale") or "")})
            counter += 1
        if kpis or charts:
            clean["dashboards"].append({"name": name, "purpose": str(board.get("purpose") or ""),
                                        "kpis": kpis[:6], "charts": charts[:6]})
    return clean


def revise_plan(plan: dict, instruction: str, semantic: dict, llm=None) -> dict:
    """Apply a natural-language change request ("make revenue by region a pie", "add a returns dashboard")."""
    if llm is None or not llm.available:
        from modules.llm_client import LLMError

        raise LLMError("Plain-English edits need a Gemini API key.")
    settings = load_dashboard_config()
    prompt = REVISION_PROMPT.format(
        metrics=", ".join(m["id"] for m in semantic["metrics"]),
        dimensions=", ".join(d["id"] for d in semantic["dimensions"]),
        chart_types=", ".join(c for c in settings["chart_types"] if c != "kpi"),
        instruction=instruction,
        plan=json.dumps({k: v for k, v in plan.items() if k != "warnings"}, indent=1),
    )
    revised = llm.generate_json(prompt, purpose="plan_revision")
    revised["planned_by"] = plan.get("planned_by", "rules") + " + revision"
    revised["warnings"] = []
    return validate_plan(revised, semantic)
