"""Source kind classifier for connector candidates.

Classifies URLs into source_kind categories using URL patterns,
file extensions, and lightweight HTTP inspection.
No deep crawling — at most a HEAD request for content-type.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# --- URL pattern → source_kind mapping ---

# API endpoint patterns
API_PATTERNS = [
    r"/api/",
    r"/api$",
    r"\bapi\b.*\b(json|xml|rest|graphql)\b",
    r"format=json",
    r"format=csv",
    r"format=xml",
    r"/v[0-9]+/",
    r"odata",
    r"data\.gov\.hk.*api",
]

# Data.gov.hk specific
DATA_GOV_HK_PATTERNS = [
    r"data\.gov\.hk",
]

# Search/portal patterns
SEARCH_PORTAL_PATTERNS = [
    r"search",
    r"检索",
    r"检索系统",
    r"智快搜",
    r"finder",
    r"query",
    r"lookup",
]

OFFICIAL_PORTAL_PATTERNS = [
    r"\.gov\.",
    r"gov\.hk",
    r"official",
    r"公报",
    r"gazette",
]

# Organization patterns
ORG_PATTERNS = [
    r"tto\b",
    r"technology.transfer",
    r"知识转移",
    r"技术转移",
    r"incubat",
    r"孵化",
    r"accelerat",
    r"加速器",
    r"创业",
    r"entrepreneur",
    r"innovation.centre",
    r"创新中心",
]

STARTUP_DIR_PATTERNS = [
    r"startup",
    r"spin.off",
    r"初创",
    r"衍生公司",
    r"incubatee",
    r"portfolio",
]

# Extension → source_kind
EXTENSION_MAP = {
    ".csv": "downloadable_csv",
    ".tsv": "downloadable_csv",
    ".xlsx": "downloadable_xlsx",
    ".xls": "downloadable_xlsx",
    ".pdf": "downloadable_pdf",
    ".json": "api_endpoint",
    ".xml": "api_endpoint",
    ".geojson": "downloadable_csv",
}

# Content-type → source_kind
CONTENT_TYPE_MAP = {
    "text/csv": "downloadable_csv",
    "application/csv": "downloadable_csv",
    "application/vnd.ms-excel": "downloadable_xlsx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "downloadable_xlsx",
    "application/pdf": "downloadable_pdf",
    "application/json": "api_endpoint",
    "application/xml": "api_endpoint",
    "text/xml": "api_endpoint",
}


def classify_source_kind(
    url: str,
    *,
    row_metadata: dict | None = None,
    content_type: str | None = None,
    page_title: str | None = None,
) -> tuple[str, float]:
    """Classify a URL into a source_kind with confidence score.

    Returns (source_kind, confidence).
    Uses URL patterns, extensions, and optional content-type/title signals.
    Does NOT fetch the URL — pass content_type if you have it.
    """
    if not url:
        return ("unknown", 0.0)

    parsed = urlparse(url)
    path_lower = parsed.path.lower()
    url_lower = url.lower()
    ext = _get_extension(path_lower)

    # 1. Strong signal: file extension
    if ext in EXTENSION_MAP:
        kind = EXTENSION_MAP[ext]
        return (kind, 0.95)

    # 2. Strong signal: content-type from HTTP header
    if content_type:
        ct_lower = content_type.split(";")[0].strip().lower()
        if ct_lower in CONTENT_TYPE_MAP:
            return (CONTENT_TYPE_MAP[ct_lower], 0.95)

    # 3. URL pattern matching (order matters — more specific first)

    # Data.gov.hk — check metadata for data type signals before defaulting to portal
    if _match_any(url_lower, DATA_GOV_HK_PATTERNS):
        if _match_any(url_lower, API_PATTERNS):
            return ("api_endpoint", 0.85)
        # Check row metadata for CSV/download signals
        if row_metadata:
            meta_text = " ".join(str(v) for v in row_metadata.values() if v).lower()
            if any(t in meta_text for t in ("csv", "下载", "download")):
                return ("downloadable_csv", 0.80)
            if any(t in meta_text for t in ("xlsx", "excel", "xls")):
                return ("downloadable_xlsx", 0.80)
            if any(t in meta_text for t in ("api", "接口")):
                return ("api_endpoint", 0.80)
        return ("official_portal", 0.80)

    # API patterns
    if _match_any(url_lower, API_PATTERNS):
        return ("api_endpoint", 0.80)

    # Startup directory
    if _match_any(url_lower, STARTUP_DIR_PATTERNS):
        return ("startup_directory", 0.75)

    # Organization page (TTO, incubator, etc.)
    if _match_any(url_lower, ORG_PATTERNS):
        return ("organization_page", 0.75)

    # Search portal
    if _match_any(url_lower, SEARCH_PORTAL_PATTERNS):
        return ("search_portal", 0.70)

    # Official portal
    if _match_any(url_lower, OFFICIAL_PORTAL_PATTERNS):
        return ("official_portal", 0.70)

    # 4. Row metadata signals (from Excel columns)
    # Exclude related-URL columns to avoid false positives from companion PDFs/links
    if row_metadata:
        _RELATED_URL_KEYS = {"相关资料", "related_url", "related_urls", "related resources"}
        filtered_meta = {k: v for k, v in row_metadata.items() if k.lower().strip() not in _RELATED_URL_KEYS}
        meta_text = " ".join(str(v) for v in filtered_meta.values() if v).lower()
        if any(t in meta_text for t in ("csv", "下载", "download", "数据", "dataset", "统计")):
            return ("downloadable_csv", 0.60)
        if any(t in meta_text for t in ("api", "接口", "endpoint")):
            return ("api_endpoint", 0.60)
        if any(t in meta_text for t in ("pdf", "报告", "report", "公报")):
            return ("downloadable_pdf", 0.60)
        if any(t in meta_text for t in ("初创", "startup", "spin-off", "孵化", "incubat")):
            return ("startup_directory", 0.60)
        if any(t in meta_text for t in ("检索", "search", "portal", "系统")):
            return ("search_portal", 0.55)
        if any(t in meta_text for t in ("tto", "技术转移", "知识转移", "knowledge transfer", "knowledge transfer office")):
            return ("organization_page", 0.55)

    # 5. Default for generic .gov/.org pages
    if parsed.scheme in ("http", "https"):
        return ("unknown", 0.30)

    return ("unknown", 0.0)


def classify_ecosystem_category(
    source_kind: str,
    row_metadata: dict | None = None,
    source_set: str | None = None,
) -> str:
    """Infer ecosystem_category from source_kind and context."""
    if source_set == "hk_patent":
        if source_kind in ("api_endpoint", "downloadable_csv", "downloadable_xlsx"):
            return "public_dataset"
        if source_kind in ("search_portal", "official_portal"):
            return "patents_ip"
        if source_kind == "downloadable_pdf":
            return "innovation_output"
        return "patents_ip"

    if source_set == "hk_tto":
        if source_kind == "startup_directory":
            return "startup_directory"
        if source_kind == "organization_page":
            return "university_tto"
        return "ecosystem_organization"

    # Infer from metadata
    if row_metadata:
        meta_text = " ".join(str(v) for v in row_metadata.values() if v).lower()
        if any(t in meta_text for t in ("tto", "技术转移", "知识转移", "knowledge transfer")):
            return "university_tto"
        if any(t in meta_text for t in ("孵化", "incubat", "accelerat")):
            return "incubator"
        if any(t in meta_text for t in ("初创", "startup", "spin-off")):
            return "startup_directory"
        if any(t in meta_text for t in ("专利", "patent", "ip", "知识产权")):
            return "patents_ip"

    return "uncategorized"


def infer_organization_type(row_metadata: dict | None = None) -> str | None:
    """Infer organization_type from TTO Excel row metadata."""
    if not row_metadata:
        return None
    type_val = str(row_metadata.get("类型", "")).strip()
    mapping = {
        "TTO": "tto",
        "孵化器": "incubator",
        "初创列表": "startup_directory",
    }
    return mapping.get(type_val, "ecosystem_organization")


def _get_extension(path: str) -> str:
    """Get file extension from URL path, handling query strings."""
    # Remove query params that look like file refs
    clean = path.split("?")[0].split("#")[0]
    if "." in clean:
        return "." + clean.rsplit(".", 1)[-1].lower()
    return ""


def _match_any(text: str, patterns: list[str]) -> bool:
    """Check if any regex pattern matches the text."""
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False
