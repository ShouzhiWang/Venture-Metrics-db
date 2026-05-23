import argparse
from pathlib import Path
from uuid import UUID

import httpx
import trafilatura

from app.agents.fetcher import detect_content_format, fetch_source
from app.agents.report_reader import basic_report_metadata
from app.agents.source_resolver import SourceResolver, verify_artifact_url
from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.datasets import DatasetRepository
from app.db.repositories.reports import ReportRepository
from app.db.repositories.sources import SourceRepository
from app.storage.local_storage import LocalStorageClient
from app.utils.logging import configure_logging


def _dataset_source_type(url: str, content_type: str | None = None) -> tuple[str, str | None]:
    lower = url.lower()
    lowered_content_type = (content_type or "").lower()
    if lower.endswith(".csv") or lowered_content_type in {"text/csv", "application/csv"}:
        return "csv", "csv"
    if lower.endswith((".xlsx", ".xlsm")) or "spreadsheet" in lowered_content_type:
        return "xlsx", "xlsx"
    if lower.endswith(".xls") or "excel" in lowered_content_type:
        return "xlsx", "xls"
    if lower.endswith(".zip") or "zip" in lowered_content_type:
        return "zip", "zip"
    return "unknown", None


def _html_looks_like_report(html: bytes) -> bool:
    text = trafilatura.extract(html.decode("utf-8", errors="ignore")) or ""
    lowered = text.lower()
    report_terms = ["methodology", "data source", "defined as", "technical notes", "executive summary", "appendix"]
    return len(text) >= 3000 and sum(1 for term in report_terms if term in lowered) >= 2


def _artifact_payload(artifact, verification=None) -> dict:
    payload = artifact.to_dict()
    if verification:
        payload["verification"] = verification.to_dict()
    return payload


def _resolve_html_source(
    *,
    source: dict,
    updated: dict,
    html: bytes,
    source_repo: SourceRepository,
    timeout_seconds: int,
    limit_candidates: int = 10,
) -> tuple[dict, dict | None, list[dict]]:
    resolver = SourceResolver()
    html_text = html.decode("utf-8", errors="ignore")
    artifacts = resolver.discover_artifacts(html_text, source["original_url"])
    ranked = artifacts[:limit_candidates]
    discovered_payload: list[dict] = []
    best_child = None

    for artifact in ranked:
        verification = verify_artifact_url(artifact.url, timeout_seconds=timeout_seconds)
        discovered_payload.append(_artifact_payload(artifact, verification))
        if not verification.is_downloadable:
            continue

        final_url = verification.final_url or artifact.url
        if final_url == source["original_url"]:
            continue

        if verification.artifact_type == "pdf":
            child_source_type, detected_format, source_role = "pdf", "pdf", "report_pdf"
        else:
            child_source_type, detected_format = _dataset_source_type(final_url, verification.content_type)
            source_role = "dataset_file"

        best_child = source_repo.create_child_source(
            parent_source_id=source["id"],
            original_url=final_url,
            source_type=child_source_type,
            source_role=source_role,
            detected_format=detected_format,
            notes=f"Resolved from landing page source {source['id']}",
        )
        updated = source_repo.update_resolution(
            source["id"],
            source_role="landing_page",
            resolution_status="resolved",
            resolved_source_id=best_child["id"],
            resolution_notes=f"Resolved downloadable {verification.artifact_type}: {final_url}",
            discovered_artifacts=discovered_payload,
        )
        return updated, best_child, discovered_payload

    signals = resolver.inspect_html(html_text)
    status = signals.status
    source_role = "gated_or_paywalled" if status == "gated_or_paywalled" else "landing_page"
    if status == "unresolved" and _html_looks_like_report(html):
        source_role = "html_report_body"
        status = "not_needed"
    updated = source_repo.update_resolution(
        source["id"],
        source_role=source_role,
        resolution_status=status,
        resolution_notes=signals.notes,
        discovered_artifacts=discovered_payload or [artifact.to_dict() for artifact in ranked],
    )
    return updated, None, discovered_payload


def process_source(source_id: UUID, *, resolve_html_artifacts: bool = True, process_resolved: bool = False) -> dict:
    settings = get_settings()
    storage = LocalStorageClient(settings.storage_root)
    engine = get_engine()
    child_to_process = None

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
        discovered_artifacts = []
        resolved_source = None
        if actual_source_type == "html" and resolve_html_artifacts:
            updated, resolved_source, discovered_artifacts = _resolve_html_source(
                source=source,
                updated=updated,
                html=fetched.content,
                source_repo=source_repo,
                timeout_seconds=settings.http_timeout_seconds,
            )
            if resolved_source:
                child_to_process = resolved_source["id"]
            elif updated.get("source_role") == "html_report_body":
                existing = report_repo.get_by_source(source_id)
                if existing:
                    report = existing
                else:
                    metadata = basic_report_metadata(updated, fetched.content)
                    report = report_repo.create(metadata)
        elif actual_source_type in {"pdf", "html"}:
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

        result = {
            "source": updated,
            "report": report,
            "dataset": dataset,
            "resolved_source": resolved_source,
            "discovered_artifacts": discovered_artifacts,
        }

    if process_resolved and child_to_process:
        result["resolved_result"] = process_source(
            child_to_process,
            resolve_html_artifacts=False,
            process_resolved=False,
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and persist one source.")
    parser.add_argument("--source-id", type=UUID, required=True)
    parser.add_argument("--resolve-html-artifacts", dest="resolve_html_artifacts", action="store_true", default=True)
    parser.add_argument("--no-resolve-html-artifacts", dest="resolve_html_artifacts", action="store_false")
    parser.add_argument("--process-resolved", action="store_true", default=False)
    args = parser.parse_args()
    configure_logging()
    result = process_source(
        args.source_id,
        resolve_html_artifacts=args.resolve_html_artifacts,
        process_resolved=args.process_resolved,
    )
    report_id = result["report"]["id"] if result["report"] else None
    dataset_id = result["dataset"]["id"] if result.get("dataset") else None
    resolved_id = result["resolved_source"]["id"] if result.get("resolved_source") else None
    print(f"Processed source {args.source_id}; report_id={report_id}; dataset_id={dataset_id}; resolved_source_id={resolved_id}")


if __name__ == "__main__":
    main()
