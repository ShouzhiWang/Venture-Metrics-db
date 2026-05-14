"""Content quality classification with dual labels and keyword awareness.

Produces two independent labels:
  1. source_resolution_status — can we fetch and parse this source?
  2. extraction_eligibility — should we run codebook extraction?

Keyword analysis detects methodology/definition/data-source language
even in short texts, allowing extraction from <5-chunk reports when
strong analytical content is present.
"""

from dataclasses import dataclass, field
from typing import Any, Literal


# --- Label types ---

SourceResolutionStatus = Literal[
    "full_report",
    "partial_report",
    "landing_page_only",
    "paywalled_or_gated",
    "js_required",
    "low_text",
    "failed",
    "pending",
]

ExtractionEligibility = Literal[
    "eligible",
    "eligible_conditional",  # extract but mark all vars needs_review
    "ineligible_gated",
    "ineligible_low_text",
    "ineligible_failed",
]


# --- Term lists ---

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

# Strong methodology/definition keywords — presence of these
# indicates the text contains extractable variable definitions
# even if short.
STRONG_KEYWORDS = {
    "defined as": 3.0,
    "measured as": 3.0,
    "measured by": 3.0,
    "calculated as": 3.0,
    "proxy for": 2.5,
    "methodology": 2.0,
    "data source": 2.0,
    "data sources": 2.0,
    "variable definition": 3.0,
    "indicator definition": 3.0,
    "temporal coverage": 2.0,
    "geographic coverage": 2.0,
    "unit of measurement": 2.0,
    "source:": 1.5,
}

STRONG_KEYWORD_THRESHOLD = 3.0  # sum of weights needed to pass


# --- Data classes ---

@dataclass(frozen=True)
class ContentQualityResult:
    """Dual-label quality result for a source/report."""
    # Label 1: fetchability
    source_resolution_status: SourceResolutionStatus
    resolution_reason: str
    # Label 2: extraction eligibility
    extraction_eligibility: ExtractionEligibility
    eligibility_reason: str
    # Shared metrics
    chunk_count: int
    total_characters: int
    strong_keyword_score: float = 0.0
    strong_keyword_hits: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Backward compat properties
    @property
    def label(self) -> SourceResolutionStatus:
        return self.source_resolution_status

    @property
    def reason(self) -> str:
        return self.resolution_reason


def compute_strong_keyword_score(text: str) -> tuple[float, list[str]]:
    """Score text for strong methodology/definition/data-source language.

    Returns (score, matched_terms). A score >= STRONG_KEYWORD_THRESHOLD
    indicates the text likely contains extractable variable definitions.
    """
    lowered = text.lower()
    score = 0.0
    hits: list[str] = []
    for keyword, weight in STRONG_KEYWORDS.items():
        occurrences = lowered.count(keyword)
        if occurrences > 0:
            contribution = min(weight * occurrences, weight * 3)
            score += contribution
            hits.append(keyword)
    return score, hits


def classify_content_quality(
    chunks: list[Any],
    *,
    source_type: str | None = None,
    crawl_status: str | None = None,
    raw_text: str | None = None,
) -> ContentQualityResult:
    """Classify content with dual labels: resolution status + extraction eligibility."""
    texts = [_get(chunk, "chunk_text") or "" for chunk in chunks]
    text = raw_text if raw_text is not None else "\n".join(texts)
    lowered = text.lower()
    chunk_count = len(chunks)
    total_characters = len(text)
    source_type = source_type or "unknown"

    # Compute strong keyword score
    kw_score, kw_hits = compute_strong_keyword_score(text)

    # --- Failure cases ---
    if crawl_status == "failed" or not text.strip():
        return ContentQualityResult(
            source_resolution_status="failed",
            resolution_reason="no extracted text or source failed",
            extraction_eligibility="ineligible_failed",
            eligibility_reason="source failed or no text",
            chunk_count=chunk_count,
            total_characters=total_characters,
            strong_keyword_score=kw_score,
            strong_keyword_hits=kw_hits,
        )

    # --- Gated/paywalled ---
    gated_hits = [term for term in GATED_TERMS if term in lowered]
    if gated_hits and kw_score < STRONG_KEYWORD_THRESHOLD:
        return ContentQualityResult(
            source_resolution_status="paywalled_or_gated",
            resolution_reason=f"gated language detected: {', '.join(gated_hits[:3])}",
            extraction_eligibility="ineligible_gated",
            eligibility_reason=f"gated language: {', '.join(gated_hits[:3])}",
            chunk_count=chunk_count,
            total_characters=total_characters,
            strong_keyword_score=kw_score,
            strong_keyword_hits=kw_hits,
            metadata={"matched_terms": gated_hits},
        )

    # --- JS required (low text only) ---
    js_hits = [term for term in JS_TERMS if term in lowered]
    if js_hits and total_characters < 5000:
        return ContentQualityResult(
            source_resolution_status="js_required",
            resolution_reason=f"javascript-required language detected: {', '.join(js_hits[:3])}",
            extraction_eligibility="ineligible_gated",
            eligibility_reason=f"JS required: {', '.join(js_hits[:3])}",
            chunk_count=chunk_count,
            total_characters=total_characters,
            strong_keyword_score=kw_score,
            strong_keyword_hits=kw_hits,
            metadata={"matched_terms": js_hits},
        )

    # --- Landing page (HTML + short + navigation-heavy) ---
    report_hits = [term for term in REPORT_TERMS if term in lowered]
    landing_hits = [term for term in LANDING_TERMS if term in lowered]
    landing_ratio = len(landing_hits) / max(len(report_hits) + len(landing_hits), 1)

    if source_type == "html" and chunk_count <= 2 and total_characters < 3000 and landing_ratio >= 0.5:
        return ContentQualityResult(
            source_resolution_status="landing_page_only",
            resolution_reason="short HTML with mostly navigation/landing-page language",
            extraction_eligibility="ineligible_low_text",
            eligibility_reason="landing page with no extractable content",
            chunk_count=chunk_count,
            total_characters=total_characters,
            strong_keyword_score=kw_score,
            strong_keyword_hits=kw_hits,
            metadata={"landing_terms": landing_hits, "report_terms": report_hits},
        )

    # --- Low text: check for strong keywords ---
    if chunk_count < 5 or total_characters < 3000:
        if kw_score >= STRONG_KEYWORD_THRESHOLD:
            # Short but rich — allow extraction, mark conditional
            return ContentQualityResult(
                source_resolution_status="low_text",
                resolution_reason=f"fewer than 5 chunks or fewer than 3,000 characters, but has strong keywords",
                extraction_eligibility="eligible_conditional",
                eligibility_reason=f"strong keyword score {kw_score:.1f} (>= {STRONG_KEYWORD_THRESHOLD}); all variables will be needs_review",
                chunk_count=chunk_count,
                total_characters=total_characters,
                strong_keyword_score=kw_score,
                strong_keyword_hits=kw_hits,
                metadata={"report_terms": report_hits},
            )
        return ContentQualityResult(
            source_resolution_status="low_text",
            resolution_reason="fewer than 5 chunks or fewer than 3,000 characters, no strong keywords",
            extraction_eligibility="ineligible_low_text",
            eligibility_reason=f"low text ({chunk_count} chunks, {total_characters} chars) with no strong methodology keywords",
            chunk_count=chunk_count,
            total_characters=total_characters,
            strong_keyword_score=kw_score,
            strong_keyword_hits=kw_hits,
        )

    # --- Partial report (HTML, short, few report terms) ---
    if source_type == "html" and total_characters < 8000 and len(report_hits) < 2:
        return ContentQualityResult(
            source_resolution_status="partial_report",
            resolution_reason="HTML content is present but lacks strong full-report markers",
            extraction_eligibility="eligible_conditional",
            eligibility_reason="partial report; all variables will be needs_review",
            chunk_count=chunk_count,
            total_characters=total_characters,
            strong_keyword_score=kw_score,
            strong_keyword_hits=kw_hits,
            metadata={"report_terms": report_hits},
        )

    # --- Full report ---
    return ContentQualityResult(
        source_resolution_status="full_report",
        resolution_reason="sufficient chunks/text and no gating markers detected",
        extraction_eligibility="eligible",
        eligibility_reason="sufficient content for extraction",
        chunk_count=chunk_count,
        total_characters=total_characters,
        strong_keyword_score=kw_score,
        strong_keyword_hits=kw_hits,
        metadata={"report_terms": report_hits},
    )


def should_skip_codebook(
    quality: ContentQualityResult,
    *,
    force: bool = False,
) -> tuple[bool, str | None]:
    """Determine whether to skip codebook extraction.

    Uses extraction_eligibility label rather than raw chunk counts.
    - 'eligible' → extract normally
    - 'eligible_conditional' → extract, but all vars get needs_review
    - 'ineligible_*' → skip unless --force
    """
    if force:
        return False, None

    eligibility = quality.extraction_eligibility
    if eligibility == "eligible":
        return False, None
    if eligibility == "eligible_conditional":
        return False, None  # allow extraction, caller handles needs_review
    # ineligible
    return True, f"{eligibility}: {quality.eligibility_reason}"


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
