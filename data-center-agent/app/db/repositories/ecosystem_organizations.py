import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.db.repositories.base import BaseRepository, row_to_dict


class EcosystemOrganizationRepository(BaseRepository):
    def get(self, organization_id: UUID | str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text("SELECT * FROM ecosystem_organizations WHERE id = :id"),
                {"id": str(organization_id)},
            ).first()
        )

    def get_detail(self, organization_id: UUID | str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text(
                    """
                    SELECT
                      o.*,
                      s.original_url AS source_url,
                      s.access_type AS source_access_type,
                      s.source_role AS source_role
                    FROM ecosystem_organizations o
                    LEFT JOIN sources s ON s.id = o.source_id
                    WHERE o.id = :id
                    """
                ),
                {"id": str(organization_id)},
            ).first()
        )

    def get_by_source(self, source_id: UUID | str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text("SELECT * FROM ecosystem_organizations WHERE source_id = :source_id LIMIT 1"),
                {"source_id": str(source_id)},
            ).first()
        )

    def get_by_website_url(self, website_url: str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text("SELECT * FROM ecosystem_organizations WHERE website_url = :website_url LIMIT 1"),
                {"website_url": website_url},
            ).first()
        )

    def upsert(self, values: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        existing = None
        if values.get("source_id"):
            existing = self.get_by_source(values["source_id"])
        if existing is None and values.get("website_url"):
            existing = self.get_by_website_url(values["website_url"])
        if existing:
            return self.update(existing["id"], values, force=force)
        return self.create(values)

    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                INSERT INTO ecosystem_organizations (
                  name, website_url, description, organization_type, geography,
                  country, city, region, sector_focus, stage_focus, market_focus,
                  source_id, original_source_url, confidence_score, review_status, metadata
                )
                VALUES (
                  :name, :website_url, :description, :organization_type, :geography,
                  :country, :city, :region, :sector_focus, :stage_focus, :market_focus,
                  :source_id, :original_source_url, :confidence_score, :review_status,
                  CAST(:metadata AS jsonb)
                )
                RETURNING *
                """
            ),
            self._params(values),
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def update(self, organization_id: UUID | str, values: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        assign = "name = coalesce(:name, name)" if not force else "name = :name"
        row = self.connection.execute(
            text(
                f"""
                UPDATE ecosystem_organizations
                SET {assign},
                    website_url = coalesce(:website_url, website_url),
                    description = coalesce(:description, description),
                    organization_type = coalesce(:organization_type, organization_type),
                    geography = coalesce(:geography, geography),
                    country = coalesce(:country, country),
                    city = coalesce(:city, city),
                    region = coalesce(:region, region),
                    sector_focus = coalesce(:sector_focus, sector_focus),
                    stage_focus = coalesce(:stage_focus, stage_focus),
                    market_focus = coalesce(:market_focus, market_focus),
                    source_id = coalesce(:source_id, source_id),
                    original_source_url = coalesce(:original_source_url, original_source_url),
                    confidence_score = coalesce(:confidence_score, confidence_score),
                    review_status = coalesce(:review_status, review_status),
                    metadata = coalesce(metadata, '{{}}'::jsonb) || CAST(:metadata AS jsonb),
                    updated_at = now()
                WHERE id = :id
                RETURNING *
                """
            ),
            {"id": str(organization_id), **self._params(values)},
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def list_for_index(self, *, source_id: UUID | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                """
                SELECT
                  o.*,
                  s.original_url AS source_original_url,
                  s.access_type AS source_access_type,
                  s.raw_file_path AS source_raw_file_path
                FROM ecosystem_organizations o
                LEFT JOIN sources s ON s.id = o.source_id
                WHERE (CAST(:source_id AS uuid) IS NULL OR o.source_id = CAST(:source_id AS uuid))
                ORDER BY o.updated_at DESC
                LIMIT :limit
                """
            ),
            {"source_id": str(source_id) if source_id else None, "limit": limit or 100000},
        )
        return [dict(row._mapping) for row in rows]

    def _params(self, values: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": values.get("name"),
            "website_url": values.get("website_url"),
            "description": values.get("description"),
            "organization_type": values.get("organization_type"),
            "geography": values.get("geography"),
            "country": values.get("country"),
            "city": values.get("city"),
            "region": values.get("region"),
            "sector_focus": values.get("sector_focus"),
            "stage_focus": values.get("stage_focus"),
            "market_focus": values.get("market_focus"),
            "source_id": str(values["source_id"]) if values.get("source_id") else None,
            "original_source_url": values.get("original_source_url"),
            "confidence_score": values.get("confidence_score"),
            "review_status": values.get("review_status", "pending"),
            "metadata": json.dumps(values.get("metadata") or {}, default=str),
        }
