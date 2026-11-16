"""Read a BRD (PDF, DOCX, TXT or MD) into plain text."""

import io
import re
from pathlib import Path

import config

SUPPORTED = (".pdf", ".docx", ".txt", ".md")


def parse_brd(source, filename: str | None = None) -> dict:
    """Return {"text", "source", "pages", "char_count", "truncated"}.

    source is a path, or bytes / a file-like object together with filename.
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        filename = filename or path.name
        data = path.read_bytes()
    elif isinstance(source, bytes):
        data = source
    else:
        data = source.read()
    if not filename:
        raise ValueError("filename is required to detect the BRD format")

    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        text, pages = _pdf_text(data)
    elif suffix == ".docx":
        text, pages = _docx_text(data), None
    elif suffix in (".txt", ".md"):
        text, pages = data.decode("utf-8", errors="replace"), None
    else:
        raise ValueError(f"Unsupported BRD format {suffix}. Use one of: {', '.join(SUPPORTED)}")

    text = _clean(text)
    if len(text) < 50:
        raise ValueError("The BRD has almost no extractable text. A scanned PDF needs OCR first.")
    truncated = len(text) > config.MAX_BRD_CHARS
    return {
        "text": text[: config.MAX_BRD_CHARS],
        "source": filename,
        "pages": pages,
        "char_count": len(text),
        "truncated": truncated,
    }


def _pdf_text(data: bytes) -> tuple:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages), len(pages)


def _docx_text(data: bytes) -> str:
    """Paragraphs and tables in document order. Tables become pipe-separated rows."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(io.BytesIO(data))
    lines = []
    for block in document.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(block, document)
            text = paragraph.text.strip()
            if not text:
                continue
            style = (paragraph.style.name or "").lower() if paragraph.style is not None else ""
            lines.append(f"\n## {text}" if style.startswith(("heading", "title")) else text)
        elif tag == "tbl":
            for row in Table(block, document).rows:
                cells = [cell.text.strip() for cell in row.cells]
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def _clean(text: str) -> str:
    text = text.replace("\x00", " ").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
