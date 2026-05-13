from dataclasses import dataclass, field
from typing import Any, Literal


ContentQualityLabel = Literal[
    "full_report",
    "partial_report",
    "landing_page_only",
    "paywalled_or_gated",
    "js_required",
    "low_text",
    "failed",
]

GATED_TERMS = [
    "subscribe",
    "subscription",
    "register to read",
    "members only",
    "paywall",
    "permission denied",
    "access denied",
]

JS_TERMS = [
    "enable javascript",
    "requires javascript",
    "please enable js",
    "javascript is disabled",
    "app-root",
    "__next_data__",
]

LANDING_TERMS = [
    "home",
    "about",
    "contact",
    "login",
    "register",
    "navigation",
    "menu",
    "copyright",
]

REPORT_TERMS = [
    "methodology",
    "data source",
    "defined as",
    "measured as",
    "appendix",
    "technical notes",
    "executive summary",
    "table of contents",
]


@dataclass(frozen=True)
class ContentQualityResult:
    label: ContentQualityLabel
    reason: str
    chunk_count: int
    total_characters: int
    metadata: dict[str, Any] = field(default_factory=dict)


def classify_content_quality(
    chunks: list[Any],
    *,
    source_type: str | None = None,
    crawl_status: str | None = None,
    raw_text: str | None = None,
) -> ContentQualityResult:
    texts = [_get(chunk, "chunk_text") or "" for chunk in chunks]
    text = raw_text if raw_text is not None else "\n".join(texts)
    lowered = text.lower()
    chunk_count = len(chunks)
    total_characters = len(text)
    source_type = source_type or "unknown"

    if crawl_status == "failed" or not text.strip():
        return ContentQualityResult("failed", "no extracted text or source failed", chunk_count, total_characters)

    gated_hits = [term for term in GATED_TERMS if term in lowered]
    if gated_hits:
        return ContentQualityResult(
            "paywalled_or_gated",
            f"gated language detected: {', '.join(gated_hits[:3])}",
            chunk_count,
            total_characters,
            {"matched_terms": gated_hits},
        )

    js_hits = [term for term in JS_TERMS if term in lowered]
    if js_hits and total_characters < 5000:
        return ContentQualityResult(
            "js_required",
            f"javascript-required language detected: {', '.join(js_hits[:3])}",
            chunk_count,
            total_characters,
            {"matched_terms": js_hits},
        )

    report_hits = [term for term in REPORT_TERMS if term in lowered]
    landing_hits = [term for term in LANDING_TERMS if term in lowered]
    landing_ratio = len(landing_hits) / max(len(report_hits) + len(landing_hits), 1)

    if source_type == "html" and chunk_count <= 2 and total_characters < 3000 and landing_ratio >= 0.5:
        return ContentQualityResult(
            "landing_page_only",
            "short HTML with mostly navigation/landing-page language",
            chunk_count,
            total_characters,
            {"landing_terms": landing_hits, "report_terms": report_hits},
        )

    if chunk_count < 5 or total_characters < 3000:
        return ContentQualityResult("low_text", "fewer than 5 chunks or fewer than 3,000 characters", chunk_count, total_characters)

    if source_type == "html" and total_characters < 8000 and len(report_hits) < 2:
        return ContentQualityResult(
            "partial_report",
            "HTML content is present but lacks strong full-report markers",
            chunk_count,
            total_characters,
            {"report_terms": report_hits},
        )

    return ContentQualityResult(
        "full_report",
        "sufficient chunks/text and no gating markers detected",
        chunk_count,
        total_characters,
        {"report_terms": report_hits},
    )


def should_skip_codebook(
    quality: ContentQualityResult,
    *,
    force: bool = False,
    min_chunks: int = 5,
    min_characters: int = 3000,
) -> tuple[bool, str | None]:
    if force:
        return False, None
    if quality.chunk_count < min_chunks:
        return True, f"report has {quality.chunk_count} chunks; minimum is {min_chunks}"
    if quality.total_characters < min_characters:
        return True, f"report has {quality.total_characters} characters; minimum is {min_characters}"
    if quality.label in {"landing_page_only", "paywalled_or_gated", "js_required"}:
        return True, f"content quality is {quality.label}: {quality.reason}"
    return False, None


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
