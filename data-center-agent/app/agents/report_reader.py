from app.agents.parser import extract_title_from_html


def basic_report_metadata(source: dict, raw_content: bytes | None = None) -> dict:
    title = source.get("title")
    if not title and raw_content and source.get("source_type") == "html":
        title = extract_title_from_html(raw_content)
    return {
        "source_id": source["id"],
        "title": title or source.get("original_url") or "Untitled report",
        "publisher": source.get("source_owner"),
        "language": None,
        "summary": "MVP placeholder metadata. Detailed report reading requires an LLM or domain-specific parser.",
        "citation_info": {"source_url": source.get("original_url")},
    }


def identify_embedded_data_sources(_report_text: str) -> list[dict]:
    # TODO: Replace with an LLM-backed evidence extractor.
    return []
