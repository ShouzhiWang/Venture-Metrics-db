import json
from pathlib import Path

import fitz
import trafilatura
from bs4 import BeautifulSoup

from app.utils.text import chunk_text, count_tokens_rough, normalize_whitespace


def extract_title_from_html(content: bytes) -> str | None:
    soup = BeautifulSoup(content, "html.parser")
    title = soup.find("title")
    if title and title.get_text(strip=True):
        return title.get_text(strip=True)
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else None


def extract_text_from_pdf(path: Path) -> tuple[str, list[dict]]:
    pages: list[dict] = []
    with fitz.open(path) as document:
        for index, page in enumerate(document, start=1):
            text = page.get_text("text")
            normalized = normalize_whitespace(text)
            if normalized:
                pages.append({"page_number": index, "text": normalized})
    return "\n\n".join(page["text"] for page in pages), pages


def extract_text_from_html(path: Path) -> tuple[str, list[dict]]:
    content = path.read_text(encoding="utf-8", errors="ignore")
    extracted = trafilatura.extract(content) or ""
    if not extracted:
        soup = BeautifulSoup(content, "html.parser")
        extracted = soup.get_text(" ")
    text = normalize_whitespace(extracted)
    return text, [{"page_number": None, "text": text}] if text else []


def parse_raw_file(path: Path, source_type: str, mime_type: str | None = None) -> tuple[str, list[dict]]:
    suffix = path.suffix.lower()
    if source_type == "pdf" or suffix == ".pdf" or mime_type == "application/pdf":
        return extract_text_from_pdf(path)
    if source_type == "html" or suffix in {".html", ".htm"} or (mime_type or "").startswith("text/html"):
        return extract_text_from_html(path)
    if suffix in {".txt", ".csv"} or (mime_type or "").startswith("text/"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        normalized = normalize_whitespace(text)
        return normalized, [{"page_number": None, "text": normalized}] if normalized else []
    return "", []


def build_chunks(report_id: str, pages: list[dict], max_words: int = 450) -> list[dict]:
    records: list[dict] = []
    for page in pages:
        for chunk in chunk_text(page["text"], max_words=max_words):
            records.append(
                {
                    "report_id": report_id,
                    "chunk_text": chunk,
                    "page_number": page.get("page_number"),
                    "section_title": None,
                    "chunk_type": infer_chunk_type(chunk),
                    "token_count": count_tokens_rough(chunk),
                    "metadata": {"parser": "mvp_rule_based"},
                }
            )
    return records


def parsed_json(text: str, pages: list[dict]) -> str:
    return json.dumps({"text_length": len(text), "pages": pages}, ensure_ascii=True, indent=2)


def infer_chunk_type(text: str) -> str:
    lowered = text.lower()
    if "methodology" in lowered or "method" in lowered:
        return "methodology"
    if "source:" in lowered or "data source" in lowered:
        return "source_note"
    if "table " in lowered[:80]:
        return "table"
    if "footnote" in lowered:
        return "footnote"
    return "narrative"
