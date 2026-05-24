import json
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
            "crawl_status": values.get("crawl_status", "pending"),
            "parent_source_id": str(values["parent_source_id"]) if values.get("parent_source_id") else None,
            "source_role": values.get("source_role"),
            "resolution_status": values.get("resolution_status"),
        }
        row = self.connection.execute(
            text(
                """
                INSERT INTO sources (
                  original_url, source_type, source_owner, access_type,
                  detected_format, title, notes, crawl_status,
                  parent_source_id, source_role, resolution_status
                )
                VALUES (
                  :original_url, :source_type, :source_owner, :access_type,
                  :detected_format, :title, :notes, :crawl_status,
                  :parent_source_id, :source_role, :resolution_status
                )
                ON CONFLICT (original_url) DO UPDATE SET
                  source_type = EXCLUDED.source_type,
                  detected_format = EXCLUDED.detected_format,
                  parent_source_id = coalesce(sources.parent_source_id, EXCLUDED.parent_source_id),
                  source_role = coalesce(sources.source_role, EXCLUDED.source_role),
                  resolution_status = coalesce(sources.resolution_status, EXCLUDED.resolution_status),
                  crawl_status = sources.crawl_status,
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

    def get_by_url(self, original_url: str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text("SELECT * FROM sources WHERE original_url = :original_url"),
                {"original_url": original_url},
            ).first()
        )

    def get_detail(self, source_id: UUID | str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text(
                    """
                    SELECT
                      s.*,
                      r.id AS report_id,
                      r.title AS report_title,
                      d.id AS dataset_id,
                      d.dataset_name AS dataset_name,
                      o.id AS organization_id,
                      o.name AS organization_name
                    FROM sources s
                    LEFT JOIN reports r ON r.source_id = s.id
                    LEFT JOIN datasets d ON d.source_id = s.id
                    LEFT JOIN ecosystem_organizations o ON o.source_id = s.id
                    WHERE s.id = :id
                    ORDER BY r.created_at DESC NULLS LAST, d.created_at DESC NULLS LAST
                    LIMIT 1
                    """
                ),
                {"id": str(source_id)},
            ).first()
        )

    def create_child_source(
        self,
        *,
        parent_source_id: UUID | str,
        original_url: str,
        source_type: str,
        source_role: str,
        detected_format: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        return self.upsert_by_url(
            original_url,
            {
                "source_type": source_type,
                "detected_format": detected_format,
                "notes": notes,
                "crawl_status": "pending",
                "parent_source_id": parent_source_id,
                "source_role": source_role,
                "resolution_status": "not_needed",
            },
        )

    def update_fetch_result(
        self,
        source_id: UUID | str,
        *,
        raw_file_path: str | None,
        raw_file_sha256: str | None,
        mime_type: str | None,
        crawl_status: str,
        detected_format: str | None = None,
        source_type: str | None = None,
        title: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                UPDATE sources
                SET raw_file_path = :raw_file_path,
                    raw_file_sha256 = :raw_file_sha256,
                    mime_type = :mime_type,
                    crawl_status = :crawl_status,
                    detected_format = coalesce(:detected_format, detected_format),
                    source_type = coalesce(:source_type, source_type),
                    title = coalesce(:title, title),
                    notes = coalesce(:notes, notes),
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
                "detected_format": detected_format,
                "source_type": source_type,
                "title": title,
                "notes": notes,
            },
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def update_resolution(
        self,
        source_id: UUID | str,
        *,
        source_role: str | None = None,
        resolution_status: str | None = None,
        resolved_source_id: UUID | str | None = None,
        resolution_notes: str | None = None,
        discovered_artifacts: list[dict[str, Any]] | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                UPDATE sources
                SET source_role = coalesce(:source_role, source_role),
                    resolution_status = coalesce(:resolution_status, resolution_status),
                    resolved_source_id = coalesce(:resolved_source_id, resolved_source_id),
                    resolution_notes = coalesce(:resolution_notes, resolution_notes),
                    discovered_artifacts = coalesce(CAST(:discovered_artifacts AS jsonb), discovered_artifacts),
                    updated_at = now()
                WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": str(source_id),
                "source_role": source_role,
                "resolution_status": resolution_status,
                "resolved_source_id": str(resolved_source_id) if resolved_source_id else None,
                "resolution_notes": resolution_notes,
                "discovered_artifacts": json.dumps(discovered_artifacts) if discovered_artifacts is not None else None,
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

    def update_status(self, source_id: UUID | str, *, crawl_status: str, notes: str | None = None) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                UPDATE sources
                SET crawl_status = :crawl_status,
                    notes = coalesce(:notes, notes),
                    last_checked_at = now(),
                    updated_at = now()
                WHERE id = :id
                RETURNING *
                """
            ),
            {"id": str(source_id), "crawl_status": crawl_status, "notes": notes},
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result
