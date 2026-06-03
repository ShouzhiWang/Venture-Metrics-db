"""Sync worker for data.gov.sg — Singapore's open data portal.

Uses the public v2 API to discover and sync datasets:
  - List datasets:  GET https://api-production.data.gov.sg/v2/public/api/datasets?page={n}
  - Dataset metadata: GET https://api-production.data.gov.sg/v2/public/api/datasets/{id}/metadata
  - Datastore search: GET https://data.gov.sg/api/action/datastore_search?resource_id={id}
  - Download: GET https://api-open.data.gov.sg/v1/public/api/datasets/{id}/initiate-download

Usage:
  python -m app.workers.sync_datagovsg --discover
  python -m app.workers.sync_datagovsg --sync --limit 10
  python -m app.workers.sync_datagovsg --sync --limit 5 --dry-run
  python -m app.workers.sync_datagovsg --search "economy"
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.connector_candidates import ExternalSourceCandidateRepository
from app.db.repositories.connectors import (
    ConnectorDatasetRepository,
    ConnectorResourceRepository,
    ConnectorRowRepository,
    ConnectorSnapshotRepository,
)
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)

# ── API endpoints ──────────────────────────────────────────────────────────
BASE_URL = "https://api-production.data.gov.sg"
DATASETS_URL = f"{BASE_URL}/v2/public/api/datasets"
COLLECTIONS_URL = f"{BASE_URL}/v2/public/api/collections"
METADATA_URL = f"{BASE_URL}/v2/public/api/datasets/{{dataset_id}}/metadata"
DATASTORE_URL = "https://data.gov.sg/api/action/datastore_search"
DOWNLOAD_INIT_URL = "https://api-open.data.gov.sg/v1/public/api/datasets/{{dataset_id}}/initiate-download"

DIAGNOSTICS_DIR = Path("/data/hermes/diagnostics/datagovsg_sync")
PAGE_SIZE = 10  # API returns 10 per page

# Categories relevant to innovation/venture ecosystem
INNOVATION_KEYWORDS = [
    "economy", "gdp", "trade", "investment", "business", "startup",
    "innovation", "technology", "patent", "employment", "labour",
    "labor", "wage", "productivity", "research", "education",
    "finance", "banking", "venture", "entrepreneur", "SME",
    "digital", "ict", "science", "rd", "r&d", "知识产权",
]

# Agencies with high innovation-ecosystem relevance
RELEVANT_AGENCIES = [
    "Ministry of Trade and Industry",
    "Economic Development Board",
    "Enterprise Singapore",
    "Monetary Authority of Singapore",
    "Ministry of Manpower",
    "Infocomm Media Development Authority",
    "Agency for Science, Technology and Research",
    "National Research Foundation",
    "Ministry of Education",
    "Department of Statistics",
    "Intellectual Property Office of Singapore",
]


def _get_headers() -> dict:
    """HTTP headers for API requests."""
    return {
        "Accept": "application/json",
        "User-Agent": "Venture-Metrics-DB/1.0 (connector sync)",
    }


def discover_datasets(max_pages: int = 50) -> list[dict]:
    """Discover all datasets from data.gov.sg API.

    Args:
        max_pages: Maximum pages to fetch (10 datasets per page).

    Returns:
        List of dataset metadata dicts.
    """
    all_datasets = []
    client = httpx.Client(timeout=30, headers=_get_headers())

    for page in range(1, max_pages + 1):
        try:
            resp = client.get(DATASETS_URL, params={"page": page})
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                logger.warning("API error on page %d: %s", page, data.get("errorMsg"))
                break

            datasets = data.get("data", {}).get("datasets", [])
            if not datasets:
                break

            all_datasets.extend(datasets)
            total_pages = data.get("data", {}).get("pages", 1)

            logger.info("Page %d/%d: %d datasets (total so far: %d)",
                        page, total_pages, len(datasets), len(all_datasets))

            if page >= total_pages:
                break

            time.sleep(0.3)  # Be polite

        except Exception as e:
            logger.error("Failed to fetch page %d: %s", page, e)
            break

    client.close()
    return all_datasets


def get_dataset_metadata(dataset_id: str) -> dict | None:
    """Fetch detailed metadata for a single dataset."""
    url = METADATA_URL.format(dataset_id=dataset_id)
    try:
        resp = httpx.get(url, timeout=30, headers=_get_headers())
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 0:
            # API returns metadata directly in data, not data.datasetMetadata
            return data.get("data")
    except Exception as e:
        logger.error("Failed to fetch metadata for %s: %s", dataset_id, e)
    return None


def search_datastore(dataset_id: str, limit: int = 100, offset: int = 0) -> dict | None:
    """Search rows in a dataset via the CKAN-style datastore API."""
    try:
        resp = httpx.get(DATASTORE_URL, params={
            "resource_id": dataset_id,
            "limit": limit,
            "offset": offset,
        }, timeout=60, headers=_get_headers())
        resp.raise_for_status()
        data = resp.json()
        if data.get("success"):
            return data.get("result")
    except Exception as e:
        logger.error("Datastore search failed for %s: %s", dataset_id, e)
    return None


def fetch_all_rows(dataset_id: str, max_rows: int = 10000) -> tuple[list[dict], list[dict]]:
    """Fetch all rows from a dataset via datastore search with pagination.

    Returns:
        Tuple of (fields, rows).
    """
    all_rows = []
    fields = []
    offset = 0
    page_size = 1000  # Max per request

    while offset < max_rows:
        result = search_datastore(dataset_id, limit=page_size, offset=offset)
        if not result:
            break

        if not fields:
            fields = result.get("fields", [])

        records = result.get("records", [])
        if not records:
            break

        all_rows.extend(records)
        total = result.get("total", 0)
        offset += len(records)

        if offset >= total or offset >= max_rows:
            break

        time.sleep(0.3)

    return fields, all_rows


def _relevance_score(ds: dict) -> float:
    """Score a dataset's relevance to the innovation/venture ecosystem."""
    score = 0.0
    name = (ds.get("name") or "").lower()
    agency = (ds.get("managedByAgencyName") or "").lower()

    # Keyword match in name
    for kw in INNOVATION_KEYWORDS:
        if kw.lower() in name:
            score += 1.0

    # Agency relevance
    for agency_name in RELEVANT_AGENCIES:
        if agency_name.lower() in agency:
            score += 2.0
            break

    # Prefer CSV format (easier to sync)
    fmt = (ds.get("format") or "").upper()
    if fmt == "CSV":
        score += 0.5

    # Prefer recent data
    coverage_end = ds.get("coverageEnd")
    if coverage_end:
        try:
            year = int(str(coverage_end)[:4])
            if year >= 2023:
                score += 1.0
            elif year >= 2020:
                score += 0.5
        except (ValueError, TypeError):
            pass

    return score


def store_discovery(all_datasets: list[dict]) -> dict:
    """Store discovered datasets as external_source_candidates.

    Returns:
        Summary dict with counts.
    """
    engine = get_engine()
    stored = 0
    updated = 0
    skipped = 0

    with engine.begin() as conn:
        cand_repo = ExternalSourceCandidateRepository(conn)

        for ds in all_datasets:
            dataset_id = ds.get("datasetId")
            name = ds.get("name", "")
            url = f"https://data.gov.sg/datasets/{dataset_id}/view"
            agency = ds.get("managedByAgencyName", "")
            fmt = ds.get("format", "")
            score = _relevance_score(ds)

            # Classify source_kind by format
            source_kind = "downloadable_csv"
            if fmt.upper() in ("XLSX", "XLS"):
                source_kind = "downloadable_xlsx"
            elif fmt.upper() in ("JSON", "GEOJSON", "KML", "KMZ"):
                source_kind = "api_endpoint"
            elif fmt.upper() in ("PDF",):
                source_kind = "downloadable_pdf"

            existing = cand_repo.get_by_url(url)
            candidate_data = {
                "title": f"{name} ({agency})" if agency else name,
                "url": url,
                "source_kind": source_kind,
                "geography": "Singapore",
                "ecosystem_category": "public_dataset",
                "discovery_method": "api_discovery",
                "confidence_score": min(score / 5.0, 1.0),
                "status": "approved" if score >= 2.0 else "pending_review",
                "metadata": json.dumps({
                    "dataset_id": dataset_id,
                    "agency": agency,
                    "format": fmt,
                    "coverage_start": ds.get("coverageStart"),
                    "coverage_end": ds.get("coverageEnd"),
                    "last_updated": ds.get("lastUpdatedAt"),
                    "created_at": ds.get("createdAt"),
                }, default=str),
            }

            if existing:
                cand_repo.upsert(candidate_data)
                updated += 1
            else:
                cand_repo.upsert(candidate_data)
                stored += 1

    return {
        "total_discovered": len(all_datasets),
        "stored": stored,
        "updated": updated,
        "skipped": skipped,
    }


def sync_dataset(dataset_id: str, *, dry_run: bool = False) -> dict:
    """Sync a single dataset: fetch metadata, download rows, create snapshot.

    Args:
        dataset_id: The dataset ID (e.g., d_8b84c4ee58e3cfc0ece0d773c8ca6abc).
        dry_run: If True, don't write to DB.

    Returns:
        Sync result dict.
    """
    result = {
        "dataset_id": dataset_id,
        "status": "pending",
        "rows_synced": 0,
        "columns": [],
        "error": None,
    }

    # 1. Fetch metadata
    metadata = get_dataset_metadata(dataset_id)
    if not metadata:
        result["status"] = "metadata_failed"
        result["error"] = "Could not fetch metadata"
        return result

    name = metadata.get("name", dataset_id)
    agency = metadata.get("managedByAgencyName", "")
    description = metadata.get("description", "")
    fmt = metadata.get("format", "CSV")

    logger.info("Syncing: %s [%s] by %s", name, fmt, agency)

    # 2. Fetch data rows (only for tabular formats)
    fields = []
    rows = []
    if fmt.upper() in ("CSV", "XLSX"):
        fields, rows = fetch_all_rows(dataset_id, max_rows=10000)
        result["rows_synced"] = len(rows)
        result["columns"] = [f.get("id", f.get("type", "")) for f in fields if isinstance(f, dict)]
        logger.info("  Fetched %d rows, %d columns", len(rows), len(fields))

    if dry_run:
        result["status"] = "dry_run"
        result["metadata"] = metadata
        result["sample_rows"] = rows[:3]
        return result

    # 3. Store in connector tables
    engine = get_engine()
    settings = get_settings()

    with engine.begin() as conn:
        ds_repo = ConnectorDatasetRepository(conn)
        res_repo = ConnectorResourceRepository(conn)
        snap_repo = ConnectorSnapshotRepository(conn)
        row_repo = ConnectorRowRepository(conn)

        # Upsert dataset
        dataset = ds_repo.upsert({
            "name": name,
            "description": description or f"Singapore government dataset from {agency}",
            "publisher": agency,
            "geography": "Singapore",
            "topic": "public_dataset",
            "source_url": f"https://data.gov.sg/datasets/{dataset_id}/view",
            "portal": "data.gov.sg",
            "access_type": fmt.lower() if fmt else "csv",
            "status": "synced",
            "metadata": json.dumps({
                "dataset_id": dataset_id,
                "coverage_start": metadata.get("coverageStart"),
                "coverage_end": metadata.get("coverageEnd"),
                "last_updated": metadata.get("lastUpdatedAt"),
                "frequency": metadata.get("frequency"),
                "sources": metadata.get("sources", []),
            }, default=str),
        })

        # Create resource
        resource = res_repo.create({
            "dataset_id": dataset["id"],
            "name": f"{name} ({fmt})",
            "url": f"https://data.gov.sg/datasets/{dataset_id}/view",
            "format": fmt.lower() if fmt else "csv",
            "status": "synced",
        })

        # Create snapshot
        now = datetime.now(timezone.utc)
        snap = snap_repo.create({
            "dataset_id": dataset["id"],
            "resource_id": resource["id"],
            "retrieved_at": now,
            "row_count": len(rows),
            "column_count": len(fields),
        })

        # Store rows
        if rows:
            row_data = []
            for r in rows:
                # Clean row - remove _id if present
                clean = {k: v for k, v in r.items() if k != "_id"}
                # Sanitize NaN/None values
                sanitized = {}
                for k, v in clean.items():
                    if v is None or (isinstance(v, float) and math.isnan(v)):
                        sanitized[k] = None
                    else:
                        sanitized[k] = v
                row_data.append(sanitized)

            row_repo.create_bulk(snap["id"], row_data)
            logger.info("  Stored %d rows in snapshot %s", len(row_data), snap["id"])

    result["status"] = "synced"
    result["dataset_db_id"] = str(dataset["id"])
    result["snapshot_id"] = str(snap["id"])
    return result


def sync_top_datasets(
    *,
    limit: int = 10,
    dry_run: bool = False,
    filter_format: str = "CSV",
) -> dict:
    """Discover and sync the top N most relevant datasets.

    Args:
        limit: Number of datasets to sync.
        dry_run: If True, don't write to DB.
        filter_format: Only sync datasets of this format (CSV, XLSX, etc.)
    """
    logger.info("Discovering datasets from data.gov.sg...")
    all_datasets = discover_datasets(max_pages=50)  # Up to 500 datasets
    logger.info("Discovered %d total datasets", len(all_datasets))

    # Filter by format
    if filter_format:
        all_datasets = [d for d in all_datasets
                       if (d.get("format") or "").upper() == filter_format.upper()]
        logger.info("After format filter (%s): %d datasets", filter_format, len(all_datasets))

    # Score and sort by relevance
    scored = [(ds, _relevance_score(ds)) for ds in all_datasets]
    scored.sort(key=lambda x: x[1], reverse=True)

    top = scored[:limit]
    logger.info("Top %d datasets by relevance:", len(top))
    for ds, score in top:
        logger.info("  %.1f - %s [%s] by %s",
                    score, ds.get("name"), ds.get("format"), ds.get("managedByAgencyName"))

    # Sync each
    results = []
    for ds, score in top:
        dataset_id = ds.get("datasetId")
        if not dataset_id:
            continue
        r = sync_dataset(dataset_id, dry_run=dry_run)
        r["relevance_score"] = score
        results.append(r)
        time.sleep(0.5)  # Rate limiting

    return {
        "total_discovered": len(all_datasets),
        "synced": len([r for r in results if r["status"] == "synced"]),
        "dry_run": len([r for r in results if r["status"] == "dry_run"]),
        "failed": len([r for r in results if r["status"] in ("metadata_failed", "error")]),
        "results": results,
    }


def search_datasets_api(query: str, max_pages: int = 10) -> list[dict]:
    """Search for datasets by keyword using the collections API.

    Since data.gov.sg doesn't have a dataset search endpoint,
    we discover all datasets and filter by keyword.
    """
    all_datasets = discover_datasets(max_pages=max_pages)
    query_lower = query.lower()

    matches = []
    for ds in all_datasets:
        name = (ds.get("name") or "").lower()
        agency = (ds.get("managedByAgencyName") or "").lower()
        if query_lower in name or query_lower in agency:
            matches.append(ds)

    return matches


def rebuild_search_index() -> dict:
    """Rebuild search index for data.gov.sg connector objects."""
    from app.workers.build_connector_search_index import rebuild_index
    return rebuild_index()


def main():
    configure_logging()
    parser = argparse.ArgumentParser(description="Sync data.gov.sg datasets")
    parser.add_argument("--discover", action="store_true",
                        help="Discover and store dataset metadata")
    parser.add_argument("--sync", action="store_true",
                        help="Sync top datasets (download data)")
    parser.add_argument("--limit", type=int, default=10,
                        help="Number of datasets to sync (default: 10)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write to DB")
    parser.add_argument("--format", default="CSV",
                        help="Filter by format (default: CSV)")
    parser.add_argument("--dataset-id",
                        help="Sync a specific dataset by ID")
    parser.add_argument("--search", help="Search datasets by keyword")
    parser.add_argument("--rebuild-index", action="store_true",
                        help="Rebuild search index after sync")
    parser.add_argument("--max-pages", type=int, default=50,
                        help="Max API pages to discover (default: 50)")

    args = parser.parse_args()

    if args.search:
        results = search_datasets_api(args.search, max_pages=args.max_pages)
        print(f"\nFound {len(results)} datasets matching '{args.search}':")
        for ds in results[:20]:
            print(f"  {ds.get('datasetId')}: {ds.get('name')} [{ds.get('format')}] "
                  f"by {ds.get('managedByAgencyName')}")
        return

    if args.dataset_id:
        result = sync_dataset(args.dataset_id, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, default=str))
        return

    if args.discover:
        all_datasets = discover_datasets(max_pages=args.max_pages)
        summary = store_discovery(all_datasets)
        print(json.dumps(summary, indent=2))
        return

    if args.sync:
        result = sync_top_datasets(
            limit=args.limit,
            dry_run=args.dry_run,
            filter_format=args.format,
        )
        print(json.dumps(result, indent=2, default=str))
        return

    if args.rebuild_index:
        result = rebuild_search_index()
        print(json.dumps(result, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
