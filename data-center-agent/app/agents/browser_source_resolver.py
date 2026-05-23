from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlparse

from app.agents.source_resolver import (
    DiscoveredArtifact,
    SourceResolver,
    artifact_type_from_response,
    artifact_type_from_url,
)


SAFE_DOWNLOAD_TEXTS = [
    "Download PDF",
    "Download report",
    "Full report",
    "View PDF",
    "Report PDF",
    "Read report",
    "Download the full report",
]


@dataclass(frozen=True)
class BrowserResolutionResult:
    artifacts: list[DiscoveredArtifact]
    rendered_html: str
    status: str
    notes: str | None = None

    def to_dict(self) -> dict:
        return {
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "rendered_html": self.rendered_html,
            "status": self.status,
            "notes": self.notes,
        }


class BrowserResolverUnavailable(RuntimeError):
    pass


def _suffix(url: str) -> str:
    return PurePosixPath(urlparse(url).path.lower()).suffix


def _score_network_artifact(url: str, artifact_type: str) -> float:
    score = 80.0
    lower = url.lower()
    if artifact_type == "pdf":
        score += 80
    if artifact_type == "dataset_file":
        score += 70
    if "download" in lower:
        score += 25
    if "report" in lower:
        score += 25
    if "publication" in lower:
        score += 20
    if _suffix(url) == ".pdf":
        score += 40
    return score


class BrowserSourceResolver:
    def __init__(self, timeout_seconds: int = 20, allow_download_clicks: bool = True):
        self.timeout_ms = timeout_seconds * 1000
        self.allow_download_clicks = allow_download_clicks
        self.static_resolver = SourceResolver()

    def resolve(self, url: str) -> BrowserResolutionResult:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserResolverUnavailable(
                "Playwright is not installed. Install the browser extra and browsers before using browser resolution."
            ) from exc

        artifacts_by_url: dict[str, DiscoveredArtifact] = {}
        status = "unresolved"
        notes = None

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            def record_response(response) -> None:
                content_type = (response.headers.get("content-type") or "").split(";")[0].lower()
                artifact_type = artifact_type_from_response(response.url, content_type)
                if artifact_type not in {"pdf", "dataset_file"}:
                    return
                artifacts_by_url[response.url] = DiscoveredArtifact(
                    url=response.url,
                    artifact_type=artifact_type,
                    link_text=None,
                    score=_score_network_artifact(response.url, artifact_type),
                    reason=["browser_network_response", f"content_type:{content_type or 'unknown'}"],
                    discovery_method="network_response",
                )

            page.on("response", record_response)
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=min(self.timeout_ms, 8000))
                except PlaywrightTimeoutError:
                    pass
                if response and response.status in {401, 403}:
                    status = "gated_or_paywalled"
                    notes = f"browser received HTTP {response.status}"

                rendered_html = page.content()
                for artifact in self.static_resolver.discover_artifacts(rendered_html, page.url):
                    artifacts_by_url[artifact.url] = DiscoveredArtifact(
                        url=artifact.url,
                        artifact_type=artifact.artifact_type,
                        link_text=artifact.link_text,
                        score=artifact.score + 10,
                        reason=[*artifact.reason, "rendered_dom"],
                        discovery_method="rendered_dom",
                    )

                if self.allow_download_clicks and not artifacts_by_url:
                    self._click_safe_download_controls(page, artifacts_by_url)

                signals = self.static_resolver.inspect_html(rendered_html)
                if artifacts_by_url:
                    status = "resolved"
                    notes = "browser discovered downloadable artifact candidates"
                elif status != "gated_or_paywalled":
                    status = signals.status
                    notes = signals.notes
                return BrowserResolutionResult(
                    artifacts=sorted(artifacts_by_url.values(), key=lambda item: item.score, reverse=True),
                    rendered_html=rendered_html,
                    status=status,
                    notes=notes,
                )
            finally:
                context.close()
                browser.close()

    def _click_safe_download_controls(self, page, artifacts_by_url: dict[str, DiscoveredArtifact]) -> None:
        for text in SAFE_DOWNLOAD_TEXTS:
            locator = page.get_by_text(text, exact=False)
            try:
                count = min(locator.count(), 3)
            except Exception:
                continue
            for index in range(count):
                candidate = locator.nth(index)
                try:
                    with page.expect_download(timeout=3000) as download_info:
                        candidate.click(timeout=3000)
                    download = download_info.value
                    url = download.url
                    artifact_type = artifact_type_from_url(url)
                    if artifact_type not in {"pdf", "dataset_file"}:
                        continue
                    artifacts_by_url[url] = DiscoveredArtifact(
                        url=url,
                        artifact_type=artifact_type,
                        link_text=text,
                        score=_score_network_artifact(url, artifact_type) + 20,
                        reason=["browser_download", "safe_text_click"],
                        discovery_method="browser_download",
                    )
                    return
                except Exception:
                    continue
