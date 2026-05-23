from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup


PDF_TEXT_TERMS = [
    "download pdf",
    "download report",
    "full report",
    "view pdf",
    "report pdf",
    "publication",
    "read report",
    "download the full report",
]
GENERIC_NAV_TERMS = {"home", "contact", "about", "privacy", "terms", "login", "menu", "search"}
DATASET_SUFFIXES = {".csv", ".xlsx", ".xls", ".xlsm", ".zip"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico"}
GATED_TERMS = [
    "sign up",
    "register",
    "email required",
    "login",
    "subscribe",
    "subscription",
    "members only",
    "paywall",
]


@dataclass(frozen=True)
class DiscoveredArtifact:
    url: str
    artifact_type: str
    link_text: str | None
    score: float
    reason: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ArtifactVerification:
    url: str
    final_url: str | None
    status_code: int | None
    content_type: str | None
    artifact_type: str
    is_downloadable: bool
    error_message: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class HtmlResolutionSignals:
    status: str
    notes: str
    button_without_href_count: int = 0
    form_count: int = 0
    email_field_count: int = 0
    download_anchor_without_url_count: int = 0
    gated_terms: list[str] | None = None


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def _path_suffix(url: str) -> str:
    return PurePosixPath(urlparse(url).path.lower()).suffix


def _content_type(headers: httpx.Headers) -> str | None:
    value = headers.get("content-type", "").split(";")[0].strip().lower()
    return value or None


def artifact_type_from_url(url: str) -> str:
    lower = url.lower()
    suffix = _path_suffix(url)
    if suffix == ".pdf" or ".pdf" in lower or "/pdf/" in lower:
        return "pdf"
    if suffix in DATASET_SUFFIXES:
        return "dataset_file"
    if suffix in {".html", ".htm"}:
        return "html"
    return "unknown"


def artifact_type_from_response(url: str, content_type: str | None, first_bytes: bytes = b"") -> str:
    lowered = (content_type or "").lower()
    if first_bytes.startswith(b"%PDF") or lowered == "application/pdf":
        return "pdf"
    if lowered in {"text/csv", "application/csv"} or "spreadsheet" in lowered or "excel" in lowered:
        return "dataset_file"
    if "zip" in lowered:
        return "dataset_file"
    if "html" in lowered:
        return "html"
    return artifact_type_from_url(url)


class SourceResolver:
    def discover_artifacts(self, html: str, base_url: str) -> list[DiscoveredArtifact]:
        soup = BeautifulSoup(html, "html.parser")
        candidates: dict[str, DiscoveredArtifact] = {}

        for a_tag in soup.find_all("a", href=True):
            href = (a_tag.get("href") or "").strip()
            link_text = _clean_text(a_tag.get_text(" "))
            artifact = self._score_link(href, link_text, base_url)
            if not artifact:
                continue
            existing = candidates.get(artifact.url)
            if existing is None or artifact.score > existing.score:
                candidates[artifact.url] = artifact

        return sorted(candidates.values(), key=lambda item: item.score, reverse=True)

    def pick_best_artifact(self, artifacts: list[DiscoveredArtifact]) -> DiscoveredArtifact | None:
        if not artifacts:
            return None
        positive = [artifact for artifact in artifacts if artifact.score > 0]
        return positive[0] if positive else None

    def inspect_html(self, html: str) -> HtmlResolutionSignals:
        soup = BeautifulSoup(html, "html.parser")
        lowered = soup.get_text(" ", strip=True).lower()
        gated_hits = [term for term in GATED_TERMS if term in lowered]
        form_count = len(soup.find_all("form"))
        email_fields = soup.find_all("input", attrs={"type": "email"})
        named_email_fields = soup.find_all("input", attrs={"name": lambda value: value and "email" in value.lower()})
        button_without_href_count = 0
        download_anchor_without_url_count = 0

        for button in soup.find_all("button"):
            text = _clean_text(button.get_text(" ")).lower()
            if any(term in text for term in ("download", "report", "pdf")):
                button_without_href_count += 1

        for a_tag in soup.find_all("a"):
            href = (a_tag.get("href") or "").strip()
            text = _clean_text(a_tag.get_text(" ")).lower()
            if any(term in text for term in ("download", "report", "pdf")) and href in {"", "#"}:
                download_anchor_without_url_count += 1

        email_count = len(email_fields) + len(named_email_fields)
        if gated_hits or email_count:
            return HtmlResolutionSignals(
                status="gated_or_paywalled",
                notes="gated/download form indicators detected",
                button_without_href_count=button_without_href_count,
                form_count=form_count,
                email_field_count=email_count,
                download_anchor_without_url_count=download_anchor_without_url_count,
                gated_terms=gated_hits,
            )
        if form_count or button_without_href_count or download_anchor_without_url_count:
            return HtmlResolutionSignals(
                status="needs_browser",
                notes="download controls found without direct artifact links",
                button_without_href_count=button_without_href_count,
                form_count=form_count,
                email_field_count=email_count,
                download_anchor_without_url_count=download_anchor_without_url_count,
                gated_terms=gated_hits,
            )
        return HtmlResolutionSignals(status="unresolved", notes="no verified downloadable artifact found")

    def _score_link(self, href: str, link_text: str, base_url: str) -> DiscoveredArtifact | None:
        if not href or href.startswith("#") or href.lower().startswith(("mailto:", "tel:", "javascript:")):
            return None

        full_url = urljoin(base_url, href)
        lower_url = full_url.lower()
        lower_text = link_text.lower()
        suffix = _path_suffix(full_url)
        score = 0.0
        reasons: list[str] = []

        if suffix == ".pdf":
            score += 100
            reasons.append("url_ends_pdf")
        if ".pdf" in lower_url:
            score += 80
            reasons.append("url_contains_pdf")
        if "/pdf/" in lower_url:
            score += 40
            reasons.append("url_pdf_path")
        if "download" in lower_url:
            score += 25
            reasons.append("url_download")
        if "download" in lower_text:
            score += 40
            reasons.append("text_download")
        if "full report" in lower_text:
            score += 40
            reasons.append("text_full_report")
        if "pdf" in lower_text:
            score += 30
            reasons.append("text_pdf")
        if "report" in lower_url:
            score += 25
            reasons.append("url_report")
        if "publication" in lower_url:
            score += 20
            reasons.append("url_publication")
        if "whitepaper" in lower_url:
            score += 20
            reasons.append("url_whitepaper")
        if "file" in lower_url:
            score += 15
            reasons.append("url_file")
        if "assets" in lower_url or "uploads" in lower_url:
            score += 15
            reasons.append("url_assets_uploads")
        if any(term in lower_text for term in PDF_TEXT_TERMS):
            score += 30
            reasons.append("report_link_text")
        if suffix in DATASET_SUFFIXES:
            score += 90
            reasons.append("dataset_extension")
            if any(term in lower_text or term in lower_url for term in ("data", "dataset", "download")):
                score += 50
                reasons.append("dataset_oriented")

        if any(term in lower_url for term in ("facebook.com", "twitter.com", "x.com/share", "linkedin.com", "mailto:")):
            score -= 50
            reasons.append("social_or_share")
        if urlparse(full_url).fragment and not urlparse(full_url).path:
            score -= 40
            reasons.append("same_page_anchor")
        if lower_text in GENERIC_NAV_TERMS:
            score -= 30
            reasons.append("generic_navigation")
        if suffix in IMAGE_SUFFIXES:
            score -= 20
            reasons.append("image_url")

        artifact_type = artifact_type_from_url(full_url)
        if score <= 0 or artifact_type == "html":
            if not any(term in lower_text for term in ("download", "report", "publication", "pdf")):
                return None
        return DiscoveredArtifact(
            url=full_url,
            artifact_type=artifact_type,
            link_text=link_text or None,
            score=score,
            reason=reasons,
        )


def verify_artifact_url(
    url: str,
    timeout_seconds: int = 30,
    client: httpx.Client | None = None,
) -> ArtifactVerification:
    owns_client = client is None
    active_client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
    try:
        try:
            response = active_client.head(url)
            if response.status_code in {405, 501} or response.status_code >= 500:
                response = active_client.get(url, headers={"Range": "bytes=0-4095"})
        except httpx.HTTPError:
            response = active_client.get(url, headers={"Range": "bytes=0-4095"})

        status_code = response.status_code
        content_type = _content_type(response.headers)
        final_url = str(response.url)
        if status_code in {401, 403}:
            return ArtifactVerification(url, final_url, status_code, content_type, "gated_or_paywalled", False)
        if status_code >= 400:
            return ArtifactVerification(url, final_url, status_code, content_type, "unknown", False)

        first_bytes = b""
        if response.request.method.upper() == "GET":
            first_bytes = response.content[:512]
        if response.request.method.upper() == "HEAD" and (
            content_type is None or "html" in content_type or artifact_type_from_url(final_url) == "unknown"
        ):
            try:
                get_response = active_client.get(final_url, headers={"Range": "bytes=0-4095"})
                first_bytes = get_response.content[:512]
                content_type = _content_type(get_response.headers) or content_type
                status_code = get_response.status_code
                final_url = str(get_response.url)
            except httpx.HTTPError:
                pass

        artifact_type = artifact_type_from_response(final_url, content_type, first_bytes)
        return ArtifactVerification(
            url=url,
            final_url=final_url,
            status_code=status_code,
            content_type=content_type,
            artifact_type=artifact_type,
            is_downloadable=artifact_type in {"pdf", "dataset_file"},
        )
    except httpx.HTTPError as exc:
        return ArtifactVerification(url, None, None, None, "unknown", False, str(exc))
    finally:
        if owns_client:
            active_client.close()
