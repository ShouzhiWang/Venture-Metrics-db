"""Real-time data.gov.sg Search Connector.

Queries the data.gov.sg API live when users search for Singapore datasets.
Returns results formatted to match find_data output structure.

Unlike pre-ingested data, these results are always fresh — no caching.
The connector is triggered when the query matches Singapore/innovation topics.

Usage:
  python -m app.workers.datagovsg_live_search "Singapore GDP"
  python -m app.workers.datagovsg_live_search "employment statistics" --limit 5
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api-production.data.gov.sg"
DATASETS_URL = f"{BASE_URL}/v2/public/api/datasets"
METADATA_URL = f"{BASE_URL}/v2/public/api/datasets/{{dataset_id}}/metadata"
DATASTORE_URL = "https://data.gov.sg/api/action/datastore_search"

MAX_RESULTS = 10
MAX_PAGES = 5  # Keep live chat fallback bounded; deeper discovery belongs in offline sync.
TIMEOUT_SECONDS = 15

# Queries that should trigger a live data.gov.sg search
LIVE_SEARCH_TRIGGERS = {
    "singapore", "sg", "hdb", "coe", "cpf", "gst",
    "economy", "gdp", "trade", "investment", "business",
    "startup", "innovation", "technology", "patent",
    "employment", "labour", "labor", "wage", "productivity",
    "research", "education", "finance", "banking",
    "venture", "entrepreneur", "sme", "digital", "ict",
    "science", "rd", "statistics", "census", "dataset",
    "data source", "public data", "open data",
    "singapore data", "sg data",
}


def should_trigger_live_search(query: str) -> bool:
    """Determine if a query should trigger a live data.gov.sg search."""
    lowered = query.lower()
    return any(trigger in lowered for trigger in LIVE_SEARCH_TRIGGERS)


def _get_headers() -> dict:
    return {
        "Accept": "application/json",
        "User-Agent": "Venture-Metrics-DB/1.0 (live search)",
    }


def _search_datasets(query: str, max_pages: int = MAX_PAGES) -> list[dict]:
    """Search datasets by keyword from the API listing."""
    all_datasets = []
    query_lower = query.lower()
    client = httpx.Client(timeout=TIMEOUT_SECONDS, headers=_get_headers())

    for page in range(1, max_pages + 1):
        try:
            resp = client.get(DATASETS_URL, params={"page": page})
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                break

            datasets = data.get("data", {}).get("datasets", [])
            if not datasets:
                break

            all_datasets.extend(datasets)
            total_pages = data.get("data", {}).get("pages", 1)

            if page >= total_pages:
                break

            time.sleep(0.2)

        except Exception as e:
            logger.error("Failed to fetch page %d: %s", page, e)
            break

    client.close()

    # Filter by keyword relevance
    stop_words = {"the", "a", "an", "in", "of", "for", "and", "or", "to", "is",
                  "on", "at", "by", "with", "from", "that", "this", "it", "as",
                  "data", "singapore", "sg", "statistics", "dataset", "information"}
    query_words = {w for w in query_lower.split() if len(w) >= 3 and w not in stop_words}
    matches = []
    for ds in all_datasets:
        name = (ds.get("name") or "").lower()
        agency = (ds.get("managedByAgencyName") or "").lower()
        # Require at least one non-trivial keyword match
        score = sum(1 for word in query_words if word in name or word in agency)
        if score > 0:
            ds["_relevance"] = score
            matches.append(ds)

    # Sort by relevance
    matches.sort(key=lambda x: x.get("_relevance", 0), reverse=True)
    return matches


def _get_sample_rows(dataset_id: str, limit: int = 5) -> list[dict]:
    """Get sample rows from a dataset via datastore search."""
    try:
        resp = httpx.get(DATASTORE_URL, params={
            "resource_id": dataset_id,
            "limit": limit,
        }, timeout=TIMEOUT_SECONDS, headers=_get_headers())
        resp.raise_for_status()
        data = resp.json()
        if data.get("success"):
            return data.get("result", {}).get("records", [])
    except Exception as e:
        logger.debug("Datastore search failed for %s: %s", dataset_id, e)
    return []


def search_live(query: str, limit: int = MAX_RESULTS) -> dict[str, Any]:
    """Query the data.gov.sg API in real-time.

    Returns:
        {
            "ok": True,
            "source": "data.gov.sg (live)",
            "query": query,
            "total_results": N,
            "results": [...],
            "fetched_at": "ISO timestamp",
        }
    """
    try:
        matches = _search_datasets(query, max_pages=MAX_PAGES)
        results = []

        for ds in matches[:limit]:
            dataset_id = ds.get("datasetId")
            name = ds.get("name", "")
            agency = ds.get("managedByAgencyName", "")
            fmt = ds.get("format", "")
            url = f"https://data.gov.sg/datasets/{dataset_id}/view"

            # Try to get sample rows for CSV datasets
            sample_rows = []
            total_records = None
            if fmt.upper() == "CSV":
                try:
                    resp = httpx.get(DATASTORE_URL, params={
                        "resource_id": dataset_id,
                        "limit": 3,
                    }, timeout=10, headers=_get_headers())
                    data = resp.json()
                    if data.get("success"):
                        result = data.get("result", {})
                        total_records = result.get("total")
                        sample_rows = result.get("records", [])
                        # Remove _id from sample rows
                        for row in sample_rows:
                            row.pop("_id", None)
                except Exception:
                    pass

            results.append({
                "title": name,
                "source_url": url,
                "publisher": agency,
                "format": fmt,
                "geography": "Singapore",
                "coverage_start": ds.get("coverageStart"),
                "coverage_end": ds.get("coverageEnd"),
                "last_updated": ds.get("lastUpdatedAt"),
                "total_records": total_records,
                "sample_rows": sample_rows[:3],
                "data_status_label": f"live from data.gov.sg API",
                "freshness": "real-time",
            })

        return {
            "ok": True,
            "source": "data.gov.sg (live)",
            "query": query,
            "total_results": len(results),
            "results": results,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error("Live search failed: %s", e)
        return {
            "ok": False,
            "source": "data.gov.sg (live)",
            "query": query,
            "error": str(e),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }


def main():
    import argparse
    from app.utils.logging import configure_logging

    configure_logging()
    parser = argparse.ArgumentParser(description="Live search data.gov.sg")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--limit", type=int, default=MAX_RESULTS,
                        help="Max results (default: 10)")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()

    result = search_live(args.query, limit=args.limit)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"\n{'='*60}")
        print(f"data.gov.sg Live Search: {args.query}")
        print(f"{'='*60}")
        print(f"Results: {result['total_results']}")
        print(f"Fetched: {result['fetched_at']}")
        for i, r in enumerate(result.get("results", []), 1):
            print(f"\n{i}. {r['title']}")
            print(f"   Publisher: {r['publisher']}")
            print(f"   Format: {r['format']}")
            print(f"   URL: {r['source_url']}")
            if r.get("total_records"):
                print(f"   Records: {r['total_records']:,}")
            if r.get("coverage_start") or r.get("coverage_end"):
                print(f"   Coverage: {r.get('coverage_start', '?')} — {r.get('coverage_end', '?')}")


if __name__ == "__main__":
    main()
