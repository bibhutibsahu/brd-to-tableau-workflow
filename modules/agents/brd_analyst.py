"""Step 1 - BRD Analyst agent.

Maps the customer's BRD onto our standard BRD format (templates/brd_template.json), flags every
missing or inferred field with a question for the customer and a suggested default, applies the
customer's answers, and finalises the BRD that Step 2 designs from.
"""

import json

import config
from modules import brd_template
from modules.agents.base import Agent, step_dir, write_json, write_text
from modules.brd_parser import parse_brd

ANSWERS_PROMPT = """You are Agent 1, a BI business analyst. The customer has answered questions about gaps in
their BRD. Update our BRD fields with the information in the answers ONLY.

Field definitions (id, label, type; table fields list their column ids):
{template}

Current values of the fields that are missing or need confirmation:
{current}

Customer answers / notes:
\"\"\"
{answers}
\"\"\"

Return ONLY JSON: {{"fields": {{"<field id>": {{"value": <value in the field's type>, "note": "what the customer said"}}}}}}
Include only fields the answers actually address. For table fields return the FULL table (existing rows plus
changes). Do not include fields the answers do not mention."""


def _template_for_prompt(field_ids: list | None = None) -> str:
    lines = []
    for field in brd_template.fields():
        if field_ids is not None and field["id"] not in field_ids:
            continue
        line = (
            f"- {field['id']}: {field['label']} ({field['type']}"
            f"{', required' if field['required'] else ''}) - {field['guidance']}"
        )
        if field["type"] == "table":
            line += " Columns: " + ", ".join(c["id"] for c in field["columns"])
        lines.append(line)
    return "\n".join(lines)


class BRDAnalystAgent(Agent):
    step = 1
    name = "Agent 1 · BRD Analyst"
    role = "Maps the customer BRD onto our standard format, finds the gaps and finalises the BRD."
    inputs = "Customer BRD (PDF / DOCX / TXT / MD)"
    outputs = "brd_final.json, brd_final.md, brd_final.docx, gap_report.md"

    # ------------------------------------------------------------ analyse

    def analyze(self, source, filename: str | None = None) -> dict:
        """Customer BRD -> draft BRD document in our format, with gaps flagged."""
        llm = self.require_llm()
        brd = parse_brd(source, filename)
        prompt = (
            (config.PROMPTS_DIR / "brd_gap_prompt.txt")
            .read_text(encoding="utf-8")
            .format(template=_template_for_prompt(), brd_text=brd["text"])
        )
        raw = llm.generate_json(prompt, purpose="step1_brd_gap_analysis")
        doc = brd_template.normalize_document(raw, brd["source"])
        doc["agent_summary"] = str(raw.get("summary") or "").strip()
        doc["analysed_by"] = f"llm:{llm.model}"
        doc["customer_brd"] = {k: brd[k] for k in ("source", "pages", "char_count", "truncated")}
        doc["customer_brd_text"] = brd["text"]
        return doc

    # ------------------------------------------------------------ fill gaps

    @staticmethod
    def accept_suggestions(doc: dict, field_ids: list | None = None) -> dict:
        """Use the AI suggestion for missing fields; they are marked 'assumed' in the final BRD."""
        for field_id in field_ids or list(doc["fields"]):
            entry = doc["fields"][field_id]
            if entry["status"] == "missing" and not brd_template.is_empty(entry.get("suggestion")):
                brd_template.set_field(doc, field_id, entry["suggestion"], status="assumed")
        return doc

    @staticmethod
    def confirm_inferred(doc: dict, field_ids: list | None = None) -> dict:
        for field_id in field_ids or list(doc["fields"]):
            entry = doc["fields"][field_id]
            if entry["status"] == "inferred":
                entry["status"] = "confirmed"
        doc["completeness"] = brd_template.completeness(doc)
        return doc

    @staticmethod
    def set_answer(doc: dict, field_id: str, value, note: str = "") -> dict:
        """The analyst types an answer (from a customer call, email, ...)."""
        return brd_template.set_field(doc, field_id, value, status="confirmed", note=note or None)

    def apply_customer_answers(self, doc: dict, answers: str) -> tuple:
        """Gemini reads free-text customer answers (e.g. a pasted email) and fills the matching fields.

        Returns (doc, list of updated field ids).
        """
        llm = self.require_llm()
        open_ids = doc["completeness"]["missing"] + doc["completeness"]["to_confirm"]
        if not open_ids:
            return doc, []
        current = {fid: doc["fields"][fid]["value"] for fid in open_ids}
        prompt = ANSWERS_PROMPT.format(
            template=_template_for_prompt(open_ids),
            current=json.dumps(current, indent=1, ensure_ascii=False),
            answers=answers,
        )
        reply = llm.generate_json(prompt, purpose="step1_apply_customer_answers")
        updated = []
        for field_id, item in (reply.get("fields") or {}).items():
            if field_id not in open_ids:
                continue
            item = item if isinstance(item, dict) else {"value": item}
            brd_template.set_field(
                doc, field_id, item.get("value"), "confirmed", "Customer: " + str(item.get("note") or "")
            )
            if doc["fields"][field_id]["status"] == "confirmed":  # set_field leaves empty answers as missing
                updated.append(field_id)
        return doc, updated

    # ------------------------------------------------------------ finalise + save

    @staticmethod
    def finalize(doc: dict, allow_open_items: bool = False) -> dict:
        return brd_template.finalize(doc, allow_open_items)

    @staticmethod
    def save(doc: dict, root=None) -> dict:
        """Write the BRD artifacts. Draft -> brd_draft.*, final -> brd_final.*. Returns {kind: path}."""
        project = doc["fields"]["project_name"]["value"] or "project"
        folder = step_dir(project, 1, root=root)
        stem = "brd_final" if doc["status"] == "final" else "brd_draft"
        public = {k: v for k, v in doc.items() if k != "customer_brd_text"}
        paths = {
            "json": write_json(folder / f"{stem}.json", public),
            "markdown": write_text(folder / f"{stem}.md", brd_template.to_markdown(doc)),
            "gap_report": write_text(folder / "gap_report.md", brd_template.gap_report_markdown(doc)),
        }
        paths["docx"] = folder / f"{stem}.docx"
        paths["docx"].write_bytes(brd_template.to_docx(doc))
        if doc.get("customer_brd_text"):
            paths["customer_text"] = write_text(folder / "customer_brd_text.txt", doc["customer_brd_text"])
        return {k: str(v) for k, v in paths.items()}
