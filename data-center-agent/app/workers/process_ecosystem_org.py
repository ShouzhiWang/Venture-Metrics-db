from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import UUID

import httpx

from app.agents.ecosystem_org_extractor import (
    classify_source_route,
    extract_directory_candidates,
    extract_ecosystem_organization,
)
from app.agents.fetcher import detect_content_format, fetch_source
from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.ecosystem_organizations import EcosystemOrganizationRepository
from app.db.repositories.sources import SourceRepository
from app.storage.local_storage import LocalStorageClient
from app.utils.logging import configure_logging


def process_ecosystem_org_source(
    source_id: UUID,
    *,
    dry_run: bool = False,
    force: bool = False,
    from_excel_row: bool = False,
) -> dict:
    settings = get_settings()
    storage = LocalStorageClient(settings.storage_root)
    engine = get_engine()
    with engine.begin() as connection:
        source_repo = SourceRepository(connection)
        org_repo = EcosystemOrganizationRepository(connection)
        source = source_repo.get(source_id)
        if not source:
            raise ValueError(f"Source not found: {source_id}")
        if not source.get("original_url"):
            raise ValueError(f"Source has no original_url: {source_id}")

        try:
            fetched = fetch_source(source["original_url"], timeout_seconds=settings.http_timeout_seconds)
        except httpx.HTTPError as exc:
            if not dry_run:
                source_repo.update_status(source_id, crawl_status="failed", notes=f"Ecosystem organization fetch failed: {exc}")
            return {"source": source, "organization": None, "route": "unknown", "error": str(exc)}

        actual_source_type, detected_format = detect_content_format(fetched.content, fetched.mime_type, fetched.filename)
        route = classify_source_route(url=source["original_url"], source_type=actual_source_type, html=fetched.content)
        raw_relative_path = str(Path("raw") / str(source_id) / fetched.filename)
        stored = storage.write_bytes(raw_relative_path, fetched.content) if not dry_run else None

        organization = None
        directory_candidates: list[dict] = []
        if route.source_route == "ecosystem_organization":
            values = extract_ecosystem_organization(fetched.content, source)
            if from_excel_row:
                values["metadata"] = {**values.get("metadata", {}), "from_excel_row": True}
            organization = values if dry_run else org_repo.upsert(values, force=force)
            if not dry_run:
                source_repo.update_fetch_result(
                    source_id,
                    raw_file_path=raw_relative_path,
                    raw_file_sha256=stored.sha256 if stored else None,
                    mime_type=fetched.mime_type,
                    crawl_status="fetched",
                    detected_format=detected_format,
                    source_type=actual_source_type,
                    title=values["name"],
                )
                source_repo.update_resolution(
                    source_id,
                    source_role="ecosystem_organization_page",
                    resolution_status="not_needed",
                    resolution_notes=route.reason,
                    discovered_artifacts={"source_route": route.source_route, "confidence_score": route.confidence_score},
                )
        elif route.source_route == "organization_directory":
            directory_candidates = extract_directory_candidates(fetched.content, source["original_url"])
            if not dry_run:
                source_repo.update_fetch_result(
                    source_id,
                    raw_file_path=raw_relative_path,
                    raw_file_sha256=stored.sha256 if stored else None,
                    mime_type=fetched.mime_type,
                    crawl_status="fetched",
                    detected_format=detected_format,
                    source_type=actual_source_type,
                )
                source_repo.update_resolution(
                    source_id,
                    source_role="organization_directory",
                    resolution_status="needs_review",
                    resolution_notes=f"{route.reason}; extracted {len(directory_candidates)} simple candidates",
                    discovered_artifacts=directory_candidates,
                )
        else:
            if not dry_run:
                source_repo.update_resolution(
                    source_id,
                    source_role=route.source_route,
                    resolution_status="needs_review",
                    resolution_notes=route.reason,
                )

        return {
            "source": source,
            "organization": organization,
            "route": route.source_route,
            "confidence_score": route.confidence_score,
            "directory_candidates": directory_candidates,
            "dry_run": dry_run,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Process one ecosystem organization or organization directory source.")
    parser.add_argument("--source-id", type=UUID, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--from-excel-row", action="store_true")
    args = parser.parse_args()
    configure_logging()
    result = process_ecosystem_org_source(
        args.source_id,
        dry_run=args.dry_run,
        force=args.force,
        from_excel_row=args.from_excel_row,
    )
    print(json.dumps(result, default=str, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
