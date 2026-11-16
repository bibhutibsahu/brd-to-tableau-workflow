"""End-to-end tests. The LLM path uses a fake client with canned replies, so no API key is needed.

    pytest -q
"""

import json
import sqlite3
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from modules import twb_builder  # noqa: E402
from modules.brd_parser import parse_brd  # noqa: E402
from modules.dashboard_generator import build_preview, generate_tableau_workbook  # noqa: E402
from modules.llm_client import LLMClient, parse_json  # noqa: E402
from modules.pipeline import run_until_preview  # noqa: E402
from modules.schema_mapper import build_semantic_layer, introspect_schema, match_dimension, match_metric  # noqa: E402
from modules.sql_generator import SQLGenerator, execute  # noqa: E402
from modules.visualization_planner import validate_plan  # noqa: E402

SAMPLE = config.DATA_DIR / "sample_brd.pdf"


class FakeLLM(LLMClient):
    """Returns canned JSON per purpose, like Gemini would."""

    def __init__(self, replies: dict):
        super().__init__(api_key="fake", model="fake-model")
        self.replies = replies

    def generate_json(self, prompt, purpose="", system=None):
        self.calls.append({"purpose": purpose})
        reply = self.replies[purpose]
        return reply(prompt) if callable(reply) else json.loads(json.dumps(reply))


@pytest.fixture(scope="module")
def schema():
    return introspect_schema()


@pytest.fixture(scope="module")
def semantic(schema):
    return build_semantic_layer(schema)


def test_brd_parser_reads_pdf_and_docx():
    pdf = parse_brd(SAMPLE)
    docx = parse_brd(config.DATA_DIR / "sample_brd.docx")
    for doc in (pdf, docx):
        assert "Average Order Value" in doc["text"]
        assert "Top 10 Products" in doc["text"]
    with pytest.raises(ValueError):
        parse_brd(b"hello", "brd.xlsx")


def test_schema_is_detected_as_star(schema):
    assert schema["fact_table"] == "fact_sales"
    assert {j["dim_table"] for j in schema["joins"]} == {
        "dim_date", "dim_customer", "dim_product", "dim_geography", "dim_channel", "dim_promotion"}


def test_fuzzy_matching(semantic):
    assert match_metric("AOV", semantic)[0] == "aov"
    assert match_metric("Total Orders", semantic)[0] == "orders"
    assert match_metric("Gross Margin %", semantic)[0] == "gross_margin_pct"
    assert match_metric("Net Promoter Score", semantic)[0] is None
    assert match_dimension("Month", semantic)[0] == "dim_date.year_month"
    assert match_dimension("Product Category", semantic)[0] == "dim_product.category"
    assert match_dimension("Sales Channel", semantic)[0] == "dim_channel.sales_channel"


def test_kpi_sql_matches_hand_written_sql(schema, semantic):
    sql, params = SQLGenerator(schema, semantic).kpi_query(["net_revenue", "orders", "aov"],
                                                          {"dim_geography.region": ["South"]})
    got = execute(sql, params)["data"].iloc[0]
    with sqlite3.connect(config.DATABASE_PATH) as conn:
        revenue, orders = conn.execute(
            "SELECT SUM(net_revenue), COUNT(DISTINCT order_id) FROM fact_sales f "
            "JOIN dim_geography g ON f.geo_key = g.geo_key WHERE g.region = 'South'").fetchone()
    assert got["net_revenue"] == pytest.approx(revenue)
    assert got["orders"] == orders
    assert got["aov"] == pytest.approx(revenue / orders)


def test_filter_values_are_parameters_not_sql(schema, semantic):
    sql, params = SQLGenerator(schema, semantic).kpi_query(["orders"], {"dim_geography.region": ["x' OR 1=1 --"]})
    assert "OR 1=1" not in sql and params == ["x' OR 1=1 --"]
    assert execute(sql, params)["data"].iloc[0]["orders"] == 0


def test_validate_plan_drops_invented_ids_and_bad_pies(semantic):
    plan = validate_plan({"title": "T", "filters": ["dim_geography.region", "made.up"], "dashboards": [{
        "name": "D", "kpis": ["net_revenue", "nps"],
        "charts": [
            {"title": "A", "chart": "pie", "metric": "gross_margin_pct", "dimension": "dim_product.category"},
            {"title": "A", "chart": "line", "metric": "net_revenue", "dimension": "dim_date.year_month"},
            {"title": "B", "chart": "bar", "metric": "clv", "dimension": "dim_product.category"}]}]}, semantic)
    board = plan["dashboards"][0]
    assert plan["filters"] == ["dim_geography.region"]
    assert board["kpis"] == ["net_revenue"]
    assert [c["chart"] for c in board["charts"]] == ["bar", "line"]
    assert len({c["title"] for c in board["charts"]}) == 2


def test_offline_pipeline_end_to_end(tmp_path):
    state = run_until_preview(SAMPLE, llm=LLMClient(api_key=""), log=lambda *_: None)
    assert state["requirements"]["extraction_method"] == "rule-based"
    assert not [r for r in state["results"] if r["error"]]
    assert len(state["plan"]["dashboards"]) == 5
    for board in state["plan"]["dashboards"]:
        assert sum(c["chart"] == "pie" for c in board["charts"]) <= 1
    _check_workbook(generate_tableau_workbook(state["plan"], state["schema"], state["semantic"], tmp_path))


def test_llm_pipeline_end_to_end(tmp_path):
    extraction = {
        "project_name": "ShopSphere Performance", "business_objective": "Track growth.", "domain": "ecommerce",
        "stakeholders": ["CXO"], "time_grain": "month", "global_filters": ["Region", "Product Category", "Loyalty Tier"],
        "dashboards": [{"name": "Executive Overview", "purpose": "Headline KPIs", "audience": "CXO",
                        "kpis": [{"name": "Net Revenue"}, {"name": "AOV"}, {"name": "NPS"}],
                        "visuals": [{"title": "Revenue Trend", "metric": "Net Revenue", "dimension": "Month"},
                                    {"title": "Top 10 Brands", "metric": "Units Sold", "dimension": "Brand", "top_n": 10},
                                    {"title": "Orders by Channel", "metric": "Orders", "dimension": "Sales Channel",
                                     "chart_hint": "pie"}]}],
        "assumptions": [], "open_questions": ["CLV pending"]}
    mapping = {"kpis": [{"key": "d0k0", "metric_id": "net_revenue", "confidence": 0.95},
                        {"key": "d0k1", "metric_id": "aov", "confidence": 0.9},
                        {"key": "d0k2", "metric_id": None, "confidence": 0}],
               "visuals": [{"key": "d0v0", "metric_id": "net_revenue", "dimension_id": "dim_date.year_month"},
                           {"key": "d0v1", "metric_id": "units_sold", "dimension_id": "dim_product.brand"},
                           {"key": "d0v2", "metric_id": "orders", "dimension_id": "dim_channel.sales_channel"}],
               "filters": [{"key": "f0", "dimension_id": "dim_geography.region"},
                           {"key": "f1", "dimension_id": "dim_product.category"},
                           {"key": "f2", "dimension_id": "invented.tier"}]}
    plan = {"title": "ShopSphere Performance", "filters": ["dim_geography.region", "dim_product.category"],
            "dashboards": [{"name": "Executive Overview", "kpis": ["net_revenue", "aov"], "charts": [
                {"title": "Revenue Trend", "chart": "line", "metric": "net_revenue", "dimension": "dim_date.year_month"},
                {"title": "Top 10 Brands", "chart": "horizontal_bar", "metric": "units_sold",
                 "dimension": "dim_product.brand", "sort": "desc", "top_n": 10},
                {"title": "Orders by Channel", "chart": "pie", "metric": "orders", "dimension": "dim_channel.sales_channel"}]}]}
    llm = FakeLLM({"brd_extraction": extraction, "schema_mapping": mapping, "visualization_planning": plan})

    state = run_until_preview(SAMPLE, llm=llm, log=lambda *_: None)
    assert [c["purpose"] for c in llm.calls] == ["brd_extraction", "schema_mapping", "visualization_planning"]
    assert state["mapped"]["filters"] == ["dim_geography.region", "dim_product.category"]
    unmapped = {u["name"] for u in state["mapped"]["unmapped"]}
    assert {"NPS", "Loyalty Tier"} <= unmapped
    top = state["preview"][0]["charts"][1]
    assert top["rows"] == 10
    result = generate_tableau_workbook(state["plan"], state["schema"], state["semantic"], tmp_path)
    _check_workbook(result)
    assert "groupfilter count='10'" in Path(result["twb_path"]).read_text()


def test_parse_json_tolerates_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Here you go: {"a": 2} thanks') == {"a": 2}


def _check_workbook(result):
    twb = Path(result["twb_path"]).read_text(encoding="utf-8")
    assert twb_builder.validate_twb(twb) == []
    root = ElementTree.fromstring(twb.encode())
    assert root.find("datasources/datasource/connection/relation").get("type") == "join"
    assert len(root.findall("dashboards/dashboard")) == len(result["dashboards"])
    with zipfile.ZipFile(result["twbx_path"]) as archive:
        names = archive.namelist()
    assert Path(result["twb_path"]).name in names and "Data/fact_sales.csv" in names
