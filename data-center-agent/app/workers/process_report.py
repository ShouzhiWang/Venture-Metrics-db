import argparse
from pathlib import Path
from uuid import UUID

from app.agents.content_quality import classify_content_quality
from app.agents.parser import build_chunks, pages_json, parse_raw_file, parsed_json
from app.agents.report_reader import extract_report_metadata_from_text
from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.reports import ReportRepository
from app.db.repositories.sources import SourceRepository
from app.storage.local_storage import LocalStorageClient
from app.utils.logging import configure_logging


def process_report(report_id: UUID) -> int:
    settings = get_settings()
    storage = LocalStorageClient(settings.storage_root)
    engine = get_engine()

    with engine.begin() as connection:
        report_repo = ReportRepository(connection)
        source_repo = SourceRepository(connection)
        chunk_repo = ChunkRepository(connection)
        report = report_repo.get(report_id)
        if not report:
            raise ValueError(f"Report not found: {report_id}")
        source = source_repo.get(report["source_id"])
        if not source or not source.get("raw_file_path"):
            raise ValueError(f"Report source has no raw file: {report_id}")

        raw_path = storage.resolve(source["raw_file_path"])
        parsed = parse_raw_file(raw_path, source.get("source_type", "unknown"), source.get("mime_type"))
        raw_text_relative = str(Path("parsed") / str(report_id) / "raw_text.txt")
        parsed_json_relative = str(Path("parsed") / str(report_id) / "parsed.json")
        pages_json_relative = str(Path("parsed") / str(report_id) / "pages.json")
        storage.write_text(raw_text_relative, parsed.text)
        storage.write_text(parsed_json_relative, parsed_json(parsed))
        storage.write_text(pages_json_relative, pages_json(parsed))
        report_repo.update_paths(report_id, raw_text_path=raw_text_relative, parsed_json_path=parsed_json_relative)
        report_repo.update_metadata(report_id, extract_report_metadata_from_text(parsed.text, parsed.metadata))

        chunks = build_chunks(str(report_id), parsed)
        inserted = chunk_repo.create_many(chunks)
        quality = classify_content_quality(
            chunks,
            source_type=source.get("source_type"),
            crawl_status=source.get("crawl_status"),
            raw_text=parsed.text,
        )
        report_repo.update_content_quality(
            report_id,
            {
                "label": quality.label,
                "reason": quality.reason,
                "chunk_count": quality.chunk_count,
                "total_characters": quality.total_characters,
                "metadata": quality.metadata,
            },
        )
        source_repo.update_status(source["id"], crawl_status="parsed")
        return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse one report and insert document chunks.")
    parser.add_argument("--report-id", type=UUID, required=True)
    args = parser.parse_args()
    configure_logging()
    count = process_report(args.report_id)
    print(f"Processed report {args.report_id}; inserted_chunks={count}")


if __name__ == "__main__":
    main()
