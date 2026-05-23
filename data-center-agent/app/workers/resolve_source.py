import argparse
from uuid import UUID

import httpx

from app.agents.browser_source_resolver import BrowserResolverUnavailable, BrowserSourceResolver
from app.agents.fetcher import fetch_source
from app.agents.source_resolver import SourceResolver, verify_artifact_url
from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.sources import SourceRepository
from app.storage.local_storage import LocalStorageClient
from app.utils.logging import configure_logging
from app.workers.process_source import _browser_verification_for_artifact, _dataset_source_type, process_source


def _load_or_fetch_html(source: dict, storage: LocalStorageClient, timeout_seconds: int) -> tuple[str, str]:
    raw_file_path = source.get("raw_file_path")
    if raw_file_path:
        path = storage.resolve(raw_file_path)
        if path.exists():
            return path.read_text(encoding="utf-8", errors="ignore"), str(source.get("original_url"))

    fetched = fetch_source(source["original_url"], timeout_seconds=timeout_seconds)
    return fetched.content.decode("utf-8", errors="ignore"), fetched.final_url or source["original_url"]


def resolve_source(
    source_id: UUID,
    *,
    process_resolved: bool = False,
    limit_candidates: int = 10,
    dry_run: bool = False,
    force: bool = False,
    mode: str = "auto",
    browser_timeout_seconds: int = 20,
    allow_download_clicks: bool = True,
) -> dict:
    settings = get_settings()
    storage = LocalStorageClient(settings.storage_root)
    engine = get_engine()
    resolver = SourceResolver()
    child_to_process = None

    with engine.begin() as connection:
        source_repo = SourceRepository(connection)
        source = source_repo.get(source_id)
        if not source:
            raise ValueError(f"Source not found: {source_id}")
        if not source.get("original_url"):
            raise ValueError(f"Source has no original_url: {source_id}")
        if source.get("resolved_source_id") and not force:
            return {
                "source": source,
                "resolved_source": source_repo.get(source["resolved_source_id"]),
                "artifacts": source.get("discovered_artifacts") or [],
                "dry_run": dry_run,
                "skipped": "already_resolved",
            }

        html, base_url = _load_or_fetch_html(source, storage, settings.http_timeout_seconds)
        artifacts = ([] if mode == "browser" else resolver.discover_artifacts(html, base_url))[:limit_candidates]
        verified = []
        best_child = None

        for artifact in artifacts:
            verification = verify_artifact_url(artifact.url, timeout_seconds=settings.http_timeout_seconds)
            payload = artifact.to_dict()
            payload["verification"] = verification.to_dict()
            verified.append(payload)
            if best_child or not verification.is_downloadable:
                continue
            final_url = verification.final_url or artifact.url
            if final_url == source["original_url"]:
                continue
            if dry_run:
                best_child = {"original_url": final_url, "source_type": verification.artifact_type}
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
            source_repo.update_resolution(
                source["id"],
                source_role="landing_page",
                resolution_status="resolved",
                resolved_source_id=best_child["id"],
                resolution_notes=f"Resolved downloadable {verification.artifact_type}: {final_url}",
                discovered_artifacts=verified,
            )
            child_to_process = best_child["id"]

        signals = resolver.inspect_html(html)
        should_try_browser = not best_child and (
            mode == "browser" or (mode == "auto" and signals.status in {"needs_browser", "unresolved"})
        )
        if should_try_browser:
            try:
                browser_result = BrowserSourceResolver(
                    timeout_seconds=browser_timeout_seconds,
                    allow_download_clicks=allow_download_clicks,
                ).resolve(source["original_url"])
                for artifact in browser_result.artifacts[:limit_candidates]:
                    verification = _browser_verification_for_artifact(artifact)
                    payload = artifact.to_dict()
                    payload["verification"] = verification.to_dict()
                    verified.append(payload)
                    if best_child or not verification.is_downloadable or artifact.url == source["original_url"]:
                        continue
                    if dry_run:
                        best_child = {"original_url": artifact.url, "source_type": verification.artifact_type}
                        continue
                    if verification.artifact_type == "pdf":
                        child_source_type, detected_format, source_role = "pdf", "pdf", "report_pdf"
                    else:
                        child_source_type, detected_format = _dataset_source_type(artifact.url, verification.content_type)
                        source_role = "dataset_file"
                    best_child = source_repo.create_child_source(
                        parent_source_id=source["id"],
                        original_url=artifact.url,
                        source_type=child_source_type,
                        source_role=source_role,
                        detected_format=detected_format,
                        notes=f"Resolved from landing page source {source['id']}",
                    )
                    source_repo.update_resolution(
                        source["id"],
                        source_role="landing_page",
                        resolution_status="resolved",
                        resolved_source_id=best_child["id"],
                        resolution_notes=f"Resolved downloadable {verification.artifact_type} via {artifact.discovery_method}: {artifact.url}",
                        discovered_artifacts=verified,
                    )
                    child_to_process = best_child["id"]
                if not best_child and not dry_run and browser_result.status in {"needs_browser", "gated_or_paywalled"}:
                    role = "gated_or_paywalled" if browser_result.status == "gated_or_paywalled" else "landing_page"
                    source_repo.update_resolution(
                        source["id"],
                        source_role=role,
                        resolution_status=browser_result.status,
                        resolution_notes=browser_result.notes,
                        discovered_artifacts=verified or [artifact.to_dict() for artifact in browser_result.artifacts],
                    )
            except BrowserResolverUnavailable as exc:
                if not dry_run:
                    source_repo.update_resolution(
                        source["id"],
                        source_role="landing_page",
                        resolution_status="needs_browser",
                        resolution_notes=str(exc),
                        discovered_artifacts=verified or [artifact.to_dict() for artifact in artifacts],
                    )
                verified.append({"discovery_method": "browser", "error": str(exc)})

        if not best_child and not dry_run:
            role = "gated_or_paywalled" if signals.status == "gated_or_paywalled" else "landing_page"
            source_repo.update_resolution(
                source["id"],
                source_role=role,
                resolution_status=signals.status,
                resolution_notes=signals.notes,
                discovered_artifacts=verified or [artifact.to_dict() for artifact in artifacts],
            )

    result = {"source_id": str(source_id), "resolved_source": best_child, "artifacts": verified, "dry_run": dry_run}
    if process_resolved and child_to_process:
        result["resolved_result"] = process_source(child_to_process, resolve_html_artifacts=False, process_resolved=False)
    return result


def print_summary(result: dict) -> None:
    artifacts = result.get("artifacts") or []
    print(f"source_id={result['source_id']} dry_run={result['dry_run']}")
    if result.get("skipped"):
        print(f"skipped={result['skipped']}")
    for index, artifact in enumerate(artifacts, start=1):
        verification = artifact.get("verification") or {}
        print(
            f"{index:02d}. score={artifact.get('score')} type={artifact.get('artifact_type')} "
            f"verified={verification.get('artifact_type')} downloadable={verification.get('is_downloadable')} "
            f"status={verification.get('status_code')}"
        )
        print(f"    url={artifact.get('url')}")
        if artifact.get("link_text"):
            print(f"    text={artifact.get('link_text')}")
        if verification.get("final_url") and verification.get("final_url") != artifact.get("url"):
            print(f"    final_url={verification.get('final_url')}")
    if result.get("resolved_source"):
        print(f"resolved_source={result['resolved_source']}")
    elif not artifacts:
        print("no_artifacts_found")


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve one HTML source into a downloadable artifact source.")
    parser.add_argument("--source-id", type=UUID, required=True)
    parser.add_argument("--process-resolved", action="store_true", default=False)
    parser.add_argument("--limit-candidates", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--force", action="store_true", default=False)
    parser.add_argument("--mode", choices=["static", "browser", "auto"], default="auto")
    parser.add_argument("--browser-timeout-seconds", type=int, default=20)
    parser.add_argument("--no-clicks", dest="allow_download_clicks", action="store_false", default=True)
    args = parser.parse_args()
    configure_logging()
    try:
        result = resolve_source(
            args.source_id,
            process_resolved=args.process_resolved,
            limit_candidates=args.limit_candidates,
            dry_run=args.dry_run,
            force=args.force,
            mode=args.mode,
            browser_timeout_seconds=args.browser_timeout_seconds,
            allow_download_clicks=args.allow_download_clicks,
        )
    except httpx.HTTPError as exc:
        raise SystemExit(f"Fetch failed: {exc}") from exc
    except OSError as exc:
        raise SystemExit(f"Local file read failed: {exc}") from exc
    print_summary(result)


if __name__ == "__main__":
    main()
