"""Sync worker for World Bank Open Data API.

Free, no auth required. 1,600+ indicators across all countries.

API docs: https://datatopics.worldbank.org/world-development-indicators/
Base URL: https://api.worldbank.org/v2/

Key endpoints:
  /v2/country/{iso}/indicator/{id}?format=json&date=YYYY:YYYY
  /v2/indicator?format=json&per_page=500
  /v2/country?format=json&per_page=300
  /v2/source/{source_id}/indicator?format=json

Usage:
  python -m app.workers.sync_worldbank --list-indicators --search "GDP"
  python -m app.workers.sync_worldbank --sync --limit 10
  python -m app.workers.sync_worldbank --sync-indicator NY.GDP.MKTP.CD --countries SGP,CHN,JPN,KOR
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import text

from app.db.connection import get_engine
from app.db.repositories.connector_candidates import ExternalSourceCandidateRepository
from app.db.repositories.connectors import (
    ConnectorDatasetRepository,
    ConnectorResourceRepository,
    ConnectorRowRepository,
    ConnectorSnapshotRepository,
)
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)

BASE_URL = "https://api.worldbank.org/v2"
DIAGNOSTICS_DIR = Path("/data/hermes/diagnostics/worldbank_sync")

# Innovation/venture ecosystem indicators
ECOSYSTEM_INDICATORS = {
    # Economy
    "NY.GDP.MKTP.CD": "GDP (current US$)",
    "NY.GDP.MKTP.KD.ZG": "GDP growth (annual %)",
    "NY.GDP.PCAP.CD": "GDP per capita (current US$)",
    "NY.GNP.MKTP.CD": "GNI (current US$)",
    # R&D
    "GB.XPD.RSDV.GD.ZS": "R&D expenditure (% of GDP)",
    "GB.XPD.RSDV.CD": "R&D expenditure (current US$)",
    "IP.JRN.ARTC.SC": "Scientific and technical journal articles",
    # Innovation
    "IP.PAT.RESD": "Patent applications, residents",
    "IP.PAT.NRES": "Patent applications, nonresidents",
    "IP.TMK.RESD": "Trademark applications, residents",
    "IP.TMK.NRES": "Trademark applications, nonresidents",
    "IP.IND.DESN": "Industrial design applications",
    # Trade
    "NE.EXP.GNFS.CS": "Exports of goods and services (current US$)",
    "NE.IMP.GNFS.CS": "Imports of goods and services (current US$)",
    "BX.KLT.DINV.WD.GD.ZS": "FDI, net inflows (% of GDP)",
    "BX.KLT.DINV.CD.WD": "FDI, net inflows (BoP, current US$)",
    # Business
    "IC.BUS.EASE.XQ": "Ease of doing business score",
    "IC.REG.COST.PC.ZS": "Cost of business start-up (% of GNI per capita)",
    "IC.BUS.NDNS.ZS": "New business density (new registrations per 1,000 people ages 15-64)",
    # Education
    "SE.XPD.TOTL.GD.ZS": "Education expenditure (% of GDP)",
    "SE.TER.ENRR": "School enrollment, tertiary (% gross)",
    # Employment
    "SL.UEM.TOTL.ZS": "Unemployment, total (% of total labor force)",
    "SL.TLF.CACT.ZS": "Labor force participation rate (% of total population ages 15+)",
    # Digital
    "IT.NET.USER.ZS": "Individuals using the Internet (% of population)",
    "IT.CEL.SETS.P2": "Mobile cellular subscriptions (per 100 people)",
}

# Default countries (ASEAN + major Asian economies + key innovation hubs)
DEFAULT_COUNTRIES = [
    "SGP", "CHN", "JPN", "KOR", "TWN", "HKG", "IND", "MYS", "THA",
    "VNM", "IDN", "PHL", "AUS", "NZL", "GBR", "USA", "DEU", "FRA", "ISR",
]

PAGE_SIZE = 1000


def _get(url: str, params: dict | None = None, timeout: int = 30) -> dict | list | None:
    """Make a GET request to the World Bank API."""
    if params is None:
        params = {}
    params["format"] = "json"
    try:
        resp = httpx.get(url, params=params, timeout=timeout,
                         headers={"User-Agent": "Venture-Metrics-DB/1.0"})
        resp.raise_for_status()
        data = resp.json()
        # WB API returns [metadata, data] or [metadata, null]
        if isinstance(data, list) and len(data) >= 2:
            if data[1] is None:
                return {"error": data[0].get("message", "No data"), "metadata": data[0]}
            return {"metadata": data[0], "data": data[1]}
        return data
    except Exception as e:
        logger.error("WB API error for %s: %s", url, e)
        return None


def list_indicators(search: str = "", page: int = 1) -> dict:
    """List available indicators, optionally filtered by search term."""
    params = {"per_page": 100, "page": page}
    if search:
        params["search"] = search
    result = _get(f"{BASE_URL}/indicator", params=params)
    if not result or "data" not in result:
        return {"indicators": [], "total": 0}

    indicators = []
    for ind in result["data"]:
        indicators.append({
            "id": ind.get("id"),
            "name": ind.get("name"),
            "source": ind.get("source", {}).get("value", ""),
            "topics": [t.get("value") for t in ind.get("topics", [])],
        })

    total = result["metadata"].get("total", 0)
    pages = result["metadata"].get("pages", 1)
    return {"indicators": indicators, "total": total, "pages": pages}


def fetch_indicator_data(
    indicator_id: str,
    countries: list[str] | None = None,
    date_range: str = "2015:2024",
    per_page: int = PAGE_SIZE,
) -> tuple[list[dict], dict]:
    """Fetch data for a specific indicator across multiple countries.

    Returns:
        (rows, metadata) where rows are flat dicts and metadata has indicator info.
    """
    if countries is None:
        countries = DEFAULT_COUNTRIES

    country_str = ";".join(countries)
    all_rows = []
    page = 1
    indicator_meta = {}

    while True:
        result = _get(
            f"{BASE_URL}/country/{country_str}/indicator/{indicator_id}",
            params={"date": date_range, "per_page": per_page, "page": page},
        )

        if not result or "data" not in result:
            logger.warning("No data for %s page %d: %s", indicator_id, page, result)
            break

        if not indicator_meta and result["data"]:
            first = result["data"][0]
            indicator_meta = {
                "indicator_id": first.get("indicator", {}).get("id", indicator_id),
                "indicator_name": first.get("indicator", {}).get("value", indicator_id),
                "source": first.get("source", {}).get("value", "World Bank"),
                "source_id": first.get("source", {}).get("id"),
            }

        for row in result["data"]:
            all_rows.append({
                "country": row.get("country", {}).get("value", ""),
                "country_iso3": row.get("countryiso3code", ""),
                "country_id": row.get("country", {}).get("id", ""),
                "indicator": row.get("indicator", {}).get("value", ""),
                "indicator_id": row.get("indicator", {}).get("id", ""),
                "date": row.get("date", ""),
                "value": row.get("value"),
                "unit": row.get("unit", ""),
                "decimal": row.get("decimal", ""),
            })

        total_pages = result["metadata"].get("pages", 1)
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.3)

    return all_rows, indicator_meta


def _relevance_score(indicator_id: str, name: str) -> float:
    """Score indicator relevance to innovation ecosystem."""
    if indicator_id in ECOSYSTEM_INDICATORS:
        return 1.0
    name_lower = name.lower()
    keywords = ["gdp", "rd", "research", "patent", "trade", "fdi", "innovation",
                "startup", "venture", "education", "employment", "internet",
                "technology", "export", "import", "investment", "business"]
    score = sum(0.2 for kw in keywords if kw in name_lower)
    return min(score, 0.9)


def sync_indicator(
    indicator_id: str,
    indicator_name: str = "",
    countries: list[str] | None = None,
    date_range: str = "2010:2024",
    dry_run: bool = False,
) -> dict:
    """Sync a single World Bank indicator into connector tables."""
    result = {
        "indicator_id": indicator_id,
        "status": "pending",
        "rows_synced": 0,
        "error": None,
    }

    logger.info("Fetching WB indicator: %s", indicator_id)
    rows, meta = fetch_indicator_data(indicator_id, countries, date_range)

    if not rows:
        result["status"] = "no_data"
        result["error"] = "No data returned"
        return result

    name = meta.get("indicator_name") or indicator_name or indicator_id
    source_name = meta.get("source", "World Bank")
    result["rows_synced"] = len(rows)

    if dry_run:
        result["status"] = "dry_run"
        result["sample_rows"] = rows[:3]
        result["total_rows"] = len(rows)
        return result

    engine = get_engine()
    with engine.begin() as conn:
        ds_repo = ConnectorDatasetRepository(conn)
        res_repo = ConnectorResourceRepository(conn)
        snap_repo = ConnectorSnapshotRepository(conn)
        row_repo = ConnectorRowRepository(conn)

        dataset = ds_repo.upsert({
            "name": f"{name} (World Bank)",
            "description": f"{name} from {source_name}. Countries: {', '.join(countries or DEFAULT_COUNTRIES[:5])}...",
            "publisher": "World Bank",
            "geography": "Global",
            "topic": "public_dataset",
            "source_url": f"https://data.worldbank.org/indicator/{indicator_id}",
            "portal": "data.worldbank.org",
            "access_type": "api",
            "status": "synced",
            "metadata": json.dumps({
                "indicator_id": indicator_id,
                "source": source_name,
                "date_range": date_range,
                "countries": countries or DEFAULT_COUNTRIES,
            }, default=str),
        })

        resource = res_repo.create({
            "dataset_id": dataset["id"],
            "name": f"{name} (JSON API)",
            "url": f"{BASE_URL}/country/all/indicator/{indicator_id}?format=json",
            "format": "json",
            "status": "synced",
        })

        snap = snap_repo.create({
            "dataset_id": dataset["id"],
            "resource_id": resource["id"],
            "retrieved_at": datetime.now(timezone.utc),
            "row_count": len(rows),
            "column_count": 8,
        })

        # Clean rows for storage
        clean_rows = []
        for r in rows:
            clean = {}
            for k, v in r.items():
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    clean[k] = None
                else:
                    clean[k] = v
            clean_rows.append(clean)

        row_repo.create_bulk(snap["id"], clean_rows)

    result["status"] = "synced"
    result["dataset_db_id"] = str(dataset["id"])
    return result


def sync_ecosystem_indicators(
    limit: int = 10,
    countries: list[str] | None = None,
    date_range: str = "2010:2024",
    dry_run: bool = False,
) -> dict:
    """Sync the top ecosystem-relevant indicators."""
    indicators = list(ECOSYSTEM_INDICATORS.items())[:limit]
    results = []

    for ind_id, ind_name in indicators:
        r = sync_indicator(ind_id, ind_name, countries, date_range, dry_run)
        results.append(r)
        time.sleep(0.5)

    return {
        "total": len(results),
        "synced": len([r for r in results if r["status"] == "synced"]),
        "dry_run": len([r for r in results if r["status"] == "dry_run"]),
        "failed": len([r for r in results if r["status"] in ("no_data", "error")]),
        "results": results,
    }


def search_live(query: str, limit: int = 10) -> dict:
    """Live search for World Bank indicators matching a query.

    Results are filtered for relevance — indicators must share at least one
    keyword (excluding stop words) with the query, or be in ECOSYSTEM_INDICATORS.
    """
    result = list_indicators(search=query, page=1)
    indicators = result.get("indicators", [])

    # Build a relevance filter from query keywords
    stop_words = {"the", "a", "an", "in", "of", "for", "and", "or", "to", "is",
                  "on", "at", "by", "with", "from", "that", "this", "it", "as",
                  "are", "was", "were", "be", "been", "has", "have", "had", "do",
                  "does", "did", "will", "would", "could", "should", "may", "might",
                  "shall", "can", "need", "dare", "ought", "used", "about", "how",
                  "what", "when", "where", "which", "who", "whom", "whose", "why",
                  "not", "no", "nor", "so", "up", "out", "if", "then", "than",
                  "too", "very", "just", "but", "also", "more", "most", "some",
                  "any", "all", "each", "every", "both", "few", "other", "another"}
    query_words = {w for w in query.lower().split() if len(w) > 2 and w not in stop_words}

    matches = []
    for ind in indicators:
        ind_id = ind.get("id", "")
        ind_name = ind.get("name", "").lower()
        # Always include ecosystem indicators
        if ind_id in ECOSYSTEM_INDICATORS:
            matches.append(_format_indicator(ind))
            if len(matches) >= limit:
                break
            continue
        # For other indicators, require at least one query keyword match
        if query_words and any(w in ind_name for w in query_words):
            matches.append(_format_indicator(ind))
            if len(matches) >= limit:
                break

    return {
        "ok": True,
        "source": "World Bank (live)",
        "query": query,
        "total_results": len(matches),
        "results": matches,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def _format_indicator(ind: dict) -> dict:
    """Format a World Bank indicator for the find_data pipeline."""
    return {
        "indicator_id": ind.get("id"),
        "name": ind.get("name"),
        "source": ind.get("source", "World Bank"),
        "topics": ind.get("topics", []),
        "source_url": f"https://data.worldbank.org/indicator/{ind['id']}",
        "api_url": f"{BASE_URL}/country/all/indicator/{ind['id']}?format=json",
        "geography": "Global",
        "data_status_label": "live from World Bank API",
        "freshness": "real-time",
    }


def main():
    configure_logging()
    parser = argparse.ArgumentParser(description="Sync World Bank data")
    parser.add_argument("--list-indicators", action="store_true")
    parser.add_argument("--search", help="Search indicators")
    parser.add_argument("--sync", action="store_true", help="Sync ecosystem indicators")
    parser.add_argument("--sync-indicator", help="Sync a specific indicator ID")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--countries", help="Comma-separated ISO3 codes")
    parser.add_argument("--date-range", default="2010:2024")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live-search", help="Live search query")

    args = parser.parse_args()
    countries = args.countries.split(",") if args.countries else None

    if args.search:
        result = list_indicators(search=args.search)
        print(f"\nFound {result['total']} indicators:")
        for ind in result["indicators"][:20]:
            print(f"  {ind['id']}: {ind['name']}")
        return

    if args.sync_indicator:
        result = sync_indicator(args.sync_indicator, countries=countries,
                               date_range=args.date_range, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, default=str))
        return

    if args.sync:
        result = sync_ecosystem_indicators(
            limit=args.limit, countries=countries,
            date_range=args.date_range, dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2, default=str))
        return

    if args.live_search:
        result = search_live(args.live_search, limit=args.limit)
        print(json.dumps(result, indent=2, default=str))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
