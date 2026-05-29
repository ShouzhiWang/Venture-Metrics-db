"""DataGovHK Resolver + Sync worker.

Resolves data.gov.hk portal URLs into downloadable resources using the
DataGovHKResourceResolver, then syncs the best candidate.

Usage:
  python -m app.workers.datagovhk_resolve_and_sync --limit 5
  python -m app.workers.datagovhk_resolve_and_sync --limit 1 --dry-run
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
import pandas as pd
from sqlalchemy import text

from app.agents.datagovhk_resolver import DataGovHKResourceResolver, ResourceCandidate
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

DIAGNOSTICS_DIR = Path("/data/hermes/diagnostics/datagovhk_resolver_fix")


def resolve_and_sync(
    *,
    limit: int = 5,
    dry_run: bool = False,
) -> dict:
    """Find data.gov.hk candidates in DB, resolve resources, and sync."""
    engine = get_engine()
    resolver = DataGovHKResourceResolver()
    settings = get_settings()

    result = {
        "candidates_processed": 0,
        "resources_resolved": 0,
        "resources_synced": 0,
        "failures": [],
        "synced_items": [],
        "resolution_details": [],
    }

    with engine.begin() as conn:
        cand_repo = ExternalSourceCandidateRepository(conn)
        ds_repo = ConnectorDatasetRepository(conn)
        res_repo = ConnectorResourceRepository(conn)
        snap_repo = ConnectorSnapshotRepository(conn)
        row_repo = ConnectorRowRepository(conn)

        # Find data.gov.hk candidates that need resolution
        rows = conn.execute(text(
            "SELECT * FROM external_source_candidates "
            "WHERE url LIKE '%data.gov.hk%' AND status IN ('needs_connector', 'pending_review')"
        )).fetchall()

        if not rows:
            print("  No data.gov.hk candidates found needing resolution.")
            return result

        # Get column names from the result
        col_names = list(rows[0]._mapping.keys())

        for row in rows[:limit]:
            cand = dict(zip(col_names, row))
            result["candidates_processed"] += 1

            cand_url = cand.get("url", "")
            raw_meta = cand.get("raw_row_metadata") or {}
            title = cand.get("title") or raw_meta.get("名称 / 系统", "")
            desc = raw_meta.get("用途 / 数据内容", "")
            source_set = cand.get("source_set", "")

            print(f"\n  Resolving: {title}")
            print(f"  URL: {cand_url}")

            # Run resolver
            resolution = resolver.resolve(
                cand_url,
                title=title,
                description=desc,
                source_set=source_set,
                provider_hint="hk-ipd" if source_set == "hk_patent" else None,
                format_hint="csv",
            )

            detail = {
                "title": title,
                "url": cand_url,
                "methods_attempted": resolution.methods_attempted,
                "ckan_candidates": len(resolution.ckan_candidates),
                "archive_candidates": len(resolution.archive_candidates),
                "selected": None,
                "confidence": None,
                "sync_result": None,
            }

            if not resolution.success:
                detail["failure_reason"] = resolution.failure_reason
                result["failures"].append(detail)
                result["resolution_details"].append(detail)

                if not dry_run:
                    cand_repo.update(cand["id"], {
                        "status": "needs_connector",
                        "notes": f"Resolution failed: {resolution.failure_reason}. "
                                 f"Methods: {', '.join(resolution.methods_attempted)}",
                    })
                continue

            # Got candidates — pick the best one
            best = resolution.selected
            result["resources_resolved"] += 1
            detail["selected"] = {
                "url": best.url,
                "dataset_name": best.dataset_name,
                "resource_name": best.resource_name,
                "format": best.format,
                "provider": best.provider,
                "confidence": best.confidence,
                "source": best.source,
            }
            detail["confidence"] = best.confidence

            print(f"  Best match: {best.dataset_name}")
            print(f"  URL: {best.url}")
            print(f"  Confidence: {best.confidence}")
            print(f"  Format: {best.format}")

            # Store all candidates as notes
            all_cand_notes = []
            for c in resolution.all_candidates[:10]:
                all_cand_notes.append(f"[{c.confidence}] {c.dataset_name} — {c.url}")

            if not dry_run:
                # Update candidate status
                cand_repo.update(cand["id"], {
                    "status": "approved",
                    "notes": f"Resolved via {best.source}. "
                             f"Confidence: {best.confidence}. "
                             f"Dataset: {best.dataset_name}. "
                             f"All candidates:\n" + "\n".join(all_cand_notes),
                })

            # Sync the resource if it's a downloadable format
            if best.format in ("csv", "xlsx", "xls"):
                sync_result = _sync_resource(
                    best, cand, settings, engine,
                    ds_repo=ds_repo, res_repo=res_repo,
                    snap_repo=snap_repo, row_repo=row_repo,
                    cand_repo=cand_repo,
                    dry_run=dry_run,
                )
                detail["sync_result"] = sync_result
                if sync_result.get("success"):
                    result["resources_synced"] += 1
                    result["synced_items"].append(detail)
                else:
                    result["failures"].append(detail)
            else:
                detail["sync_result"] = {"success": False, "reason": f"Unsupported format: {best.format}"}
                result["failures"].append(detail)

            result["resolution_details"].append(detail)

    return result


def _sync_resource(
    candidate: ResourceCandidate,
    orig_cand: dict,
    settings,
    engine,
    *,
    ds_repo, res_repo, snap_repo, row_repo, cand_repo,
    dry_run: bool = False,
) -> dict:
    """Download and sync a resolved resource."""
    url = candidate.url
    sync_result = {
        "success": False,
        "url": url,
        "local_path": None,
        "checksum": None,
        "row_count": 0,
        "column_count": 0,
        "columns": [],
    }

    # Download
    try:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        sync_result["error"] = f"Download failed: {exc}"
        return sync_result

    content = resp.content
    checksum = hashlib.sha256(content).hexdigest()

    # Save locally
    storage_root = settings.storage_root
    connector_dir = storage_root / "connector_downloads"
    connector_dir.mkdir(parents=True, exist_ok=True)

    parsed_url = urlparse(url)
    filename = Path(parsed_url.path).name or "data.csv"
    local_path = connector_dir / f"{checksum[:12]}_{filename}"
    local_path.write_bytes(content)

    sync_result["local_path"] = str(local_path)
    sync_result["checksum"] = checksum

    # Parse to get columns and rows
    ext = candidate.format
    rows_data = []
    try:
        if ext == "csv":
            # Try multiple encodings
            df = None
            for enc in ("utf-8", "latin-1", "cp1252", "iso-8859-1", "big5"):
                try:
                    df = pd.read_csv(io.BytesIO(content), nrows=5000, encoding=enc)
                    break
                except (UnicodeDecodeError, UnicodeError):
                    continue
            if df is None:
                sync_result["error"] = "Could not decode CSV with any encoding"
                return sync_result
        elif ext in ("xlsx", "xls"):
            df = pd.read_excel(io.BytesIO(content), nrows=5000)
        else:
            sync_result["error"] = f"Cannot parse format: {ext}"
            return sync_result

        sync_result["row_count"] = len(df)
        sync_result["column_count"] = len(df.columns)
        sync_result["columns"] = list(df.columns)
        # Replace NaN with None for JSON serialization
        df = df.where(df.notna(), None)
        rows_data = df.to_dict(orient="records")
    except Exception as exc:
        sync_result["error"] = f"Parse failed: {exc}"
        # Still store the file even if parse fails
        if not dry_run:
            sync_result["parse_failed"] = True

    sync_result["success"] = True

    if dry_run:
        return sync_result

    # Store in DB
    # 1. Update or create connector_dataset
    dataset = ds_repo.upsert({
        "name": candidate.dataset_name or orig_cand.get("title", ""),
        "description": f"HK IP statistics from data.gov.hk. "
                       f"Dataset: {candidate.dataset_name}. "
                       f"Resource: {candidate.resource_name}.",
        "publisher": "Hong Kong Intellectual Property Department" if candidate.provider == "hk-ipd" else candidate.provider,
        "geography": "Hong Kong",
        "topic": "patents_ip",
        "source_url": url,
        "portal": "data.gov.hk",
        "access_type": "csv",
        "status": "synced",
        "source_candidate_id": orig_cand.get("id"),
        "metadata": {
            "original_candidate_url": orig_cand.get("url"),
            "resolved_url": url,
            "provider": candidate.provider,
            "dataset_id": candidate.dataset_id,
            "source": candidate.source,
            "confidence": candidate.confidence,
        },
    })

    # 2. Create connector_resource
    resource = res_repo.create({
        "dataset_id": dataset["id"],
        "resource_name": candidate.resource_name or filename,
        "resource_url": url,
        "format": ext,
        "schema_metadata": {"columns": sync_result["columns"]},
        "local_path": str(local_path),
        "status": "synced",
        "metadata": {
            "checksum": checksum,
            "file_size": len(content),
        },
    })

    # 3. Create connector_snapshot
    snapshot = snap_repo.create({
        "dataset_id": dataset["id"],
        "resource_id": resource["id"],
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "query_params": {"source": "datagovhk_resolver", "url": url},
        "row_count": sync_result["row_count"],
        "column_count": sync_result["column_count"],
        "local_path": str(local_path),
        "checksum": checksum,
        "status": "captured",
        "metadata": {
            "columns": sync_result["columns"],
            "format": ext,
            "source": "data.gov.hk Historical Archive",
            "resolved_from": orig_cand.get("url"),
        },
    })

    # 4. Populate connector_rows
    if rows_data:
        row_repo.create_bulk(snapshot["id"], rows_data[:5000])

    # 5. Update candidate status
    cand_repo.update(orig_cand["id"], {"status": "synced"})

    sync_result["dataset_id"] = str(dataset["id"])
    sync_result["resource_id"] = str(resource["id"])
    sync_result["snapshot_id"] = str(snapshot["id"])

    return sync_result


def generate_diagnostics(result: dict) -> dict:
    """Generate diagnostic files."""
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {}

    # Summary markdown
    summary_path = DIAGNOSTICS_DIR / "datagovhk_resolution_summary.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("# DataGovHK Resolution Summary\n\n")
        f.write(f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n")
        f.write(f"## Overview\n\n")
        f.write(f"- Candidates processed: {result['candidates_processed']}\n")
        f.write(f"- Resources resolved: {result['resources_resolved']}\n")
        f.write(f"- Resources synced: {result['resources_synced']}\n")
        f.write(f"- Failures: {len(result['failures'])}\n\n")

        f.write("## Resolution Details\n\n")
        for detail in result["resolution_details"]:
            f.write(f"### {detail['title']}\n\n")
            f.write(f"- URL: {detail['url']}\n")
            f.write(f"- Methods: {', '.join(detail['methods_attempted'])}\n")
            f.write(f"- CKAN candidates: {detail['ckan_candidates']}\n")
            f.write(f"- Archive candidates: {detail['archive_candidates']}\n")

            if detail.get("selected"):
                sel = detail["selected"]
                f.write(f"- **Selected**: {sel['dataset_name']}\n")
                f.write(f"  - URL: {sel['url']}\n")
                f.write(f"  - Confidence: {sel['confidence']}\n")
                f.write(f"  - Format: {sel['format']}\n")
                f.write(f"  - Provider: {sel['provider']}\n")
                f.write(f"  - Source: {sel['source']}\n")

            if detail.get("sync_result"):
                sr = detail["sync_result"]
                f.write(f"  - Sync success: {sr.get('success')}\n")
                if sr.get("row_count"):
                    f.write(f"  - Rows: {sr['row_count']}\n")
                    f.write(f"  - Columns: {sr['column_count']}\n")
                    f.write(f"  - Checksum: {sr.get('checksum', 'N/A')[:16]}...\n")
                    f.write(f"  - Local file: {sr.get('local_path', 'N/A')}\n")
                if sr.get("error"):
                    f.write(f"  - Error: {sr['error']}\n")

            if detail.get("failure_reason"):
                f.write(f"- **Failure**: {detail['failure_reason']}\n")

            f.write("\n")
    outputs["summary"] = summary_path

    # Resource candidates CSV
    cand_path = DIAGNOSTICS_DIR / "datagovhk_resource_candidates.csv"
    with open(cand_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "title", "url", "methods", "ckan_count", "archive_count",
            "selected_name", "selected_url", "confidence", "sync_status",
        ])
        writer.writeheader()
        for detail in result["resolution_details"]:
            sel = detail.get("selected") or {}
            writer.writerow({
                "title": detail["title"],
                "url": detail["url"],
                "methods": "; ".join(detail["methods_attempted"]),
                "ckan_count": detail["ckan_candidates"],
                "archive_count": detail["archive_candidates"],
                "selected_name": sel.get("dataset_name", ""),
                "selected_url": sel.get("url", ""),
                "confidence": sel.get("confidence", ""),
                "sync_status": "synced" if detail.get("sync_result", {}).get("success") else "failed",
            })
    outputs["candidates"] = cand_path

    # Synced resources CSV
    synced_path = DIAGNOSTICS_DIR / "datagovhk_synced_resources.csv"
    with open(synced_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "dataset_name", "url", "format", "rows", "columns",
            "checksum", "local_path", "dataset_id", "snapshot_id",
        ])
        writer.writeheader()
        for item in result.get("synced_items", []):
            sel = item.get("selected") or {}
            sr = item.get("sync_result") or {}
            writer.writerow({
                "dataset_name": sel.get("dataset_name", ""),
                "url": sel.get("url", ""),
                "format": sel.get("format", ""),
                "rows": sr.get("row_count", ""),
                "columns": sr.get("column_count", ""),
                "checksum": (sr.get("checksum") or "")[:16],
                "local_path": sr.get("local_path", ""),
                "dataset_id": sr.get("dataset_id", ""),
                "snapshot_id": sr.get("snapshot_id", ""),
            })
    outputs["synced"] = synced_path

    # Snapshot preview CSV
    preview_path = DIAGNOSTICS_DIR / "datagovhk_snapshot_preview.csv"
    for item in result.get("synced_items", []):
        sr = item.get("sync_result") or {}
        if sr.get("local_path") and Path(sr["local_path"]).exists():
            try:
                df = pd.read_csv(sr["local_path"], nrows=5)
                df.to_csv(preview_path, index=False)
                outputs["preview"] = preview_path
            except Exception:
                pass

    # Failures CSV
    fail_path = DIAGNOSTICS_DIR / "datagovhk_failures.csv"
    with open(fail_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["title", "url", "reason", "methods"])
        writer.writeheader()
        for fail in result.get("failures", []):
            writer.writerow({
                "title": fail.get("title", ""),
                "url": fail.get("url", ""),
                "reason": fail.get("failure_reason") or fail.get("sync_result", {}).get("error", ""),
                "methods": "; ".join(fail.get("methods_attempted", [])),
            })
    outputs["failures"] = fail_path

    return outputs


def main():
    parser = argparse.ArgumentParser(description="DataGovHK Resolve + Sync")
    parser.add_argument("--limit", type=int, default=5, help="Max candidates to process")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB or download")
    args = parser.parse_args()

    configure_logging()

    print("=" * 60)
    print("DataGovHK Resource Resolver + Sync")
    print("=" * 60)

    result = resolve_and_sync(limit=args.limit, dry_run=args.dry_run)

    print(f"\n{'='*60}")
    print(f"Results:")
    print(f"  Candidates processed: {result['candidates_processed']}")
    print(f"  Resources resolved: {result['resources_resolved']}")
    print(f"  Resources synced: {result['resources_synced']}")
    print(f"  Failures: {len(result['failures'])}")

    if result["synced_items"]:
        print(f"\nSynced:")
        for item in result["synced_items"]:
            sel = item.get("selected") or {}
            sr = item.get("sync_result") or {}
            print(f"  [{sel.get('format')}] {sel.get('dataset_name')} — {sr.get('row_count')} rows")
            print(f"    {sr.get('local_path')}")

    if result["failures"]:
        print(f"\nFailures:")
        for fail in result["failures"]:
            reason = fail.get("failure_reason") or fail.get("sync_result", {}).get("error", "unknown")
            print(f"  {fail.get('title')}: {reason}")

    # Generate diagnostics
    outputs = generate_diagnostics(result)
    print(f"\nDiagnostics:")
    for name, path in outputs.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
