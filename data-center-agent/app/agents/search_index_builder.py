from __future__ import annotations

import json
import re
from typing import Any


DEFAULT_OBJECT_TYPES = ("variable", "report", "source", "dataset", "organization")
HIGH_VALUE_CHUNK_TYPES = {"methodology", "definitions", "data_sources", "technical_notes", "source_note"}
HIGH_VALUE_TERMS = (
    "data",
    "dataset",
    "indicator",
    "variable",
    "measure",
    "source",
    "methodology",
    "coverage",
    "definition",
    "table",
    "survey",
    "funding",
    "venture",
    "startup",
    "sme",
    "innovation",
    "r&d",
    "electricity",
)


def compact_text(*parts: Any, max_chars: int | None = None) -> str:
    normalized_parts = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, (dict, list)):
            value = json.dumps(part, ensure_ascii=False, default=str)
        else:
            value = str(part)
        value = value.strip()
        if value:
            normalized_parts.append(value)
    text = re.sub(r"\s+", " ", " ".join(normalized_parts)).strip()
    if max_chars and len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "..."
    return text


def metadata_value(metadata: dict[str, Any] | None, *keys: str) -> Any:
    if not metadata:
        return None
    for key in keys:
        if metadata.get(key):
            return metadata[key]
    return None


def _base_item(
    *,
    object_type: str,
    object_id: Any,
    title: str | None,
    content: str,
    search_text: str,
    metadata: dict[str, Any] | None = None,
    **values: Any,
) -> dict[str, Any]:
    return {
        "object_type": object_type,
        "object_id": object_id,
        "title": title,
        "content": content,
        "search_text": search_text,
        "metadata": metadata or {},
        "availability": values.pop("availability", None) or "unclear",
        "rank_weight": values.pop("rank_weight", 1.0),
        **values,
    }


def source_item(source: dict[str, Any]) -> dict[str, Any]:
    content = compact_text(
        source.get("original_url"),
        source.get("title"),
        source.get("source_type"),
        source.get("source_owner"),
        source.get("access_type"),
        source.get("source_role"),
        source.get("resolution_status"),
        source.get("notes"),
    )
    return _base_item(
        object_type="source",
        object_id=source["id"],
        source_id=source["id"],
        title=source.get("title") or source.get("original_url"),
        content=content,
        search_text=content,
        availability=source.get("access_type"),
        source_url=source.get("original_url"),
        local_path=source.get("raw_file_path"),
        rank_weight=0.6,
        metadata={
            "source_type": source.get("source_type"),
            "source_owner": source.get("source_owner"),
            "source_role": source.get("source_role"),
            "resolution_status": source.get("resolution_status"),
            "detected_format": source.get("detected_format"),
        },
    )


def report_item(report: dict[str, Any], source: dict[str, Any] | None = None) -> dict[str, Any]:
    content = compact_text(
        report.get("title"),
        report.get("publisher"),
        report.get("summary"),
        report.get("geography"),
        report.get("report_year"),
        report.get("language"),
        report.get("citation_info"),
        source.get("original_url") if source else None,
    )
    return _base_item(
        object_type="report",
        object_id=report["id"],
        source_id=report.get("source_id"),
        report_id=report["id"],
        title=report.get("title"),
        content=content,
        search_text=content,
        geography=report.get("geography"),
        time_coverage=str(report.get("report_year") or report.get("publication_date") or "") or None,
        availability=source.get("access_type") if source else "unclear",
        source_url=source.get("original_url") if source else None,
        local_path=report.get("raw_text_path") or (source.get("raw_file_path") if source else None),
        rank_weight=0.8,
        metadata={
            "publisher": report.get("publisher"),
            "publication_date": str(report.get("publication_date")) if report.get("publication_date") else None,
            "language": report.get("language"),
        },
    )


def dataset_item(dataset: dict[str, Any], source: dict[str, Any] | None = None, report: dict[str, Any] | None = None) -> dict[str, Any]:
    time_coverage = compact_text(dataset.get("temporal_coverage_start"), dataset.get("temporal_coverage_end"))
    content = compact_text(
        dataset.get("dataset_name"),
        dataset.get("data_origin_type"),
        time_coverage,
        dataset.get("geography_coverage"),
        dataset.get("license_or_access_note"),
        dataset.get("metadata"),
        report.get("title") if report else None,
        source.get("original_url") if source else None,
    )
    return _base_item(
        object_type="dataset",
        object_id=dataset["id"],
        source_id=dataset.get("source_id"),
        report_id=dataset.get("report_id"),
        dataset_id=dataset["id"],
        title=dataset.get("dataset_name") or (source.get("title") if source else None),
        content=content,
        search_text=content,
        geography=dataset.get("geography_coverage") or (report.get("geography") if report else None),
        time_coverage=time_coverage or None,
        availability=dataset.get("license_or_access_note") or (source.get("access_type") if source else "unclear"),
        source_url=source.get("original_url") if source else None,
        local_path=dataset.get("raw_data_path") or (source.get("raw_file_path") if source else None),
        rank_weight=1.0,
        metadata={"data_origin_type": dataset.get("data_origin_type")},
    )


def organization_item(organization: dict[str, Any]) -> dict[str, Any]:
    source_url = organization.get("source_original_url") or organization.get("original_source_url") or organization.get("website_url")
    content = compact_text(
        organization.get("name"),
        organization.get("description"),
        organization.get("organization_type"),
        organization.get("geography"),
        organization.get("country"),
        organization.get("city"),
        organization.get("region"),
        organization.get("sector_focus"),
        organization.get("stage_focus"),
        organization.get("market_focus"),
        organization.get("website_url"),
    )
    return _base_item(
        object_type="organization",
        object_id=organization["id"],
        source_id=organization.get("source_id"),
        title=organization.get("name"),
        content=content,
        search_text=content,
        geography=organization.get("geography") or organization.get("country") or organization.get("region"),
        availability=organization.get("source_access_type") or "public",
        source_url=source_url,
        local_path=organization.get("source_raw_file_path"),
        rank_weight=0.9,
        metadata={
            "organization_type": organization.get("organization_type"),
            "sector_focus": organization.get("sector_focus"),
            "stage_focus": organization.get("stage_focus"),
            "market_focus": organization.get("market_focus"),
            "review_status": organization.get("review_status"),
            "confidence_score": float(organization["confidence_score"]) if organization.get("confidence_score") is not None else None,
            "website_url": organization.get("website_url"),
        },
    )


def variable_item(
    variable: dict[str, Any],
    report: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
    evidence_chunk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = variable.get("metadata") or {}
    quote = metadata_value(metadata, "evidence_quote", "quote")
    if not quote and evidence_chunk:
        quote = compact_text(evidence_chunk.get("chunk_text"), max_chars=600)
    title = variable.get("raw_variable_name")
    content = compact_text(
        title,
        variable.get("definition"),
        variable.get("measurement_method"),
        variable.get("unit"),
        variable.get("data_source_text"),
        variable.get("data_source_type"),
        variable.get("availability"),
        variable.get("temporal_coverage"),
        variable.get("geographic_coverage"),
        metadata_value(metadata, "item_type"),
        metadata_value(metadata, "domain_relevance"),
        quote,
        report.get("title") if report else None,
    )
    return _base_item(
        object_type="variable",
        object_id=variable["id"],
        source_id=report.get("source_id") if report else None,
        report_id=variable.get("report_id"),
        variable_id=variable["id"],
        title=title,
        content=content,
        search_text=content,
        geography=variable.get("geographic_coverage") or (report.get("geography") if report else None),
        time_coverage=variable.get("temporal_coverage") or (str(report.get("report_year")) if report and report.get("report_year") else None),
        availability=variable.get("availability") or "unclear",
        source_url=source.get("original_url") if source else None,
        local_path=source.get("raw_file_path") if source else None,
        evidence_quote=quote,
        rank_weight=1.2,
        metadata={
            "confidence_score": float(variable["confidence_score"]) if variable.get("confidence_score") is not None else None,
            "review_status": variable.get("review_status"),
            "item_type": metadata_value(metadata, "item_type"),
            "domain_relevance": metadata_value(metadata, "domain_relevance"),
            "availability": variable.get("availability"),
            "data_source_type": variable.get("data_source_type"),
            "evidence_chunk_id": str(variable.get("evidence_chunk_id")) if variable.get("evidence_chunk_id") else None,
            "evidence_quote": quote,
            "page_number": variable.get("page_number"),
            "definition": variable.get("definition"),
            "measurement_method": variable.get("measurement_method"),
            "unit": variable.get("unit"),
            "data_source_text": variable.get("data_source_text"),
        },
    )


def should_index_chunk(chunk: dict[str, Any], evidence_chunk_ids: set[str] | None = None) -> bool:
    if evidence_chunk_ids and str(chunk.get("id")) in evidence_chunk_ids:
        return True
    chunk_type = (chunk.get("chunk_type") or "unknown").lower()
    if chunk_type in HIGH_VALUE_CHUNK_TYPES:
        return True
    text = (chunk.get("chunk_text") or "").lower()
    return len(text) >= 80 and any(term in text for term in HIGH_VALUE_TERMS)


def chunk_item(chunk: dict[str, Any], report: dict[str, Any] | None = None, source: dict[str, Any] | None = None) -> dict[str, Any]:
    title = compact_text(chunk.get("section_title"), report.get("title") if report else None, max_chars=300)
    content = compact_text(
        chunk.get("section_title"),
        chunk.get("chunk_type"),
        chunk.get("chunk_text"),
        report.get("title") if report else None,
        source.get("original_url") if source else None,
        max_chars=6000,
    )
    return _base_item(
        object_type="chunk",
        object_id=chunk["id"],
        source_id=report.get("source_id") if report else None,
        report_id=chunk.get("report_id"),
        chunk_id=chunk["id"],
        title=title or None,
        content=content,
        search_text=content,
        geography=report.get("geography") if report else None,
        time_coverage=str(report.get("report_year")) if report and report.get("report_year") else None,
        availability=source.get("access_type") if source else "unclear",
        source_url=source.get("original_url") if source else None,
        local_path=report.get("raw_text_path") if report else None,
        evidence_quote=compact_text(chunk.get("chunk_text"), max_chars=600),
        rank_weight=0.5,
        metadata={
            "chunk_type": chunk.get("chunk_type"),
            "page_number": chunk.get("page_number"),
            "section_title": chunk.get("section_title"),
        },
    )
