import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.db.repositories.base import BaseRepository, row_to_dict
from app.models.variable import ExtractedVariable


class VariableRepository(BaseRepository):
    def insert_report_variable(self, extracted_variable: ExtractedVariable | dict[str, Any]) -> dict[str, Any]:
        values = (
            extracted_variable.model_dump(mode="python")
            if isinstance(extracted_variable, ExtractedVariable)
            else dict(extracted_variable)
        )
        metadata = dict(values.get("metadata") or {})
        if values.get("evidence_quote"):
            metadata["evidence_quote"] = values["evidence_quote"]
        values["metadata"] = metadata
        return self.create_report_variable(values)

    def insert_many_report_variables(self, extracted_variables: list[ExtractedVariable | dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.insert_report_variable(variable) for variable in extracted_variables]

    def get_report_variables_by_report(self, report_id: UUID | str) -> list[dict[str, Any]]:
        return self.list_by_report(report_id)

    def delete_report_variables_by_report(self, report_id: UUID | str) -> int:
        result = self.connection.execute(
            text("DELETE FROM report_variables WHERE report_id = :report_id"),
            {"report_id": str(report_id)},
        )
        return result.rowcount or 0

    def create_report_variable(self, values: dict[str, Any]) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                INSERT INTO report_variables (
                  report_id, variable_id, raw_variable_name, definition,
                  measurement_method, unit, data_source_text, data_source_type,
                  availability, temporal_coverage, geographic_coverage,
                  page_number, evidence_chunk_id, confidence_score, review_status, metadata
                )
                VALUES (
                  :report_id, :variable_id, :raw_variable_name, :definition,
                  :measurement_method, :unit, :data_source_text, :data_source_type,
                  :availability, :temporal_coverage, :geographic_coverage,
                  :page_number, :evidence_chunk_id, :confidence_score, :review_status, CAST(:metadata AS jsonb)
                )
                RETURNING *
                """
            ),
            {
                **values,
                "report_id": str(values["report_id"]),
                "variable_id": str(values["variable_id"]) if values.get("variable_id") else None,
                "evidence_chunk_id": str(values["evidence_chunk_id"]) if values.get("evidence_chunk_id") else None,
                "data_source_type": values.get("data_source_type", "unknown"),
                "availability": values.get("availability", "unclear"),
                "review_status": values.get("review_status", "pending"),
                "metadata": json.dumps(values.get("metadata")) if values.get("metadata") is not None else None,
            },
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def list_by_report(self, report_id: UUID | str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text("SELECT * FROM report_variables WHERE report_id = :report_id ORDER BY created_at"),
            {"report_id": str(report_id)},
        )
        return [dict(row._mapping) for row in rows]

    def get_detail(self, variable_id: UUID | str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text(
                    """
                    SELECT
                      v.*,
                      r.title AS report_title,
                      r.publisher AS report_publisher,
                      r.report_year AS report_year,
                      r.geography AS report_geography,
                      s.original_url AS source_url,
                      c.chunk_text AS evidence_chunk_text,
                      c.page_number AS evidence_page_number
                    FROM report_variables v
                    LEFT JOIN reports r ON r.id = v.report_id
                    LEFT JOIN sources s ON s.id = r.source_id
                    LEFT JOIN document_chunks c ON c.id = v.evidence_chunk_id
                    WHERE v.id = :id
                    """
                ),
                {"id": str(variable_id)},
            ).first()
        )

    def compare_concepts(self, query: str, report_ids: list[str] | None = None, limit: int = 25) -> list[dict[str, Any]]:
        try:
            UUID(query)
            where = ["(v.id = CAST(:concept_id AS uuid) OR v.variable_id = CAST(:concept_id AS uuid))"]
            params: dict[str, Any] = {"concept_id": query, "pattern": f"%{query}%", "limit": limit}
        except ValueError:
            where = ["(v.raw_variable_name ILIKE :pattern OR v.definition ILIKE :pattern)"]
            params = {"pattern": f"%{query}%", "limit": limit}
        if report_ids:
            where.append("v.report_id = ANY(CAST(:report_ids AS uuid[]))")
            params["report_ids"] = [str(report_id) for report_id in report_ids]
        rows = self.connection.execute(
            text(
                f"""
                SELECT
                  v.id, v.report_id, v.raw_variable_name, v.definition,
                  v.measurement_method, v.unit, v.temporal_coverage,
                  v.geographic_coverage, v.confidence_score, v.review_status,
                  r.title AS report_title, r.report_year, r.geography AS report_geography
                FROM report_variables v
                LEFT JOIN reports r ON r.id = v.report_id
                WHERE {' AND '.join(where)}
                ORDER BY v.confidence_score DESC NULLS LAST, v.updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        )
        return [dict(row._mapping) for row in rows]

    def keyword_search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                """
                SELECT *
                FROM report_variables
                WHERE raw_variable_name ILIKE :pattern
                   OR definition ILIKE :pattern
                   OR data_source_text ILIKE :pattern
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"pattern": f"%{query}%", "limit": limit},
        )
        return [dict(row._mapping) for row in rows]
