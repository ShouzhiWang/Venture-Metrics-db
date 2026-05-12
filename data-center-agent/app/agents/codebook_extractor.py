import re
from typing import Any


VARIABLE_PATTERNS = [
    re.compile(
        r"(?P<name>[A-Z][A-Za-z0-9_ /-]{2,60})\s+(?:is defined as|means|refers to)\s+(?P<definition>[^.]{20,300})\.",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<name>[A-Za-z][A-Za-z0-9_ /-]{2,60})\s*[:\-]\s*(?P<definition>[^.\n]{20,300})",
        re.IGNORECASE,
    ),
]


def extract_codebook_candidates(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for chunk in chunks:
        text = chunk["chunk_text"]
        if not _looks_like_codebook_text(text):
            continue
        for pattern in VARIABLE_PATTERNS:
            for match in pattern.finditer(text):
                name = _clean_name(match.group("name"))
                definition = match.group("definition").strip()
                key = (name.lower(), definition.lower())
                if len(name) > 80 or key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    {
                        "report_id": chunk["report_id"],
                        "raw_variable_name": name,
                        "definition": definition,
                        "measurement_method": None,
                        "unit": _infer_unit(text),
                        "data_source_text": _infer_source_text(text),
                        "data_source_type": _infer_data_source_type(text),
                        "availability": _infer_availability(text),
                        "temporal_coverage": _infer_temporal_coverage(text),
                        "geographic_coverage": None,
                        "page_number": chunk.get("page_number"),
                        "evidence_chunk_id": chunk.get("id"),
                        "confidence_score": 0.35,
                        "review_status": "pending",
                        "metadata": {"extractor": "mvp_rule_based"},
                    }
                )
    return candidates[:25]


def _looks_like_codebook_text(text: str) -> bool:
    lowered = text.lower()
    hints = ["variable", "defined as", "definition", "indicator", "measure", "data source", "unit"]
    return any(hint in lowered for hint in hints)


def _clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip(" :-")


def _infer_unit(text: str) -> str | None:
    match = re.search(r"unit(?:s)?\s*[:\-]\s*([A-Za-z%/$ ]{1,40})", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _infer_source_text(text: str) -> str | None:
    match = re.search(r"(?:data source|source)\s*[:\-]\s*([^.;]{5,160})", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _infer_data_source_type(text: str) -> str:
    lowered = text.lower()
    if "survey" in lowered:
        return "survey"
    if "estimate" in lowered or "estimated" in lowered:
        return "estimate"
    if "table" in lowered:
        return "report_table"
    if "database" in lowered or "dataset" in lowered:
        return "public_dataset" if "public" in lowered else "private_database"
    return "unknown"


def _infer_availability(text: str) -> str:
    lowered = text.lower()
    if "proprietary" in lowered or "private" in lowered or "confidential" in lowered:
        return "private"
    if "not available" in lowered or "unavailable" in lowered:
        return "not_obtainable"
    if "public" in lowered or "download" in lowered:
        return "obtainable"
    return "unclear"


def _infer_temporal_coverage(text: str) -> str | None:
    match = re.search(r"(?:19|20)\d{2}\s*(?:-|to|through)\s*(?:19|20)\d{2}", text)
    return match.group(0) if match else None
