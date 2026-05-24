from __future__ import annotations

import argparse
import json
from collections import Counter
from uuid import UUID

from sqlalchemy import text

from app.agents.search_index_builder import (
    DEFAULT_OBJECT_TYPES,
    chunk_item,
    dataset_item,
    report_item,
    should_index_chunk,
    source_item,
    variable_item,
)
from app.db.connection import get_engine
from app.db.repositories.search_index import SearchIndexRepository
from app.utils.logging import configure_logging


def parse_object_types(value: str | None) -> list[str]:
    if not value:
        return list(DEFAULT_OBJECT_TYPES)
    return [item.strip() for item in value.split(",") if item.strip()]


def build_search_index(
    *,
    object_types: list[str] | None = None,
    report_id: UUID | None = None,
    source_id: UUID | None = None,
    rebuild: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict:
    selected = object_types or list(DEFAULT_OBJECT_TYPES)
    engine = get_engine()
    counts: Counter[str] = Counter()
    samples: list[dict] = []
    with engine.begin() as connection:
        repo = SearchIndexRepository(connection)
        if rebuild and not dry_run:
            for object_type in selected:
                repo.delete_by_object_type(object_type)

        for item in iter_search_items(connection, selected, report_id=report_id, source_id=source_id, limit=limit):
            counts[item["object_type"]] += 1
            if dry_run and len(samples) < 5:
                samples.append(
                    {
                        "object_type": item["object_type"],
                        "object_id": str(item["object_id"]),
                        "title": item.get("title"),
                        "search_text": item["search_text"][:600],
                    }
                )
            elif not dry_run:
                repo.upsert_search_item(item)
    return {"counts": dict(counts), "dry_run": dry_run, "samples": samples}


def iter_search_items(connection, object_types: list[str], *, report_id: UUID | None, source_id: UUID | None, limit: int | None):
    if "source" in object_types:
        for row in _source_rows(connection, source_id=source_id, limit=limit):
            yield source_item(row)
    if "report" in object_types:
        for row in _report_rows(connection, report_id=report_id, source_id=source_id, limit=limit):
            report = {key.removeprefix("report_"): value for key, value in row.items() if key.startswith("report_")}
            source = {key.removeprefix("source_"): value for key, value in row.items() if key.startswith("source_") and value is not None}
            yield report_item(report, source or None)
    if "dataset" in object_types:
        for row in _dataset_rows(connection, report_id=report_id, source_id=source_id, limit=limit):
            dataset = {key.removeprefix("dataset_"): value for key, value in row.items() if key.startswith("dataset_")}
            report = {key.removeprefix("report_"): value for key, value in row.items() if key.startswith("report_") and value is not None}
            source = {key.removeprefix("source_"): value for key, value in row.items() if key.startswith("source_") and value is not None}
            yield dataset_item(dataset, source or None, report or None)
    if "variable" in object_types:
        for row in _variable_rows(connection, report_id=report_id, source_id=source_id, limit=limit):
            variable = {key.removeprefix("variable_"): value for key, value in row.items() if key.startswith("variable_")}
            report = {key.removeprefix("report_"): value for key, value in row.items() if key.startswith("report_") and value is not None}
            source = {key.removeprefix("source_"): value for key, value in row.items() if key.startswith("source_") and value is not None}
            chunk = {key.removeprefix("chunk_"): value for key, value in row.items() if key.startswith("chunk_") and value is not None}
            yield variable_item(variable, report or None, source or None, chunk or None)
    if "chunk" in object_types:
        evidence_ids = set(_evidence_chunk_ids(connection))
        for row in _chunk_rows(connection, report_id=report_id, source_id=source_id, limit=limit):
            chunk = {key.removeprefix("chunk_"): value for key, value in row.items() if key.startswith("chunk_")}
            if not should_index_chunk(chunk, evidence_ids):
                continue
            report = {key.removeprefix("report_"): value for key, value in row.items() if key.startswith("report_") and value is not None}
            source = {key.removeprefix("source_"): value for key, value in row.items() if key.startswith("source_") and value is not None}
            yield chunk_item(chunk, report or None, source or None)


def _source_rows(connection, *, source_id: UUID | None, limit: int | None) -> list[dict]:
    where = ["(CAST(:source_id AS uuid) IS NULL OR id = CAST(:source_id AS uuid))"]
    return _rows(connection, f"SELECT * FROM sources WHERE {' AND '.join(where)} ORDER BY updated_at DESC LIMIT :limit", source_id=source_id, limit=limit)


def _report_rows(connection, *, report_id: UUID | None, source_id: UUID | None, limit: int | None) -> list[dict]:
    return _rows(
        connection,
        """
        SELECT
          r.id AS report_id, r.source_id AS report_source_id, r.title AS report_title,
          r.publisher AS report_publisher, r.publication_date AS report_publication_date,
          r.report_year AS report_report_year, r.geography AS report_geography,
          r.language AS report_language, r.summary AS report_summary,
          r.raw_text_path AS report_raw_text_path, r.citation_info AS report_citation_info,
          s.id AS source_id, s.original_url AS source_original_url, s.title AS source_title,
          s.access_type AS source_access_type, s.raw_file_path AS source_raw_file_path
        FROM reports r
        LEFT JOIN sources s ON s.id = r.source_id
        WHERE (CAST(:report_id AS uuid) IS NULL OR r.id = CAST(:report_id AS uuid))
          AND (CAST(:source_id AS uuid) IS NULL OR r.source_id = CAST(:source_id AS uuid))
        ORDER BY r.updated_at DESC
        LIMIT :limit
        """,
        report_id=report_id,
        source_id=source_id,
        limit=limit,
    )


def _dataset_rows(connection, *, report_id: UUID | None, source_id: UUID | None, limit: int | None) -> list[dict]:
    return _rows(
        connection,
        """
        SELECT
          d.id AS dataset_id, d.source_id AS dataset_source_id, d.report_id AS dataset_report_id,
          d.dataset_name AS dataset_dataset_name, d.data_origin_type AS dataset_data_origin_type,
          d.temporal_coverage_start AS dataset_temporal_coverage_start,
          d.temporal_coverage_end AS dataset_temporal_coverage_end,
          d.geography_coverage AS dataset_geography_coverage,
          d.license_or_access_note AS dataset_license_or_access_note,
          d.raw_data_path AS dataset_raw_data_path, d.metadata AS dataset_metadata,
          r.id AS report_id, r.title AS report_title, r.geography AS report_geography,
          s.id AS source_id, s.original_url AS source_original_url, s.title AS source_title,
          s.access_type AS source_access_type, s.raw_file_path AS source_raw_file_path
        FROM datasets d
        LEFT JOIN reports r ON r.id = d.report_id
        LEFT JOIN sources s ON s.id = d.source_id
        WHERE (CAST(:report_id AS uuid) IS NULL OR d.report_id = CAST(:report_id AS uuid))
          AND (CAST(:source_id AS uuid) IS NULL OR d.source_id = CAST(:source_id AS uuid))
        ORDER BY d.created_at DESC
        LIMIT :limit
        """,
        report_id=report_id,
        source_id=source_id,
        limit=limit,
    )


def _variable_rows(connection, *, report_id: UUID | None, source_id: UUID | None, limit: int | None) -> list[dict]:
    return _rows(
        connection,
        """
        SELECT
          v.id AS variable_id, v.report_id AS variable_report_id, v.variable_id AS variable_variable_id,
          v.raw_variable_name AS variable_raw_variable_name, v.definition AS variable_definition,
          v.measurement_method AS variable_measurement_method, v.unit AS variable_unit,
          v.data_source_text AS variable_data_source_text, v.data_source_type AS variable_data_source_type,
          v.availability AS variable_availability, v.temporal_coverage AS variable_temporal_coverage,
          v.geographic_coverage AS variable_geographic_coverage, v.page_number AS variable_page_number,
          v.evidence_chunk_id AS variable_evidence_chunk_id, v.confidence_score AS variable_confidence_score,
          v.review_status AS variable_review_status, v.metadata AS variable_metadata,
          r.id AS report_id, r.source_id AS report_source_id, r.title AS report_title,
          r.report_year AS report_report_year, r.geography AS report_geography, r.summary AS report_summary,
          s.id AS source_id, s.original_url AS source_original_url, s.title AS source_title,
          s.access_type AS source_access_type, s.raw_file_path AS source_raw_file_path,
          c.id AS chunk_id, c.chunk_text AS chunk_chunk_text, c.page_number AS chunk_page_number
        FROM report_variables v
        JOIN reports r ON r.id = v.report_id
        LEFT JOIN sources s ON s.id = r.source_id
        LEFT JOIN document_chunks c ON c.id = v.evidence_chunk_id
        WHERE (CAST(:report_id AS uuid) IS NULL OR v.report_id = CAST(:report_id AS uuid))
          AND (CAST(:source_id AS uuid) IS NULL OR r.source_id = CAST(:source_id AS uuid))
        ORDER BY v.updated_at DESC
        LIMIT :limit
        """,
        report_id=report_id,
        source_id=source_id,
        limit=limit,
    )


def _chunk_rows(connection, *, report_id: UUID | None, source_id: UUID | None, limit: int | None) -> list[dict]:
    return _rows(
        connection,
        """
        SELECT
          c.id AS chunk_id, c.report_id AS chunk_report_id, c.chunk_text AS chunk_chunk_text,
          c.page_number AS chunk_page_number, c.section_title AS chunk_section_title,
          c.chunk_type AS chunk_chunk_type, c.token_count AS chunk_token_count, c.metadata AS chunk_metadata,
          r.id AS report_id, r.source_id AS report_source_id, r.title AS report_title,
          r.report_year AS report_report_year, r.geography AS report_geography,
          r.raw_text_path AS report_raw_text_path,
          s.id AS source_id, s.original_url AS source_original_url, s.access_type AS source_access_type
        FROM document_chunks c
        JOIN reports r ON r.id = c.report_id
        LEFT JOIN sources s ON s.id = r.source_id
        WHERE (CAST(:report_id AS uuid) IS NULL OR c.report_id = CAST(:report_id AS uuid))
          AND (CAST(:source_id AS uuid) IS NULL OR r.source_id = CAST(:source_id AS uuid))
        ORDER BY c.created_at DESC
        LIMIT :limit
        """,
        report_id=report_id,
        source_id=source_id,
        limit=limit,
    )


def _evidence_chunk_ids(connection) -> list[str]:
    rows = connection.execute(text("SELECT DISTINCT evidence_chunk_id FROM report_variables WHERE evidence_chunk_id IS NOT NULL"))
    return [str(row._mapping["evidence_chunk_id"]) for row in rows]


def _rows(connection, statement: str, **params) -> list[dict]:
    normalized = {key: (str(value) if isinstance(value, UUID) else value) for key, value in params.items()}
    normalized["limit"] = normalized.get("limit") or 100000
    result = connection.execute(text(statement), normalized)
    return [dict(row._mapping) for row in result]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or refresh rows in the rebuildable search_index table.")
    parser.add_argument("--object-types", help="Comma-separated object types. Default: variable,report,source,dataset")
    parser.add_argument("--report-id", type=UUID)
    parser.add_argument("--source-id", type=UUID)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    configure_logging()
    result = build_search_index(
        object_types=parse_object_types(args.object_types),
        report_id=args.report_id,
        source_id=args.source_id,
        rebuild=args.rebuild,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, default=str, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
