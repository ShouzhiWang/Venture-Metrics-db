"""Tavily Web Discovery Fallback for Venture-Metrics-db.

Tavily is an AI-agent search API that discovers candidate URLs for reports,
datasets, official sources, and PDFs. Results are NOT validated data — they
are candidate sources stored as external_source_candidates for review.

Use cases:
  - Find external candidate reports when DB has weak coverage
  - Find official source pages and public datasets
  - Find PDFs for ingestion
  - Fallback when internal DB and live APIs return thin results

API docs: https://docs.tavily.com/
Base URL: https://api.tavily.com/

Endpoints:
  /search  — web search (titles, URLs, snippets, scores)
  /extract — extract clean content from URLs
  /crawl   — crawl websites for content
  /map     — map website structure

Usage:
  python -m app.workers.tavily_discovery --search "Singapore venture capital report" --limit 5
  python -m app.workers.tavily_discovery --discover-and-store "patent statistics Asia" --limit 10
  python -m app.workers.tavily_discovery --extract "https://singstat.gov.sg/find-data/search-by-theme"
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from sqlalchemy import text

from app.db.connection import get_engine
from app.db.repositories.connector_candidates import ExternalSourceCandidateRepository
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)

TAVILY_API_KEY = "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"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"

# Domains that are high-confidence official/government sources
OFFICIAL_DOMAINS = {
    "gov.sg", "gov.hk", "gov.cn", "gov.uk", "gov.au", "gov.in", "gov.my",
    "gov.th", "gov.vn", "gov.ph", "gov.tw", "gov.kr", "go.jp",
    "worldbank.org", "imf.org", "oecd.org", "wipo.org", "un.org",
    "singstat.gov.sg", "data.gov.sg", "data.gov.hk", "data.gov.tw",
    "data.gov.uk", "data.gov.in", "data.gov.au",
    "statista.com", "fred.stlouisfed.org",
    "nature.com", "science.org", "ieee.org", "acm.org",
    "ssrn.com", "arxiv.org", "nih.gov", "ncbi.nlm.nih.gov",
}

# Domains to exclude (aggregators, SEO spam, paywalls)
EXCLUDED_DOMAINS = {
    "youtube.com", "facebook.com", "twitter.com", "x.com",
    "reddit.com", "quora.com", "pinterest.com", "instagram.com",
    "wikipedia.org", "medium.com", "linkedin.com",
}


def _classify_source_kind(url: str, title: str = "") -> str:
    """Classify a URL into a source_kind based on URL patterns."""
    url_lower = url.lower()
    title_lower = title.lower()

    if url_lower.endswith(".pdf") or "/pdf/" in url_lower:
        return "downloadable_pdf"
    if url_lower.endswith(".csv") or "/csv/" in url_lower:
        return "downloadable_csv"
    if url_lower.endswith(".xlsx") or ".xls" in url_lower:
        return "downloadable_xlsx"
    if "/api/" in url_lower or ".json" in url_lower:
        return "api_endpoint"
    if "dataset" in url_lower or "data" in title_lower or "statistics" in title_lower:
        return "official_portal"
    if "report" in url_lower or "publication" in url_lower or "white paper" in title_lower:
        return "report_page"
    return "organization_page"


def _is_official_domain(url: str) -> bool:
    """Check if URL is from a known official/government domain."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    return any(host.endswith(d) or host == d for d in OFFICIAL_DOMAINS)


def _is_excluded(url: str) -> bool:
    """Check if URL should be excluded."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    return any(host.endswith(d) or host == d for d in EXCLUDED_DOMAINS)


def _relevance_score(result: dict) -> float:
    """Score a Tavily result's relevance for storage as a candidate."""
    score = result.get("score", 0.5)
    url = result.get("url", "")
    title = result.get("title", "")

    # Boost official domains
    if _is_official_domain(url):
        score += 0.3

    # Boost dataset/report keywords
    keywords = ["data", "dataset", "statistics", "report", "indicator",
                "survey", "census", "open data", "download"]
    for kw in keywords:
        if kw in title.lower() or kw in url.lower():
            score += 0.1

    return min(score, 1.0)


def search(
    query: str,
    limit: int = 10,
    search_depth: str = "basic",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    topic: str = "general",
) -> dict:
    """Search Tavily for candidate sources.

    Args:
        query: Search query.
        limit: Max results.
        search_depth: "basic" (fast) or "advanced" (thorough).
        include_domains: Only return results from these domains.
        exclude_domains: Exclude results from these domains.
        topic: "general" or "news".
    """
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "max_results": limit,
        "search_depth": search_depth,
        "include_answer": False,
        "include_raw_content": False,
        "topic": topic,
    }
    if include_domains:
        payload["include_domains"] = include_domains
    if exclude_domains:
        payload["exclude_domains"] = exclude_domains

    try:
        resp = httpx.post(TAVILY_SEARCH_URL, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for r in data.get("results", []):
            url = r.get("url", "")
            if _is_excluded(url):
                continue
            results.append({
                "title": r.get("title", ""),
                "url": url,
                "snippet": r.get("content", ""),
                "score": _relevance_score(r),
                "raw_score": r.get("score", 0),
                "source_kind": _classify_source_kind(url, r.get("title", "")),
                "is_official": _is_official_domain(url),
            })

        # Sort by relevance score
        results.sort(key=lambda x: x["score"], reverse=True)

        return {
            "ok": True,
            "source": "Tavily",
            "query": query,
            "total_results": len(results),
            "response_time": data.get("response_time", 0),
            "results": results,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error("Tavily search failed: %s", e)
        return {
            "ok": False,
            "source": "Tavily",
            "query": query,
            "error": str(e),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }


def extract(urls: list[str]) -> dict:
    """Extract clean content from URLs using Tavily Extract."""
    payload = {
        "api_key": TAVILY_API_KEY,
        "urls": urls,
    }
    try:
        resp = httpx.post(TAVILY_EXTRACT_URL, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for r in data.get("results", []):
            results.append({
                "url": r.get("url", ""),
                "raw_content": r.get("raw_content", ""),
                "content_length": len(r.get("raw_content", "")),
            })

        return {"ok": True, "results": results}

    except Exception as e:
        logger.error("Tavily extract failed: %s", e)
        return {"ok": False, "error": str(e)}


def discover_and_store(
    query: str,
    limit: int = 10,
    search_depth: str = "basic",
    geography: str = "",
    ecosystem_category: str = "public_dataset",
) -> dict:
    """Search Tavily and store results as external_source_candidates.

    This is the main discovery flow: search → classify → store as candidates.
    """
    search_result = search(query, limit=limit, search_depth=search_depth)
    if not search_result.get("ok"):
        return search_result

    engine = get_engine()
    stored = 0
    updated = 0

    with engine.begin() as conn:
        cand_repo = ExternalSourceCandidateRepository(conn)

        for r in search_result["results"]:
            url = r["url"]
            existing = cand_repo.get_by_url(url)

            candidate_data = {
                "title": r["title"],
                "url": url,
                "source_kind": r["source_kind"],
                "geography": geography or _infer_geography(url, r["title"]),
                "ecosystem_category": ecosystem_category,
                "discovery_method": "tavily_search",
                "confidence_score": r["score"],
                "status": "pending_review" if r["score"] < 0.8 else "approved",
                "metadata": json.dumps({
                    "query": query,
                    "snippet": r["snippet"],
                    "raw_score": r["raw_score"],
                    "is_official": r["is_official"],
                    "discovered_at": datetime.now(timezone.utc).isoformat(),
                }, default=str),
            }

            cand_repo.upsert(candidate_data)
            if existing:
                updated += 1
            else:
                stored += 1

    search_result["stored"] = stored
    search_result["updated"] = updated
    return search_result


def _infer_geography(url: str, title: str) -> str:
    """Infer geography from URL and title."""
    combined = f"{url} {title}".lower()
    geo_map = {
        "singapore": "Singapore", "sgp": "Singapore",
        "hong kong": "Hong Kong", "hkg": "Hong Kong",
        "china": "China", "shenzhen": "China", "guangdong": "China",
        "japan": "Japan", "korea": "South Korea", "taiwan": "Taiwan",
        "india": "India", "malaysia": "Malaysia", "thailand": "Thailand",
        "vietnam": "Vietnam", "indonesia": "Indonesia",
        "united kingdom": "United Kingdom", "uk": "United Kingdom",
        "united states": "United States", "usa": "United States",
        "europe": "Europe", "asean": "ASEAN", "asia": "Asia",
    }
    for keyword, geo in geo_map.items():
        if keyword in combined:
            return geo
    return "Global"


def search_live(query: str, limit: int = 10) -> dict:
    """Live search wrapper for find_data integration.

    Returns results as candidate sources — NOT validated data.
    """
    result = search(query, limit=limit)
    if result.get("ok"):
        # Format for find_data consumption
        for r in result["results"]:
            r["data_status_label"] = "candidate from Tavily web search"
            r["data_status"] = "discovery_candidate"
            r["freshness"] = "real-time"
    return result


def main():
    configure_logging()
    parser = argparse.ArgumentParser(description="Tavily web discovery fallback")
    parser.add_argument("--search", help="Search query")
    parser.add_argument("--discover-and-store", help="Search and store as candidates")
    parser.add_argument("--extract", nargs="+", help="Extract content from URLs")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--depth", default="basic", choices=["basic", "advanced"])
    parser.add_argument("--geography", default="")
    parser.add_argument("--include-domains", nargs="+")
    parser.add_argument("--exclude-domains", nargs="+")

    args = parser.parse_args()

    if args.search:
        result = search(args.search, limit=args.limit, search_depth=args.depth,
                       include_domains=args.include_domains,
                       exclude_domains=args.exclude_domains)
        print(f"\n{'='*60}")
        print(f"Tavily: {args.search}")
        print(f"{'='*60}")
        print(f"Results: {result['total_results']}")
        print(f"Time: {result.get('response_time', 0)}s")
        for r in result.get("results", []):
            marker = "🏛️" if r["is_official"] else "  "
            print(f"\n{marker} [{r['score']:.2f}] {r['title'][:70]}")
            print(f"    {r['url']}")
            print(f"    [{r['source_kind']}] {r['snippet'][:100]}...")
        return

    if args.discover_and_store:
        result = discover_and_store(
            args.discover_and_store, limit=args.limit,
            search_depth=args.depth, geography=args.geography,
        )
        print(json.dumps(result, indent=2, default=str))
        return

    if args.extract:
        result = extract(args.extract)
        for r in result.get("results", []):
            print(f"\n{'='*60}")
            print(f"URL: {r['url']}")
            print(f"Content length: {r['content_length']}")
            print(f"Preview: {r['raw_content'][:300]}...")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
