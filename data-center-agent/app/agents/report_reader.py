from app.agents.parser import extract_title_from_html
import re


def basic_report_metadata(source: dict, raw_content: bytes | None = None) -> dict:
    title = source.get("title")
    if not title and raw_content and source.get("source_type") == "html":
        title = extract_title_from_html(raw_content)
    return {
        "source_id": source["id"],
        "title": title,
        "publisher": source.get("source_owner"),
        "language": None,
        "summary": None,
        "citation_info": {"source_url": source.get("original_url")},
    }


def extract_report_metadata_from_text(text: str, parsed_metadata: dict | None = None) -> dict:
    metadata = parsed_metadata or {}
    title = metadata.get("title") or _first_non_empty_line(text)
    publication_date = _extract_publication_date(text)
    report_year = publication_date.year if publication_date else _extract_report_year(text)
    return {
        "title": title,
        "publisher": _extract_publisher(text),
        "publication_date": publication_date,
        "report_year": report_year,
        "geography": _extract_geography(text),
        "language": _guess_language(text),
        "summary": _build_summary(text),
    }


def identify_embedded_data_sources(_report_text: str) -> list[dict]:
    # TODO: Replace with an LLM-backed evidence extractor.
    return []


def _first_non_empty_line(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if 8 <= len(stripped) <= 180:
            return stripped
    return None


def _extract_publication_date(text: str):
    from datetime import date

    match = re.search(r"\b(20\d{2}|19\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return date(year, month, day)
    return None


def _extract_report_year(text: str) -> int | None:
    match = re.search(r"\b(20\d{2}|19\d{2})\b", text[:5000])
    return int(match.group(1)) if match else None


def _extract_publisher(text: str) -> str | None:
    match = re.search(r"(?:published by|publisher)\s*[:\-]?\s*([^.\n]{3,120})", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _extract_geography(text: str) -> str | None:
    match = re.search(r"(?:geography|geographic coverage|region)\s*[:\-]\s*([^.\n]{3,120})", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _guess_language(text: str) -> str | None:
    if not text:
        return None
    ascii_chars = sum(1 for char in text[:2000] if ord(char) < 128)
    return "en" if ascii_chars / max(len(text[:2000]), 1) > 0.85 else None


def _build_summary(text: str) -> str | None:
    stripped = " ".join(text.split())
    if not stripped:
        return None
    return stripped[:500]
