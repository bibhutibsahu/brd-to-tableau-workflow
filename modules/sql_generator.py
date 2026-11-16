"""SQL and KPI logic for every requirement, built from validated ids only.

The LLM never writes SQL. Metric expressions come from templates/dashboard_config.json,
dimension columns from the introspected schema, and filter values are bound parameters.
"""

import time

import pandas as pd

import config
from modules.schema_mapper import connect, load_dashboard_config


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class SQLGenerator:
    def __init__(self, schema: dict, semantic: dict):
        self.schema = schema
        self.semantic = semantic
        self.fact = schema["fact_table"]
        self.alias = load_dashboard_config().get("fact_alias", "f")
        self.metrics = {m["id"]: m for m in semantic["metrics"]}
        self.dimensions = {d["id"]: d for d in semantic["dimensions"]}
        self.joins = {j["dim_table"]: j for j in schema["joins"]}

    # ------------------------------------------------------------ building blocks

    def _column_sql(self, dimension_id: str) -> str:
        dim = self.dimensions[dimension_id]
        table = self.alias if dim["table"] == self.fact else _quote(dim["table"])
        return f"{table}.{_quote(dim['column'])}"

    def _from_sql(self, dimension_ids: list) -> str:
        sql = f"FROM {_quote(self.fact)} AS {self.alias}"
        added = set()
        for dimension_id in dimension_ids:
            table = self.dimensions[dimension_id]["table"]
            if table == self.fact or table in added:
                continue
            join = self.joins[table]
            sql += (f"\nLEFT JOIN {_quote(table)} ON {self.alias}.{_quote(join['fact_column'])}"
                    f" = {_quote(table)}.{_quote(join['dim_column'])}")
            added.add(table)
        return sql

    def _where_sql(self, filters: dict | None) -> tuple:
        clauses, params = [], []
        for dimension_id, values in (filters or {}).items():
            if dimension_id not in self.dimensions or not values:
                continue
            clauses.append(f"{self._column_sql(dimension_id)} IN ({', '.join('?' * len(values))})")
            params += list(values)
        return ("\nWHERE " + "\n  AND ".join(clauses)) if clauses else "", params

    def _check(self, metric_ids: list, dimension_id: str | None):
        for metric_id in metric_ids:
            if metric_id not in self.metrics:
                raise KeyError(f"Unknown metric id: {metric_id}")
        if dimension_id is not None and dimension_id not in self.dimensions:
            raise KeyError(f"Unknown dimension id: {dimension_id}")

    # ------------------------------------------------------------ queries

    def kpi_query(self, metric_ids: list, filters: dict | None = None) -> tuple:
        """One row with a column per metric."""
        self._check(metric_ids, None)
        select = ",\n  ".join(f"{self.metrics[m]['sql']} AS {_quote(m)}" for m in metric_ids)
        where, params = self._where_sql(filters)
        return f"SELECT\n  {select}\n{self._from_sql(list(filters or {}))}{where}", params

    def chart_query(self, metric_id: str, dimension_id: str, filters: dict | None = None,
                    sort: str = "desc", top_n: int | None = None) -> tuple:
        """Metric grouped by one dimension."""
        self._check([metric_id], dimension_id)
        dim = self.dimensions[dimension_id]
        column = self._column_sql(dimension_id)
        where, params = self._where_sql(filters)
        if dim["temporal"] or sort == "none":
            order = f"{column} ASC"
        else:
            order = f"{_quote(metric_id)} {'ASC' if sort == 'asc' else 'DESC'}"
        limit = int(top_n) if top_n else config.PREVIEW_ROW_LIMIT
        sql = (f"SELECT\n  {column} AS {_quote(dim['column'])},\n  {self.metrics[metric_id]['sql']} AS {_quote(metric_id)}\n"
               f"{self._from_sql([dimension_id] + list(filters or {}))}{where}\n"
               f"GROUP BY {column}\nORDER BY {order}\nLIMIT {limit}")
        return sql, params

    def kpi_logic(self, metric_ids: list | None = None) -> list:
        """Business definition, SQL and Tableau formula for each metric (shown in the UI and docs)."""
        ids = metric_ids or list(self.metrics)
        return [{"id": m, "label": self.metrics[m]["label"], "definition": self.metrics[m]["description"],
                 "sql": self.metrics[m]["sql"], "tableau_formula": self.metrics[m]["tableau"],
                 "format": self.metrics[m]["format"]} for m in ids if m in self.metrics]


def execute(sql: str, params: list | None = None, db_path=None) -> dict:
    """Run a read-only query. Returns {"data", "rows", "ms", "error"}."""
    started = time.perf_counter()
    try:
        with connect(db_path) as conn:
            frame = pd.read_sql_query(sql, conn, params=params or [])
        return {"data": frame, "rows": len(frame), "ms": round((time.perf_counter() - started) * 1000, 1), "error": None}
    except Exception as error:
        return {"data": pd.DataFrame(), "rows": 0, "ms": round((time.perf_counter() - started) * 1000, 1), "error": str(error)}


def generate_queries(mapped: dict, generator: SQLGenerator) -> list:
    """SQL for every mapped KPI set and visual, before execution."""
    queries = []
    for board in mapped["dashboards"]:
        metric_ids = list(dict.fromkeys(k["metric_id"] for k in board["kpis"] if k["metric_id"]))
        if metric_ids:
            sql, params = generator.kpi_query(metric_ids)
            queries.append({"dashboard": board["name"], "kind": "kpis", "name": "KPI cards",
                            "metric_ids": metric_ids, "sql": sql, "params": params})
        for visual in board["visuals"]:
            if visual["metric_id"] and visual["dimension_id"]:
                sql, params = generator.chart_query(visual["metric_id"], visual["dimension_id"], top_n=visual.get("top_n"))
                queries.append({"dashboard": board["name"], "kind": "visual", "name": visual["title"] or visual["metric"],
                                "metric_ids": [visual["metric_id"]], "dimension_id": visual["dimension_id"],
                                "sql": sql, "params": params})
    return queries


def execute_queries(queries: list, db_path=None) -> list:
    results = []
    for query in queries:
        outcome = execute(query["sql"], query["params"], db_path)
        results.append({**query, **outcome})
    return results
