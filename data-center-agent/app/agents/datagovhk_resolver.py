"""DataGovHK Resource Resolver.

Resolves data.gov.hk portal/homepage URLs into actual downloadable CSV/XLSX
resources using CKAN metadata APIs and Historical Archive File List API.

Resolution strategy:
1. If URL has a CKAN dataset ID → package_show
2. If URL is portal homepage → keyword search via Historical Archive
3. If URL is dataset page → try CKAN package_show, fallback to archive search
4. Rank candidates by keyword/provider/format match
5. Return best candidates for sync
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Historical Archive API base
ARCHIVE_API = "https://app.data.gov.hk/v1/historical-archive/list-files"

# CKAN API patterns
CKAN_BASES = [
    "https://data.gov.hk/en-data",
    "https://data.gov.hk/tc-data",
    "https://data.gov.hk/sc-data",
]

# IP-related keywords for matching
IP_KEYWORDS_EN = [
    "patent", "trademark", "trade mark", "design", "intellectual property",
    "ip statistics", "registration", "application", "ipd",
]
IP_KEYWORDS_ZH = [
    "商标", "商標", "专利", "專利", "外观设计", "外觀設計",
    "知识产权", "知識產權", "申请", "申請", "注册", "註冊", "统计", "統計",
]

# Best-first dataset descriptions for the curated row
BEST_DATASET_HINTS = [
    "trademark.*patent.*design.*application",
    "registrations.*grants.*trademarks.*patents.*designs",
    "standard patent.*applications",
    "design applications.*origin",
    "short.term.patents",
]


@dataclass
class ResourceCandidate:
    """A candidate resource found by the resolver."""
    url: str
    dataset_id: str | None = None
    dataset_name: str | None = None
    resource_name: str | None = None
    format: str = "csv"
    provider: str | None = None
    source: str = "unknown"  # 'ckan', 'archive', 'direct'
    confidence: float = 0.0
    size: int | None = None
    version_count: int | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ResolutionResult:
    """Result of resolving a data.gov.hk URL."""
    success: bool = False
    original_url: str = ""
    methods_attempted: list[str] = field(default_factory=list)
    ckan_candidates: list[ResourceCandidate] = field(default_factory=list)
    archive_candidates: list[ResourceCandidate] = field(default_factory=list)
    selected: ResourceCandidate | None = None
    failure_reason: str | None = None
    all_candidates: list[ResourceCandidate] = field(default_factory=list)


class DataGovHKResourceResolver:
    """Resolves data.gov.hk portal URLs into downloadable resource URLs."""

    def __init__(self, *, timeout: int = 30, max_candidates: int = 50):
        self.timeout = timeout
        self.max_candidates = max_candidates

    def resolve(
        self,
        url: str,
        *,
        title: str | None = None,
        description: str | None = None,
        source_set: str | None = None,
        provider_hint: str | None = None,
        format_hint: str | None = None,
    ) -> ResolutionResult:
        """Main resolution entry point."""
        result = ResolutionResult(original_url=url)
        parsed = urlparse(url)
        path = parsed.path.lower()

        # Strategy A: URL has a CKAN dataset ID
        dataset_id = self._extract_dataset_id(path)
        if dataset_id:
            result.methods_attempted.append(f"ckan_package_show({dataset_id})")
            candidates = self._ckan_package_show(dataset_id)
            result.ckan_candidates.extend(candidates)

        # Strategy B: Portal homepage or generic URL — use keyword search
        if not result.ckan_candidates:
            keywords = self._build_keywords(title, description, source_set)

            # Try Historical Archive API
            result.methods_attempted.append(f"archive_search(keywords={keywords[:3]})")
            archive_cands = self._search_historical_archive(
                keywords,
                provider_hint=provider_hint or "hk-ipd",
                format_hint=format_hint or "csv",
            )
            result.archive_candidates.extend(archive_cands)

            # Try CKAN package search (via list + local filter)
            result.methods_attempted.append("ckan_keyword_search")
            ckan_cands = self._ckan_keyword_search(keywords, provider_hint=provider_hint)
            result.ckan_candidates.extend(ckan_cands)

        # Combine and rank
        all_candidates = result.ckan_candidates + result.archive_candidates
        ranked = self.rank_candidates(all_candidates, title=title, description=description)
        result.all_candidates = ranked

        if ranked and ranked[0].confidence >= 2.5:
            result.selected = ranked[0]
            result.success = True
        else:
            best_conf = ranked[0].confidence if ranked else 0
            result.failure_reason = (
                f"No high-confidence match found. Best candidate confidence: {best_conf}. "
                f"Found {len(ranked)} candidates but none matched IP/trademark/patent criteria strongly enough."
            )

        return result

    def _extract_dataset_id(self, path: str) -> str | None:
        """Extract CKAN dataset ID from URL path."""
        # /en-data/dataset/<id>
        match = re.search(r"/dataset/([a-zA-Z0-9_-]+)", path)
        if match:
            return match.group(1)
        # /en-data/api/3/action/package_show?id=<id>
        match = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", path)
        if match:
            return match.group(1)
        return None

    def _build_keywords(self, title: str | None, description: str | None, source_set: str | None) -> list[str]:
        """Build keyword list from curated row metadata."""
        keywords = []

        if title:
            # Extract meaningful words — split Chinese compound terms
            raw_words = re.findall(r'[\w\u4e00-\u9fff]+', title.lower())
            for w in raw_words:
                keywords.append(w)
                # Split Chinese compound terms (e.g. 外观设计 → 外观, 设计)
                if len(w) > 2 and any('\u4e00' <= c <= '\u9fff' for c in w):
                    # Add 2-char substrings for better matching
                    for i in range(0, len(w) - 1):
                        sub = w[i:i+2]
                        if sub not in ('申请', '注册', '统计', '及注'):  # Skip generic terms
                            keywords.append(sub)

        if description:
            keywords.extend(re.findall(r'[\w\u4e00-\u9fff]+', description.lower()))

        if source_set == "hk_patent":
            keywords.extend(["patent", "trademark", "design", "statistics",
                             "商标", "专利", "外观设计", "统计",
                             "registration", "application", "ipd"])

        # Deduplicate while preserving order, prioritize English and specific terms
        seen = set()
        unique = []
        # Prioritize high-value keywords
        priority = {"patent", "trademark", "design", "ipd", "专利", "商标", "外观设计"}
        for kw in priority:
            if kw not in seen and len(kw) > 1:
                seen.add(kw)
                unique.append(kw)
        for kw in keywords:
            if kw not in seen and len(kw) > 1:
                seen.add(kw)
                unique.append(kw)

        return unique[:20]  # Limit keywords

    def _search_historical_archive(
        self,
        keywords: list[str],
        provider_hint: str | None = None,
        format_hint: str | None = None,
    ) -> list[ResourceCandidate]:
        """Search the Historical Archive File List API."""
        candidates = []

        # Build search queries — try provider-based search first, then keyword-based
        search_queries = []

        # If we have a provider hint, search by provider directly
        if provider_hint:
            search_queries.append({"provider": provider_hint})

        # Then try keyword searches with English keywords (archive API works better with English)
        english_keywords = [kw for kw in keywords if kw.isascii() and len(kw) > 2]
        chinese_keywords = [kw for kw in keywords if not kw.isascii() and len(kw) > 1]

        for kw in english_keywords[:3]:
            search_queries.append({"search": kw})
            if provider_hint:
                search_queries.append({"search": kw, "provider": provider_hint})

        for kw in chinese_keywords[:2]:
            search_queries.append({"search": kw})

        seen_urls = set()
        for query_params in search_queries[:5]:  # Limit API calls
            try:
                params = {
                    "start": "20100101",
                    "end": datetime.now(timezone.utc).strftime("%Y%m%d"),
                    "max": str(self.max_candidates),
                }
                params.update(query_params)
                if format_hint and "format" not in params:
                    params["format"] = format_hint

                query = "&".join(f"{k}={v}" for k, v in params.items())
                url = f"{ARCHIVE_API}?{query}"

                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.get(url)
                    resp.raise_for_status()
                    data = resp.json()

                for f in data.get("files", []):
                    file_url = f.get("url", "")
                    if not file_url or file_url in seen_urls:
                        continue
                    seen_urls.add(file_url)

                    # Determine format
                    fmt = f.get("format", "").lower()
                    if not fmt:
                        ext = urlparse(file_url).path.rsplit(".", 1)[-1].lower() if "." in urlparse(file_url).path else ""
                        fmt = ext if ext in ("csv", "xls", "xlsx", "json") else "unknown"

                    candidates.append(ResourceCandidate(
                        url=file_url,
                        dataset_id=f.get("dataset-id"),
                        dataset_name=f.get("dataset-name-en") or f.get("dataset-name-sc") or f.get("dataset-name-tc"),
                        resource_name=f.get("resource-name-en") or f.get("resource-name-sc"),
                        format=fmt,
                        provider=f.get("provider-id"),
                        source="archive",
                        size=f.get("total-size"),
                        version_count=f.get("version-count"),
                        metadata={
                            "category": f.get("category-id"),
                            "data_dictionary": f.get("data_dictionary"),
                        },
                    ))

            except Exception as exc:
                logger.warning("Historical Archive search failed for %s: %s", query_params, exc)

        return candidates

    def _ckan_package_show(self, dataset_id: str) -> list[ResourceCandidate]:
        """Fetch a CKAN package and extract resources."""
        candidates = []
        for base in CKAN_BASES:
            try:
                url = f"{base}/api/3/action/package_show?id={dataset_id}"
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.get(url, headers={"Accept": "application/json"})
                    if resp.status_code != 200:
                        continue
                    data = resp.json()

                if not data.get("success"):
                    continue

                pkg = data.get("result", {})
                for res in pkg.get("resources", []):
                    res_url = res.get("url", "")
                    fmt = res.get("format", "").lower()
                    if fmt in ("csv", "xls", "xlsx", "json"):
                        candidates.append(ResourceCandidate(
                            url=res_url,
                            dataset_id=dataset_id,
                            dataset_name=pkg.get("title"),
                            resource_name=res.get("name") or res.get("description"),
                            format=fmt,
                            source="ckan",
                            metadata={
                                "ckan_package": dataset_id,
                                "resource_id": res.get("id"),
                                "last_modified": res.get("last_modified"),
                            },
                        ))
                if candidates:
                    break  # Found on this locale

            except Exception as exc:
                logger.warning("CKAN package_show failed for %s on %s: %s", dataset_id, base, exc)

        return candidates

    def _ckan_keyword_search(
        self,
        keywords: list[str],
        provider_hint: str | None = None,
    ) -> list[ResourceCandidate]:
        """Search CKAN by fetching package_list and filtering locally."""
        candidates = []

        for base in CKAN_BASES[:1]:  # Only try en-data to avoid redundancy
            try:
                # Try package_search first (CKAN standard)
                search_q = " ".join(keywords[:3])
                url = f"{base}/api/3/action/package_search?q={search_q}&rows=20"
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.get(url, headers={"Accept": "application/json"})
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("success"):
                            for pkg in data["result"].get("results", []):
                                self._extract_ckan_resources(pkg, candidates)
                            if candidates:
                                break

                # Fallback: package_list + local filtering
                url = f"{base}/api/3/action/package_list"
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.get(url, headers={"Accept": "application/json"})
                    if resp.status_code != 200:
                        continue
                    data = resp.json()

                if not data.get("success"):
                    continue

                pkg_ids = data.get("result", [])
                # Filter by keyword match on package ID
                keyword_set = set(kw.lower() for kw in keywords)
                matched = [
                    pid for pid in pkg_ids
                    if any(kw in pid.lower() for kw in keyword_set)
                ]

                # Fetch matched packages
                for pid in matched[:10]:  # Safety limit
                    try:
                        pkg_url = f"{base}/api/3/action/package_show?id={pid}"
                        with httpx.Client(timeout=self.timeout) as client:
                            resp = client.get(pkg_url, headers={"Accept": "application/json"})
                            if resp.status_code == 200:
                                pkg_data = resp.json()
                                if pkg_data.get("success"):
                                    self._extract_ckan_resources(pkg_data["result"], candidates)
                    except Exception:
                        continue

            except Exception as exc:
                logger.warning("CKAN keyword search failed on %s: %s", base, exc)

        return candidates

    def _extract_ckan_resources(self, pkg: dict, candidates: list[ResourceCandidate]):
        """Extract resource candidates from a CKAN package."""
        for res in pkg.get("resources", []):
            fmt = res.get("format", "").lower()
            if fmt in ("csv", "xls", "xlsx", "json"):
                candidates.append(ResourceCandidate(
                    url=res.get("url", ""),
                    dataset_id=pkg.get("name"),
                    dataset_name=pkg.get("title"),
                    resource_name=res.get("name") or res.get("description"),
                    format=fmt,
                    source="ckan",
                    metadata={
                        "ckan_package": pkg.get("name"),
                        "resource_id": res.get("id"),
                    },
                ))

    def rank_candidates(
        self,
        candidates: list[ResourceCandidate],
        *,
        title: str | None = None,
        description: str | None = None,
    ) -> list[ResourceCandidate]:
        """Rank candidates by relevance to the curated row."""
        for cand in candidates:
            score = 0.0

            # Provider match (hk-ipd is the IP office)
            if cand.provider == "hk-ipd":
                score += 3.0

            # Format preference (CSV > XLSX > XLS > JSON)
            fmt_scores = {"csv": 2.0, "xlsx": 1.5, "xls": 1.0, "json": 0.5}
            score += fmt_scores.get(cand.format, 0.0)

            # Title/description keyword match
            name_lower = (cand.dataset_name or "").lower()
            res_name_lower = (cand.resource_name or "").lower()
            combined = f"{name_lower} {res_name_lower}"

            # IP keyword matches
            for kw in IP_KEYWORDS_EN + IP_KEYWORDS_ZH:
                if kw.lower() in combined:
                    score += 0.5

            # Curated row title match
            if title:
                title_words = set(re.findall(r'[\w\u4e00-\u9fff]+', title.lower()))
                matched_words = sum(1 for w in title_words if w in combined)
                score += matched_words * 0.3

            # Prefer English resources (more parseable)
            if "/en/" in (cand.url or "").lower():
                score += 0.5

            # Prefer registration/grants over searches (more data-rich)
            if any(kw in combined for kw in ("registration", "grant", "application", "registrations", "grants")):
                score += 1.0
            if any(kw in combined for kw in ("注册", "註冊", "申请", "申請")):
                score += 1.0

            # Penalize survey/awareness data (less relevant)
            if any(kw in combined for kw in ("survey", "awareness", "pledge", "counter")):
                score -= 1.0

            cand.confidence = round(score, 2)

        # Sort by confidence descending
        return sorted(candidates, key=lambda c: c.confidence, reverse=True)
