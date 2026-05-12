import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz
import pdfplumber
import trafilatura
from bs4 import BeautifulSoup

from app.utils.text import count_tokens_rough, normalize_whitespace


PDF_FALLBACK_MIN_CHARS = 500
DEFAULT_TARGET_TOKENS = 1000
DEFAULT_MIN_TOKENS = 800
DEFAULT_MAX_TOKENS = 1200


@dataclass
class ParsedPage:
    page_number: int | None
    text: str
    extraction_method: str
    tables: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ParsedDocument:
    text: str
    pages: list[ParsedPage]
    metadata: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(
            {
                "text_length": len(self.text),
                "page_count": len(self.pages),
                "metadata": self.metadata,
                "pages": [
                    {
                        "page_number": page.page_number,
                        "text_length": len(page.text),
                        "extraction_method": page.extraction_method,
                        "tables": page.tables,
                    }
                    for page in self.pages
                ],
            },
            ensure_ascii=True,
            indent=2,
        )


def extract_title_from_html(content: bytes) -> str | None:
    soup = BeautifulSoup(content, "html.parser")
    title = soup.find("title")
    if title and title.get_text(strip=True):
        return title.get_text(strip=True)
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else None


def extract_text_from_pdf(path: Path) -> ParsedDocument:
    pymupdf_pages = _extract_pdf_with_pymupdf(path)
    pymupdf_text = _join_page_text(pymupdf_pages)
    used_fallback = len(pymupdf_text) < PDF_FALLBACK_MIN_CHARS

    if used_fallback:
        pdfplumber_pages = _extract_pdf_with_pdfplumber(path)
        pdfplumber_text = _join_page_text(pdfplumber_pages)
        if len(pdfplumber_text) > len(pymupdf_text):
            return ParsedDocument(
                text=pdfplumber_text,
                pages=pdfplumber_pages,
                metadata={
                    "parser": "pdfplumber",
                    "fallback_from": "pymupdf",
                    "fallback_reason": "pymupdf_output_too_short",
                    "pymupdf_text_length": len(pymupdf_text),
                    "pdfplumber_text_length": len(pdfplumber_text),
                },
            )

    return ParsedDocument(
        text=pymupdf_text,
        pages=pymupdf_pages,
        metadata={
            "parser": "pymupdf",
            "fallback_considered": used_fallback,
            "pymupdf_text_length": len(pymupdf_text),
        },
    )


def _extract_pdf_with_pymupdf(path: Path) -> list[ParsedPage]:
    pages: list[ParsedPage] = []
    with fitz.open(path) as document:
        for index, page in enumerate(document, start=1):
            text = normalize_whitespace(page.get_text("text"))
            tables = detect_table_placeholders(text)
            if text or tables:
                pages.append(ParsedPage(index, text, "pymupdf", tables))
    return pages


def _extract_pdf_with_pdfplumber(path: Path) -> list[ParsedPage]:
    pages: list[ParsedPage] = []
    with pdfplumber.open(path) as document:
        for index, page in enumerate(document.pages, start=1):
            text = normalize_whitespace(page.extract_text() or "")
            tables = detect_table_placeholders(text)
            try:
                extracted_tables = page.extract_tables() or []
            except Exception:
                extracted_tables = []
            for table_index, table in enumerate(extracted_tables, start=1):
                tables.append(
                    {
                        "kind": "pdf_table",
                        "table_index": table_index,
                        "row_count": len(table),
                        "column_count": max((len(row or []) for row in table), default=0),
                        "extraction_method": "pdfplumber",
                    }
                )
            if text or tables:
                pages.append(ParsedPage(index, text, "pdfplumber", tables))
    return pages


def extract_text_from_html(path: Path) -> ParsedDocument:
    content = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(content, "html.parser")
    tables = detect_html_tables(soup)

    extracted = trafilatura.extract(content) or ""
    method = "trafilatura"
    if not extracted:
        extracted = soup.get_text(" ")
        method = "beautifulsoup"

    text = normalize_whitespace(extracted)
    pages = [ParsedPage(None, text, method, tables)] if text or tables else []
    return ParsedDocument(
        text=text,
        pages=pages,
        metadata={
            "parser": method,
            "html_table_count": len(tables),
            "title": extract_title_from_html(content.encode("utf-8")),
        },
    )


def extract_text_from_plain_file(path: Path) -> ParsedDocument:
    text = normalize_whitespace(path.read_text(encoding="utf-8", errors="ignore"))
    pages = [ParsedPage(None, text, "plain_text", detect_table_placeholders(text))] if text else []
    return ParsedDocument(text=text, pages=pages, metadata={"parser": "plain_text"})


def parse_raw_file(path: Path, source_type: str, mime_type: str | None = None) -> ParsedDocument:
    suffix = path.suffix.lower()
    if source_type == "pdf" or suffix == ".pdf" or mime_type == "application/pdf":
        return extract_text_from_pdf(path)
    if source_type == "html" or suffix in {".html", ".htm"} or (mime_type or "").startswith("text/html"):
        return extract_text_from_html(path)
    if suffix in {".txt", ".csv"} or (mime_type or "").startswith("text/"):
        return extract_text_from_plain_file(path)
    return ParsedDocument(text="", pages=[], metadata={"parser": "unsupported", "source_type": source_type})


def build_chunks(
    report_id: str,
    parsed: ParsedDocument | list[dict[str, Any]],
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    min_tokens: int = DEFAULT_MIN_TOKENS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[dict[str, Any]]:
    pages = _coerce_pages(parsed)
    parser_metadata = parsed.metadata if isinstance(parsed, ParsedDocument) else {"parser": "legacy_pages"}
    records: list[dict[str, Any]] = []

    for page in pages:
        for chunk_index, chunk in enumerate(chunk_text_by_tokens(page.text, target_tokens, min_tokens, max_tokens), start=1):
            records.append(
                {
                    "report_id": report_id,
                    "chunk_text": chunk,
                    "page_number": page.page_number,
                    "section_title": None,
                    "chunk_type": infer_chunk_type(chunk, page.tables),
                    "token_count": count_tokens_rough(chunk),
                    "metadata": {
                        "parser": parser_metadata.get("parser"),
                        "page_extraction_method": page.extraction_method,
                        "chunk_index_on_page": chunk_index,
                        "target_tokens": target_tokens,
                        "table_placeholders": page.tables,
                    },
                }
            )
    return records


def chunk_text_by_tokens(
    text: str,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    min_tokens: int = DEFAULT_MIN_TOKENS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[str]:
    words = re.findall(r"\S+", text)
    if not words:
        return []
    if len(words) <= max_tokens:
        return [" ".join(words)]

    chunks: list[str] = []
    start = 0
    overlap = max(80, target_tokens // 10)
    while start < len(words):
        end = min(start + target_tokens, len(words))
        if len(words) - end < min_tokens // 2:
            end = len(words)
        chunk_words = words[start:end]
        if len(chunk_words) > max_tokens:
            chunk_words = chunk_words[:max_tokens]
            end = start + max_tokens
        chunks.append(" ".join(chunk_words))
        if end >= len(words):
            break
        start = max(end - overlap, start + 1)
    return chunks


def parsed_json(parsed: ParsedDocument | str, pages: list[dict[str, Any]] | None = None) -> str:
    if isinstance(parsed, ParsedDocument):
        return parsed.to_json()
    legacy_pages = pages or []
    return json.dumps({"text_length": len(parsed), "pages": legacy_pages}, ensure_ascii=True, indent=2)


def infer_chunk_type(text: str, tables: list[dict[str, Any]] | None = None) -> str:
    if tables:
        return "table"
    lowered = text.lower()
    if "methodology" in lowered or "method" in lowered:
        return "methodology"
    if "source:" in lowered or "data source" in lowered:
        return "source_note"
    if "table " in lowered[:120]:
        return "table"
    if "footnote" in lowered:
        return "footnote"
    return "narrative"


def detect_html_tables(soup: BeautifulSoup) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for table_index, table in enumerate(soup.find_all("table"), start=1):
        rows = table.find_all("tr")
        columns = max((len(row.find_all(["td", "th"])) for row in rows), default=0)
        caption = table.find("caption")
        tables.append(
            {
                "kind": "html_table",
                "table_index": table_index,
                "row_count": len(rows),
                "column_count": columns,
                "caption": caption.get_text(" ", strip=True) if caption else None,
            }
        )
    return tables


def detect_table_placeholders(text: str) -> list[dict[str, Any]]:
    lowered = text.lower()
    if "table " not in lowered and "\t" not in text:
        return []
    return [{"kind": "text_table_hint", "reason": "table_keyword_or_tabular_text"}]


def _join_page_text(pages: list[ParsedPage]) -> str:
    return "\n\n".join(page.text for page in pages if page.text)


def _coerce_pages(parsed: ParsedDocument | list[dict[str, Any]]) -> list[ParsedPage]:
    if isinstance(parsed, ParsedDocument):
        return parsed.pages
    return [
        ParsedPage(
            page_number=page.get("page_number"),
            text=page.get("text", ""),
            extraction_method=page.get("extraction_method", "legacy"),
            tables=page.get("tables", []),
        )
        for page in parsed
    ]
