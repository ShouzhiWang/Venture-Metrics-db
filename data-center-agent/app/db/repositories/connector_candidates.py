"""Repository for external_source_candidates table."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.db.repositories.base import BaseRepository, row_to_dict


class ExternalSourceCandidateRepository(BaseRepository):
    def get(self, candidate_id: UUID | str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text("SELECT * FROM external_source_candidates WHERE id = :id"),
                {"id": str(candidate_id)},
            ).first()
        )

    def get_by_url(self, url: str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text("SELECT * FROM external_source_candidates WHERE url = :url LIMIT 1"),
                {"url": url},
            ).first()
        )

    def upsert(self, values: dict[str, Any]) -> dict[str, Any]:
        existing = None
        if values.get("url"):
            existing = self.get_by_url(values["url"])
        if existing:
            return self.update(existing["id"], values)
        return self.create(values)

    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                INSERT INTO external_source_candidates (
                  title, url, source_kind, candidate_type, geography,
                  ecosystem_category, discovery_method, confidence_score,
                  status, source_set, raw_row_metadata, notes
                ) VALUES (
                  :title, :url, :source_kind, :candidate_type, :geography,
                  :ecosystem_category, :discovery_method, :confidence_score,
                  :status, :source_set, CAST(:raw_row_metadata AS jsonb), :notes
                ) RETURNING *
                """
            ),
            {
                "title": values.get("title"),
                "url": values.get("url"),
                "source_kind": values.get("source_kind", "unknown"),
                "candidate_type": values.get("candidate_type"),
                "geography": values.get("geography"),
                "ecosystem_category": values.get("ecosystem_category"),
                "discovery_method": values.get("discovery_method"),
                "confidence_score": values.get("confidence_score"),
                "status": values.get("status", "pending_review"),
                "source_set": values.get("source_set"),
                "raw_row_metadata": json.dumps(values["raw_row_metadata"]) if values.get("raw_row_metadata") else None,
                "notes": values.get("notes"),
            },
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def update(self, candidate_id: UUID | str, values: dict[str, Any]) -> dict[str, Any]:
        sets = []
        params: dict[str, Any] = {"id": str(candidate_id)}
        for col in (
            "title", "url", "source_kind", "candidate_type", "geography",
            "ecosystem_category", "discovery_method", "confidence_score",
            "status", "source_set", "notes",
        ):
            if col in values:
                sets.append(f"{col} = :{col}")
                params[col] = values[col]
        if "raw_row_metadata" in values:
            sets.append("raw_row_metadata = CAST(:raw_row_metadata AS jsonb)")
            params["raw_row_metadata"] = json.dumps(values["raw_row_metadata"]) if values["raw_row_metadata"] else None
        sets.append("updated_at = now()")
        row = self.connection.execute(
            text(f"UPDATE external_source_candidates SET {', '.join(sets)} WHERE id = :id RETURNING *"),
            params,
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def list_by_source_set(self, source_set: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text("SELECT * FROM external_source_candidates WHERE source_set = :ss ORDER BY created_at"),
            {"ss": source_set},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def list_by_status(self, status: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text("SELECT * FROM external_source_candidates WHERE status = :status ORDER BY created_at"),
            {"status": status},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def count_by_source_kind(self, source_set: str | None = None) -> list[dict[str, Any]]:
        if source_set:
            rows = self.connection.execute(
                text(
                    "SELECT source_kind, COUNT(*) as cnt FROM external_source_candidates "
                    "WHERE source_set = :ss GROUP BY source_kind ORDER BY cnt DESC"
                ),
                {"ss": source_set},
            ).fetchall()
        else:
            rows = self.connection.execute(
                text(
                    "SELECT source_kind, COUNT(*) as cnt FROM external_source_candidates "
                    "GROUP BY source_kind ORDER BY cnt DESC"
                ),
            ).fetchall()
        return [row_to_dict(r) for r in rows]
