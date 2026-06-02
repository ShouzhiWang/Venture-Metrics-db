"""Sync expanded data.gov.hk datasets.

Syncs remaining IPD datasets and key Census innovation-relevant datasets.

Usage:
  python -m app.workers.sync_datagovhk_expanded
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd
from sqlalchemy import text

from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.connectors import (
    ConnectorDatasetRepository,
    ConnectorResourceRepository,
    ConnectorSnapshotRepository,
    ConnectorRowRepository,
)
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)

# Remaining IPD datasets (not yet synced)
IPD_DATASETS = [
    {
        "name": "Statistics of Trade Mark Registrations by Origin and by Class",
        "description": "Trade mark registrations broken down by country/region of origin and Nice classification class. IPD.",
        "publisher": "Intellectual Property Department",
        "topic": "patents_ip",
        "csv_url": "https://www.ipd.gov.hk/datagovhk/ipstatistics/en/Statistics-of-trade-mark-registrations-by-origin-class.csv",
    },
    {
        "name": "Statistics of Trade Mark Applications by Origin and by Class",
        "description": "Trade mark applications broken down by country/region of origin and Nice classification class. IPD.",
        "publisher": "Intellectual Property Department",
        "topic": "patents_ip",
        "csv_url": "https://www.ipd.gov.hk/datagovhk/ipstatistics/en/Statistics-of-trade-mark-applications-by-origin-class.csv",
    },
    {
        "name": "Statistics of Trade Marks in Force by Year of Registration",
        "description": "Trade marks currently in force, broken down by year of registration. IPD.",
        "publisher": "Intellectual Property Department",
        "topic": "patents_ip",
        "csv_url": "https://www.ipd.gov.hk/datagovhk/ipstatistics/en/Statistics-of-trade-marks-in-force-by-registration.csv",
    },
    {
        "name": "Statistics of Collective and Certification Marks in Force",
        "description": "Collective and certification marks currently in force by year of registration. IPD.",
        "publisher": "Intellectual Property Department",
        "topic": "patents_ip",
        "csv_url": "https://www.ipd.gov.hk/datagovhk/ipstatistics/en/Statistics-of-collective-and-certification-marks-in-force-by-registration.csv",
    },
]

# Key Census datasets for innovation ecosystem
CENSUS_DATASETS = [
    {
        "name": "Employed persons by industry and occupation of main employment",
        "description": "Labour force statistics: employed persons by industry and occupation. Census and Statistics Department.",
        "publisher": "Census and Statistics Department",
        "topic": "employment",
        "csv_url": "https://www.censtatd.gov.hk/en/web_table.html?id=210-06308&full_series=1&download_excel=1",
    },
    {
        "name": "Employed persons by industry of main employment, age and sex",
        "description": "Labour force statistics: employed persons by industry, age and sex. Census and Statistics Department.",
        "publisher": "Census and Statistics Department",
        "topic": "employment",
        "csv_url": "https://www.censtatd.gov.hk/en/web_table.html?id=210-06306&full_series=1&download_excel=1",
    },
    {
        "name": "Median monthly employment earnings by occupation and sex",
        "description": "Earnings statistics: median monthly employment earnings by occupation. Census and Statistics Department.",
        "publisher": "Census and Statistics Department",
        "topic": "employment",
        "csv_url": "https://www.censtatd.gov.hk/en/web_table.html?id=210-06321&full_series=1&download_excel=1",
    },
    {
        "name": "Median monthly employment earnings by industry and sex",
        "description": "Earnings statistics: median monthly employment earnings by industry. Census and Statistics Department.",
        "publisher": "Census and Statistics Department",
        "topic": "employment",
        "csv_url": "https://www.censtatd.gov.hk/en/web_table.html?id=210-06320&full_series=1&download_excel=1",
    },
    {
        "name": "Employed persons by employment status, age and sex",
        "description": "Labour force statistics: employed persons by employment status. Census and Statistics Department.",
        "publisher": "Census and Statistics Department",
        "topic": "employment",
        "csv_url": "https://www.censtatd.gov.hk/en/web_table.html?id=210-06303&full_series=1&download_excel=1",
    },
    {
        "name": "Stoppages of work by industry",
        "description": "Work stoppages by industry sector. Census and Statistics Department.",
        "publisher": "Census and Statistics Department",
        "topic": "employment",
        "csv_url": "https://www.censtatd.gov.hk/en/web_table.html?id=990-92061&full_series=1&download_excel=1",
    },
]


def download_and_parse(url: str, limit: int = 500) -> dict:
    """Download and parse a CSV/Excel file."""
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()

    content = resp.content
    checksum = hashlib.sha256(content).hexdigest()
    content_type = resp.headers.get("content-type", "")

    rows = []
    columns = []
    row_count = 0

    try:
        if "excel" in content_type or url.endswith((".xlsx", ".xls")) or "download_excel" in url:
            df = pd.read_excel(io.BytesIO(content), nrows=limit)
        else:
            # Try CSV with different encodings
            for encoding in ["utf-8", "utf-8-sig", "latin-1"]:
                try:
                    df = pd.read_csv(io.BytesIO(content), nrows=limit, encoding=encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                return {"error": "Could not decode file", "content": content, "checksum": checksum}

        row_count = len(df)
        columns = list(df.columns)
        rows = df.head(limit).to_dict(orient="records")
        # Sanitize NaN
        for r in rows:
            for k, v in r.items():
                if isinstance(v, float) and (pd.isna(v) or v != v):
                    r[k] = None
    except Exception as exc:
        logger.warning("Failed to parse from %s: %s", url, exc)
        return {"error": str(exc), "content": content, "checksum": checksum}

    return {
        "content": content,
        "checksum": checksum,
        "row_count": row_count,
        "column_count": len(columns),
        "columns": columns,
        "rows": rows,
    }


def sync_candidate(candidate: dict) -> dict:
    """Sync a single candidate dataset."""
    engine = get_engine()
    url = candidate["csv_url"]

    result = {
        "name": candidate["name"],
        "url": url,
        "status": "pending",
        "dataset_id": None,
        "snapshot_id": None,
        "rows_synced": 0,
        "columns": [],
        "error": None,
    }

    try:
        parsed = download_and_parse(url)
    except Exception as exc:
        result["status"] = "download_failed"
        result["error"] = str(exc)
        return result

    if "error" in parsed:
        result["status"] = "parse_failed"
        result["error"] = parsed["error"]
        return result

    with engine.begin() as conn:
        ds_repo = ConnectorDatasetRepository(conn)
        res_repo = ConnectorResourceRepository(conn)
        snap_repo = ConnectorSnapshotRepository(conn)
        row_repo = ConnectorRowRepository(conn)

        # Check if already synced (by URL)
        existing = ds_repo.get_by_source_url(url)
        if existing and existing.get("status") == "synced":
            result["status"] = "already_synced"
            result["dataset_id"] = str(existing["id"])
            return result

        dataset = ds_repo.upsert({
            "name": candidate["name"],
            "description": candidate.get("description", ""),
            "publisher": candidate.get("publisher", ""),
            "geography": "Hong Kong",
            "topic": candidate.get("topic", "general"),
            "source_url": url,
            "portal": "data.gov.hk",
            "access_type": "csv",
            "status": "synced",
            "metadata": {
                "source": "data.gov.hk_ckan",
                "columns": parsed["columns"],
                "checksum": parsed["checksum"],
            },
        })
        result["dataset_id"] = str(dataset["id"])

        resource = res_repo.create({
            "dataset_id": dataset["id"],
            "resource_name": candidate["name"],
            "resource_url": url,
            "format": "csv",
            "status": "synced",
            "schema_metadata": {"columns": parsed["columns"]},
        })

        snap = snap_repo.create({
            "dataset_id": dataset["id"],
            "resource_id": resource["id"],
            "retrieved_at": datetime.now(timezone.utc),
            "row_count": parsed["row_count"],
            "column_count": parsed["column_count"],
            "status": "captured",
            "metadata": {
                "format": "csv",
                "source": "data.gov.hk_ckan",
                "columns": parsed["columns"],
                "checksum": parsed["checksum"],
            },
        })
        result["snapshot_id"] = str(snap["id"])

        if parsed["rows"]:
            count = row_repo.create_bulk(snap["id"], parsed["rows"])
            result["rows_synced"] = count
            result["columns"] = parsed["columns"]

        result["status"] = "synced"

    return result


def sync_all() -> dict:
    """Sync all candidates."""
    all_candidates = IPD_DATASETS + CENSUS_DATASETS
    results = []

    for candidate in all_candidates:
        print(f"\n  Syncing: {candidate['name'][:60]}...")
        result = sync_candidate(candidate)
        print(f"    Status: {result['status']}")
        if result["error"]:
            print(f"    Error: {result['error']}")
        elif result["status"] == "synced":
            print(f"    Rows: {result['rows_synced']}, Columns: {len(result['columns'])}")
        results.append(result)

    synced = sum(1 for r in results if r["status"] in ("synced", "already_synced"))
    return {
        "total": len(results),
        "synced": synced,
        "failed": sum(1 for r in results if r["status"] not in ("synced", "already_synced")),
        "results": results,
    }


def main() -> None:
    configure_logging()
    print("=" * 60)
    print("Syncing Expanded data.gov.hk Datasets")
    print("=" * 60)
    print(f"  IPD datasets: {len(IPD_DATASETS)}")
    print(f"  Census datasets: {len(CENSUS_DATASETS)}")

    results = sync_all()

    print(f"\n{'=' * 60}")
    print(f"Synced: {results['synced']}/{results['total']}")
    print(f"Failed: {results['failed']}/{results['total']}")

    output_dir = Path("/data/hermes/diagnostics/connector_priority_eval")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "datagovhk_expanded_sync_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
