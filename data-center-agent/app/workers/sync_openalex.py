"""Sync worker for OpenAlex API — open scholarly metadata.

Free, no auth required. 250M+ works, institutions, concepts, funders.

API docs: https://docs.openalex.org/
Base URL: https://api.openalex.org/

Key endpoints:
  /works?filter=...          — scholarly works (papers, datasets)
  /institutions?search=...   — research institutions
  /concepts?search=...       — research topics/concepts
  /funders?search=...        — research funders
  /publishers?search=...     — publishers

Usage:
  python -m app.workers.sync_openalex --search-institutions "singapore"
  python -m app.workers.sync_openalex --sync-top-institutions --limit 20
  python -m app.workers.sync_openalex --live-search "venture capital"
"""

from __future__ import annotations

import argparse
import json
import logging
import math
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

BASE_URL = "https://api.openalex.org"
POLITE_EMAIL = "venture-metrics@hermes.agent"  # For polite pool
DIAGNOSTICS_DIR = "/data/hermes/diagnostics/openalex_sync"

# Innovation-relevant concept IDs in OpenAlex
ECOSYSTEM_CONCEPTS = {
    "C154945302": "Venture capital",
    "C138885662": "Patent",
    "C119857082": "Innovation",
    "C42841829": "Business",
    "C162324750": "Entrepreneurship",
    "C33923547": "Computer science",
    "C86803240": "Research and development",
    "C191058": "Economics",
}


def _get(path: str, params: dict | None = None, timeout: int = 30) -> dict | None:
    """Make a GET request to OpenAlex API."""
    if params is None:
        params = {}
    params["mailto"] = POLITE_EMAIL
    url = f"{BASE_URL}{path}" if path.startswith("/") else f"{BASE_URL}/{path}"
    try:
        resp = httpx.get(url, params=params, timeout=timeout,
                         headers={"User-Agent": "Venture-Metrics-DB/1.0"})
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("OpenAlex API error for %s: %s", path, e)
        return None


def search_institutions(query: str, limit: int = 20) -> list[dict]:
    """Search for research institutions."""
    result = _get("/institutions", params={
        "search": query,
        "per_page": limit,
        "sort": "works_count:desc",
    })
    if not result:
        return []

    institutions = []
    for inst in result.get("results", []):
        institutions.append({
            "id": inst.get("id"),
            "name": inst.get("display_name"),
            "ror": inst.get("ror"),
            "country": inst.get("country_code"),
            "type": inst.get("type"),
            "works_count": inst.get("works_count", 0),
            "cited_by_count": inst.get("cited_by_count", 0),
            "h_index": inst.get("summary_stats", {}).get("h_index", 0),
            "2yr_mean_citedness": inst.get("summary_stats", {}).get("2yr_mean_citedness", 0),
            "homepage_url": inst.get("homepage_url"),
            "geo": inst.get("geo", {}),
        })
    return institutions


def search_works(
    query: str = "",
    concept_id: str = "",
    institution_id: str = "",
    from_year: int = 2020,
    limit: int = 25,
) -> dict:
    """Search for scholarly works."""
    params = {"per_page": limit}
    filters = []
    if from_year:
        filters.append(f"publication_year:{from_year}-")
    if concept_id:
        filters.append(f"concepts.id:{concept_id}")
    if institution_id:
        filters.append(f"authorships.institutions.id:{institution_id}")
    if filters:
        params["filter"] = ",".join(filters)
    if query:
        params["search"] = query

    result = _get("/works", params=params)
    if not result:
        return {"works": [], "total": 0}

    works = []
    for w in result.get("results", []):
        works.append({
            "id": w.get("id"),
            "title": w.get("title"),
            "doi": w.get("doi"),
            "publication_year": w.get("publication_year"),
            "type": w.get("type"),
            "cited_by_count": w.get("cited_by_count", 0),
            "concepts": [c.get("display_name") for c in (w.get("concepts") or [])[:5]],
            "institutions": [
                a.get("institutions", [{}])[0].get("display_name", "")
                for a in (w.get("authorships") or [])[:3]
                if a.get("institutions")
            ],
            "open_access": w.get("open_access", {}).get("is_oa", False),
        })

    return {"works": works, "total": result.get("meta", {}).get("count", 0)}


def fetch_institution_works_summary(institution_id: str, from_year: int = 2015) -> dict:
    """Fetch works summary for an institution (counts by year, type, concept)."""
    # Get yearly counts
    result = _get("/works", params={
        "filter": f"authorships.institutions.id:{institution_id},publication_year:{from_year}-",
        "group_by": "publication_year",
        "per_page": 0,
    })
    yearly = {}
    if result and result.get("group_by"):
        for item in result["group_by"]:
            yearly[item.get("key")] = item.get("count", 0)

    # Get type breakdown
    result2 = _get("/works", params={
        "filter": f"authorships.institutions.id:{institution_id},publication_year:{from_year}-",
        "group_by": "type",
        "per_page": 0,
    })
    types = {}
    if result2 and result2.get("group_by"):
        for item in result2["group_by"]:
            types[item.get("key")] = item.get("count", 0)

    # Get top concepts
    result3 = _get("/works", params={
        "filter": f"authorships.institutions.id:{institution_id},publication_year:{from_year}-",
        "group_by": "concepts.id",
        "per_page": 10,
    })
    concepts = []
    if result3 and result3.get("group_by"):
        for item in result3["group_by"]:
            concepts.append({
                "concept": item.get("key_display_name"),
                "count": item.get("count", 0),
            })

    return {"yearly": yearly, "types": types, "top_concepts": concepts}


def sync_institution_data(
    institution_id: str,
    institution_name: str = "",
    from_year: int = 2015,
    dry_run: bool = False,
) -> dict:
    """Sync an institution's research output data into connector tables."""
    result = {"institution_id": institution_id, "status": "pending", "rows_synced": 0}

    logger.info("Fetching OpenAlex institution: %s", institution_id)
    summary = fetch_institution_works_summary(institution_id, from_year)

    if not summary["yearly"]:
        result["status"] = "no_data"
        return result

    # Build rows: one per year with type/concept breakdowns
    rows = []
    for year, count in sorted(summary["yearly"].items()):
        row = {"year": year, "total_works": count}
        # Add type columns
        for t, c in summary["types"].items():
            row[f"type_{t}"] = c
        rows.append(row)

    name = institution_name or institution_id.split("/")[-1]
    result["rows_synced"] = len(rows)

    if dry_run:
        result["status"] = "dry_run"
        result["sample_rows"] = rows[:3]
        result["top_concepts"] = summary["top_concepts"][:5]
        return result

    engine = get_engine()
    with engine.begin() as conn:
        ds_repo = ConnectorDatasetRepository(conn)
        res_repo = ConnectorResourceRepository(conn)
        snap_repo = ConnectorSnapshotRepository(conn)
        row_repo = ConnectorRowRepository(conn)

        dataset = ds_repo.upsert({
            "name": f"{name} — Research Output (OpenAlex)",
            "description": f"Scholarly works by {name} from {from_year}. Top concepts: {', '.join(c['concept'] for c in summary['top_concepts'][:3])}",
            "publisher": "OpenAlex",
            "geography": "Global",
            "topic": "research_output",
            "source_url": institution_id,
            "portal": "openalex.org",
            "access_type": "api",
            "status": "synced",
            "metadata": json.dumps({
                "from_year": from_year,
                "top_concepts": summary["top_concepts"],
                "type_breakdown": summary["types"],
            }, default=str),
        })

        resource = res_repo.create({
            "dataset_id": dataset["id"],
            "name": f"{name} works summary",
            "url": institution_id,
            "format": "json",
            "status": "synced",
        })

        snap = snap_repo.create({
            "dataset_id": dataset["id"],
            "resource_id": resource["id"],
            "retrieved_at": datetime.now(timezone.utc),
            "row_count": len(rows),
            "column_count": 2 + len(summary["types"]),
        })

        row_repo.create_bulk(snap["id"], rows)

    result["status"] = "synced"
    result["dataset_db_id"] = str(dataset["id"])
    return result


def sync_top_institutions(
    query: str = "innovation technology",
    limit: int = 10,
    from_year: int = 2015,
    dry_run: bool = False,
) -> dict:
    """Sync top research institutions by query."""
    institutions = search_institutions(query, limit=limit)
    results = []

    for inst in institutions:
        r = sync_institution_data(inst["id"], inst["name"], from_year, dry_run)
        r["works_count"] = inst["works_count"]
        results.append(r)
        time.sleep(0.5)

    return {
        "total": len(results),
        "synced": len([r for r in results if r["status"] == "synced"]),
        "results": results,
    }


def search_live(query: str, limit: int = 10) -> dict:
    """Live search for OpenAlex institutions and works.

    Extracts key domain terms from the query for better matching.
    OpenAlex's semantic search can return tangentially related results
    for long natural language queries.
    """
    # Extract key terms for OpenAlex search
    stop_words = {"the", "a", "an", "in", "of", "for", "and", "or", "to", "is",
                  "on", "at", "by", "with", "from", "that", "this", "it", "as",
                  "are", "was", "were", "be", "been", "has", "have", "had", "do",
                  "does", "did", "will", "would", "could", "should", "may", "might",
                  "shall", "can", "need", "dare", "ought", "used", "about", "how",
                  "what", "when", "where", "which", "who", "whom", "whose", "why",
                  "not", "no", "nor", "so", "up", "out", "if", "then", "than",
                  "too", "very", "just", "but", "also", "more", "most", "some",
                  "any", "all", "each", "every", "both", "few", "other", "another"}
    words = [w for w in query.lower().split() if len(w) > 2 and w not in stop_words]
    # Use top 4 keywords for OpenAlex search
    search_query = " ".join(words[:4]) if words else query

    institutions = search_institutions(query, limit=min(limit, 5))
    works_result = search_works(query=search_query, limit=min(limit, 5))

    results = []
    for inst in institutions:
        results.append({
            "type": "institution",
            "name": inst["name"],
            "country": inst["country"],
            "works_count": inst["works_count"],
            "cited_by_count": inst["cited_by_count"],
            "h_index": inst["h_index"],
            "source_url": inst["id"],
            "data_status_label": "live from OpenAlex API",
        })
    for w in works_result.get("works", []):
        results.append({
            "type": "work",
            "title": w["title"],
            "year": w["publication_year"],
            "cited_by_count": w["cited_by_count"],
            "concepts": w["concepts"],
            "source_url": w["id"],
            "data_status_label": "live from OpenAlex API",
        })

    return {
        "ok": True,
        "source": "OpenAlex (live)",
        "query": query,
        "total_results": len(results),
        "results": results,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    configure_logging()
    parser = argparse.ArgumentParser(description="Sync OpenAlex data")
    parser.add_argument("--search-institutions", help="Search institutions")
    parser.add_argument("--search-works", help="Search works")
    parser.add_argument("--sync-top-institutions", action="store_true")
    parser.add_argument("--sync-institution", help="Sync specific institution URL")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--from-year", type=int, default=2015)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live-search", help="Live search query")

    args = parser.parse_args()

    if args.search_institutions:
        results = search_institutions(args.search_institutions, limit=args.limit)
        for inst in results:
            print(f"  {inst['name']} ({inst['country']}): {inst['works_count']:,} works, "
                  f"h-index={inst['h_index']}, {inst['id']}")
        return

    if args.search_works:
        result = search_works(query=args.search_works, limit=args.limit)
        print(f"Found {result['total']} works:")
        for w in result["works"]:
            print(f"  [{w['publication_year']}] {w['title'][:80]} ({w['cited_by_count']} cites)")
        return

    if args.sync_institution:
        result = sync_institution_data(args.sync_institution, from_year=args.from_year,
                                       dry_run=args.dry_run)
        print(json.dumps(result, indent=2, default=str))
        return

    if args.sync_top_institutions:
        result = sync_top_institutions(limit=args.limit, from_year=args.from_year,
                                       dry_run=args.dry_run)
        print(json.dumps(result, indent=2, default=str))
        return

    if args.live_search:
        result = search_live(args.live_search, limit=args.limit)
        print(json.dumps(result, indent=2, default=str))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
