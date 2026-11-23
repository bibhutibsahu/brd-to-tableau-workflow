"""Our standard BRD format (templates/brd_template.json) and the filled-in BRD document built on it.

A BRD document is the contract between Step 1 (BRD Analyst) and Step 2 (Dashboard Designer):
{
  "template_version": "1.0",
  "source": "customer file name",
  "status": "draft | final",
  "fields": {field_id: {"value", "status", "source", "note", "question", "suggestion"}},
  "completeness": {...},
  "finalized_at": "ISO time or null"
}
status per field: provided | inferred | missing | assumed | confirmed (see the template's "statuses").
"""

import io
import json
from datetime import datetime
from functools import lru_cache

import config

TEMPLATE_PATH = config.TEMPLATES_DIR / "brd_template.json"
STATUSES = ("provided", "inferred", "missing", "assumed", "confirmed")
FILLED = ("provided", "inferred", "assumed", "confirmed")  # a value is present
SETTLED = ("provided", "assumed", "confirmed")  # no further confirmation needed
STATUS_ICONS = {"provided": "✅", "inferred": "🟡", "missing": "❌", "assumed": "🟠", "confirmed": "✍️"}


@lru_cache(maxsize=1)
def load_template() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def fields() -> list:
    """Every template field, with its section id and title attached."""
    return [
        {**field, "section": section["id"], "section_title": section["title"]}
        for section in load_template()["sections"]
        for field in section["fields"]
    ]


def field_map() -> dict:
    return {f["id"]: f for f in fields()}


def empty_value(field: dict):
    return "" if field["type"] == "text" else []


def coerce_value(field: dict, value):
    """Force a value into the field's type: text -> str, list -> [str], table -> [{column: str}]."""
    if field["type"] == "text":
        if isinstance(value, list):
            value = "; ".join(str(v) for v in value if str(v).strip())
        return "" if value is None else str(value).strip()
    if field["type"] == "list":
        if isinstance(value, str):
            value = [line.strip(" -•\t") for line in value.splitlines()]
        return [str(v).strip() for v in value or [] if str(v).strip()]
    columns = [c["id"] for c in field["columns"]]
    rows = []
    for row in value or []:
        if isinstance(row, str):
            row = {columns[0]: row}
        if not isinstance(row, dict):
            continue
        clean = {c: "" if row.get(c) is None else str(row.get(c)).strip() for c in columns}
        if any(clean.values()):
            rows.append(clean)
    return rows


def is_empty(value) -> bool:
    return not value


def new_document(source: str = "") -> dict:
    doc = {
        "template_version": load_template()["template_version"],
        "source": source,
        "status": "draft",
        "fields": {
            f["id"]: {
                "value": empty_value(f),
                "status": "missing",
                "source": "",
                "note": "",
                "question": "",
                "suggestion": empty_value(f),
            }
            for f in fields()
        },
        "finalized_at": None,
    }
    doc["completeness"] = completeness(doc)
    return doc


def normalize_document(raw: dict, source: str = "") -> dict:
    """Turn the agent's JSON into a valid BRD document. Never raises on LLM output."""
    doc = new_document(source)
    reply = (raw or {}).get("fields") or {}
    for field in fields():
        item = reply.get(field["id"])
        if not isinstance(item, dict):
            item = {"value": item} if item else {}
        value = coerce_value(field, item.get("value"))
        status = str(item.get("status") or "").lower()
        if status not in ("provided", "inferred"):
            status = "provided" if value else "missing"
        if is_empty(value):
            status = "missing"
        doc["fields"][field["id"]] = {
            "value": value,
            "status": status,
            "source": str(item.get("source") or "").strip(),
            "note": str(item.get("note") or "").strip(),
            "question": str(item.get("question") or "").strip()
            or (f"Please provide: {field['label']}. {field['guidance']}" if status == "missing" else ""),
            "suggestion": coerce_value(field, item.get("suggestion")),
        }
    doc["completeness"] = completeness(doc)
    return doc


def load_document(data: dict) -> dict:
    """A saved BRD document (brd_draft.json / brd_final.json), checked against the current template."""
    if not isinstance(data, dict) or not isinstance(data.get("fields"), dict):
        raise ValueError("Not a BRD document: expected a JSON object with a 'fields' object (brd_draft/final.json).")
    doc = new_document(str(data.get("source") or ""))
    for key in ("status", "finalized_at", "agent_summary", "analysed_by", "customer_brd"):
        if key in data:
            doc[key] = data[key]
    for field in fields():
        saved = data["fields"].get(field["id"])
        if not isinstance(saved, dict):
            continue
        entry = doc["fields"][field["id"]]
        entry.update({k: str(saved.get(k) or "") for k in ("source", "note", "question")})
        entry["value"] = coerce_value(field, saved.get("value"))
        entry["suggestion"] = coerce_value(field, saved.get("suggestion"))
        status = saved.get("status")
        entry["status"] = status if status in STATUSES and not is_empty(entry["value"]) else "missing"
    doc["status"] = "final" if doc.get("status") == "final" else "draft"
    doc["completeness"] = completeness(doc)
    return doc


def set_field(doc: dict, field_id: str, value, status: str = "confirmed", note: str | None = None) -> dict:
    field = field_map()[field_id]
    entry = doc["fields"][field_id]
    entry["value"] = coerce_value(field, value)
    entry["status"] = status if not is_empty(entry["value"]) else "missing"
    if note is not None:
        entry["note"] = note
    doc["completeness"] = completeness(doc)
    return doc


def completeness(doc: dict) -> dict:
    """Score over required fields, and the lists the UI and gap report need."""
    required = [f for f in fields() if f["required"]]
    entries = doc["fields"]
    filled = [f["id"] for f in required if entries[f["id"]]["status"] in FILLED]
    missing = [f["id"] for f in fields() if entries[f["id"]]["status"] == "missing"]
    missing_required = [f["id"] for f in required if entries[f["id"]]["status"] == "missing"]
    to_confirm = [f["id"] for f in fields() if entries[f["id"]]["status"] == "inferred"]
    counts = {s: sum(1 for e in entries.values() if e["status"] == s) for s in STATUSES}
    return {
        "score": round(len(filled) / len(required), 3) if required else 1.0,
        "required_total": len(required),
        "required_filled": len(filled),
        "missing": missing,
        "missing_required": missing_required,
        "to_confirm": to_confirm,
        "counts": counts,
        "ready": not missing_required,
    }


def consistency_issues(doc: dict) -> list:
    """Cross-field checks: dashboards, KPIs and visuals must reference each other."""
    values = {k: v["value"] for k, v in doc["fields"].items()}
    boards = {row["name"].strip().lower() for row in values["dashboards"] if row.get("name")}
    kpi_names = {row["name"].strip().lower() for row in values["kpis"] if row.get("name")}
    issues = []
    for row in values["visuals"]:
        if row.get("dashboard", "").strip().lower() not in boards:
            issues.append(
                f"Visual '{row.get('ref') or row.get('title')}' points to unknown dashboard '{row.get('dashboard')}'."
            )
        if not row.get("metric"):
            issues.append(f"Visual '{row.get('ref') or row.get('title')}' has no measure.")
    for row in values["dashboards"]:
        names = [n.strip() for n in row.get("kpis", "").split(",") if n.strip()]
        undefined = [n for n in names if n.lower() not in kpi_names]
        if undefined:
            issues.append(f"Dashboard '{row['name']}' uses KPIs not defined in section 7: {', '.join(undefined)}.")
        if not any(v.get("dashboard", "").strip().lower() == row["name"].strip().lower() for v in values["visuals"]):
            issues.append(f"Dashboard '{row['name']}' has no visual requirements.")
    return issues


def finalize(doc: dict, allow_open_items: bool = False) -> dict:
    """Mark the BRD final. Remaining gaps become open questions (only if allow_open_items)."""
    doc["completeness"] = completeness(doc)
    if doc["completeness"]["missing_required"] and not allow_open_items:
        labels = [field_map()[f]["label"] for f in doc["completeness"]["missing_required"]]
        raise ValueError("Required BRD fields are still missing: " + ", ".join(labels))
    open_items = list(doc["fields"]["open_questions"]["value"])
    for field_id in doc["completeness"]["missing"]:
        question = doc["fields"][field_id]["question"] or f"Provide {field_map()[field_id]['label']}"
        if question not in open_items and field_id != "open_questions":
            open_items.append(question)
    if open_items:
        doc["fields"]["open_questions"]["value"] = open_items
        if doc["fields"]["open_questions"]["status"] == "missing":
            doc["fields"]["open_questions"]["status"] = "confirmed"
    doc["status"] = "final"
    doc["finalized_at"] = datetime.now().isoformat(timespec="seconds")
    doc["completeness"] = completeness(doc)
    return doc


# ---------------------------------------------------------------- Step 2 hand-off


def to_requirements(doc: dict) -> dict:
    """Finalised BRD -> the requirements shape the dashboard designer uses (normalize_requirements input)."""
    from modules.requirement_extractor import normalize_requirements

    v = {k: e["value"] for k, e in doc["fields"].items()}
    kpi_rows = {row["name"].strip().lower(): row for row in v["kpis"] if row.get("name")}
    dashboards = []
    for board in v["dashboards"]:
        names = [n.strip() for n in board.get("kpis", "").split(",") if n.strip()]
        kpis = [
            {
                "name": name,
                "definition": kpi_rows.get(name.lower(), {}).get("definition", ""),
                "priority": kpi_rows.get(name.lower(), {}).get("priority", "") or "medium",
            }
            for name in names
        ]
        visuals = [
            {
                "ref": row.get("ref", ""),
                "title": row.get("title", ""),
                "metric": row.get("metric", ""),
                "dimension": row.get("dimension", ""),
                "chart_hint": row.get("chart_hint", ""),
                "top_n": row.get("top_n", "").strip() or None,
            }
            for row in v["visuals"]
            if row.get("dashboard", "").strip().lower() == board.get("name", "").strip().lower()
        ]
        dashboards.append(
            {
                "name": board.get("name"),
                "purpose": board.get("purpose"),
                "audience": board.get("audience"),
                "kpis": kpis,
                "visuals": visuals,
            }
        )
    assumptions = list(v["assumptions"]) + [
        f"{field_map()[k]['label']}: {_inline(e['value'])} (assumed)"
        for k, e in doc["fields"].items()
        if e["status"] == "assumed"
    ]
    requirements = normalize_requirements(
        {
            "project_name": v["project_name"],
            "business_objective": v["business_objective"],
            "domain": v["industry_domain"] or "ecommerce",
            "stakeholders": [row.get("role") for row in v["stakeholders"] if row.get("role")],
            "time_grain": v["time_grain"] or "month",
            "global_filters": v["global_filters"],
            "dashboards": dashboards,
            "assumptions": assumptions,
            "open_questions": v["open_questions"],
        }
    )
    requirements["extraction_method"] = "finalised BRD (Step 1)"
    return requirements


# ---------------------------------------------------------------- rendering


def _inline(value) -> str:
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            return f"{len(value)} rows"
        return "; ".join(value)
    return str(value)


def _md_cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _md_value(field: dict, value) -> list:
    if is_empty(value):
        return ["_Not provided._"]
    if field["type"] == "text":
        return [str(value)]
    if field["type"] == "list":
        return [f"- {item}" for item in value]
    columns = field["columns"]
    lines = [
        "| " + " | ".join(c["label"] for c in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    lines += ["| " + " | ".join(_md_cell(row.get(c["id"], "")) for c in columns) + " |" for row in value]
    return lines


def to_markdown(doc: dict | None = None, blank: bool = False) -> str:
    """The BRD as Markdown. blank=True renders the empty template with guidance (to send to a customer)."""
    template = load_template()
    lines = []
    if blank or doc is None:
        lines += [
            f"# {template['template_name']}",
            "",
            f"Template version {template['template_version']}. Fill in every section; fields marked "
            "**(required)** are needed before dashboard design can start.",
            "",
        ]
    else:
        values = doc["fields"]
        comp = doc["completeness"]
        lines += [
            f"# {values['project_name']['value'] or 'Untitled project'} - Business Requirements Document",
            "",
            f"Status: **{doc['status']}**"
            + (f" (finalised {doc['finalized_at']})" if doc.get("finalized_at") else "")
            + f" · Source: {doc.get('source') or '-'} · Template v{doc['template_version']}",
            "",
            f"Completeness: **{comp['score'] * 100:.0f}%** of required fields "
            f"({comp['required_filled']}/{comp['required_total']}).",
            "",
            "Legend: " + " · ".join(f"{STATUS_ICONS[s]} {s}" for s in STATUSES),
            "",
        ]
    for section in template["sections"]:
        lines += [f"## {section['title']}", ""]
        for field in section["fields"]:
            required = " (required)" if field["required"] else ""
            if blank or doc is None:
                lines += [f"### {field['label']}{required}", "", f"_{field['guidance']}_", ""]
                if field["type"] == "table":
                    cols = field["columns"]
                    lines += [
                        "| " + " | ".join(c["label"] for c in cols) + " |",
                        "| " + " | ".join("---" for _ in cols) + " |",
                        "| " + " | ".join(" " for _ in cols) + " |",
                    ]
                elif field["type"] == "list":
                    lines += ["-"]  # no trailing space: the trailing-whitespace hook would strip it
                else:
                    lines += [""]
                lines += [""]
                continue
            entry = doc["fields"][field["id"]]
            lines += [f"### {field['label']}{required} {STATUS_ICONS[entry['status']]} _{entry['status']}_", ""]
            lines += _md_value(field, entry["value"])
            notes = []
            if entry.get("source"):
                notes.append(f"Source: {entry['source']}")
            if entry.get("note"):
                notes.append(f"Note: {entry['note']}")
            if entry["status"] in ("missing", "inferred") and entry.get("question"):
                notes.append(f"Question for customer: {entry['question']}")
            if notes:
                lines += [""] + [f"> {n}" for n in notes]
            lines += [""]
    return "\n".join(lines).rstrip() + "\n"


def gap_report_markdown(doc: dict) -> str:
    """Questionnaire to send back to the customer: missing and to-be-confirmed items."""
    comp = doc["completeness"]
    fm = field_map()
    project = doc["fields"]["project_name"]["value"] or "the project"
    lines = [
        f"# BRD gap report - {project}",
        "",
        f"Source BRD: {doc.get('source') or '-'} · Completeness {comp['score'] * 100:.0f}% "
        f"({comp['required_filled']}/{comp['required_total']} required fields)",
        "",
    ]
    groups = (
        ("Missing - required", [f for f in comp["missing"] if fm[f]["required"]]),
        ("Missing - optional", [f for f in comp["missing"] if not fm[f]["required"]]),
        ("Inferred by AI - please confirm", comp["to_confirm"]),
    )
    number = 1
    for title, ids in groups:
        if not ids:
            continue
        lines += [f"## {title}", ""]
        for field_id in ids:
            entry = doc["fields"][field_id]
            lines.append(
                f"{number}. **{fm[field_id]['label']}** ({fm[field_id]['section_title']}): {entry['question']}"
            )
            proposal = entry["value"] if entry["status"] == "inferred" else entry.get("suggestion")
            if not is_empty(proposal):
                lines.append(f"   - Proposed: {_inline(proposal) if fm[field_id]['type'] != 'text' else proposal}")
            number += 1
        lines.append("")
    issues = consistency_issues(doc)
    if issues:
        lines += ["## Consistency checks", ""] + [f"- {i}" for i in issues] + [""]
    if number == 1 and not issues:
        lines += ["No gaps: every field is filled.", ""]
    return "\n".join(lines)


def to_docx(doc: dict | None = None, blank: bool = False) -> bytes:
    """The BRD (or the blank template) as a Word document."""
    from docx import Document
    from docx.shared import Pt

    template = load_template()
    word = Document()
    word.styles["Normal"].font.size = Pt(10)
    if blank or doc is None:
        word.add_heading(template["template_name"], 0)
        word.add_paragraph(
            f"Template version {template['template_version']}. Fields marked (required) are needed before "
            "dashboard design can start."
        )
    else:
        comp = doc["completeness"]
        word.add_heading(f"{doc['fields']['project_name']['value'] or 'Untitled project'} - BRD", 0)
        word.add_paragraph(
            f"Status: {doc['status']} · Source: {doc.get('source') or '-'} · "
            f"Completeness {comp['score'] * 100:.0f}% ({comp['required_filled']}/{comp['required_total']})"
        )
    for section in template["sections"]:
        word.add_heading(section["title"], 1)
        for field in section["fields"]:
            entry = None if (blank or doc is None) else doc["fields"][field["id"]]
            heading = field["label"] + (" (required)" if field["required"] else "")
            if entry:
                heading += f"  [{entry['status']}]"
            word.add_heading(heading, 2)
            value = entry["value"] if entry else empty_value(field)
            if entry is None:
                word.add_paragraph(field["guidance"]).runs[0].italic = True
            if field["type"] == "table":
                rows = value or [{}]
                table = word.add_table(rows=1, cols=len(field["columns"]))
                table.style = "Light Grid Accent 1"
                for cell, col in zip(table.rows[0].cells, field["columns"], strict=True):
                    cell.text = col["label"]
                for row in rows:
                    cells = table.add_row().cells
                    for cell, col in zip(cells, field["columns"], strict=True):
                        cell.text = row.get(col["id"], "")
            elif field["type"] == "list":
                for item in value or [""]:
                    word.add_paragraph(item, style="List Bullet")
            else:
                word.add_paragraph(value or "")
            if entry and entry["status"] in ("missing", "inferred") and entry.get("question"):
                word.add_paragraph(f"Question for customer: {entry['question']}").runs[0].italic = True
    buffer = io.BytesIO()
    word.save(buffer)
    return buffer.getvalue()
