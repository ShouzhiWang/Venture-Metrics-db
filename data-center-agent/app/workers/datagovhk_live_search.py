"""Real-time data.gov.hk Search Connector.

Queries the data.gov.hk CKAN API live when users search for datasets.
Returns results formatted to match find_data output structure.

Unlike pre-ingested data, these results are always fresh — no caching.
The connector is triggered when the query matches innovation/IP/HK data topics.

Usage:
  python -m app.workers.datagovhk_live_search "Hong Kong patent statistics"
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CKAN_API = "https://data.gov.hk/en-data/api/3/action/package_search"
MAX_RESULTS = 10
TIMEOUT_SECONDS = 10

# Queries that should trigger a live data.gov.hk search
LIVE_SEARCH_TRIGGERS = {
    "patent", "trademark", "trade mark", "intellectual property", "ip",
    "innovation", "startup", "technology", "r&d", "research",
    "sme", "enterprise", "business", "registration", "copyright",
    "licensing", "design", "venture", "fund", "employment",
    "statistics", "census", "dataset", "data source", "public data",
    "open data", "hong kong data", "hk data",
}

# Normalize common variants for CKAN search
_CKAN_SYNONYMS = {
    "trademark": "trade mark",
    "trade mark": "trade mark",
    "ip": "intellectual property",
    "intellectual property": "intellectual property",
    "r&d": "research",
    "sme": "small and medium enterprise",
}


def should_trigger_live_search(query: str) -> bool:
    """Determine if a query should trigger a live data.gov.hk search."""
    lowered = query.lower()
    return any(trigger in lowered for trigger in LIVE_SEARCH_TRIGGERS)


def search_live(query: str, limit: int = MAX_RESULTS) -> dict[str, Any]:
    """Query the data.gov.hk CKAN API in real-time.

    Extracts key domain terms from the query for better CKAN matching.
    CKAN's full-text search is literal — long natural language queries
    often return 0 results. Extracting keywords improves recall.

    Returns:
        {
            "results": [...],  # formatted results matching find_data structure
            "source": "data.gov.hk_live_api",
            "retrieved_at": "2026-06-02T19:50:00Z",
            "query": query,
            "total_available": int,
            "latency_ms": int,
        }
    """
    start_time = datetime.now(timezone.utc)

    # Extract key terms for CKAN search — use trigger keywords that appear in query
    lowered = query.lower()
    matched_triggers = sorted(
        (t for t in LIVE_SEARCH_TRIGGERS if t in lowered),
        key=len, reverse=True,
    )
    # Normalize triggers to CKAN-friendly terms (e.g., "trademark" → "trade mark")
    normalized = []
    for t in matched_triggers[:3]:
        normalized.append(_CKAN_SYNONYMS.get(t, t))
    # Build a concise search query from matched triggers
    search_query = " ".join(normalized) if normalized else query

    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
            resp = client.get(CKAN_API, params={"q": search_query, "rows": limit})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Live data.gov.hk search failed: %s", exc)
        return {
            "results": [],
            "source": "data.gov.hk_live_api",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "total_available": 0,
            "error": str(exc),
            "latency_ms": 0,
        }

    end_time = datetime.now(timezone.utc)
    latency_ms = int((end_time - start_time).total_seconds() * 1000)

    if not data.get("success"):
        return {
            "results": [],
            "source": "data.gov.hk_live_api",
            "retrieved_at": end_time.isoformat(),
            "query": query,
            "total_available": 0,
            "error": "API returned success=false",
            "latency_ms": latency_ms,
        }

    result = data.get("result", {})
    raw_results = result.get("results", [])
    total = result.get("count", 0)

    # Format results to match find_data structure
    formatted = []
    for ds in raw_results:
        formatted.append(_format_ckan_dataset(ds))

    return {
        "results": formatted,
        "source": "data.gov.hk_live_api",
        "retrieved_at": end_time.isoformat(),
        "query": query,
        "total_available": total,
        "latency_ms": latency_ms,
    }


def _format_ckan_dataset(ds: dict) -> dict[str, Any]:
    """Format a CKAN dataset into find_data-compatible structure."""
    # Extract resource info
    resources = ds.get("resources", [])
    csv_resources = [r for r in resources if r.get("format", "").upper() in ("CSV", "XLSX", "XLS")]
    api_resources = [r for r in resources if r.get("format", "").upper() == "API"]

    # Best download URL
    download_url = None
    access_type = "portal"
    if csv_resources:
        download_url = csv_resources[0].get("url")
        access_type = csv_resources[0].get("format", "csv").lower()
    elif api_resources:
        download_url = api_resources[0].get("url")
        access_type = "api"

    # Provider
    org = ds.get("organization", {})
    provider = org.get("title", "")

    return {
        "object_type": "connector_dataset",
        "object_id": ds.get("id", ""),
        "title": ds.get("title", ""),
        "content": ds.get("notes", "")[:300],
        "source_url": download_url or ds.get("url") or f"https://data.gov.hk/en-data/dataset/{ds.get('name', '')}",
        "availability": "obtainable" if download_url else "metadata_only",
        "geography": "Hong Kong",
        "score": 0.7,
        "metadata": {
            "access_type": access_type,
            "portal": "data.gov.hk",
            "provider": provider,
            "num_resources": len(resources),
            "update_frequency": ds.get("update_frequency", ""),
            "last_modified": ds.get("metadata_modified", ""),
            "download_url": download_url,
            "data_source": "live_api",
            "freshness": "real-time",
        },
        "data_status": "live_api_result",
        "data_status_label": "live from data.gov.hk API",
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Real-time data.gov.hk search")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--limit", type=int, default=MAX_RESULTS)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = search_live(args.query, limit=args.limit)

    if args.json:
        print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
    else:
        print(f"Query: {result['query']}")
        print(f"Source: {result['source']}")
        print(f"Retrieved: {result['retrieved_at']}")
        print(f"Latency: {result['latency_ms']}ms")
        print(f"Total available: {result['total_available']}")
        print(f"Results returned: {len(result['results'])}")
        print()
        for r in result["results"]:
            status = r.get("data_status_label", "")
            print(f"  [{status}] {r['title'][:70]}")
            meta = r.get("metadata", {})
            if meta.get("provider"):
                print(f"    Provider: {meta['provider']}")
            if meta.get("download_url"):
                print(f"    Download: {meta['download_url'][:80]}")


if __name__ == "__main__":
    main()
