import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.db.repositories.base import BaseRepository, row_to_dict


class VariableRepository(BaseRepository):
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
