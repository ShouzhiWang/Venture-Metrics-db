import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.db.repositories.base import BaseRepository


class ChunkRepository(BaseRepository):
    def create_many(self, chunks: list[dict[str, Any]]) -> int:
        if not chunks:
            return 0
        self.connection.execute(
            text(
                """
                INSERT INTO document_chunks (
                  report_id, chunk_text, page_number, section_title,
                  chunk_type, token_count, metadata
                )
                VALUES (
                  :report_id, :chunk_text, :page_number, :section_title,
                  :chunk_type, :token_count, CAST(:metadata AS jsonb)
                )
                """
            ),
            [
                {
                    **chunk,
                    "report_id": str(chunk["report_id"]),
                    "chunk_type": chunk.get("chunk_type", "unknown"),
                    "metadata": json.dumps(chunk.get("metadata")) if chunk.get("metadata") is not None else None,
                }
                for chunk in chunks
            ],
        )
        return len(chunks)

    def list_by_report(self, report_id: UUID | str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text("SELECT * FROM document_chunks WHERE report_id = :report_id ORDER BY page_number NULLS LAST, created_at"),
            {"report_id": str(report_id)},
        )
        return [dict(row._mapping) for row in rows]

    def keyword_search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                """
                SELECT *
                FROM document_chunks
                WHERE chunk_text ILIKE :pattern
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"pattern": f"%{query}%", "limit": limit},
        )
        return [dict(row._mapping) for row in rows]
