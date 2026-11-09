from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class TextUnit:
    text: str
    source: str
    unit_id: str


def _unit(text: str, source: str, unit_id: str) -> TextUnit | None:
    text = (text or "").strip()
    if not text:
        return None
    return TextUnit(text=text, source=source, unit_id=unit_id)


def _load_pdf(path: Path) -> list[TextUnit]:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    result = []
    for page_no, page in enumerate(reader.pages, start=1):
        item = _unit(page.extract_text() or "", path.name, f"page-{page_no}")
        if item:
            result.append(item)
    return result


def _load_docx(path: Path) -> list[TextUnit]:
    from docx import Document
    doc = Document(str(path))
    result = []
    for idx, paragraph in enumerate(doc.paragraphs, start=1):
        item = _unit(paragraph.text, path.name, f"paragraph-{idx}")
        if item:
            result.append(item)
    for table_no, table in enumerate(doc.tables, start=1):
        rows = [" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows]
        item = _unit("\n".join(rows), path.name, f"table-{table_no}")
        if item:
            result.append(item)
    return result


def _load_html(path: Path) -> list[TextUnit]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    text = soup.get_text("\n", strip=True)
    item = _unit(text, path.name, "html-body")
    return [item] if item else []


def _load_csv(path: Path) -> list[TextUnit]:
    result = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader, start=1):
            text = "\n".join(f"{key}: {value}" for key, value in row.items() if value not in (None, ""))
            item = _unit(text, path.name, f"row-{idx}")
            if item:
                result.append(item)
    return result


def _flatten_json(value, prefix: str = "") -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _flatten_json(child, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from _flatten_json(child, f"{prefix}[{idx}]")
    elif value is not None:
        yield f"{prefix}: {value}"


def _load_json(path: Path) -> list[TextUnit]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    # Keep individual top-level records as separate units where possible.
    records = payload if isinstance(payload, list) else [payload]
    result = []
    for idx, record in enumerate(records, start=1):
        text = "\n".join(_flatten_json(record))
        item = _unit(text, path.name, f"record-{idx}")
        if item:
            result.append(item)
    return result


def load_document(path: str | Path) -> list[TextUnit]:
    path = Path(path)
    suffix = path.suffix.lower()
    loaders = {
        ".pdf": _load_pdf,
        ".docx": _load_docx,
        ".html": _load_html,
        ".htm": _load_html,
        ".csv": _load_csv,
        ".json": _load_json,
        ".txt": lambda p: [u for u in [_unit(p.read_text(encoding="utf-8", errors="ignore"), p.name, "text-body")] if u],
        ".md": lambda p: [u for u in [_unit(p.read_text(encoding="utf-8", errors="ignore"), p.name, "markdown-body")] if u],
    }
    if suffix not in loaders:
        raise ValueError(f"Unsupported file type: {suffix}")
    units = loaders[suffix](path)
    # Stable IDs help identify source units in retrieval citations.
    for unit in units:
        digest = hashlib.sha1(unit.text.encode("utf-8")).hexdigest()[:10]
        unit.unit_id = f"{unit.unit_id}-{digest}"
    return units
