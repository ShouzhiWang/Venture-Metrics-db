import argparse
from pathlib import Path
from uuid import UUID

from app.agents.fetcher import fetch_source
from app.agents.report_reader import basic_report_metadata
from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.reports import ReportRepository
from app.db.repositories.sources import SourceRepository
from app.storage.local_storage import LocalStorageClient
from app.utils.logging import configure_logging


def process_source(source_id: UUID) -> dict:
    settings = get_settings()
    storage = LocalStorageClient(settings.storage_root)
    engine = get_engine()

    with engine.begin() as connection:
        source_repo = SourceRepository(connection)
        report_repo = ReportRepository(connection)
        source = source_repo.get(source_id)
        if not source:
            raise ValueError(f"Source not found: {source_id}")
        if not source.get("original_url"):
            raise ValueError(f"Source has no original_url: {source_id}")

        fetched = fetch_source(source["original_url"], timeout_seconds=settings.http_timeout_seconds)
        raw_relative_path = str(Path("raw") / str(source_id) / fetched.filename)
        stored = storage.write_bytes(raw_relative_path, fetched.content)
        updated = source_repo.update_fetch_result(
            source_id,
            raw_file_path=raw_relative_path,
            raw_file_sha256=stored.sha256,
            mime_type=fetched.mime_type,
            crawl_status="completed",
            title=None,
        )

        report = None
        if updated["source_type"] in {"pdf", "html"}:
            existing = report_repo.get_by_source(source_id)
            if existing:
                report = existing
            else:
                metadata = basic_report_metadata(updated, fetched.content)
                report = report_repo.create(metadata)

        return {"source": updated, "report": report}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and persist one source.")
    parser.add_argument("--source-id", type=UUID, required=True)
    args = parser.parse_args()
    configure_logging()
    result = process_source(args.source_id)
    report_id = result["report"]["id"] if result["report"] else None
    print(f"Processed source {args.source_id}; report_id={report_id}")


if __name__ == "__main__":
    main()
