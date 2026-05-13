import argparse
from pathlib import Path
from uuid import UUID

import httpx

from app.agents.fetcher import detect_content_format, fetch_source
from app.agents.report_reader import basic_report_metadata
from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.datasets import DatasetRepository
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
        dataset_repo = DatasetRepository(connection)
        source = source_repo.get(source_id)
        if not source:
            raise ValueError(f"Source not found: {source_id}")
        if not source.get("original_url"):
            raise ValueError(f"Source has no original_url: {source_id}")

        try:
            fetched = fetch_source(source["original_url"], timeout_seconds=settings.http_timeout_seconds)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {401, 403}:
                status = "private_or_paywalled"
            elif status_code == 404:
                status = "inaccessible"
            else:
                status = "failed"
            updated = source_repo.update_status(source_id, crawl_status=status, notes=f"Fetch failed with HTTP {status_code}")
            return {"source": updated, "report": None, "dataset": None}
        except httpx.RequestError as exc:
            updated = source_repo.update_status(source_id, crawl_status="failed", notes=f"Fetch failed: {exc}")
            return {"source": updated, "report": None, "dataset": None}
        except OSError as exc:
            updated = source_repo.update_status(source_id, crawl_status="failed", notes=f"Local file read failed: {exc}")
            return {"source": updated, "report": None, "dataset": None}

        actual_source_type, detected_format = detect_content_format(fetched.content, fetched.mime_type, fetched.filename)
        raw_relative_path = str(Path("raw") / str(source_id) / fetched.filename)
        stored = storage.write_bytes(raw_relative_path, fetched.content)
        updated = source_repo.update_fetch_result(
            source_id,
            raw_file_path=raw_relative_path,
            raw_file_sha256=stored.sha256,
            mime_type=fetched.mime_type,
            crawl_status="fetched",
            detected_format=detected_format,
            source_type=actual_source_type,
            title=None,
        )

        report = None
        dataset = None
        if actual_source_type in {"pdf", "html"}:
            existing = report_repo.get_by_source(source_id)
            if existing:
                report = existing
            else:
                metadata = basic_report_metadata(updated, fetched.content)
                report = report_repo.create(metadata)
        elif actual_source_type in {"csv", "xlsx"}:
            dataset = dataset_repo.create(
                {
                    "source_id": source_id,
                    "dataset_name": Path(fetched.filename).stem,
                    "data_origin_type": "downloaded_csv" if actual_source_type == "csv" else "unknown",
                    "raw_data_path": raw_relative_path,
                    "metadata": {"mime_type": fetched.mime_type, "detected_format": detected_format},
                }
            )

        return {"source": updated, "report": report, "dataset": dataset}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and persist one source.")
    parser.add_argument("--source-id", type=UUID, required=True)
    args = parser.parse_args()
    configure_logging()
    result = process_source(args.source_id)
    report_id = result["report"]["id"] if result["report"] else None
    dataset_id = result["dataset"]["id"] if result.get("dataset") else None
    print(f"Processed source {args.source_id}; report_id={report_id}; dataset_id={dataset_id}")


if __name__ == "__main__":
    main()
