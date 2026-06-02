"""Sync top data.gov.hk candidates for innovation ecosystem.

Syncs 4 new datasets:
1. ITC Innovation & Technology Venture Fund Investment Portfolio
2. IPD Registrations/Grants in Force
3. IPD Applications filed by Agents
4. IPD Online Search Statistics

Usage:
  python -m app.workers.sync_datagovhk_candidates
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

# Top candidates to sync (excluding already-synced IPD stats CSV)
SYNC_CANDIDATES = [
    {
        "name": "Innovation and Technology Venture Fund Investment Portfolio",
        "description": "ITVF investment portfolio data including investee companies, investment amounts, and sectors. Innovation and Technology Commission.",
        "publisher": "Innovation and Technology Commission",
        "topic": "innovation_funding",
        "csv_url": "http://www.itf.gov.hk/datagovhk/itvf_ip_20260520_e.csv",
        "portal": "data.gov.hk",
        "geography": "Hong Kong",
    },
    {
        "name": "Number of Registrations/Grants of Trade Marks, Patents and Designs in force in Hong Kong",
        "description": "IP rights currently in force in Hong Kong: trademarks, standard patents, short-term patents, designs. Intellectual Property Department.",
        "publisher": "Intellectual Property Department",
        "topic": "patents_ip",
        "csv_url": "https://www.ipd.gov.hk/datagovhk/ipstatistics/en/No_of_registrations_grants_in_force_in_hong_kong.csv",
        "portal": "data.gov.hk",
        "geography": "Hong Kong",
    },
    {
        "name": "Statistics of Trade Mark, Design and Patent Applications filed by unrepresented applicants and by agents",
        "description": "Filing statistics showing agent-represented vs unrepresented applicants. Intellectual Property Department.",
        "publisher": "Intellectual Property Department",
        "topic": "patents_ip",
        "csv_url": "https://www.ipd.gov.hk/datagovhk/ipstatistics/en/Applications-filed-by-agents.csv",
        "portal": "data.gov.hk",
        "geography": "Hong Kong",
    },
    {
        "name": "Number of Searches conducted on Trade Marks, Patents and Designs through IPD Online Search System",
        "description": "Search volume statistics for IPD's online search system. Intellectual Property Department.",
        "publisher": "Intellectual Property Department",
        "topic": "patents_ip",
        "csv_url": "https://www.ipd.gov.hk/datagovhk/ipstatistics/en/Number-of-Online-Searches.csv",
        "portal": "data.gov.hk",
        "geography": "Hong Kong",
    },
]


def download_and_parse_csv(url: str, limit: int = 500) -> dict:
    """Download a CSV and parse it. Returns metadata + rows."""
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()

    content = resp.content
    checksum = hashlib.sha256(content).hexdigest()

    # Try to parse
    rows = []
    columns = []
    row_count = 0
    try:
        df = pd.read_csv(io.BytesIO(content), nrows=limit)
        row_count = len(df)
        columns = list(df.columns)
        rows = df.head(limit).to_dict(orient="records")
        # Sanitize NaN
        for r in rows:
            for k, v in r.items():
                if isinstance(v, float) and (pd.isna(v) or v != v):
                    r[k] = None
    except Exception as exc:
        logger.warning("Failed to parse CSV from %s: %s", url, exc)

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
        parsed = download_and_parse_csv(url)
    except Exception as exc:
        result["status"] = "download_failed"
        result["error"] = str(exc)
        return result

    with engine.begin() as conn:
        ds_repo = ConnectorDatasetRepository(conn)
        res_repo = ConnectorResourceRepository(conn)
        snap_repo = ConnectorSnapshotRepository(conn)
        row_repo = ConnectorRowRepository(conn)

        # Upsert dataset
        dataset = ds_repo.upsert({
            "name": candidate["name"],
            "description": candidate["description"],
            "publisher": candidate["publisher"],
            "geography": candidate["geography"],
            "topic": candidate["topic"],
            "source_url": url,
            "portal": candidate["portal"],
            "access_type": "csv",
            "status": "synced",
            "metadata": {
                "source": "data.gov.hk_ckan",
                "columns": parsed["columns"],
                "checksum": parsed["checksum"],
            },
        })
        result["dataset_id"] = str(dataset["id"])

        # Create resource
        resource = res_repo.create({
            "dataset_id": dataset["id"],
            "resource_name": candidate["name"],
            "resource_url": url,
            "format": "csv",
            "status": "synced",
            "schema_metadata": {"columns": parsed["columns"]},
        })

        # Create snapshot
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

        # Store rows
        if parsed["rows"]:
            count = row_repo.create_bulk(snap["id"], parsed["rows"])
            result["rows_synced"] = count
            result["columns"] = parsed["columns"]

        result["status"] = "synced"

    return result


def sync_all() -> dict:
    """Sync all top candidates."""
    results = []
    for candidate in SYNC_CANDIDATES:
        print(f"\n  Syncing: {candidate['name'][:60]}...")
        result = sync_candidate(candidate)
        print(f"    Status: {result['status']}")
        if result["error"]:
            print(f"    Error: {result['error']}")
        else:
            print(f"    Rows: {result['rows_synced']}, Columns: {len(result['columns'])}")
        results.append(result)

    return {
        "total": len(results),
        "synced": sum(1 for r in results if r["status"] == "synced"),
        "failed": sum(1 for r in results if r["status"] != "synced"),
        "results": results,
    }


def main() -> None:
    configure_logging()
    print("=" * 60)
    print("Syncing Top data.gov.hk Candidates")
    print("=" * 60)

    results = sync_all()

    print(f"\n{'=' * 60}")
    print(f"Synced: {results['synced']}/{results['total']}")
    print(f"Failed: {results['failed']}/{results['total']}")

    # Save results
    output_dir = Path("/data/hermes/diagnostics/connector_priority_eval")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "datagovhk_sync_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
