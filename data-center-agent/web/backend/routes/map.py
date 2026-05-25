from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter
except ImportError:  # pragma: no cover
    APIRouter = None

from sqlalchemy import text

from app.db.connection import get_engine


if APIRouter:
    router = APIRouter(prefix="/api/map")
else:  # pragma: no cover
    router = None


CITY_COORDS: dict[str, tuple[float, float]] = {
    "singapore": (1.3521, 103.8198),
    "hong kong": (22.3193, 114.1694),
    "shenzhen": (22.5431, 114.0579),
    "beijing": (39.9042, 116.4074),
    "shanghai": (31.2304, 121.4737),
    "tokyo": (35.6762, 139.6503),
    "seoul": (37.5665, 126.9780),
    "jakarta": (-6.2088, 106.8456),
    "bangkok": (13.7563, 100.5018),
    "ho chi minh city": (10.8231, 106.6297),
    "bangalore": (12.9716, 77.5946),
    "bengaluru": (12.9716, 77.5946),
    "taipei": (25.0330, 121.5654),
}

COUNTRY_COORDS: dict[str, tuple[float, float]] = {
    "singapore": (1.3521, 103.8198),
    "hong kong": (22.3193, 114.1694),
    "china": (35.8617, 104.1954),
    "japan": (36.2048, 138.2529),
    "south korea": (35.9078, 127.7669),
    "korea": (35.9078, 127.7669),
    "indonesia": (-0.7893, 113.9213),
    "thailand": (15.8700, 100.9925),
    "vietnam": (14.0583, 108.2772),
    "india": (20.5937, 78.9629),
    "taiwan": (23.6978, 120.9605),
}


def map_items() -> list[dict[str, Any]]:
    with get_engine().begin() as connection:
        rows = [*_organization_rows(connection), *_report_rows(connection), *_variable_rows(connection), *_source_rows(connection)]
    return [item for item in (_to_map_item(row) for row in rows) if item]


def _organization_rows(connection: Any) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            """
            SELECT
              id,
              'organization' AS type,
              name AS title,
              description,
              country,
              city,
              geography,
              organization_type,
              NULL::text AS availability,
              website_url AS source_url,
              metadata
            FROM ecosystem_organizations
            ORDER BY updated_at DESC
            LIMIT 500
            """
        )
    )
    return [dict(row._mapping) for row in rows]


def _report_rows(connection: Any) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            """
            SELECT
              r.id,
              'report' AS type,
              r.title,
              r.summary AS description,
              NULL::text AS country,
              NULL::text AS city,
              r.geography,
              NULL::text AS organization_type,
              s.access_type AS availability,
              s.original_url AS source_url,
              r.citation_info AS metadata
            FROM reports r
            LEFT JOIN sources s ON s.id = r.source_id
            WHERE r.geography IS NOT NULL
            ORDER BY r.updated_at DESC
            LIMIT 500
            """
        )
    )
    return [dict(row._mapping) for row in rows]


def _variable_rows(connection: Any) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            """
            SELECT
              v.id,
              'variable' AS type,
              v.raw_variable_name AS title,
              v.definition AS description,
              NULL::text AS country,
              NULL::text AS city,
              coalesce(v.geographic_coverage, r.geography) AS geography,
              NULL::text AS organization_type,
              v.availability,
              s.original_url AS source_url,
              v.metadata
            FROM report_variables v
            LEFT JOIN reports r ON r.id = v.report_id
            LEFT JOIN sources s ON s.id = r.source_id
            WHERE coalesce(v.geographic_coverage, r.geography) IS NOT NULL
            ORDER BY v.updated_at DESC
            LIMIT 500
            """
        )
    )
    return [dict(row._mapping) for row in rows]


def _source_rows(connection: Any) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            """
            SELECT
              id,
              'source' AS type,
              coalesce(title, original_url) AS title,
              notes AS description,
              NULL::text AS country,
              NULL::text AS city,
              source_owner AS geography,
              source_type AS organization_type,
              access_type AS availability,
              original_url AS source_url,
              discovered_artifacts AS metadata
            FROM sources
            WHERE source_owner IS NOT NULL
            ORDER BY updated_at DESC
            LIMIT 300
            """
        )
    )
    return [dict(row._mapping) for row in rows]


def _to_map_item(row: dict[str, Any]) -> dict[str, Any] | None:
    city, country = _infer_location(row)
    coords = _coords_for(city, country, row.get("geography"))
    if not coords:
        return None
    lat, lng = coords
    metadata = dict(row.get("metadata") or {})
    metadata["source_url"] = row.get("source_url")
    if row.get("organization_type"):
        metadata["organization_type"] = row.get("organization_type")
    return {
        "id": str(row["id"]),
        "type": row.get("type"),
        "title": row.get("title") or "Untitled",
        "description": row.get("description"),
        "country": country,
        "city": city,
        "lat": lat,
        "lng": lng,
        "availability": row.get("availability"),
        "metadata": metadata,
    }


def _infer_location(row: dict[str, Any]) -> tuple[str | None, str | None]:
    text = " ".join(str(value or "") for value in [row.get("city"), row.get("country"), row.get("geography")]).lower()
    city = _first_match(text, CITY_COORDS)
    country = row.get("country") or _first_match(text, COUNTRY_COORDS)
    if not city and row.get("city"):
        city = str(row["city"])
    if not country and row.get("geography"):
        country = _first_match(str(row["geography"]).lower(), COUNTRY_COORDS)
    return city, country


def _first_match(text_value: str, coords: dict[str, tuple[float, float]]) -> str | None:
    for name in coords:
        if name in text_value:
            return name.title()
    return None


def _coords_for(city: str | None, country: str | None, geography: str | None) -> tuple[float, float] | None:
    if city and city.lower() in CITY_COORDS:
        return CITY_COORDS[city.lower()]
    if country and country.lower() in COUNTRY_COORDS:
        return COUNTRY_COORDS[country.lower()]
    text_value = str(geography or "").lower()
    city = _first_match(text_value, CITY_COORDS)
    if city:
        return CITY_COORDS[city.lower()]
    country = _first_match(text_value, COUNTRY_COORDS)
    if country:
        return COUNTRY_COORDS[country.lower()]
    return None


if router:
    @router.get("/items")
    def get_map_items() -> list[dict[str, Any]]:
        return map_items()
