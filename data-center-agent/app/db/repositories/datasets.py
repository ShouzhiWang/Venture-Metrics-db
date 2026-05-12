import json
from typing import Any

from sqlalchemy import text

from app.db.repositories.base import BaseRepository, row_to_dict


class DatasetRepository(BaseRepository):
    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                INSERT INTO datasets (
                  source_id, report_id, dataset_name, data_origin_type,
                  temporal_coverage_start, temporal_coverage_end,
                  geography_coverage, license_or_access_note, raw_data_path, metadata
                )
                VALUES (
                  :source_id, :report_id, :dataset_name, :data_origin_type,
                  :temporal_coverage_start, :temporal_coverage_end,
                  :geography_coverage, :license_or_access_note, :raw_data_path, CAST(:metadata AS jsonb)
                )
                RETURNING *
                """
            ),
            {
                **values,
                "source_id": str(values["source_id"]),
                "report_id": str(values["report_id"]) if values.get("report_id") else None,
                "data_origin_type": values.get("data_origin_type", "unknown"),
                "metadata": json.dumps(values.get("metadata")) if values.get("metadata") is not None else None,
            },
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result
