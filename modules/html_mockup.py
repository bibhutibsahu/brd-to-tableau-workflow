"""Single-file HTML dashboard mockup (Step 2 deliverable).

The page is templates/mockup_template.html with the dashboard spec and the computed numbers embedded
as JSON. Charts are drawn in the browser with Apache ECharts: from cdnjs, or inlined from
templates/vendor/ when a local copy exists (offline demos). The numbers are the same SQL results the
Streamlit preview shows, so the mockup, the preview and the later Tableau / Power BI build agree.
"""

import json
import math

import config
from modules.dashboard_generator import format_value

TEMPLATE_PATH = config.TEMPLATES_DIR / "mockup_template.html"
ECHARTS_VERSION = "5.6.0"
ECHARTS_URL = f"https://cdnjs.cloudflare.com/ajax/libs/echarts/{ECHARTS_VERSION}/echarts.min.js"
# Optional local copy for offline demos: python -m modules.workflow vendor. When present it is inlined.
ECHARTS_LOCAL = config.TEMPLATES_DIR / "vendor" / f"echarts-{ECHARTS_VERSION}.min.js"


def download_echarts() -> str:
    """Cache ECharts locally so mockups work without internet. Returns the path."""
    import urllib.request

    ECHARTS_LOCAL.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(ECHARTS_URL, timeout=60) as response:
        ECHARTS_LOCAL.write_bytes(response.read())
    return str(ECHARTS_LOCAL)


def _number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) or math.isinf(value) else value


def mockup_payload(spec: dict, preview: list, insights: dict, semantic: dict) -> dict:
    """Everything the page needs: spec metadata + rows for each chart (dimension value, metric value)."""
    metrics = {m["id"]: m for m in semantic["metrics"]}
    dims = {d["id"]: d for d in semantic["dimensions"]}
    spec_charts = {c["id"]: c for board in spec["dashboards"] for c in board["charts"]}
    boards = []
    for board in preview:
        kpis = [
            {
                "metric": k["metric"],
                "label": k["label"],
                "display": k["display"],
                "value": _number(k["value"]),
                "error": k["error"],
            }
            for k in board["kpis"]
        ]
        charts = []
        for chart in board["charts"]:
            metric, dim = metrics[chart["metric"]], dims[chart["dimension"]]
            rows = []
            if not chart["error"]:
                for _, row in chart["data"].iterrows():
                    value = _number(row[chart["metric"]])
                    rows.append([str(row[dim["column"]]), value, format_value(value, metric["format"])])
            charts.append(
                {
                    "id": chart["id"],
                    "title": chart["title"],
                    "type": chart["chart"],
                    "metric": metric["label"],
                    "dimension": dim["label"],
                    "format": metric["format"],
                    "temporal": dim["temporal"],
                    "rationale": chart.get("rationale", ""),
                    "brd_refs": spec_charts.get(chart["id"], {}).get("brd_refs", []),
                    "error": chart["error"],
                    "rows": rows,
                }
            )
        boards.append(
            {
                "name": board["name"],
                "purpose": board["purpose"],
                "insight": insights.get(board["name"]),
                "kpis": kpis,
                "charts": charts,
            }
        )
    return {
        "project": spec["project"],
        "generated_at": spec["generated_at"],
        "generated_by": spec["generated_by"],
        "filters_applied": spec.get("filters_applied") or {},
        "currency": spec["formatting"]["currency_symbol"],
        "kpi_catalog": spec["kpis"],
        "traceability": spec["traceability"],
        "tech_stack": spec["tech_stack"],
        "dashboards": boards,
    }


def render_mockup(spec: dict, preview: list, insights: dict, semantic: dict) -> str:
    payload = mockup_payload(spec, preview, insights, semantic)
    data = json.dumps(payload, ensure_ascii=False, default=str).replace("</", "<\\/")  # safe inside <script>
    page = TEMPLATE_PATH.read_text(encoding="utf-8")
    title = spec["project"]["name"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if ECHARTS_LOCAL.exists():
        library = "<script>" + ECHARTS_LOCAL.read_text(encoding="utf-8").replace("</script", "<\\/script") + "</script>"
    else:
        library = f'<script src="{ECHARTS_URL}"></script>'
    page = page.replace('<script src="__ECHARTS_URL__"></script>', "__ECHARTS_TAG__")
    return page.replace("__TITLE__", title).replace("/*__DATA__*/null", data).replace("__ECHARTS_TAG__", library)
