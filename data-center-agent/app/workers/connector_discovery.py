"""Connector Discovery Worker.

Parses curated Excel files, classifies sources, and runs discover/sync modes.

Usage:
  python -m app.workers.connector_discovery <excel_path> --source-set hk_patent --mode discover --dry-run
  python -m app.workers.connector_discovery <excel_path> --source-set hk_tto --mode sync --limit 10
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd

from app.agents.connectors import ConnectorResult, get_connector_for_candidate
from app.agents.source_kind_classifier import (
    classify_ecosystem_category,
    classify_source_kind,
    infer_organization_type,
)
from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.connector_candidates import ExternalSourceCandidateRepository
from app.db.repositories.connectors import (
    ConnectorDatasetRepository,
    ConnectorResourceRepository,
    ConnectorRowRepository,
    ConnectorSnapshotRepository,
)
from app.db.repositories.ecosystem_organizations import EcosystemOrganizationRepository
from app.db.repositories.search_index import SearchIndexRepository
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)

DIAGNOSTICS_DIR = Path("/data/hermes/diagnostics/targeted_connector_discovery")


def parse_excel_rows(
    path: Path,
    source_set: str,
) -> list[dict[str, Any]]:
    """Parse an Excel file into candidate dicts with row metadata."""
    df = pd.read_excel(path)
    rows = []

    for idx, row in df.iterrows():
        # Find URL column
        url = _extract_url(row, df.columns)
        if not url:
            continue

        # Build row metadata from all columns
        row_meta = {}
        for col in df.columns:
            val = row[col]
            if pd.notna(val):
                row_meta[col] = str(val).strip()

        # Title from name columns
        title = None
        for name_col in ("名称 / 系统", "名称 / 说明"):
            if name_col in row_meta:
                title = row_meta[name_col]
                break

        rows.append({
            "url": url.strip(),
            "title": title,
            "source_set": source_set,
            "raw_row_metadata": row_meta,
            "row_index": idx,
        })

    return rows


def classify_candidates(
    rows: list[dict[str, Any]],
    source_set: str,
    geography: str = "Hong Kong",
) -> list[dict[str, Any]]:
    """Classify each row into source_kind and ecosystem_category."""
    classified = []
    for row in rows:
        url = row["url"]
        kind, confidence = classify_source_kind(
            url,
            row_metadata=row.get("raw_row_metadata"),
        )
        eco_cat = classify_ecosystem_category(kind, row.get("raw_row_metadata"), source_set)

        classified.append({
            **row,
            "source_kind": kind,
            "confidence_score": confidence,
            "ecosystem_category": eco_cat,
            "geography": geography,
            "discovery_method": "curated_excel",
            "status": "pending_review",
        })
    return classified


def run_discover(
    candidates: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Discover mode: classify and store metadata only."""
    results = {
        "total": len(candidates),
        "by_source_kind": {},
        "by_ecosystem_category": {},
        "candidates": [],
        "organizations": [],
        "datasets": [],
        "errors": [],
    }

    engine = get_engine() if not dry_run else None

    for cand in candidates:
        kind = cand["source_kind"]
        eco = cand["ecosystem_category"]

        results["by_source_kind"][kind] = results["by_source_kind"].get(kind, 0) + 1
        results["by_ecosystem_category"][eco] = results["by_ecosystem_category"].get(eco, 0) + 1

        connector = get_connector_for_candidate(cand)
        connector_name = type(connector).__name__ if connector else "None"

        result_entry = {
            "url": cand["url"],
            "title": cand.get("title"),
            "source_kind": kind,
            "ecosystem_category": eco,
            "confidence_score": cand["confidence_score"],
            "connector": connector_name,
            "needs_connector": kind in ("search_portal", "official_portal", "unknown"),
        }

        # Run connector discover
        if connector:
            try:
                disc_result = connector.discover(cand)
                result_entry["discover_success"] = disc_result.success
                result_entry["needs_connector"] = disc_result.needs_connector or result_entry["needs_connector"]
                if disc_result.dataset_meta:
                    result_entry["dataset_preview"] = disc_result.dataset_meta
            except Exception as exc:
                result_entry["discover_error"] = str(exc)
                results["errors"].append({"url": cand["url"], "error": str(exc)})

        results["candidates"].append(result_entry)

        # Store in DB if not dry-run
        if not dry_run and engine:
            _store_candidate(engine, cand)

    return results


def run_sync(
    candidates: list[dict[str, Any]],
    *,
    limit: int = 10,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sync mode: download/sync selected approved resources."""
    results = {
        "total_candidates": len(candidates),
        "synced": 0,
        "skipped": 0,
        "failed": 0,
        "synced_items": [],
        "errors": [],
    }

    engine = get_engine() if not dry_run else None
    syncable_kinds = {"downloadable_csv", "downloadable_xlsx", "api_endpoint", "html_table"}
    synced_count = 0

    for cand in candidates:
        if synced_count >= limit:
            results["skipped"] += 1
            continue

        kind = cand["source_kind"]
        if kind not in syncable_kinds:
            results["skipped"] += 1
            continue

        connector = get_connector_for_candidate(cand)
        if not connector:
            results["skipped"] += 1
            continue

        try:
            sync_result = connector.sync(cand, limit=100)
            if sync_result.success:
                synced_count += 1
                sync_entry = {
                    "url": cand["url"],
                    "source_kind": kind,
                    "connector": type(connector).__name__,
                    "rows_captured": len(sync_result.rows) if sync_result.rows else 0,
                    "local_path": sync_result.local_path,
                }
                results["synced_items"].append(sync_entry)
                results["synced"] += 1

                # Store in DB
                if not dry_run and engine:
                    _store_sync_result(engine, cand, sync_result)
            else:
                results["failed"] += 1
                results["errors"].append({"url": cand["url"], "error": sync_result.error})
        except Exception as exc:
            results["failed"] += 1
            results["errors"].append({"url": cand["url"], "error": str(exc)})

    return results


def create_tto_organizations(
    candidates: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Create ecosystem_organizations records for TTO rows."""
    orgs = []
    engine = get_engine() if not dry_run else None

    for cand in candidates:
        meta = cand.get("raw_row_metadata", {})
        school = meta.get("学校", "")
        row_type = meta.get("类型", "")
        name_desc = meta.get("名称 / 说明", "")
        url = cand.get("url", "")
        related = meta.get("相关资料", "")

        org_type = infer_organization_type(meta)

        org_data = {
            "name": name_desc or school,
            "website_url": url,
            "description": f"{school} - {name_desc}",
            "organization_type": org_type,
            "geography": "Hong Kong",
            "country": "Hong Kong",
            "city": "Hong Kong",
            "confidence_score": 0.85,
            "review_status": "pending",
            "metadata": {
                "parent_organization": school,
                "row_type": row_type,
                "related_url": related if pd.notna(related) else None,
                "source": "curated_excel",
                "source_set": "hk_tto",
                **{k: v for k, v in meta.items() if k not in ("学校", "类型", "名称 / 说明", "URL", "相关资料")},
            },
        }
        orgs.append(org_data)

        if not dry_run and engine:
            _store_organization(engine, org_data)

    return orgs


def generate_dry_run_outputs(
    discover_results: dict,
    org_candidates: list[dict],
    source_set: str,
) -> dict[str, Path]:
    """Generate CSV and markdown diagnostics files."""
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {}

    prefix = "hk_patent" if source_set == "hk_patent" else "hk_tto"

    # Classification CSV
    classification_path = DIAGNOSTICS_DIR / f"{prefix}_source_classification.csv"
    with open(classification_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "url", "title", "source_kind", "ecosystem_category",
            "confidence_score", "connector", "needs_connector",
        ])
        writer.writeheader()
        for cand in discover_results.get("candidates", []):
            writer.writerow({k: cand.get(k, "") for k in writer.fieldnames})
    outputs["classification"] = classification_path

    # Extractable sources CSV
    extractable = [c for c in discover_results.get("candidates", [])
                   if c.get("source_kind") in ("downloadable_csv", "downloadable_xlsx", "api_endpoint", "html_table")]
    extractable_path = DIAGNOSTICS_DIR / "extractable_sources.csv"
    with open(extractable_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "title", "source_kind", "connector", "confidence_score"])
        writer.writeheader()
        for cand in extractable:
            writer.writerow({k: cand.get(k, "") for k in writer.fieldnames})
    outputs["extractable"] = extractable_path

    # Manual review CSV
    manual = [c for c in discover_results.get("candidates", []) if c.get("needs_connector")]
    manual_path = DIAGNOSTICS_DIR / "manual_review_sources.csv"
    with open(manual_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "title", "source_kind", "connector", "needs_connector"])
        writer.writeheader()
        for cand in manual:
            writer.writerow({k: cand.get(k, "") for k in writer.fieldnames})
    outputs["manual_review"] = manual_path

    # API candidates CSV
    api_cands = [c for c in discover_results.get("candidates", [])
                 if c.get("source_kind") == "api_endpoint"]
    api_path = DIAGNOSTICS_DIR / "api_dataset_candidates.csv"
    with open(api_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "title", "connector", "confidence_score"])
        writer.writeheader()
        for cand in api_cands:
            writer.writerow({k: cand.get(k, "") for k in writer.fieldnames})
    outputs["api_candidates"] = api_path

    # Organization candidates CSV
    org_path = DIAGNOSTICS_DIR / "organization_candidates.csv"
    with open(org_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "website_url", "organization_type", "geography", "description"])
        writer.writeheader()
        for org in org_candidates:
            writer.writerow({k: org.get(k, "") for k in writer.fieldnames})
    outputs["organizations"] = org_path

    # Summary markdown
    summary_path = DIAGNOSTICS_DIR / "connector_discovery_summary.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"# Connector Discovery Summary — {source_set}\n\n")
        f.write(f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n")
        f.write(f"## Rows Read: {discover_results['total']}\n\n")

        f.write("## Source Kind Distribution\n\n")
        for kind, count in sorted(discover_results.get("by_source_kind", {}).items(), key=lambda x: -x[1]):
            f.write(f"- **{kind}**: {count}\n")

        f.write("\n## Ecosystem Category Distribution\n\n")
        for cat, count in sorted(discover_results.get("by_ecosystem_category", {}).items(), key=lambda x: -x[1]):
            f.write(f"- **{cat}**: {count}\n")

        f.write(f"\n## Extractable Resources: {len(extractable)}\n")
        f.write(f"## API Candidates: {len(api_cands)}\n")
        f.write(f"## Manual Review Needed: {len(manual)}\n")
        f.write(f"## Organization Candidates: {len(org_candidates)}\n")
        f.write(f"## Errors: {len(discover_results.get('errors', []))}\n")

        if discover_results.get("errors"):
            f.write("\n## Errors Detail\n\n")
            for err in discover_results["errors"]:
                f.write(f"- {err['url']}: {err['error']}\n")

        f.write("\n## Recommended Next Sync Batch\n\n")
        syncable = [c for c in extractable if c.get("confidence_score", 0) >= 0.6]
        f.write(f"High-confidence extractable resources (confidence ≥ 0.6): {len(syncable)}\n\n")
        for cand in syncable[:10]:
            f.write(f"- [{cand['source_kind']}] {cand.get('title', cand['url'])} — {cand['url']}\n")

    outputs["summary"] = summary_path
    return outputs


# --- DB storage helpers ---

def _store_candidate(engine, cand: dict[str, Any]) -> None:
    """Store a candidate in external_source_candidates."""
    with engine.begin() as conn:
        repo = ExternalSourceCandidateRepository(conn)
        repo.upsert({
            "title": cand.get("title"),
            "url": cand["url"],
            "source_kind": cand["source_kind"],
            "geography": cand.get("geography"),
            "ecosystem_category": cand.get("ecosystem_category"),
            "discovery_method": cand.get("discovery_method"),
            "confidence_score": cand.get("confidence_score"),
            "status": cand.get("status", "pending_review"),
            "source_set": cand.get("source_set"),
            "raw_row_metadata": cand.get("raw_row_metadata"),
        })


def _store_sync_result(engine, cand: dict[str, Any], result: ConnectorResult) -> None:
    """Store sync result as dataset + resource + snapshot."""
    with engine.begin() as conn:
        cand_repo = ExternalSourceCandidateRepository(conn)
        ds_repo = ConnectorDatasetRepository(conn)
        res_repo = ConnectorResourceRepository(conn)
        snap_repo = ConnectorSnapshotRepository(conn)
        row_repo = ConnectorRowRepository(conn)

        # Upsert candidate
        candidate = cand_repo.upsert({
            "title": cand.get("title"),
            "url": cand["url"],
            "source_kind": cand["source_kind"],
            "geography": cand.get("geography"),
            "ecosystem_category": cand.get("ecosystem_category"),
            "discovery_method": cand.get("discovery_method"),
            "confidence_score": cand.get("confidence_score"),
            "status": "synced",
            "source_set": cand.get("source_set"),
            "raw_row_metadata": cand.get("raw_row_metadata"),
        })

        # Create dataset
        ds_meta = {**result.dataset_meta, "source_candidate_id": candidate["id"]}
        dataset = ds_repo.upsert(ds_meta)

        # Create resource
        resource = None
        if result.resource_meta:
            resource = res_repo.create({
                **result.resource_meta,
                "dataset_id": dataset["id"],
            })

        # Create snapshot
        if result.snapshot_meta:
            snapshot = snap_repo.create({
                **result.snapshot_meta,
                "dataset_id": dataset["id"],
                "resource_id": resource["id"] if resource else None,
            })

            # Store rows
            if result.rows:
                row_repo.create_bulk(snapshot["id"], result.rows)


def _store_organization(engine, org_data: dict[str, Any]) -> None:
    """Store an ecosystem organization."""
    with engine.begin() as conn:
        org_repo = EcosystemOrganizationRepository(conn)
        org_repo.upsert(org_data, force=True)


def _extract_url(row: pd.Series, columns: list[str]) -> str | None:
    """Extract URL from a row, checking URL-like columns."""
    url_columns = ["URL", "url", "link", "链接", "連結", "网址"]
    for col in url_columns:
        if col in columns:
            val = str(row[col]).strip()
            if val and val.lower() != "nan" and val.startswith("http"):
                return val

    # Fallback: scan all columns for URLs
    import re
    for col in columns:
        val = str(row[col]).strip()
        match = re.search(r"https?://[^\s，,；;）)]+", val, re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Connector Discovery Worker")
    parser.add_argument("excel_path", type=Path, help="Path to curated Excel file")
    parser.add_argument("--source-set", required=True, choices=["hk_patent", "hk_tto"],
                        help="Source set identifier")
    parser.add_argument("--mode", default="discover", choices=["discover", "sync"],
                        help="Operation mode")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB or download")
    parser.add_argument("--limit", type=int, default=10, help="Max resources to sync")
    parser.add_argument("--geography", default="Hong Kong", help="Geography label")
    args = parser.parse_args()

    configure_logging()

    if not args.excel_path.exists():
        print(f"ERROR: File not found: {args.excel_path}")
        return

    print(f"Parsing {args.excel_path} (source_set={args.source_set})...")
    rows = parse_excel_rows(args.excel_path, args.source_set)
    print(f"  Found {len(rows)} rows with URLs")

    print("Classifying candidates...")
    candidates = classify_candidates(rows, args.source_set, args.geography)

    if args.mode == "discover":
        print(f"Running discover mode (dry_run={args.dry_run})...")
        results = run_discover(candidates, dry_run=args.dry_run)

        # Create org candidates for TTO
        org_candidates = []
        if args.source_set == "hk_tto":
            print("Creating TTO organization candidates...")
            org_candidates = create_tto_organizations(candidates, dry_run=args.dry_run)
            results["organizations"] = org_candidates

        print(f"\nResults:")
        print(f"  Total: {results['total']}")
        print(f"  By source_kind: {json.dumps(results['by_source_kind'], indent=2)}")
        print(f"  By ecosystem_category: {json.dumps(results['by_ecosystem_category'], indent=2)}")
        print(f"  Organizations: {len(org_candidates)}")
        print(f"  Errors: {len(results['errors'])}")

        # Generate diagnostics
        outputs = generate_dry_run_outputs(results, org_candidates, args.source_set)
        print(f"\nDiagnostics written to:")
        for name, path in outputs.items():
            print(f"  {name}: {path}")

    elif args.mode == "sync":
        print(f"Running sync mode (limit={args.limit}, dry_run={args.dry_run})...")

        # First discover to get classified candidates
        discover_results = run_discover(candidates, dry_run=True)

        # Then sync
        sync_results = run_sync(candidates, limit=args.limit, dry_run=args.dry_run)

        print(f"\nSync Results:")
        print(f"  Synced: {sync_results['synced']}")
        print(f"  Skipped: {sync_results['skipped']}")
        print(f"  Failed: {sync_results['failed']}")

        if sync_results["synced_items"]:
            print(f"\nSynced items:")
            for item in sync_results["synced_items"]:
                print(f"  [{item['source_kind']}] {item['url']} — {item['rows_captured']} rows")

        if sync_results["errors"]:
            print(f"\nErrors:")
            for err in sync_results["errors"]:
                print(f"  {err['url']}: {err['error']}")

        # Write synced_resources.csv
        DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
        synced_path = DIAGNOSTICS_DIR / "synced_resources.csv"
        with open(synced_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["url", "source_kind", "connector", "rows_captured", "local_path"])
            writer.writeheader()
            for item in sync_results["synced_items"]:
                writer.writerow(item)
        print(f"\nSynced resources list: {synced_path}")


if __name__ == "__main__":
    main()
