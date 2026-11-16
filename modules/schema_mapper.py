"""Star-schema introspection and requirement -> schema mapping.

introspect_schema   reads tables, columns, keys and row counts from the SQLite database
build_semantic_layer turns the schema + KPI catalog into metric ids and dimension ids
map_requirements    maps the BRD's business names to those ids (LLM, checked by fuzzy match)
"""

import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

import config

MAPPING_PROMPT = """You map business requirements from a BRD to a star-schema semantic layer.

Metrics (id: label - description - synonyms):
{metrics}

Dimensions (id: label):
{dimensions}

Requirements:
{requirements}

For every item in "requirements", choose the best metric id / dimension id from the lists above.
Use null when nothing fits; never invent ids. Return ONLY JSON:
{{"kpis": [{{"key": "<key>", "metric_id": "id or null", "confidence": 0.0-1.0}}],
  "visuals": [{{"key": "<key>", "metric_id": "id or null", "dimension_id": "id or null", "confidence": 0.0-1.0}}],
  "filters": [{{"key": "<key>", "dimension_id": "id or null"}}]}}
"""


# ---------------------------------------------------------------- configuration

@lru_cache(maxsize=1)
def _load_config(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_dashboard_config() -> dict:
    return _load_config(str(config.DASHBOARD_CONFIG_PATH))


def normalize(text: str) -> str:
    text = str(text).lower().replace("%", " pct ").replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


# ---------------------------------------------------------------- schema

def connect(db_path=None) -> sqlite3.Connection:
    path = Path(db_path or config.DATABASE_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}. Run: python scripts/generate_ecommerce_db.py")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def introspect_schema(db_path=None) -> dict:
    """Return tables, columns, keys, the fact table and its joins to each dimension."""
    settings = load_dashboard_config()
    tables = {}
    with connect(db_path) as conn:
        names = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for name in names:
            columns = [{"name": col[1], "type": _sql_type(col[2]), "pk": bool(col[5])}
                       for col in conn.execute(f'PRAGMA table_info("{name}")')]
            fks = [{"column": fk[3], "ref_table": fk[2], "ref_column": fk[4]}
                   for fk in conn.execute(f'PRAGMA foreign_key_list("{name}")')]
            rows = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            tables[name] = {"name": name, "columns": columns, "foreign_keys": fks, "row_count": rows}

    fact = _pick_fact(tables, settings.get("fact_table"))
    joins = _joins(tables, fact)
    for name, table in tables.items():
        table["role"] = "fact" if name == fact else "dimension" if any(j["dim_table"] == name for j in joins) else "unused"
    return {"database": str(db_path or config.DATABASE_PATH), "fact_table": fact, "joins": joins, "tables": tables}


def _sql_type(declared: str) -> str:
    declared = (declared or "").upper()
    if "INT" in declared:
        return "integer"
    if any(word in declared for word in ("REAL", "FLOA", "DOUB", "NUM", "DEC")):
        return "real"
    return "string"


def _pick_fact(tables: dict, preferred: str | None) -> str:
    if preferred in tables:
        return preferred
    scored = sorted(tables.values(), key=lambda t: (len(t["foreign_keys"]), t["name"].startswith("fact"), t["row_count"]),
                    reverse=True)
    if not scored:
        raise ValueError("The database has no tables")
    return scored[0]["name"]


def _joins(tables: dict, fact: str) -> list:
    """Declared foreign keys first; otherwise a fact column with the same name as a table's primary key."""
    joins, seen = [], set()
    for fk in tables[fact]["foreign_keys"]:
        if fk["ref_table"] in tables and fk["ref_table"] not in seen:
            joins.append({"dim_table": fk["ref_table"], "fact_column": fk["column"], "dim_column": fk["ref_column"]})
            seen.add(fk["ref_table"])
    fact_columns = {col["name"] for col in tables[fact]["columns"]}
    for name, table in tables.items():
        if name == fact or name in seen:
            continue
        keys = [col["name"] for col in table["columns"] if col["pk"]]
        if len(keys) == 1 and keys[0] in fact_columns:
            joins.append({"dim_table": name, "fact_column": keys[0], "dim_column": keys[0]})
            seen.add(name)
    return joins


# ---------------------------------------------------------------- semantic layer

def build_semantic_layer(schema: dict, db_path=None) -> dict:
    """Metrics whose columns exist in the fact table, and every usable dimension column."""
    settings = load_dashboard_config()
    fact = schema["fact_table"]
    fact_columns = {col["name"] for col in schema["tables"][fact]["columns"]}

    metrics, missing = [], []
    for metric in settings["metrics"]:
        absent = [col for col in metric["columns"] if col not in fact_columns]
        (missing.append({"id": metric["id"], "missing_columns": absent}) if absent else metrics.append(metric))

    labels = settings["dimension_labels"]
    excluded = set(settings["excluded_dimensions"])
    temporal = set(settings["temporal_dimensions"])
    key_columns = {j["fact_column"] for j in schema["joins"]} | {j["dim_column"] for j in schema["joins"]}

    candidates = []
    for join in schema["joins"]:
        table = schema["tables"][join["dim_table"]]
        candidates += [(table["name"], col) for col in table["columns"] if not col["pk"]]
    candidates += [(fact, col) for col in schema["tables"][fact]["columns"]
                   if col["type"] == "string" and not col["pk"]]

    dimensions = []
    with connect(db_path or schema["database"]) as conn:
        for table, col in candidates:
            name = col["name"]
            if name in excluded or name in key_columns or name.endswith(("_id", "_key")):
                continue
            distinct = conn.execute(f'SELECT COUNT(DISTINCT "{name}") FROM "{table}"').fetchone()[0]
            if distinct < 2:
                continue
            dimensions.append({
                "id": f"{table}.{name}", "table": table, "column": name,
                "label": labels.get(name, name.replace("_", " ").title()),
                "temporal": name in temporal, "distinct_count": distinct,
            })
    return {"fact_table": fact, "metrics": metrics, "unavailable_metrics": missing, "dimensions": dimensions}


# ---------------------------------------------------------------- matching

def _tokens(text: str) -> set:
    stop = {"by", "of", "the", "and", "per", "total", "count", "number", "rate", "a", "in", "for", "wise"}
    words = set(normalize(text).split())
    return (words - stop) or words


def _score(query: str, phrases: list) -> float:
    q = normalize(query)
    if not q:
        return 0.0
    best = 0.0
    for phrase in phrases:
        p = normalize(phrase)
        if not p:
            continue
        if q == p:
            return 1.0
        if f" {p} " in f" {q} " or f" {q} " in f" {p} ":
            shorter, longer = sorted((len(p.split()), len(q.split())))
            best = max(best, 0.5 + 0.4 * shorter / longer)
        a, b = _tokens(q), _tokens(p)
        if a and b:
            best = max(best, 0.8 * len(a & b) / len(a | b))
    return best


def match_metric(name: str, semantic: dict, threshold: float = 0.45):
    ids = {m["id"] for m in semantic["metrics"]}
    if name in ids:
        return name, 1.0
    scored = [(_score(name, [m["label"], m["id"].replace("_", " ")] + m["synonyms"]), m["id"]) for m in semantic["metrics"]]
    score, metric_id = max(scored, default=(0.0, None))
    return (metric_id, round(score, 2)) if score >= threshold else (None, round(score, 2))


def match_dimension(name: str, semantic: dict, threshold: float = 0.45):
    if not name:
        return None, 0.0
    by_id = {d["id"]: d for d in semantic["dimensions"]}
    if name in by_id:
        return name, 1.0
    scored = []
    for dim in semantic["dimensions"]:
        table = dim["table"].replace("dim_", "").replace("fact_", "").replace("_", " ")
        phrases = [dim["label"], dim["column"].replace("_", " "), f"{table} {dim['column'].replace('_', ' ')}"]
        bonus = 0.05 if dim["temporal"] and normalize(name) in ("month", "monthly", "trend", "time", "date") else 0.0
        scored.append((_score(name, phrases) + bonus, dim["id"]))
    if normalize(name) in ("month", "monthly", "trend", "time", "date", "over time", "monthly trend"):
        scored.append((0.99, next((d["id"] for d in semantic["dimensions"] if d["column"] == "year_month"), None)))
    score, dim_id = max(((s, i) for s, i in scored if i), default=(0.0, None))
    return (dim_id, round(min(score, 1.0), 2)) if score >= threshold else (None, round(score, 2))


# ---------------------------------------------------------------- requirement mapping

def map_requirements(requirements: dict, semantic: dict, llm=None) -> dict:
    """Return dashboards whose KPIs and visuals carry metric_id / dimension_id, plus an unmapped list."""
    llm_map, method = {}, "fuzzy"
    if llm is not None and llm.available:
        try:
            llm_map = _llm_mapping(requirements, semantic, llm)
            method = f"llm:{llm.model}"
        except Exception as error:  # fall back to fuzzy matching for every item
            method = f"fuzzy (LLM mapping failed: {error})"

    metric_ids = {m["id"] for m in semantic["metrics"]}
    dim_ids = {d["id"] for d in semantic["dimensions"]}
    unmapped, dashboards = [], []
    for b, board in enumerate(requirements["dashboards"]):
        kpis = []
        for k, kpi in enumerate(board["kpis"]):
            key = f"d{b}k{k}"
            metric_id, confidence = llm_map.get(key, (None, 0.0))[:2]
            source = "llm"
            if metric_id not in metric_ids:
                metric_id, confidence = match_metric(kpi["name"] + " " + kpi.get("definition", ""), semantic)
                if metric_id is None:
                    metric_id, confidence = match_metric(kpi["name"], semantic)
                source = "fuzzy"
            kpis.append({**kpi, "metric_id": metric_id, "confidence": confidence, "matched_by": source})
            if metric_id is None:
                unmapped.append({"dashboard": board["name"], "type": "kpi", "name": kpi["name"],
                                 "reason": "No catalog KPI or database column matches this requirement."})

        visuals = []
        for v, visual in enumerate(board["visuals"]):
            key = f"d{b}v{v}"
            metric_id, dimension_id, confidence = llm_map.get(key, (None, None, 0.0))
            source = "llm"
            if metric_id not in metric_ids:
                metric_id, confidence = match_metric(visual["metric"], semantic)
                source = "fuzzy"
            if dimension_id not in dim_ids:
                dimension_id, dim_conf = match_dimension(visual["dimension"], semantic)
                confidence = min(confidence, dim_conf) if dimension_id else confidence
                source = "fuzzy"
            entry = {**visual, "metric_id": metric_id, "dimension_id": dimension_id,
                     "confidence": confidence, "matched_by": source}
            visuals.append(entry)
            if metric_id is None or dimension_id is None:
                missing = "metric" if metric_id is None else "dimension"
                unmapped.append({"dashboard": board["name"], "type": "visual", "name": visual["title"] or visual["metric"],
                                 "reason": f"No matching {missing} for '{visual['metric'] if metric_id is None else visual['dimension']}'."})
        dashboards.append({**board, "kpis": kpis, "visuals": visuals})

    filters = []
    for f, name in enumerate(requirements.get("global_filters") or []):
        dim_id = llm_map.get(f"f{f}", (None,))[0]
        if dim_id not in dim_ids:
            dim_id, _ = match_dimension(name, semantic)
        if dim_id and dim_id not in filters:
            filters.append(dim_id)
        elif not dim_id:
            unmapped.append({"dashboard": "(global)", "type": "filter", "name": name, "reason": "No matching dimension."})

    return {"method": method, "dashboards": dashboards, "filters": filters, "unmapped": unmapped}


def _llm_mapping(requirements: dict, semantic: dict, llm) -> dict:
    metrics = "\n".join(f"- {m['id']}: {m['label']} - {m['description']} - {', '.join(m['synonyms'])}"
                        for m in semantic["metrics"])
    dimensions = "\n".join(f"- {d['id']}: {d['label']}" for d in semantic["dimensions"])
    items = {"kpis": [], "visuals": [], "filters": []}
    for b, board in enumerate(requirements["dashboards"]):
        items["kpis"] += [{"key": f"d{b}k{k}", "name": kpi["name"], "definition": kpi.get("definition", "")}
                          for k, kpi in enumerate(board["kpis"])]
        items["visuals"] += [{"key": f"d{b}v{v}", "metric": vis["metric"], "dimension": vis["dimension"], "title": vis["title"]}
                             for v, vis in enumerate(board["visuals"])]
    items["filters"] = [{"key": f"f{i}", "name": name} for i, name in enumerate(requirements.get("global_filters") or [])]

    reply = llm.generate_json(
        MAPPING_PROMPT.format(metrics=metrics, dimensions=dimensions, requirements=json.dumps(items, indent=1)),
        purpose="schema_mapping",
    )
    result = {}
    for item in reply.get("kpis") or []:
        result[str(item.get("key"))] = (item.get("metric_id"), float(item.get("confidence") or 0.7))
    for item in reply.get("visuals") or []:
        result[str(item.get("key"))] = (item.get("metric_id"), item.get("dimension_id"), float(item.get("confidence") or 0.7))
    for index, item in enumerate(reply.get("filters") or []):
        key = str(item.get("key") or f"f{index}")
        result[key] = (item.get("dimension_id"),)
    return result
