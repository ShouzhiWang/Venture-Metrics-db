"""Search index integration for connector data.

Adds connector_datasets, connector_candidates, and ecosystem_organizations
to the search_index table for unified search.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.db.connection import get_engine
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)


def build_connector_search_index(*, rebuild: bool = False, dry_run: bool = False) -> dict[str, int]:
    """Build search_index rows for connector data.

    Returns counts by object_type.
    """
    engine = get_engine()
    counts = {"connector_dataset": 0, "connector_candidate": 0, "organization": 0, "connector_metric": 0}

    with engine.begin() as conn:
        if rebuild:
            conn.execute(text(
                "DELETE FROM search_index WHERE object_type IN "
                "('connector_dataset', 'connector_candidate', 'connector_metric')"
            ))

        # Connector datasets
        rows = conn.execute(text(
            "SELECT id, name, description, publisher, geography, topic, "
            "source_url, portal, access_type, status "
            "FROM connector_datasets"
        )).fetchall()

        for row in rows:
            ds_id = row[0]
            search_text = _build_dataset_search_text(row)
            if dry_run:
                counts["connector_dataset"] += 1
                continue

            # For synced datasets, include snapshot metadata (row_count, column_count, retrieved_at)
            ds_metadata = {"access_type": row[8], "portal": row[7], "topic": row[4]}
            availability = "unclear"
            if row[9] == "synced":
                availability = "obtainable"
                # Fetch latest snapshot metadata
                snap_row = conn.execute(text(
                    "SELECT row_count, column_count, retrieved_at, id "
                    "FROM connector_snapshots WHERE dataset_id = :did "
                    "ORDER BY retrieved_at DESC LIMIT 1"
                ), {"did": str(ds_id)}).first()
                if snap_row:
                    ds_metadata["row_count"] = snap_row[0]
                    ds_metadata["column_count"] = snap_row[1]
                    ds_metadata["retrieved_at"] = str(snap_row[2]) if snap_row[2] else None
                    ds_metadata["snapshot_id"] = str(snap_row[3]) if snap_row[3] else None

            _upsert_search_row(conn, {
                "object_type": "connector_dataset",
                "object_id": str(ds_id),
                "title": row[1],
                "content": row[2] or row[1],
                "search_text": search_text,
                "geography": row[3],
                "source_url": row[6],
                "availability": availability,
                "metadata": ds_metadata,
            })
            counts["connector_dataset"] += 1

        # External source candidates (useful ones only)
        rows = conn.execute(text(
            "SELECT id, title, url, source_kind, geography, ecosystem_category, "
            "status, notes "
            "FROM external_source_candidates "
            "WHERE status NOT IN ('rejected', 'failed')"
        )).fetchall()

        for row in rows:
            cand_id = row[0]
            search_text = _build_candidate_search_text(row)
            if dry_run:
                counts["connector_candidate"] += 1
                continue

            _upsert_search_row(conn, {
                "object_type": "connector_candidate",
                "object_id": str(cand_id),
                "title": row[1],
                "content": row[1] or "",
                "search_text": search_text,
                "geography": row[4],
                "source_url": row[2],
                "availability": row[6],
                "metadata": {"source_kind": row[3], "ecosystem_category": row[5]},
            })
            counts["connector_candidate"] += 1

        # Ecosystem organizations (from connector TTO ingestion)
        rows = conn.execute(text(
            "SELECT id, name, description, organization_type, geography, "
            "website_url, metadata "
            "FROM ecosystem_organizations "
            "WHERE metadata->>'source' = 'curated_excel'"
        )).fetchall()

        for row in rows:
            org_id = row[0]
            search_text = _build_org_search_text(row)
            if dry_run:
                counts["organization"] += 1
                continue

            _upsert_search_row(conn, {
                "object_type": "organization",
                "object_id": str(org_id),
                "title": row[1],
                "content": row[2] or row[1],
                "search_text": search_text,
                "geography": row[4],
                "source_url": row[5],
                "availability": "obtainable",
                "metadata": {"organization_type": row[3]},
            })
            counts["organization"] += 1

        # Connector dataset metrics (include both active and needs_review)
        metric_rows = conn.execute(text(
            "SELECT m.id, m.metric_name, m.metric_description, m.unit, "
            "m.geography, m.time_period, m.category, m.dimension, "
            "m.source_url, m.retrieved_at, m.confidence_score, "
            "cd.name as dataset_name, cd.portal, cd.access_type "
            "FROM connector_dataset_metrics m "
            "JOIN connector_datasets cd ON m.dataset_id = cd.id "
            "WHERE m.status IN ('active', 'needs_review')"
        )).fetchall()

        for row in metric_rows:
            metric_id = row[0]
            search_text = _build_metric_search_text(row)
            if dry_run:
                counts["connector_metric"] += 1
                continue

            _upsert_search_row(conn, {
                "object_type": "connector_metric",
                "object_id": str(metric_id),
                "title": row[1],  # metric_name
                "content": row[2] or row[1],  # metric_description
                "search_text": search_text,
                "geography": row[4],
                "source_url": row[8],
                "availability": "obtainable",
                "metadata": {
                    "unit": row[3],
                    "category": row[6],
                    "dimension": row[7],
                    "time_period": row[5],
                    "dataset_name": row[11],
                    "portal": row[12],
                    "access_type": row[13],
                    "retrieved_at": str(row[9]) if row[9] else None,
                    "confidence_score": float(row[10]) if row[10] else None,
                },
            })
            counts["connector_metric"] += 1

    return counts


def _build_dataset_search_text(row) -> str:
    """Build search text for a connector dataset."""
    parts = []
    for i, field in enumerate(["name", "description", "publisher", "geography", "topic", "portal"]):
        val = row[i + 1] if i + 1 < len(row) else None
        if val:
            parts.append(str(val))
    if row[6]:  # source_url
        parts.append(row[6])
    if row[8]:  # access_type
        parts.append(row[8])
    return " ".join(parts)


def _build_candidate_search_text(row) -> str:
    """Build search text for a source candidate."""
    parts = []
    for val in row[1:7]:
        if val:
            parts.append(str(val))
    return " ".join(parts)


def _build_org_search_text(row) -> str:
    """Build search text for an ecosystem organization."""
    parts = []
    for val in row[1:6]:
        if val:
            parts.append(str(val))
    return " ".join(parts)


def _build_metric_search_text(row) -> str:
    """Build search text for a connector dataset metric.

    Columns: id(0), metric_name(1), metric_description(2), unit(3),
    geography(4), time_period(5), category(6), dimension(7),
    source_url(8), retrieved_at(9), confidence_score(10),
    dataset_name(11), portal(12), access_type(13)
    """
    parts = []
    # Metric identity
    for idx in (1, 2, 6, 7):  # name, description, category, dimension
        if idx < len(row) and row[idx]:
            parts.append(str(row[idx]))
    # Dataset context
    for idx in (11, 12):  # dataset_name, portal
        if idx < len(row) and row[idx]:
            parts.append(str(row[idx]))
    # Geography and unit
    if row[4]:
        parts.append(str(row[4]))
    if row[3]:
        parts.append(str(row[3]))
    return " ".join(parts)


def _upsert_search_row(conn, values: dict[str, Any]) -> None:
    """Insert or update a search_index row."""
    import json as _json
    metadata_raw = values.get("metadata", {})
    # Properly serialize to JSON (handles None, nested dicts, etc.)
    metadata_json = _json.dumps(metadata_raw, default=str, ensure_ascii=False) if metadata_raw else "{}"

    conn.execute(
        text(
            """
            INSERT INTO search_index (
              object_type, object_id, title, content, search_text,
              geography, source_url, availability, metadata
            ) VALUES (
              :object_type, :object_id, :title, :content, :search_text,
              :geography, :source_url, :availability, CAST(:metadata AS jsonb)
            )
            ON CONFLICT (object_type, object_id) DO UPDATE SET
              title = EXCLUDED.title,
              content = EXCLUDED.content,
              search_text = EXCLUDED.search_text,
              geography = EXCLUDED.geography,
              source_url = EXCLUDED.source_url,
              availability = EXCLUDED.availability,
              metadata = EXCLUDED.metadata,
              updated_at = now()
            """
        ),
        {
            "object_type": values["object_type"],
            "object_id": str(values["object_id"]),
            "title": values.get("title"),
            "content": values.get("content", ""),
            "search_text": values["search_text"],
            "geography": values.get("geography"),
            "source_url": values.get("source_url"),
            "availability": values.get("availability", "unclear"),
            "metadata": metadata_json,
        },
    )


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Build connector search index")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild from scratch")
    parser.add_argument("--dry-run", action="store_true", help="Count only, don't write")
    args = parser.parse_args()

    configure_logging()
    counts = build_connector_search_index(rebuild=args.rebuild, dry_run=args.dry_run)
    print(f"Search index {'(dry run) ' if args.dry_run else ''}counts: {counts}")


if __name__ == "__main__":
    main()
