import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.db.repositories.base import BaseRepository, row_to_dict


class ReportRepository(BaseRepository):
    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                INSERT INTO reports (
                  source_id, title, publisher, publication_date, report_year,
                  geography, language, summary, raw_text_path, parsed_json_path, citation_info
                )
                VALUES (
                  :source_id, :title, :publisher, :publication_date, :report_year,
                  :geography, :language, :summary, :raw_text_path, :parsed_json_path, CAST(:citation_info AS jsonb)
                )
                RETURNING *
                """
            ),
            {
                "source_id": str(values["source_id"]) if values.get("source_id") else None,
                "title": values.get("title"),
                "publisher": values.get("publisher"),
                "publication_date": values.get("publication_date"),
                "report_year": values.get("report_year"),
                "geography": values.get("geography"),
                "language": values.get("language"),
                "summary": values.get("summary"),
                "raw_text_path": values.get("raw_text_path"),
                "parsed_json_path": values.get("parsed_json_path"),
                "citation_info": json.dumps(values.get("citation_info")) if values.get("citation_info") is not None else None,
            },
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def get(self, report_id: UUID | str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(text("SELECT * FROM reports WHERE id = :id"), {"id": str(report_id)}).first()
        )

    def get_by_source(self, source_id: UUID | str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text("SELECT * FROM reports WHERE source_id = :source_id ORDER BY created_at DESC LIMIT 1"),
                {"source_id": str(source_id)},
            ).first()
        )

    def update_paths(self, report_id: UUID | str, *, raw_text_path: str | None, parsed_json_path: str | None = None) -> None:
        self.connection.execute(
            text(
                """
                UPDATE reports
                SET raw_text_path = coalesce(:raw_text_path, raw_text_path),
                    parsed_json_path = coalesce(:parsed_json_path, parsed_json_path),
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": str(report_id), "raw_text_path": raw_text_path, "parsed_json_path": parsed_json_path},
        )
