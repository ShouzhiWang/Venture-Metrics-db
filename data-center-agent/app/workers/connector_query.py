"""Connector Query Worker.

Query external APIs/resources only when cache is missing, stale,
or user explicitly requests latest data. Stores results as snapshots.

Usage:
  python -m app.workers.connector_query --dataset-id <id> --latest
  python -m app.workers.connector_query --dataset-id <id> --max-age-hours 24
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.agents.connectors import get_connector_for_candidate
from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.connectors import (
    ConnectorDatasetRepository,
    ConnectorResourceRepository,
    ConnectorRowRepository,
    ConnectorSnapshotRepository,
)
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)


def is_snapshot_stale(snapshot: dict[str, Any], max_age_hours: int = 24) -> bool:
    """Check if a snapshot is older than max_age_hours."""
    retrieved_at = snapshot.get("retrieved_at")
    if not retrieved_at:
        return True
    if isinstance(retrieved_at, str):
        retrieved_at = datetime.fromisoformat(retrieved_at)
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - retrieved_at
    return age > timedelta(hours=max_age_hours)


def query_dataset(
    dataset_id: str,
    *,
    latest: bool = False,
    max_age_hours: int = 24,
    params: dict | None = None,
) -> dict[str, Any]:
    """Query a dataset's external source, using cache when available."""
    engine = get_engine()
    result = {
        "dataset_id": dataset_id,
        "cache_hit": False,
        "live_query": False,
        "snapshot": None,
        "rows": [],
        "metadata": {},
    }

    with engine.begin() as conn:
        ds_repo = ConnectorDatasetRepository(conn)
        res_repo = ConnectorResourceRepository(conn)
        snap_repo = ConnectorSnapshotRepository(conn)
        row_repo = ConnectorRowRepository(conn)

        dataset = ds_repo.get(dataset_id)
        if not dataset:
            return {**result, "error": f"Dataset not found: {dataset_id}"}

        result["metadata"] = {
            "name": dataset.get("name"),
            "source_url": dataset.get("source_url"),
            "portal": dataset.get("portal"),
            "access_type": dataset.get("access_type"),
        }

        # Check for cached snapshot
        latest_snap = snap_repo.get_latest(dataset_id)
        needs_live = latest or not latest_snap or is_snapshot_stale(latest_snap, max_age_hours)

        if not needs_live and latest_snap:
            # Use cache
            result["cache_hit"] = True
            result["snapshot"] = {
                "id": str(latest_snap["id"]),
                "retrieved_at": str(latest_snap.get("retrieved_at")),
                "row_count": latest_snap.get("row_count"),
                "status": latest_snap.get("status"),
            }
            # Load cached rows
            cached_rows = row_repo.list_by_snapshot(latest_snap["id"], limit=1000)
            result["rows"] = [r.get("row_json") for r in cached_rows]
            result["metadata"]["data_source"] = "cached_snapshot"
            result["metadata"]["snapshot_date"] = str(latest_snap.get("retrieved_at"))
            return result

        # Need live query
        result["live_query"] = True

        # Find connector for this dataset
        resources = res_repo.list_by_dataset(dataset_id)
        resource = resources[0] if resources else None

        # Build a candidate dict for connector dispatch
        candidate = {
            "url": dataset.get("source_url"),
            "source_kind": _access_type_to_source_kind(dataset.get("access_type", "")),
            "raw_row_metadata": dataset.get("metadata", {}),
        }

        connector = get_connector_for_candidate(candidate)
        if not connector:
            return {**result, "error": "No connector available for this dataset type"}

        # Run live query
        try:
            query_result = connector.query(dataset, params=params or {})
            if query_result.success:
                # Store as new snapshot
                snap = snap_repo.create({
                    "dataset_id": dataset_id,
                    "resource_id": resource["id"] if resource else None,
                    "query_params": params,
                    "row_count": query_result.snapshot_meta.get("row_count"),
                    "column_count": query_result.snapshot_meta.get("column_count"),
                    "status": "captured",
                    "metadata": query_result.snapshot_meta.get("metadata", {}),
                })

                # Store rows
                if query_result.rows:
                    row_repo.create_bulk(snap["id"], query_result.rows)

                result["snapshot"] = {
                    "id": str(snap["id"]),
                    "retrieved_at": str(snap.get("retrieved_at")),
                    "row_count": query_result.snapshot_meta.get("row_count"),
                    "status": "captured",
                }
                result["rows"] = query_result.rows or []
                result["metadata"]["data_source"] = "live_api"
                result["metadata"]["snapshot_date"] = str(snap.get("retrieved_at"))
            else:
                result["error"] = query_result.error
        except Exception as exc:
            result["error"] = str(exc)

    return result


def _access_type_to_source_kind(access_type: str) -> str:
    """Map connector_datasets.access_type back to source_kind for dispatch."""
    mapping = {
        "api": "api_endpoint",
        "csv": "downloadable_csv",
        "xlsx": "downloadable_xlsx",
        "html_table": "html_table",
        "portal": "official_portal",
    }
    return mapping.get(access_type, "unknown")


def main() -> None:
    parser = argparse.ArgumentParser(description="Connector Query Worker")
    parser.add_argument("--dataset-id", required=True, help="Dataset UUID to query")
    parser.add_argument("--latest", action="store_true", help="Force live query for latest data")
    parser.add_argument("--max-age-hours", type=int, default=24, help="Max cache age in hours")
    parser.add_argument("--params", type=str, default=None, help="JSON query params")
    args = parser.parse_args()

    configure_logging()

    params = json.loads(args.params) if args.params else None
    result = query_dataset(
        args.dataset_id,
        latest=args.latest,
        max_age_hours=args.max_age_hours,
        params=params,
    )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
