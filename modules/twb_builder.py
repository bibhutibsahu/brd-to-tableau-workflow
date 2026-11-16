"""Tableau workbook XML (.twb) for an approved plan over a star schema.

Data source: one textscan connection over Data/*.csv, the fact table LEFT JOINed to each
dimension on its key. Every plan metric becomes a calculated field whose formula comes from
the KPI catalog, so Tableau numbers match the SQL preview.
"""

from xml.etree import ElementTree

DS = "federated.0"
FORMATS = {"percent": "p0.0%", "decimal": "n#,##0.00", "number": "n#,##0"}


def esc(value) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))


def br(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


class WorkbookModel:
    """Field names, datatypes and calculated fields for the joined data source."""

    def __init__(self, schema: dict, semantic: dict, currency: str = "₹"):
        self.schema, self.semantic = schema, semantic
        self.fact = schema["fact_table"]
        self.tables = [self.fact] + [j["dim_table"] for j in schema["joins"]]
        self.currency = currency
        self.fields = {}  # (table, column) -> field name
        used = set()
        for table in self.tables:
            for col in schema["tables"][table]["columns"]:
                name = col["name"]
                if name in used:
                    name = f"{col['name']} ({table}.csv)"
                used.add(name)
                self.fields[(table, col["name"])] = name
        self.keys = {(self.fact, j["fact_column"]) for j in schema["joins"]} | \
                    {(j["dim_table"], j["dim_column"]) for j in schema["joins"]}
        self.metrics = {m["id"]: m for m in semantic["metrics"]}
        self.dims = {d["id"]: d for d in semantic["dimensions"]}
        self.labels = {d["id"]: d["label"] for d in semantic["dimensions"]}

    def column_type(self, table: str, column: str) -> str:
        return next(c["type"] for c in self.schema["tables"][table]["columns"] if c["name"] == column)

    def dim_field(self, dim_id: str) -> str:
        dim = self.dims[dim_id]
        return self.fields[(dim["table"], dim["column"])]

    def column_xml(self, table: str, column: str) -> str:
        name = self.fields[(table, column)]
        kind = self.column_type(table, column)
        datatype = kind
        measure = table == self.fact and kind in ("integer", "real") and (table, column) not in self.keys
        role, semantic = ("measure", "quantitative") if measure else ("dimension", "nominal" if kind == "string" else "ordinal")
        caption = self.labels.get(f"{table}.{column}", column.replace("_", " ").title())
        hidden = " hidden='true'" if (table, column) in self.keys else ""
        return (f"<column caption='{esc(caption)}' datatype='{datatype}' name='{esc(br(name))}' "
                f"role='{role}' type='{semantic}'{hidden} />")

    # calculated metric fields
    def calc_name(self, metric_id: str) -> str:
        return f"Calculation_{metric_id}"

    def calc_xml(self, metric_id: str) -> str:
        metric = self.metrics[metric_id]
        fmt = FORMATS.get(metric["format"])
        if metric["format"] == "currency":
            fmt = f'c"{self.currency}"#,##0;-"{self.currency}"#,##0'
        return (f"<column caption='{esc(metric['label'])}' datatype='real' default-format='{esc(fmt)}' "
                f"name='{esc(br(self.calc_name(metric_id)))}' role='measure' type='quantitative'>"
                f"<calculation class='tableau' formula='{esc(metric['tableau'])}' /></column>")

    def metric_columns(self, metric_id: str) -> list:
        return [(self.fact, col) for col in self.metrics[metric_id]["columns"]]

    def measure_instance(self, metric_id: str) -> str:
        return f"[usr:{self.calc_name(metric_id)}:qk]"

    def dim_instance(self, dim_id: str) -> str:
        return f"[none:{self.dim_field(dim_id).replace(']', ']]')}:nk]"


# ------------------------------------------------------------------ data source

def datasource_xml(model: WorkbookModel, caption: str, metric_ids: list) -> str:
    def table_relation(table):
        cols = "\n".join(
            f"              <column datatype='{c['type']}' name='{esc(c['name'])}' ordinal='{i}' />"
            for i, c in enumerate(model.schema["tables"][table]["columns"]))
        return (f"<relation connection='textscan.0' name='{esc(table)}.csv' table='{esc('[' + table + '#csv]')}' type='table'>\n"
                f"            <columns character-set='UTF-8' header='yes' outcome='6' separator=','>\n{cols}\n"
                f"            </columns>\n          </relation>")

    relation = table_relation(model.fact)
    for join in model.schema["joins"]:
        left = f"[{model.fact}.csv].{br(join['fact_column'])}"
        right = f"[{join['dim_table']}.csv].{br(join['dim_column'])}"
        relation = (f"<relation join='left' type='join'>\n"
                    f"          <clause type='join'><expression op='='><expression op='{esc(left)}' />"
                    f"<expression op='{esc(right)}' /></expression></clause>\n"
                    f"          {relation}\n          {table_relation(join['dim_table'])}\n        </relation>")

    maps = "\n".join(f"          <map key='{esc(br(field))}' value='{esc(f'[{table}.csv].' + br(column))}' />"
                     for (table, column), field in sorted(model.fields.items(), key=lambda kv: kv[1]))
    columns = "\n".join("    " + model.column_xml(t, c) for (t, c) in model.fields)
    calcs = "\n".join("    " + model.calc_xml(m) for m in metric_ids)
    return f"""  <datasources>
    <datasource caption='{esc(caption)}' inline='true' name='{DS}' version='18.1'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='Data' name='textscan.0'>
            <connection class='textscan' directory='Data' filename='{esc(model.fact)}.csv' password='' server='' />
          </named-connection>
        </named-connections>
        {relation}
        <cols>
{maps}
        </cols>
      </connection>
{columns}
{calcs}
    </datasource>
  </datasources>"""


def _dependencies(model: WorkbookModel, metric_ids: list, dim_ids: list, indent: str) -> str:
    base = []
    for metric_id in metric_ids:
        base += [pair for pair in model.metric_columns(metric_id) if pair not in base]
    for dim_id in dim_ids:
        dim = model.dims[dim_id]
        if (dim["table"], dim["column"]) not in base:
            base.append((dim["table"], dim["column"]))
    lines = [f"{indent}<datasource-dependencies datasource='{DS}'>"]
    lines += [indent + "  " + model.column_xml(t, c) for t, c in base]
    lines += [indent + "  " + model.calc_xml(m) for m in metric_ids]
    lines += [f"{indent}  <column-instance column='{esc(br(model.dim_field(d)))}' derivation='None' "
              f"name='{esc(model.dim_instance(d))}' pivot='key' type='nominal' />" for d in dim_ids]
    lines += [f"{indent}  <column-instance column='{esc(br(model.calc_name(m)))}' derivation='User' "
              f"name='{esc(model.measure_instance(m))}' pivot='key' type='quantitative' />" for m in metric_ids]
    lines.append(f"{indent}</datasource-dependencies>")
    return "\n".join(lines)


# ------------------------------------------------------------------ worksheets

def worksheet_xml(model: WorkbookModel, caption: str, sheet: dict, filters: list) -> str:
    """sheet: {name, chart, metric, dimension, sort, top_n, label}"""
    metric_id, dim_id, chart = sheet["metric"], sheet.get("dimension"), sheet["chart"]
    measure = f"[{DS}].{model.measure_instance(metric_id)}"
    dimension = f"[{DS}].{model.dim_instance(dim_id)}" if dim_id else ""
    dim_ids = list(dict.fromkeys(([dim_id] if dim_id else []) + filters))
    deps = _dependencies(model, [metric_id], dim_ids, "          ")

    encodings, label, rows, cols, mark = "", "", "", "", "Bar"
    style = "<format attr='mark-labels-show' value='true' /><format attr='mark-labels-cull' value='true' />"
    if chart == "kpi":
        mark = "Text"
        encodings = f"<encodings><text column='{esc(measure)}' /></encodings>"
        label = ("<customized-label><formatted-text>"
                 f"<run fontcolor='#6b7280' fontsize='11'>{esc(sheet['label'])}</run><run>Æ&#10;</run>"
                 f"<run bold='true' fontsize='22'>&lt;{esc(measure)}&gt;</run></formatted-text></customized-label>")
        style = "<format attr='text-align' value='center' />"
    elif chart == "pie":
        mark = "Pie"
        encodings = (f"<encodings><color column='{esc(dimension)}' /><wedge-size column='{esc(measure)}' />"
                     f"<text column='{esc(dimension)}' /><text column='{esc(measure)}' /></encodings>")
        style += "<format attr='size' value='2' />"
    elif chart == "horizontal_bar":
        rows, cols = dimension, measure
    elif chart == "table":
        mark, rows = "Text", dimension
        encodings = f"<encodings><text column='{esc(measure)}' /></encodings>"
    elif chart == "line":
        mark, rows, cols = "Line", measure, dimension
        style = "<format attr='mark-labels-show' value='false' />"
    else:
        rows, cols = measure, dimension

    view_extra = ""
    if dim_id and sheet.get("top_n"):
        level = model.dim_instance(dim_id)
        view_extra += (f"\n          <filter class='categorical' column='{esc(dimension)}'>"
                       f"<groupfilter count='{int(sheet['top_n'])}' end='top' function='end' units='records' "
                       f"user:ui-marker='end' user:ui-top-by-field='true'>"
                       f"<groupfilter direction='DESC' expression='{esc(model.metrics[metric_id]['tableau'])}' "
                       f"function='order' user:ui-marker='order'>"
                       f"<groupfilter function='level-members' level='{esc(level)}' user:ui-enumeration='all' "
                       f"user:ui-marker='enumerate' /></groupfilter></groupfilter></filter>")
    if dim_id and chart != "kpi" and sheet.get("sort") in ("asc", "desc"):
        direction = "ASC" if sheet["sort"] == "asc" else "DESC"
        view_extra += f"\n          <computed-sort column='{esc(dimension)}' direction='{direction}' using='{esc(measure)}' />"
    if dim_id and sheet.get("top_n"):
        view_extra += f"\n          <slices><column>{esc(dimension)}</column></slices>"

    rows_xml = f"<rows>{esc(rows)}</rows>" if rows else "<rows />"
    cols_xml = f"<cols>{esc(cols)}</cols>" if cols else "<cols />"
    return f"""    <worksheet name='{esc(sheet["name"])}'>
      <table>
        <view>
          <datasources>
            <datasource caption='{esc(caption)}' name='{DS}' />
          </datasources>
{deps}{view_extra}
          <aggregation value='true' />
        </view>
        <style />
        <panes>
          <pane>
            <view><breakdown value='auto' /></view>
            <mark class='{mark}' />
            {encodings}
            {label}
            <style><style-rule element='mark'>{style}</style-rule></style>
          </pane>
        </panes>
        {rows_xml}
        {cols_xml}
      </table>
    </worksheet>"""


def shared_filters_xml(model: WorkbookModel, caption: str, filters: list) -> str:
    """Filters on the data source, so they apply to every sheet (Tableau: 'All using this data source')."""
    if not filters:
        return ""
    deps = _dependencies(model, [], filters, "      ")
    body = "\n".join(
        f"      <filter class='categorical' column='[{DS}].{esc(model.dim_instance(d))}'>\n"
        f"        <groupfilter function='level-members' level='{esc(model.dim_instance(d))}' "
        "user:ui-enumeration='all' user:ui-marker='enumerate' />\n      </filter>" for d in filters)
    slices = "\n".join(f"        <column>[{DS}].{esc(model.dim_instance(d))}</column>" for d in filters)
    return f"""  <shared-views>
    <shared-view name='{DS}'>
      <datasources>
        <datasource caption='{esc(caption)}' name='{DS}' />
      </datasources>
{deps}
{body}
      <slices>
{slices}
      </slices>
      <aggregation value='true' />
    </shared-view>
  </shared-views>
"""


# ------------------------------------------------------------------ dashboards

def dashboard_xml(model: WorkbookModel, board: dict, kpi_sheets: list, chart_sheets: list,
                  filters: list, zone_start: int) -> tuple:
    """Title row, KPI row, two-column chart grid, filter column on the right. Units: 1/100000."""
    full, side = 100000, (16000 if filters else 0)
    body = full - side
    title_h, kpi_h = 6000, 11000 if kpi_sheets else 0
    top = title_h + kpi_h
    rows = max(1, (len(chart_sheets) + 1) // 2)
    chart_h = (full - top) // rows
    zid = zone_start
    zones = [f"        <zone h='{title_h}' id='{zid}' type-v2='text' w='{full}' x='0' y='0'>"
             f"<formatted-text><run bold='true' fontsize='20'>{esc(board['name'])}</run>"
             f"<run fontcolor='#6b7280' fontsize='11'>{esc('   ' + board.get('purpose', ''))}</run></formatted-text></zone>"]
    for i, name in enumerate(kpi_sheets):
        zid += 1
        width = body // len(kpi_sheets)
        zones.append(f"        <zone h='{kpi_h}' id='{zid}' name='{esc(name)}' show-title='false' "
                     f"w='{width}' x='{i * width}' y='{title_h}' />")
    for i, name in enumerate(chart_sheets):
        zid += 1
        last_odd = len(chart_sheets) % 2 == 1 and i == len(chart_sheets) - 1
        width = body if (len(chart_sheets) == 1 or last_odd) else body // 2
        x = 0 if last_odd else (i % 2) * (body // 2)
        zones.append(f"        <zone h='{chart_h}' id='{zid}' name='{esc(name)}' w='{width}' x='{x}' "
                     f"y='{top + (i // 2) * chart_h}' />")
    owner = (chart_sheets or kpi_sheets)[0]
    for i, dim_id in enumerate(filters):
        zid += 1
        zones.append(f"        <zone h='9000' id='{zid}' mode='checkdropdown' name='{esc(owner)}' "
                     f"param='[{DS}].{esc(model.dim_instance(dim_id))}' type-v2='filter' values='database' "
                     f"w='{side}' x='{body}' y='{title_h + i * 9000}' />")
    xml = f"""    <dashboard name='{esc(board['name'])}'>
      <style />
      <size maxheight='1000' maxwidth='1400' minheight='1000' minwidth='1400' sizing-mode='fixed' />
      <zones>
        <zone h='100000' id='{zone_start - 1}' type-v2='layout-basic' w='100000' x='0' y='0'>
{chr(10).join(zones)}
        </zone>
      </zones>
    </dashboard>"""
    return xml, zid + 2


def build_twb(plan: dict, schema: dict, semantic: dict, currency: str = "₹") -> tuple:
    """Return (twb_xml, sheet_index). sheet_index lists every worksheet and dashboard written."""
    model = WorkbookModel(schema, semantic, currency)
    caption = plan["title"]
    filters = [f for f in plan.get("filters", []) if f in model.dims]
    dashboard_names = {b["name"] for b in plan["dashboards"]}

    sheets, order = {}, []  # name -> sheet spec

    def add(sheet):
        name = sheet["name"]
        while name in dashboard_names or (name in sheets and sheets[name] != {**sheet, "name": name}):
            name += " *"
        sheet["name"] = name
        if name not in sheets:
            sheets[name] = sheet
            order.append(name)
        return name

    layout = []
    for board in plan["dashboards"]:
        kpi_names = [add({"name": f"KPI - {model.metrics[m]['label']}", "chart": "kpi", "metric": m,
                          "dimension": None, "label": model.metrics[m]["label"]}) for m in board["kpis"]]
        chart_names = [add({"name": c["title"], "chart": c["chart"], "metric": c["metric"], "dimension": c["dimension"],
                            "sort": c.get("sort"), "top_n": c.get("top_n"), "label": c["title"]}) for c in board["charts"]]
        layout.append((board, kpi_names, chart_names))

    metric_ids = list(dict.fromkeys(sheets[n]["metric"] for n in order))
    worksheets = "\n".join(worksheet_xml(model, caption, sheets[n], filters) for n in order)
    dashboards, zone_id = [], 2
    for board, kpis, charts in layout:
        xml, zone_id = dashboard_xml(model, board, kpis, charts, filters, zone_id + 1)
        dashboards.append(xml)

    sheet_windows = "\n".join(
        f"    <window class='worksheet' hidden='true' maximized='true' name='{esc(n)}'>"
        "<cards><edge name='left'><strip size='160'><card type='pages' /><card type='filters' />"
        "<card type='marks' /></strip></edge></cards></window>" for n in order)
    board_windows = "\n".join(
        f"    <window class='dashboard'{' maximized=' + chr(39) + 'true' + chr(39) if i == 0 else ''} name='{esc(b['name'])}'>"
        f"<viewpoints>{''.join(f'<viewpoint name={chr(39)}{esc(n)}{chr(39)} />' for n in k + c)}</viewpoints>"
        "<active id='-1' /></window>" for i, (b, k, c) in enumerate(layout))

    twb = f"""<?xml version='1.0' encoding='utf-8' ?>
<workbook source-build='2024.2.0' source-platform='mac' version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>
  <preferences />
{datasource_xml(model, caption, metric_ids)}
{shared_filters_xml(model, caption, filters)}  <worksheets>
{worksheets}
  </worksheets>
  <dashboards>
{chr(10).join(dashboards)}
  </dashboards>
  <windows source-height='30'>
{sheet_windows}
{board_windows}
  </windows>
</workbook>
"""
    index = {"worksheets": [{"name": n, "chart": sheets[n]["chart"]} for n in order],
             "dashboards": [b["name"] for b, _, _ in layout]}
    return twb, index


def validate_twb(twb: str) -> list:
    """Structural checks: well-formed XML, zones point at real sheets, every used instance is declared."""
    problems = []
    try:
        root = ElementTree.fromstring(twb.encode("utf-8"))
    except ElementTree.ParseError as error:
        return [f"XML is not well-formed: {error}"]
    sheets = {w.get("name") for w in root.iter("worksheet")}
    for zone in root.iter("zone"):
        name = zone.get("name")
        if name and name not in sheets:
            problems.append(f"Dashboard zone references missing sheet: {name}")
    for sheet in root.iter("worksheet"):
        declared = {f"[{DS}].{ci.get('name')}" for ci in sheet.iter("column-instance")}
        used = [el.text for el in sheet.iter() if el.tag in ("rows", "cols") and el.text]
        used += [el.get("column") for el in sheet.iter() if el.tag in ("text", "color", "wedge-size")]
        for ref in used:
            if ref and ref not in declared:
                problems.append(f"Sheet '{sheet.get('name')}' uses undeclared field {ref}")
    return problems
