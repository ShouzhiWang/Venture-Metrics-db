import json
from typing import Any

from sqlalchemy import text

from app.db.repositories.base import BaseRepository, row_to_dict


class JobRepository(BaseRepository):
    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                INSERT INTO ingestion_jobs (job_type, status, source_id, report_id, input_payload)
                VALUES (:job_type, :status, :source_id, :report_id, CAST(:input_payload AS jsonb))
                RETURNING *
                """
            ),
            {
                "job_type": values["job_type"],
                "status": values.get("status", "pending"),
                "source_id": str(values["source_id"]) if values.get("source_id") else None,
                "report_id": str(values["report_id"]) if values.get("report_id") else None,
                "input_payload": json.dumps(values.get("input_payload")) if values.get("input_payload") is not None else None,
            },
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result
