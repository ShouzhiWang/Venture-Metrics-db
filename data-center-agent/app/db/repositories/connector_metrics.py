"""Repository for connector_dataset_metrics and connector_dataset_observations."""

from __future__ import annotations

import json
import math
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.db.repositories.base import BaseRepository, row_to_dict


class ConnectorMetricRepository(BaseRepository):
    def get(self, metric_id: UUID | str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text("SELECT * FROM connector_dataset_metrics WHERE id = :id"),
                {"id": str(metric_id)},
            ).first()
        )

    def list_by_dataset(self, dataset_id: UUID | str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                "SELECT * FROM connector_dataset_metrics "
                "WHERE dataset_id = :did AND status = 'active' "
                "ORDER BY category, metric_name"
            ),
            {"did": str(dataset_id)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def list_by_snapshot(self, snapshot_id: UUID | str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                "SELECT * FROM connector_dataset_metrics "
                "WHERE snapshot_id = :sid AND status = 'active' "
                "ORDER BY category, metric_name"
            ),
            {"sid": str(snapshot_id)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def get_by_name_and_dataset(self, metric_name: str, dataset_id: UUID | str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text(
                    "SELECT * FROM connector_dataset_metrics "
                    "WHERE metric_name = :name AND dataset_id = :did LIMIT 1"
                ),
                {"name": metric_name, "did": str(dataset_id)},
            ).first()
        )

    def search(
        self,
        query: str,
        *,
        geography: str | None = None,
        category: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Full-text search across metric name, description, category."""
        conditions = ["status = 'active'"]
        params: dict[str, Any] = {"q": f"%{query}%", "limit": limit}

        if geography:
            conditions.append("geography = :geo")
            params["geo"] = geography
        if category:
            conditions.append("category = :cat")
            params["cat"] = category

        where = " AND ".join(conditions)
        rows = self.connection.execute(
            text(
                f"SELECT * FROM connector_dataset_metrics "
                f"WHERE {where} AND ("
                f"  metric_name ILIKE :q OR metric_description ILIKE :q "
                f"  OR category ILIKE :q OR dimension ILIKE :q"
                f") ORDER BY confidence_score DESC LIMIT :limit"
            ),
            params,
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def count_by_geography(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                "SELECT geography, COUNT(*) as cnt "
                "FROM connector_dataset_metrics WHERE status = 'active' "
                "GROUP BY geography ORDER BY cnt DESC"
            )
        ).fetchall()
        return [{"geography": r[0], "count": r[1]} for r in rows]


class ConnectorObservationRepository(BaseRepository):
    def get(self, observation_id: UUID | str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text("SELECT * FROM connector_dataset_observations WHERE id = :id"),
                {"id": str(observation_id)},
            ).first()
        )

    def list_by_metric(self, metric_id: UUID | str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                "SELECT * FROM connector_dataset_observations "
                "WHERE metric_id = :mid AND status = 'active' "
                "ORDER BY time_period LIMIT :limit"
            ),
            {"mid": str(metric_id), "limit": limit},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def list_by_dataset(self, dataset_id: UUID | str, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                "SELECT * FROM connector_dataset_observations "
                "WHERE dataset_id = :did AND status = 'active' "
                "ORDER BY metric_id, time_period LIMIT :limit"
            ),
            {"did": str(dataset_id), "limit": limit},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def get_latest_by_metric(self, metric_id: UUID | str) -> dict[str, Any] | None:
        """Get the most recent observation for a metric."""
        return row_to_dict(
            self.connection.execute(
                text(
                    "SELECT * FROM connector_dataset_observations "
                    "WHERE metric_id = :mid AND status = 'active' "
                    "AND value_numeric IS NOT NULL "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"mid": str(metric_id)},
            ).first()
        )

    def search(
        self,
        query: str,
        *,
        geography: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search observations by metric name via join."""
        params: dict[str, Any] = {"q": f"%{query}%", "limit": limit}
        geo_clause = ""
        if geography:
            geo_clause = "AND o.geography = :geo"
            params["geo"] = geography

        rows = self.connection.execute(
            text(
                f"SELECT o.* FROM connector_dataset_observations o "
                f"JOIN connector_dataset_metrics m ON o.metric_id = m.id "
                f"WHERE m.status = 'active' AND o.status = 'active' "
                f"{geo_clause} AND ("
                f"  m.metric_name ILIKE :q OR m.metric_description ILIKE :q "
                f"  OR m.category ILIKE :q"
                f") ORDER BY o.confidence_score DESC LIMIT :limit"
            ),
            params,
        ).fetchall()
        return [row_to_dict(r) for r in rows]
