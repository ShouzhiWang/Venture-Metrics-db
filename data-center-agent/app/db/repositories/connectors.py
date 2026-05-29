"""Repository for connector_datasets, connector_resources, connector_snapshots, connector_rows."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.db.repositories.base import BaseRepository, row_to_dict


class ConnectorDatasetRepository(BaseRepository):
    def get(self, dataset_id: UUID | str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text("SELECT * FROM connector_datasets WHERE id = :id"),
                {"id": str(dataset_id)},
            ).first()
        )

    def get_by_source_url(self, source_url: str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text("SELECT * FROM connector_datasets WHERE source_url = :url LIMIT 1"),
                {"url": source_url},
            ).first()
        )

    def upsert(self, values: dict[str, Any]) -> dict[str, Any]:
        existing = None
        if values.get("source_url"):
            existing = self.get_by_source_url(values["source_url"])
        if existing:
            return self.update(existing["id"], values)
        return self.create(values)

    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                INSERT INTO connector_datasets (
                  name, description, publisher, geography, topic, source_url,
                  portal, license, update_frequency, last_modified_external,
                  access_type, status, source_candidate_id, metadata
                ) VALUES (
                  :name, :description, :publisher, :geography, :topic, :source_url,
                  :portal, :license, :update_frequency, :last_modified_external,
                  :access_type, :status, :source_candidate_id, CAST(:metadata AS jsonb)
                ) RETURNING *
                """
            ),
            {
                "name": values["name"],
                "description": values.get("description"),
                "publisher": values.get("publisher"),
                "geography": values.get("geography"),
                "topic": values.get("topic"),
                "source_url": values.get("source_url"),
                "portal": values.get("portal"),
                "license": values.get("license"),
                "update_frequency": values.get("update_frequency"),
                "last_modified_external": values.get("last_modified_external"),
                "access_type": values.get("access_type", "unknown"),
                "status": values.get("status", "discovered"),
                "source_candidate_id": str(values["source_candidate_id"]) if values.get("source_candidate_id") else None,
                "metadata": json.dumps(values["metadata"]) if values.get("metadata") else None,
            },
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def update(self, dataset_id: UUID | str, values: dict[str, Any]) -> dict[str, Any]:
        sets = []
        params: dict[str, Any] = {"id": str(dataset_id)}
        for col in (
            "name", "description", "publisher", "geography", "topic",
            "source_url", "portal", "license", "update_frequency",
            "last_modified_external", "access_type", "status", "source_candidate_id",
        ):
            if col in values:
                sets.append(f"{col} = :{col}")
                params[col] = values[col]
        if "metadata" in values:
            sets.append("metadata = CAST(:metadata AS jsonb)")
            params["metadata"] = json.dumps(values["metadata"]) if values["metadata"] else None
        sets.append("updated_at = now()")
        row = self.connection.execute(
            text(f"UPDATE connector_datasets SET {', '.join(sets)} WHERE id = :id RETURNING *"),
            params,
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def list_by_status(self, status: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text("SELECT * FROM connector_datasets WHERE status = :status ORDER BY created_at"),
            {"status": status},
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def list_all(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text("SELECT * FROM connector_datasets ORDER BY created_at"),
        ).fetchall()
        return [row_to_dict(r) for r in rows]


class ConnectorResourceRepository(BaseRepository):
    def get(self, resource_id: UUID | str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text("SELECT * FROM connector_resources WHERE id = :id"),
                {"id": str(resource_id)},
            ).first()
        )

    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                INSERT INTO connector_resources (
                  dataset_id, resource_name, resource_url, format,
                  schema_metadata, local_path, status, metadata
                ) VALUES (
                  :dataset_id, :resource_name, :resource_url, :format,
                  CAST(:schema_metadata AS jsonb), :local_path, :status,
                  CAST(:metadata AS jsonb)
                ) RETURNING *
                """
            ),
            {
                "dataset_id": str(values["dataset_id"]),
                "resource_name": values.get("resource_name"),
                "resource_url": values.get("resource_url"),
                "format": values.get("format", "unknown"),
                "schema_metadata": json.dumps(values["schema_metadata"]) if values.get("schema_metadata") else None,
                "local_path": values.get("local_path"),
                "status": values.get("status", "pending"),
                "metadata": json.dumps(values["metadata"]) if values.get("metadata") else None,
            },
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def update(self, resource_id: UUID | str, values: dict[str, Any]) -> dict[str, Any]:
        sets = []
        params: dict[str, Any] = {"id": str(resource_id)}
        for col in ("resource_name", "resource_url", "format", "local_path", "status"):
            if col in values:
                sets.append(f"{col} = :{col}")
                params[col] = values[col]
        for json_col in ("schema_metadata", "metadata"):
            if json_col in values:
                sets.append(f"{json_col} = CAST(:{json_col} AS jsonb)")
                params[json_col] = json.dumps(values[json_col]) if values[json_col] else None
        sets.append("updated_at = now()")
        row = self.connection.execute(
            text(f"UPDATE connector_resources SET {', '.join(sets)} WHERE id = :id RETURNING *"),
            params,
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def list_by_dataset(self, dataset_id: UUID | str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text("SELECT * FROM connector_resources WHERE dataset_id = :did ORDER BY created_at"),
            {"did": str(dataset_id)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]


class ConnectorSnapshotRepository(BaseRepository):
    def get(self, snapshot_id: UUID | str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text("SELECT * FROM connector_snapshots WHERE id = :id"),
                {"id": str(snapshot_id)},
            ).first()
        )

    def get_latest(self, dataset_id: UUID | str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text(
                    "SELECT * FROM connector_snapshots WHERE dataset_id = :did "
                    "ORDER BY retrieved_at DESC LIMIT 1"
                ),
                {"did": str(dataset_id)},
            ).first()
        )

    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                INSERT INTO connector_snapshots (
                  dataset_id, resource_id, retrieved_at, query_params,
                  row_count, column_count, local_path, checksum,
                  schema_version, status, metadata
                ) VALUES (
                  :dataset_id, :resource_id, :retrieved_at, CAST(:query_params AS jsonb),
                  :row_count, :column_count, :local_path, :checksum,
                  :schema_version, :status, CAST(:metadata AS jsonb)
                ) RETURNING *
                """
            ),
            {
                "dataset_id": str(values["dataset_id"]),
                "resource_id": str(values["resource_id"]) if values.get("resource_id") else None,
                "retrieved_at": values.get("retrieved_at"),
                "query_params": json.dumps(values["query_params"]) if values.get("query_params") else None,
                "row_count": values.get("row_count"),
                "column_count": values.get("column_count"),
                "local_path": values.get("local_path"),
                "checksum": values.get("checksum"),
                "schema_version": values.get("schema_version"),
                "status": values.get("status", "captured"),
                "metadata": json.dumps(values["metadata"]) if values.get("metadata") else None,
            },
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def list_by_dataset(self, dataset_id: UUID | str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                "SELECT * FROM connector_snapshots WHERE dataset_id = :did ORDER BY retrieved_at DESC"
            ),
            {"did": str(dataset_id)},
        ).fetchall()
        return [row_to_dict(r) for r in rows]


class ConnectorRowRepository(BaseRepository):
    def create_bulk(self, snapshot_id: UUID | str, rows: list[dict]) -> int:
        """Insert rows in bulk. Returns count inserted."""
        import math
        count = 0
        for row_data in rows:
            # Sanitize NaN/Inf values for JSON
            clean = {}
            for k, v in row_data.items():
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    clean[k] = None
                else:
                    clean[k] = v
            self.connection.execute(
                text(
                    "INSERT INTO connector_rows (snapshot_id, row_json) "
                    "VALUES (:sid, CAST(:row_json AS jsonb))"
                ),
                {
                    "sid": str(snapshot_id),
                    "row_json": json.dumps(clean),
                },
            )
            count += 1
        return count

    def count_by_snapshot(self, snapshot_id: UUID | str) -> int:
        row = self.connection.execute(
            text("SELECT COUNT(*) FROM connector_rows WHERE snapshot_id = :sid"),
            {"sid": str(snapshot_id)},
        ).first()
        return row[0] if row else 0

    def list_by_snapshot(self, snapshot_id: UUID | str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                "SELECT * FROM connector_rows WHERE snapshot_id = :sid "
                "ORDER BY created_at LIMIT :limit"
            ),
            {"sid": str(snapshot_id), "limit": limit},
        ).fetchall()
        return [row_to_dict(r) for r in rows]
