"""Connector Dataset Metric Extraction Worker.

Extracts structured metrics from synced connector dataset rows.
For each synced snapshot, parses row_json into:
- connector_dataset_metrics (metric definitions)
- connector_dataset_observations (individual data points)

Usage:
  python -m app.workers.connector_metric_extract --snapshot-id <id>
  python -m app.workers.connector_metric_extract --dataset-id <id>
  python -m app.workers.connector_metric_extract --all-synced
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.db.connection import get_engine
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)

# ============================================================
# Metric Pattern Registry
# ============================================================

# Maps row label patterns to structured metric metadata
METRIC_PATTERNS: list[dict[str, Any]] = [
    # Trademarks
    {
        "pattern": r"^Trademarks\s*[-–]\s*Applications\s+Received",
        "metric_name": "trademark_applications_received",
        "metric_description": "Number of trademark applications received",
        "unit": "count",
        "category": "trademarks",
        "dimension": "applications",
    },
    {
        "pattern": r"^Trademarks\s*[-–]\s*Applications\s+Registered",
        "metric_name": "trademark_applications_registered",
        "metric_description": "Number of trademark applications registered",
        "unit": "count",
        "category": "trademarks",
        "dimension": "registrations",
    },
    {
        "pattern": r"^Trademarks\s*[-–]\s*Providing first response",
        "metric_name": "trademark_first_response_rate",
        "metric_description": "Percentage of trademark applications receiving first response within two months",
        "unit": "percent",
        "category": "trademarks",
        "dimension": "processing_time",
    },
    {
        "pattern": r"^Trademarks\s*[-–]\s*Providing second response",
        "metric_name": "trademark_second_response_rate",
        "metric_description": "Percentage of trademark applications receiving second response within three months",
        "unit": "percent",
        "category": "trademarks",
        "dimension": "processing_time",
    },
    {
        "pattern": r"^Trademarks\s*[-–]\s*Outstanding applications pending",
        "metric_name": "trademark_applications_pending",
        "metric_description": "Number of trademark applications pending first response",
        "unit": "count",
        "category": "trademarks",
        "dimension": "pending",
    },
    # Standard Patents
    {
        "pattern": r"^Standard Patents.*Applications received",
        "metric_name": "standard_patent_applications_received",
        "metric_description": "Number of standard patent applications received",
        "unit": "count",
        "category": "standard_patents",
        "dimension": "applications",
    },
    {
        "pattern": r"^Standard Patents.*Patents granted",
        "metric_name": "standard_patents_granted",
        "metric_description": "Number of standard patents granted",
        "unit": "count",
        "category": "standard_patents",
        "dimension": "grants",
    },
    {
        "pattern": r"^Standard Patents.*Processing applications within ten days",
        "metric_name": "standard_patent_processing_rate",
        "metric_description": "Percentage of standard patent applications processed within ten days",
        "unit": "percent",
        "category": "standard_patents",
        "dimension": "processing_time",
    },
    {
        "pattern": r"^Standard Patents.*Applications pending.*first stage",
        "metric_name": "standard_patent_pending_first_stage",
        "metric_description": "Number of standard patent applications pending first examination report",
        "unit": "count",
        "category": "standard_patents",
        "dimension": "pending",
    },
    {
        "pattern": r"^Standard Patents.*Applications pending.*second stage",
        "metric_name": "standard_patent_pending_second_stage",
        "metric_description": "Number of standard patent applications pending second stage",
        "unit": "count",
        "category": "standard_patents",
        "dimension": "pending",
    },
    # Short-term Patents
    {
        "pattern": r"^Short-term Patents\s*[-–]\s*Applications received",
        "metric_name": "short_term_patent_applications_received",
        "metric_description": "Number of short-term patent applications received",
        "unit": "count",
        "category": "short_term_patents",
        "dimension": "applications",
    },
    {
        "pattern": r"^Short-term Patents\s*[-–]\s*Patents granted",
        "metric_name": "short_term_patents_granted",
        "metric_description": "Number of short-term patents granted",
        "unit": "count",
        "category": "short_term_patents",
        "dimension": "grants",
    },
    {
        "pattern": r"^Short-term Patents.*Processing applications within ten days",
        "metric_name": "short_term_patent_processing_rate",
        "metric_description": "Percentage of short-term patent applications processed within ten days",
        "unit": "percent",
        "category": "short_term_patents",
        "dimension": "processing_time",
    },
    {
        "pattern": r"^Short-term Patents.*Applications pending",
        "metric_name": "short_term_patent_applications_pending",
        "metric_description": "Number of short-term patent applications pending",
        "unit": "count",
        "category": "short_term_patents",
        "dimension": "pending",
    },
    # Designs
    {
        "pattern": r"^Designs\s*[-–]\s*Applications received\s*$",
        "metric_name": "design_applications_received",
        "metric_description": "Number of design applications received (by application)",
        "unit": "count",
        "category": "designs",
        "dimension": "applications",
    },
    {
        "pattern": r"^Designs\s*[-–]\s*Applications received.*number of designs",
        "metric_name": "design_applications_received_count",
        "metric_description": "Number of design applications received (by number of designs)",
        "unit": "count",
        "category": "designs",
        "dimension": "applications",
    },
    {
        "pattern": r"^Designs\s*[-–]\s*Designs registered",
        "metric_name": "designs_registered",
        "metric_description": "Number of designs registered",
        "unit": "count",
        "category": "designs",
        "dimension": "registrations",
    },
    {
        "pattern": r"^Designs.*Processing applications within ten days",
        "metric_name": "design_processing_rate",
        "metric_description": "Percentage of design applications processed within ten days",
        "unit": "percent",
        "category": "designs",
        "dimension": "processing_time",
    },
    {
        "pattern": r"^Designs.*Applications pending",
        "metric_name": "design_applications_pending",
        "metric_description": "Number of design applications pending",
        "unit": "count",
        "category": "designs",
        "dimension": "pending",
    },
]

# Time period column patterns
TIME_PERIOD_PATTERNS: list[dict[str, Any]] = [
    {
        "pattern": r"^Apr (\d{4}) to Mar (\d{4})",
        "extractor": lambda m: f"Apr {m.group(1)} to Mar {m.group(2)}",
        "type": "fiscal_year",
    },
    {
        "pattern": r"^Monthly average of (\d{4})",
        "extractor": lambda m: f"Monthly average {m.group(1)}",
        "type": "monthly_average",
    },
    {
        "pattern": r"^Cumulative total of (\d{4})",
        "extractor": lambda m: f"Cumulative total {m.group(1)} (Jan-Mar)",
        "type": "cumulative",
    },
    {
        "pattern": r"^as at (Mar \d{4})",
        "extractor": lambda m: f"As at {m.group(1)}",
        "type": "point_in_time",
    },
    {
        "pattern": r"^(Mar \d{4}|Jan \d{4}|Feb \d{4})\s*\(the figures are provisional",
        "extractor": lambda m: f"{m.group(1)} (provisional)",
        "type": "monthly_provisional",
    },
]


def parse_value(raw: str | None) -> tuple[str | None, float | None]:
    """Parse a value string into (display_value, numeric_value).

    Handles: "34,120", "98%", "1,537", null.
    Returns (None, None) for null/empty.
    """
    if raw is None:
        return None, None
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return None, None

    # Percentage
    if s.endswith("%"):
        try:
            return s, float(s.replace("%", "").replace(",", "")) / 100.0
        except ValueError:
            return s, None

    # Numeric with commas
    cleaned = s.replace(",", "")
    try:
        return s, float(cleaned)
    except ValueError:
        return s, None


def match_metric_pattern(label: str) -> dict[str, Any] | None:
    """Match a row label to a known metric pattern."""
    for entry in METRIC_PATTERNS:
        if re.match(entry["pattern"], label, re.IGNORECASE):
            return entry
    return None


def classify_time_period(col_name: str) -> dict[str, str] | None:
    """Classify a column name into a time period descriptor."""
    for entry in TIME_PERIOD_PATTERNS:
        m = re.match(entry["pattern"], col_name, re.IGNORECASE)
        if m:
            return {
                "time_period": entry["extractor"](m),
                "period_type": entry["type"],
            }
    return None


def extract_metrics_from_snapshot(
    snapshot_id: str,
    dataset_id: str,
    source_url: str | None,
    retrieved_at: str | None,
    geography: str = "Hong Kong",
) -> dict[str, Any]:
    """Extract structured metrics from a connector snapshot's rows.

    Returns:
        {
            "metrics": [...],  # metric definitions
            "observations": [...],  # individual data points
            "unmatched_rows": [...],  # rows that didn't match any pattern
            "summary": {...},
        }
    """
    engine = get_engine()
    metrics = []
    observations = []
    unmatched_rows = []

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, row_json FROM connector_rows WHERE snapshot_id = :sid ORDER BY created_at"),
            {"sid": snapshot_id},
        ).fetchall()

        for row_id, row_json_raw in rows:
            row_json = json.loads(row_json_raw) if isinstance(row_json_raw, str) else row_json_raw
            label = str(row_json.get("Unnamed: 0", "")).strip()

            if not label:
                unmatched_rows.append({"row_id": str(row_id), "reason": "empty label", "row_json": row_json})
                continue

            metric_def = match_metric_pattern(label)
            if not metric_def:
                unmatched_rows.append({"row_id": str(row_id), "reason": "no pattern match", "label": label, "row_json": row_json})
                continue

            # Create metric definition (one per unique metric_name)
            existing_metric = next((m for m in metrics if m["metric_name"] == metric_def["metric_name"]), None)
            if not existing_metric:
                metric_entry = {
                    "dataset_id": dataset_id,
                    "snapshot_id": snapshot_id,
                    "metric_name": metric_def["metric_name"],
                    "metric_description": metric_def["metric_description"],
                    "unit": metric_def["unit"],
                    "geography": geography,
                    "category": metric_def["category"],
                    "dimension": metric_def["dimension"],
                    "source_url": source_url,
                    "retrieved_at": retrieved_at,
                    "confidence_score": 0.85,
                    "status": "active",
                }
                metrics.append(metric_entry)
                existing_metric = metric_entry

            # Extract observations from each time-period column
            for col_name, raw_value in row_json.items():
                if col_name == "Unnamed: 0":
                    continue

                display_value, numeric_value = parse_value(raw_value)
                if display_value is None:
                    continue

                time_info = classify_time_period(col_name)
                time_period = time_info["time_period"] if time_info else col_name.strip()

                observations.append({
                    "metric_name": metric_def["metric_name"],
                    "dataset_id": dataset_id,
                    "snapshot_id": snapshot_id,
                    "value": display_value,
                    "value_numeric": numeric_value,
                    "time_period": time_period,
                    "geography": geography,
                    "unit": metric_def["unit"],
                    "dimension": metric_def["dimension"],
                    "row_json": row_json,
                    "confidence_score": 0.85 if numeric_value is not None else 0.6,
                    "status": "active" if numeric_value is not None else "needs_review",
                })

    return {
        "metrics": metrics,
        "observations": observations,
        "unmatched_rows": unmatched_rows,
        "summary": {
            "total_rows": len(rows),
            "metrics_extracted": len(metrics),
            "observations_extracted": len(observations),
            "unmatched_rows": len(unmatched_rows),
        },
    }


def store_metrics_and_observations(extracted: dict[str, Any]) -> dict[str, Any]:
    """Store extracted metrics and observations in the database."""
    engine = get_engine()
    stored_metrics = 0
    stored_observations = 0

    with engine.begin() as conn:
        # Store metric definitions
        for metric in extracted["metrics"]:
            conn.execute(
                text("""
                    INSERT INTO connector_dataset_metrics (
                        dataset_id, snapshot_id, metric_name, metric_description,
                        unit, geography, category, dimension,
                        source_url, retrieved_at, confidence_score, status
                    ) VALUES (
                        :dataset_id, :snapshot_id, :metric_name, :metric_description,
                        :unit, :geography, :category, :dimension,
                        :source_url, :retrieved_at, :confidence_score, :status
                    )
                """),
                {
                    "dataset_id": metric["dataset_id"],
                    "snapshot_id": metric["snapshot_id"],
                    "metric_name": metric["metric_name"],
                    "metric_description": metric["metric_description"],
                    "unit": metric["unit"],
                    "geography": metric["geography"],
                    "category": metric["category"],
                    "dimension": metric["dimension"],
                    "source_url": metric["source_url"],
                    "retrieved_at": metric["retrieved_at"],
                    "confidence_score": metric["confidence_score"],
                    "status": metric["status"],
                },
            )
            stored_metrics += 1

        # Fetch metric IDs for observation linking
        metric_id_map = {}
        if extracted["metrics"]:
            metric_names = [m["metric_name"] for m in extracted["metrics"]]
            dataset_id = extracted["metrics"][0]["dataset_id"]
            rows = conn.execute(
                text(
                    "SELECT id, metric_name FROM connector_dataset_metrics "
                    "WHERE dataset_id = :did AND metric_name = ANY(:names)"
                ),
                {"did": dataset_id, "names": metric_names},
            ).fetchall()
            metric_id_map = {r[1]: str(r[0]) for r in rows}

        # Store observations
        for obs in extracted["observations"]:
            metric_id = metric_id_map.get(obs["metric_name"])
            if not metric_id:
                logger.warning("No metric_id for %s, skipping observation", obs["metric_name"])
                continue

            # Sanitize NaN
            value_numeric = obs.get("value_numeric")
            if value_numeric is not None and (math.isnan(value_numeric) or math.isinf(value_numeric)):
                value_numeric = None

            conn.execute(
                text("""
                    INSERT INTO connector_dataset_observations (
                        metric_id, dataset_id, snapshot_id,
                        value, value_numeric, time_period, geography,
                        unit, dimension, row_json, confidence_score, status
                    ) VALUES (
                        :metric_id, :dataset_id, :snapshot_id,
                        :value, :value_numeric, :time_period, :geography,
                        :unit, :dimension, CAST(:row_json AS jsonb), :confidence_score, :status
                    )
                """),
                {
                    "metric_id": metric_id,
                    "dataset_id": obs["dataset_id"],
                    "snapshot_id": obs["snapshot_id"],
                    "value": obs["value"],
                    "value_numeric": value_numeric,
                    "time_period": obs["time_period"],
                    "geography": obs["geography"],
                    "unit": obs["unit"],
                    "dimension": obs["dimension"],
                    "row_json": json.dumps(obs["row_json"]),
                    "confidence_score": obs["confidence_score"],
                    "status": obs["status"],
                },
            )
            stored_observations += 1

    return {
        "stored_metrics": stored_metrics,
        "stored_observations": stored_observations,
    }


def extract_and_store_all_synced() -> dict[str, Any]:
    """Find all synced datasets and extract metrics from their latest snapshots."""
    engine = get_engine()
    results = []

    with engine.begin() as conn:
        synced_datasets = conn.execute(
            text(
                "SELECT cd.id, cd.source_url, cd.geography, cs.id as snap_id, cs.retrieved_at "
                "FROM connector_datasets cd "
                "JOIN connector_snapshots cs ON cs.dataset_id = cd.id "
                "WHERE cd.status = 'synced' "
                "ORDER BY cs.retrieved_at DESC"
            )
        ).fetchall()

        for ds_id, source_url, geography, snap_id, retrieved_at in synced_datasets:
            # Check if metrics already exist for this snapshot
            existing = conn.execute(
                text("SELECT COUNT(*) FROM connector_dataset_metrics WHERE snapshot_id = :sid"),
                {"sid": str(snap_id)},
            ).scalar()

            if existing and existing > 0:
                results.append({
                    "dataset_id": str(ds_id),
                    "snapshot_id": str(snap_id),
                    "status": "already_extracted",
                    "existing_metrics": existing,
                })
                continue

            extracted = extract_metrics_from_snapshot(
                snapshot_id=str(snap_id),
                dataset_id=str(ds_id),
                source_url=source_url,
                retrieved_at=str(retrieved_at) if retrieved_at else None,
                geography=geography or "Hong Kong",
            )

            stored = store_metrics_and_observations(extracted)

            results.append({
                "dataset_id": str(ds_id),
                "snapshot_id": str(snap_id),
                "status": "extracted",
                **extracted["summary"],
                **stored,
            })

    return {"datasets": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Connector Dataset Metric Extraction")
    parser.add_argument("--snapshot-id", help="Extract metrics from a specific snapshot")
    parser.add_argument("--dataset-id", help="Extract metrics from the latest snapshot of a dataset")
    parser.add_argument("--all-synced", action="store_true", help="Extract metrics from all synced datasets")
    parser.add_argument("--dry-run", action="store_true", help="Extract but don't store")
    args = parser.parse_args()

    configure_logging()

    if args.snapshot_id:
        engine = get_engine()
        with engine.begin() as conn:
            snap = conn.execute(
                text("SELECT dataset_id, metadata FROM connector_snapshots WHERE id = :sid"),
                {"sid": args.snapshot_id},
            ).first()
            if not snap:
                print(f"Snapshot not found: {args.snapshot_id}")
                return
            ds = conn.execute(
                text("SELECT source_url, geography FROM connector_datasets WHERE id = :did"),
                {"did": str(snap[0])},
            ).first()
            meta = json.loads(snap[1]) if isinstance(snap[1], str) else (snap[1] or {})

        extracted = extract_metrics_from_snapshot(
            snapshot_id=args.snapshot_id,
            dataset_id=str(snap[0]),
            source_url=ds[0] if ds else None,
            retrieved_at=None,
            geography=ds[1] if ds else "Hong Kong",
        )

        if args.dry_run:
            print(json.dumps(extracted, indent=2, default=str, ensure_ascii=False))
        else:
            stored = store_metrics_and_observations(extracted)
            print(json.dumps({"extracted": extracted["summary"], "stored": stored}, indent=2))

    elif args.dataset_id:
        engine = get_engine()
        with engine.begin() as conn:
            snap = conn.execute(
                text(
                    "SELECT id, retrieved_at FROM connector_snapshots "
                    "WHERE dataset_id = :did ORDER BY retrieved_at DESC LIMIT 1"
                ),
                {"did": args.dataset_id},
            ).first()
            if not snap:
                print(f"No snapshots for dataset: {args.dataset_id}")
                return
            ds = conn.execute(
                text("SELECT source_url, geography FROM connector_datasets WHERE id = :did"),
                {"did": args.dataset_id},
            ).first()

        extracted = extract_metrics_from_snapshot(
            snapshot_id=str(snap[0]),
            dataset_id=args.dataset_id,
            source_url=ds[0] if ds else None,
            retrieved_at=str(snap[1]) if snap[1] else None,
            geography=ds[1] if ds else "Hong Kong",
        )

        if args.dry_run:
            print(json.dumps(extracted, indent=2, default=str, ensure_ascii=False))
        else:
            stored = store_metrics_and_observations(extracted)
            print(json.dumps({"extracted": extracted["summary"], "stored": stored}, indent=2))

    elif args.all_synced:
        results = extract_and_store_all_synced()
        print(json.dumps(results, indent=2, default=str))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
