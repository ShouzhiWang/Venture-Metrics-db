from __future__ import annotations

import argparse
import json
import re

from app.llm.embedding_client import EmbeddingClient
from app.models.search import SuggestedClarification
from app.utils.logging import configure_logging
from app.workers.semantic_search import semantic_search


KNOWN_GEOGRAPHIES = (
    "Singapore",
    "Hong Kong",
    "Shenzhen",
    "China",
    "Asia",
    "Malaysia",
    "Indonesia",
    "Vietnam",
    "Thailand",
    "India",
    "Japan",
    "Korea",
)


def find_data(
    query: str,
    *,
    limit: int = 10,
    public_only: bool = False,
    geography: str | None = None,
    time_range: str | None = None,
    client: EmbeddingClient | None = None,
    search_fn=None,
) -> dict:
    intent = parse_query_intent(query, geography=geography, time_range=time_range, public_only=public_only)
    filters = {
        "public_only": intent.get("public_only"),
        "geography": intent.get("geography"),
        "time_range": intent.get("time_range"),
    }
    search_callable = search_fn or semantic_search
    search = search_callable(
        query,
        object_types=["variable", "dataset", "report", "source", "organization",
                       "connector_dataset", "connector_candidate"],
        limit=max(limit * 3, 20),
        hybrid=True,
        client=client,
        filters=filters,
    )
    groups = group_results(search["results"], limit=limit)
    has_results = any(len(group) > 0 for group in groups.values())
    return {
        "query": query,
        "parsed_intent": intent,
        "search_mode": search["mode"],
        "warning": search.get("warning"),
        "closest_variables": groups["variables"],
        "closest_datasets": groups["datasets"],
        "connector_datasets": groups["connector_datasets"],
        "relevant_reports": groups["reports"],
        "source_links": groups["sources"],
        "relevant_organizations": groups["organizations"],
        "connector_candidates": groups["connector_candidates"],
        "suggested_clarifications": [
            item.model_dump() for item in suggest_clarifications(query, intent, has_results=has_results)
        ],
    }


def parse_query_intent(query: str, *, geography: str | None = None, time_range: str | None = None, public_only: bool = False) -> dict:
    lowered = query.lower()
    detected_geo = geography
    if not detected_geo:
        for candidate in KNOWN_GEOGRAPHIES:
            if candidate.lower() in lowered:
                detected_geo = candidate
                break
    years = re.findall(r"\b(?:19|20)\d{2}\b", query)
    detected_time = time_range
    if not detected_time and years:
        detected_time = "-".join([years[0], years[-1]]) if len(years) > 1 else years[0]
    measure_intent = None
    for label, terms in {
        "amount": ("amount", "funding", "expenditure", "investment", "capital"),
        "count": ("count", "number of", "deal count", "births"),
        "rate": ("rate", "percentage", "percent", "share", "%"),
        "breakdown": ("by stage", "by sector", "by country", "breakdown"),
    }.items():
        if any(term in lowered for term in terms):
            measure_intent = label
            break
    return {
        "geography": detected_geo,
        "time_range": detected_time,
        "public_only": public_only or "public" in lowered,
        "measure_intent": measure_intent,
        "broad": is_broad_query(lowered),
    }


def is_broad_query(lowered_query: str) -> bool:
    broad_terms = ("understand", "what data", "data about", "i want data", "adoption", "innovation", "startup")
    specific_terms = ("percentage", "deal count", "by stage", "gdp", "electricity usage", "electricity consumption")
    return any(term in lowered_query for term in broad_terms) and not any(term in lowered_query for term in specific_terms)


def group_results(results: list[dict], *, limit: int) -> dict[str, list[dict]]:
    grouped = {
        "variables": [], "datasets": [], "reports": [], "sources": [],
        "organizations": [], "connector_datasets": [], "connector_candidates": [],
    }
    seen_sources: set[str] = set()
    for row in results:
        item = format_find_data_item(row)
        object_type = row["object_type"]
        if object_type == "variable" and len(grouped["variables"]) < limit:
            grouped["variables"].append(item)
        elif object_type == "dataset" and len(grouped["datasets"]) < limit:
            grouped["datasets"].append(item)
        elif object_type == "connector_dataset" and len(grouped["connector_datasets"]) < limit:
            grouped["connector_datasets"].append(item)
        elif object_type == "connector_candidate" and len(grouped["connector_candidates"]) < limit:
            grouped["connector_candidates"].append(item)
        elif object_type == "report" and len(grouped["reports"]) < limit:
            grouped["reports"].append(item)
        elif object_type == "organization" and len(grouped["organizations"]) < limit:
            grouped["organizations"].append(item)
        source_key = row.get("source_url") or row.get("source_id") or row.get("object_id")
        if source_key and source_key not in seen_sources and len(grouped["sources"]) < limit:
            seen_sources.add(source_key)
            grouped["sources"].append(
                {
                    "title": row.get("title"),
                    "source_url": row.get("source_url"),
                    "source_id": row.get("source_id"),
                    "availability": row.get("availability"),
                    "local_path": row.get("local_path"),
                }
            )
        if object_type == "source" and len(grouped["sources"]) < limit and source_key not in seen_sources:
            grouped["sources"].append(item)
    return grouped


def format_find_data_item(row: dict) -> dict:
    metadata = row.get("metadata") or {}
    item = {
        "title": row.get("title"),
        "object_type": row.get("object_type"),
        "object_id": row.get("object_id"),
        "score": row.get("score"),
        "why_it_matched": row.get("snippet"),
        "definition": metadata.get("definition"),
        "measurement_method": metadata.get("measurement_method"),
        "unit": metadata.get("unit"),
        "data_source": metadata.get("data_source_text") or metadata.get("data_source_type"),
        "availability": row.get("availability"),
        "temporal_coverage": row.get("time_coverage"),
        "geographic_coverage": row.get("geography"),
        "source_url": row.get("source_url"),
        "local_path": row.get("local_path"),
        "evidence_quote": row.get("evidence_quote"),
        "report_id": row.get("report_id"),
        "source_id": row.get("source_id"),
    }
    # Enrich connector objects with metadata
    obj_type = row.get("object_type")
    if obj_type in ("connector_dataset", "connector_candidate"):
        item["access_type"] = metadata.get("access_type")
        item["portal"] = metadata.get("portal")
        item["source_kind"] = metadata.get("source_kind")
        item["ecosystem_category"] = metadata.get("ecosystem_category")
        item["data_status"] = "synced" if row.get("availability") == "obtainable" else "metadata_only"
    if obj_type == "organization":
        item["organization_type"] = metadata.get("organization_type")
        item["parent_organization"] = metadata.get("parent_organization")
        item["data_status"] = "organization_metadata"
    return item


def suggest_clarifications(query: str, intent: dict, *, has_results: bool = True) -> list[SuggestedClarification]:
    suggestions: list[SuggestedClarification] = []
    if intent.get("broad"):
        if not intent.get("measure_intent"):
            suggestions.append(SuggestedClarification(question="Do you need amount, count, rate, share, or a breakdown?", reason="Broad data requests can map to multiple measurement types."))
        if not intent.get("geography"):
            suggestions.append(SuggestedClarification(question="Which geography should be prioritized?", reason="Most startup and innovation indicators are geography-specific."))
        if not intent.get("time_range"):
            suggestions.append(SuggestedClarification(question="What time range matters?", reason="Reports and datasets often cover different periods."))
        if "startup" in query.lower() or "vc" in query.lower():
            suggestions.append(SuggestedClarification(question="Do you need sector, stage, investor type, or exit breakdowns?", reason="Startup datasets are commonly sliced by these dimensions."))
        suggestions.append(SuggestedClarification(question="Should private or unclear-access sources be included?", reason="Some useful variables may come from private databases or report-only tables."))
    if not has_results:
        topic = query.strip() or "this topic"
        suggestions.extend(
            [
                SuggestedClarification(
                    question=f"Broader overview of {topic} key metrics and trends",
                    reason="No exact variable matched; a wider metric search may surface related indicators.",
                ),
                SuggestedClarification(
                    question=f"Official statistics and publications on {topic}",
                    reason="Reports and source links may exist even when structured variables do not.",
                ),
                SuggestedClarification(
                    question=f"Organizations and programs related to {topic}",
                    reason="Agencies, associations, and directories can anchor follow-up research.",
                ),
            ]
        )
    return suggestions[:5]


def main() -> None:
    parser = argparse.ArgumentParser(description="Find variables, datasets, reports, and sources for a user-style data request.")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--public-only", action="store_true")
    parser.add_argument("--geography")
    parser.add_argument("--time-range")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    configure_logging()
    result = find_data(
        args.query,
        limit=args.limit,
        public_only=args.public_only,
        geography=args.geography,
        time_range=args.time_range,
    )
    if args.json:
        print(json.dumps(result, default=str, ensure_ascii=True, indent=2))
    else:
        if result.get("warning"):
            print(f"Warning: {result['warning']}")
        print(json.dumps(result, default=str, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
