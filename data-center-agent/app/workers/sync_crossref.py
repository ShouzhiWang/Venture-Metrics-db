"""Sync worker for Crossref API — scholarly metadata via DOIs.

Free, no auth required. 168M+ works, publishers, funders.

API docs: https://api.crossref.org/swagger-ui/index.html
Base URL: https://api.crossref.org/

Key endpoints:
  /works?query=...           — search works by keyword
  /works/{doi}               — single work by DOI
  /publishers                — list publishers
  /funders                   — list funders
  /journals                  — list journals

Usage:
  python -m app.workers.sync_crossref --search "venture capital innovation" --limit 10
  python -m app.workers.sync_crossref --sync-publisher --prefix 10.1016
  python -m app.workers.sync_crossref --live-search "startup funding"
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.db.connection import get_engine
from app.db.repositories.connectors import (
    ConnectorDatasetRepository,
    ConnectorResourceRepository,
    ConnectorRowRepository,
    ConnectorSnapshotRepository,
)
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)

BASE_URL = "https://api.crossref.org"
POLITE_EMAIL = "venture-metrics@hermes.agent"

# Innovation-relevant publishers
ECOSYSTEM_PUBLISHERS = {
    "10.1016": "Elsevier",
    "10.1007": "Springer",
    "10.1002": "Wiley",
    "10.1080": "Taylor & Francis",
    "10.1108": "Emerald",
    "10.1145": "ACM",
    "10.1109": "IEEE",
    "10.3390": "MDPI",
    "10.1038": "Nature",
    "10.1126": "Science (AAAS)",
}


def _get(path: str, params: dict | None = None, timeout: int = 30) -> dict | None:
    """Make a GET request to Crossref API."""
    if params is None:
        params = {}
    params["mailto"] = POLITE_EMAIL
    url = f"{BASE_URL}{path}" if path.startswith("/") else f"{BASE_URL}/{path}"
    try:
        resp = httpx.get(url, params=params, timeout=timeout,
                         headers={"User-Agent": "Venture-Metrics-DB/1.0"})
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", data)
    except Exception as e:
        logger.error("Crossref API error for %s: %s", path, e)
        return None


def search_works(query: str, limit: int = 20, from_year: int = 2020) -> dict:
    """Search for scholarly works by keyword."""
    params = {
        "query": query,
        "rows": limit,
        "sort": "relevance",
        "filter": f"from-pub-date:{from_year}",
    }
    result = _get("/works", params=params)
    if not result:
        return {"works": [], "total": 0}

    works = []
    for w in result.get("items", []):
        title = w.get("title", [""])[0] if w.get("title") else ""
        works.append({
            "doi": w.get("DOI"),
            "title": title,
            "type": w.get("type"),
            "published": w.get("published-print", w.get("published-online", {})).get("date-parts", [[None]])[0][0],
            "publisher": w.get("publisher"),
            "container": w.get("container-title", [""])[0] if w.get("container-title") else "",
            "cited_by_count": w.get("is-referenced-by-count", 0),
            "authors": [
                f"{a.get('given', '')} {a.get('family', '')}".strip()
                for a in (w.get("author") or [])[:3]
            ],
            "subjects": w.get("subject", []),
            "funder_count": len(w.get("funder") or []),
            "url": w.get("URL"),
        })

    return {
        "works": works,
        "total": result.get("total-results", 0),
    }


def list_publishers(limit: int = 20) -> list[dict]:
    """List publishers by works count."""
    result = _get("/publishers", params={"rows": limit, "sort": "works-count", "order": "desc"})
    if not result:
        return []

    publishers = []
    for p in result.get("items", []):
        publishers.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "prefix": p.get("prefix", [""])[0] if p.get("prefix") else "",
            "works_count": p.get("works-count", 0),
            "location": p.get("location"),
        })
    return publishers


def fetch_publisher_works(prefix: str, limit: int = 50, from_year: int = 2020) -> list[dict]:
    """Fetch recent works from a publisher."""
    result = _get(f"/publishers/{prefix}/works", params={
        "rows": limit,
        "filter": f"from-pub-date:{from_year}",
        "sort": "published",
        "order": "desc",
    })
    if not result:
        return []

    works = []
    for w in result.get("items", []):
        title = w.get("title", [""])[0] if w.get("title") else ""
        works.append({
            "doi": w.get("DOI"),
            "title": title,
            "type": w.get("type"),
            "published": w.get("published-print", w.get("published-online", {})).get("date-parts", [[None]])[0][0],
            "container": w.get("container-title", [""])[0] if w.get("container-title") else "",
            "cited_by_count": w.get("is-referenced-by-count", 0),
            "subjects": w.get("subject", []),
        })
    return works


def fetch_funders(query: str = "", limit: int = 20) -> list[dict]:
    """Search for research funders."""
    params = {"rows": limit}
    if query:
        params["query"] = query
    result = _get("/funders", params=params)
    if not result:
        return []

    funders = []
    for f in result.get("items", []):
        funders.append({
            "id": f.get("id"),
            "name": f.get("name"),
            "country": f.get("country"),
            "works_count": f.get("work-count", 0),
            "funding_count": f.get("funding-count", 0),
            "location": f.get("location", {}),
        })
    return funders


def sync_publisher(
    prefix: str,
    publisher_name: str = "",
    from_year: int = 2020,
    limit: int = 100,
    dry_run: bool = False,
) -> dict:
    """Sync a publisher's recent works into connector tables."""
    result = {"prefix": prefix, "status": "pending", "rows_synced": 0}

    name = publisher_name or ECOSYSTEM_PUBLISHERS.get(prefix, prefix)
    logger.info("Fetching Crossref publisher: %s (%s)", name, prefix)

    works = fetch_publisher_works(prefix, limit=limit, from_year=from_year)
    if not works:
        result["status"] = "no_data"
        return result

    result["rows_synced"] = len(works)

    if dry_run:
        result["status"] = "dry_run"
        result["sample_rows"] = works[:3]
        return result

    engine = get_engine()
    with engine.begin() as conn:
        ds_repo = ConnectorDatasetRepository(conn)
        res_repo = ConnectorResourceRepository(conn)
        snap_repo = ConnectorSnapshotRepository(conn)
        row_repo = ConnectorRowRepository(conn)

        dataset = ds_repo.upsert({
            "name": f"{name} — Recent Works (Crossref)",
            "description": f"Recent scholarly works published by {name} since {from_year}.",
            "publisher": name,
            "geography": "Global",
            "topic": "research_output",
            "source_url": f"https://doi.org/prefix/{prefix}",
            "portal": "crossref.org",
            "access_type": "api",
            "status": "synced",
            "metadata": json.dumps({
                "prefix": prefix,
                "from_year": from_year,
                "total_works": len(works),
            }, default=str),
        })

        resource = res_repo.create({
            "dataset_id": dataset["id"],
            "name": f"{name} works",
            "url": f"{BASE_URL}/publishers/{prefix}/works",
            "format": "json",
            "status": "synced",
        })

        snap = snap_repo.create({
            "dataset_id": dataset["id"],
            "resource_id": resource["id"],
            "retrieved_at": datetime.now(timezone.utc),
            "row_count": len(works),
            "column_count": 7,
        })

        # Clean for storage
        clean_rows = []
        for w in works:
            clean = {}
            for k, v in w.items():
                if v is None:
                    clean[k] = None
                elif isinstance(v, list):
                    clean[k] = ", ".join(str(x) for x in v) if v else None
                else:
                    clean[k] = v
            clean_rows.append(clean)

        row_repo.create_bulk(snap["id"], clean_rows)

    result["status"] = "synced"
    result["dataset_db_id"] = str(dataset["id"])
    return result


def search_live(query: str, limit: int = 10) -> dict:
    """Live search for Crossref works matching a query."""
    works_result = search_works(query, limit=limit)
    funders_result = fetch_funders(query, limit=3)

    results = []
    for w in works_result.get("works", []):
        results.append({
            "type": "work",
            "title": w["title"],
            "doi": w["doi"],
            "published": w.get("published"),
            "publisher": w.get("publisher"),
            "cited_by_count": w.get("cited_by_count", 0),
            "source_url": w.get("url") or f"https://doi.org/{w['doi']}",
            "data_status_label": "live from Crossref API",
        })
    for f in funders_result:
        results.append({
            "type": "funder",
            "name": f["name"],
            "country": f["country"],
            "works_count": f["works_count"],
            "source_url": f["id"],
            "data_status_label": "live from Crossref API",
        })

    return {
        "ok": True,
        "source": "Crossref (live)",
        "query": query,
        "total_results": len(results),
        "total_works": works_result.get("total", 0),
        "results": results,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    configure_logging()
    parser = argparse.ArgumentParser(description="Sync Crossref data")
    parser.add_argument("--search", help="Search works")
    parser.add_argument("--search-funders", help="Search funders")
    parser.add_argument("--list-publishers", action="store_true")
    parser.add_argument("--sync-publisher", help="Publisher prefix (e.g., 10.1016)")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--from-year", type=int, default=2020)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live-search", help="Live search query")

    args = parser.parse_args()

    if args.search:
        result = search_works(args.search, limit=args.limit, from_year=args.from_year)
        print(f"\nFound {result['total']} works:")
        for w in result["works"][:20]:
            print(f"  [{w.get('published', '?')}] {w['title'][:80]} ({w['cited_by_count']} cites) — {w['publisher']}")
        return

    if args.search_funders:
        results = fetch_funders(args.search_funders, limit=args.limit)
        for f in results:
            print(f"  {f['name']} ({f['country']}): {f['works_count']} works, {f['funding_count']} grants")
        return

    if args.list_publishers:
        results = list_publishers(limit=args.limit)
        for p in results:
            print(f"  {p['name']}: {p['works_count']:,} works ({p['prefix']})")
        return

    if args.sync_publisher:
        result = sync_publisher(args.sync_publisher, from_year=args.from_year,
                               limit=args.limit, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, default=str))
        return

    if args.live_search:
        result = search_live(args.live_search, limit=args.limit)
        print(json.dumps(result, indent=2, default=str))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
