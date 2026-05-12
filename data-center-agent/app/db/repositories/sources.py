from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.db.repositories.base import BaseRepository, row_to_dict


class SourceRepository(BaseRepository):
    def upsert_by_url(self, original_url: str, values: dict[str, Any]) -> dict[str, Any]:
        params = {
            "original_url": original_url,
            "source_type": values.get("source_type", "unknown"),
            "source_owner": values.get("source_owner"),
            "access_type": values.get("access_type", "unknown"),
            "detected_format": values.get("detected_format"),
            "title": values.get("title"),
            "notes": values.get("notes"),
        }
        row = self.connection.execute(
            text(
                """
                INSERT INTO sources (
                  original_url, source_type, source_owner, access_type,
                  detected_format, title, notes
                )
                VALUES (
                  :original_url, :source_type, :source_owner, :access_type,
                  :detected_format, :title, :notes
                )
                ON CONFLICT (original_url) DO UPDATE SET
                  source_type = EXCLUDED.source_type,
                  detected_format = EXCLUDED.detected_format,
                  updated_at = now()
                RETURNING *
                """
            ),
            params,
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def get(self, source_id: UUID | str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(text("SELECT * FROM sources WHERE id = :id"), {"id": str(source_id)}).first()
        )

    def update_fetch_result(
        self,
        source_id: UUID | str,
        *,
        raw_file_path: str | None,
        raw_file_sha256: str | None,
        mime_type: str | None,
        crawl_status: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                UPDATE sources
                SET raw_file_path = :raw_file_path,
                    raw_file_sha256 = :raw_file_sha256,
                    mime_type = :mime_type,
                    crawl_status = :crawl_status,
                    title = coalesce(:title, title),
                    last_checked_at = now(),
                    updated_at = now()
                WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": str(source_id),
                "raw_file_path": raw_file_path,
                "raw_file_sha256": raw_file_sha256,
                "mime_type": mime_type,
                "crawl_status": crawl_status,
                "title": title,
            },
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def list_pending(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text("SELECT * FROM sources WHERE crawl_status = 'pending' ORDER BY created_at LIMIT :limit"),
            {"limit": limit},
        )
        return [dict(row._mapping) for row in rows]
