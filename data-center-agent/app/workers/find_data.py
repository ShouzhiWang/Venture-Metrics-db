from __future__ import annotations

import argparse
import json
import logging
import re

logger = logging.getLogger(__name__)

from app.llm.embedding_client import EmbeddingClient
from app.models.search import SuggestedClarification
from app.utils.logging import configure_logging
from app.workers.semantic_search import semantic_search

CHUNK_RESULT_LIMIT = 6
TAVILY_RESULT_LIMIT = 5
LIVE_CONNECTOR_RESULT_LIMIT = 5
RELEVANCE_LEVELS = ("direct", "partial", "contextual", "irrelevant")


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
    live_search: bool = True,
    tavily_search_fn=None,
) -> dict:
    intent = parse_query_intent(query, geography=geography, time_range=time_range, public_only=public_only)
    filters = {
        "public_only": intent.get("public_only"),
        "geography": intent.get("geography"),
        "time_range": intent.get("time_range"),
    }
    search_callable = search_fn or semantic_search
    object_types = search_object_types(intent, query)
    search = search_callable(
        query,
        object_types=object_types,
        limit=max(limit * 3, 20),
        hybrid=True,
        client=client,
        filters=filters,
    )
    groups = group_results(search["results"], limit=limit)
    has_results = any(len(group) > 0 for group in groups.values())

    result = {
        "query": query,
        "parsed_intent": intent,
        "search_mode": search["mode"],
        "warning": search.get("warning"),
        "closest_variables": groups["variables"],
        "closest_datasets": groups["datasets"],
        "connector_datasets": groups["connector_datasets"],
        "connector_metrics": groups["connector_metrics"],
        "relevant_reports": groups["reports"],
        "relevant_chunks": groups["chunks"],
        "source_links": groups["sources"],
        "relevant_organizations": groups["organizations"],
        "connector_candidates": groups["connector_candidates"],
        "suggested_clarifications": [
            item.model_dump() for item in suggest_clarifications(query, intent, has_results=has_results)
        ],
        "retrieval_config": {
            "object_types": object_types,
            "chunk_result_limit": CHUNK_RESULT_LIMIT,
            "tavily_result_limit": min(limit, TAVILY_RESULT_LIMIT),
            "live_connector_result_limit": min(limit, LIVE_CONNECTOR_RESULT_LIMIT),
        },
    }
    annotate_result_quality(result, query, intent)

    # Real-time data.gov.hk search for innovation/IP/HK data queries
    if live_search:
        try:
            from app.workers.datagovhk_live_search import search_live, should_trigger_live_search
            if should_trigger_live_search(query):
                live = search_live(query, limit=min(limit, LIVE_CONNECTOR_RESULT_LIMIT))
                result["live_api_results"] = {
                    "source": live["source"],
                    "retrieved_at": live["retrieved_at"],
                    "total_available": live["total_available"],
                    "latency_ms": live["latency_ms"],
                    "results": live["results"],
                    "error": live.get("error"),
                }
                # Merge live results into connector_datasets if not already present
                existing_urls = {cd.get("source_url") for cd in result["connector_datasets"]}
                for live_ds in live["results"]:
                    if live_ds.get("source_url") not in existing_urls:
                        live_ds["data_status"] = "live_api_result"
                        live_ds["data_status_label"] = "live from data.gov.hk API"
                        live_ds.setdefault("title", live_ds.get("name") or live_ds.get("title"))
                        result["connector_datasets"].append(live_ds)
                annotate_result_quality(result, query, intent)
        except Exception as exc:
            logger.debug("Live data.gov.hk search skipped: %s", exc)

    # Real-time data.gov.sg search for Singapore data queries
    if live_search:
        try:
            from app.workers.datagovsg_live_search import search_live as sg_search_live, should_trigger_live_search as sg_should_trigger
            if sg_should_trigger(query):
                sg_live = sg_search_live(query, limit=min(limit, LIVE_CONNECTOR_RESULT_LIMIT))
                if sg_live.get("ok"):
                    result["live_api_results_sg"] = {
                        "source": sg_live["source"],
                        "retrieved_at": sg_live["fetched_at"],
                        "total_available": sg_live["total_results"],
                        "results": sg_live["results"],
                    }
                    # Merge live results into connector_datasets
                    existing_urls = {cd.get("source_url") for cd in result["connector_datasets"]}
                    for live_ds in sg_live.get("results", []):
                        if live_ds.get("source_url") not in existing_urls:
                            live_ds["data_status"] = "live_api_result"
                            live_ds["data_status_label"] = "live from data.gov.sg API"
                            live_ds.setdefault("title", live_ds.get("name") or live_ds.get("title"))
                            result["connector_datasets"].append(live_ds)
                    annotate_result_quality(result, query, intent)
        except Exception as exc:
            logger.debug("Live data.gov.sg search skipped: %s", exc)

    # Real-time World Bank search for economic/development data queries
    if live_search:
        try:
            from app.workers.sync_worldbank import search_live as wb_search_live
            # Trigger on economic/development/innovation topics
            wb_triggers = {"gdp", "economic", "trade", "investment", "export", "import",
                           "unemployment", "employment", "education", "r&d", "research",
                           "patent", "innovation", "business", "development", "poverty",
                           "population", "gdp per capita", "gni", "fdi", "indicator"}
            if any(t in query.lower() for t in wb_triggers):
                wb_live = wb_search_live(query, limit=min(limit, LIVE_CONNECTOR_RESULT_LIMIT))
                if wb_live.get("ok") and wb_live.get("results"):
                    result["live_api_results_wb"] = {
                        "source": wb_live["source"],
                        "retrieved_at": wb_live["fetched_at"],
                        "total_available": wb_live["total_results"],
                        "results": wb_live["results"],
                    }
                    existing_urls = {cd.get("source_url") for cd in result["connector_datasets"]}
                    for live_ds in wb_live["results"]:
                        if live_ds.get("source_url") not in existing_urls:
                            live_ds["data_status"] = "live_api_result"
                            live_ds["data_status_label"] = "live from World Bank API"
                            live_ds.setdefault("title", live_ds.get("name"))
                            result["connector_datasets"].append(live_ds)
                    annotate_result_quality(result, query, intent)
        except Exception as exc:
            logger.debug("Live World Bank search skipped: %s", exc)

    # Real-time OpenAlex search for research/academic data queries
    if live_search:
        try:
            from app.workers.sync_openalex import search_live as oa_search_live
            oa_triggers = {"research", "publication", "paper", "journal", "academic",
                           "university", "institution", "scholar", "citation", "h-index",
                           "patent", "innovation", "science", "technology", "literature"}
            if any(t in query.lower() for t in oa_triggers):
                oa_live = oa_search_live(query, limit=min(limit, LIVE_CONNECTOR_RESULT_LIMIT))
                if oa_live.get("ok") and oa_live.get("results"):
                    result["live_api_results_oa"] = {
                        "source": oa_live["source"],
                        "retrieved_at": oa_live["fetched_at"],
                        "total_available": oa_live["total_results"],
                        "results": oa_live["results"],
                    }
                    existing_urls = {cd.get("source_url") for cd in result["connector_datasets"]}
                    for live_ds in oa_live["results"]:
                        if live_ds.get("source_url") not in existing_urls:
                            live_ds["data_status"] = "live_api_result"
                            live_ds["data_status_label"] = "live from OpenAlex API"
                            live_ds.setdefault("title", live_ds.get("name") or live_ds.get("title"))
                            result["connector_datasets"].append(live_ds)
                    annotate_result_quality(result, query, intent)
        except Exception as exc:
            logger.debug("Live OpenAlex search skipped: %s", exc)

    # Real-time Crossref search for scholarly works queries
    if live_search:
        try:
            from app.workers.sync_crossref import search_live as cr_search_live
            cr_triggers = {"paper", "publication", "doi", "journal", "article",
                           "scholarly", "funder", "funding", "grant", "research",
                           "literature", "review", "meta-analysis"}
            if any(t in query.lower() for t in cr_triggers):
                cr_live = cr_search_live(query, limit=min(limit, LIVE_CONNECTOR_RESULT_LIMIT))
                if cr_live.get("ok") and cr_live.get("results"):
                    result["live_api_results_cr"] = {
                        "source": cr_live["source"],
                        "retrieved_at": cr_live["fetched_at"],
                        "total_available": cr_live["total_results"],
                        "results": cr_live["results"],
                    }
                    existing_urls = {cd.get("source_url") for cd in result["connector_datasets"]}
                    for live_ds in cr_live["results"]:
                        if live_ds.get("source_url") not in existing_urls:
                            live_ds["data_status"] = "live_api_result"
                            live_ds["data_status_label"] = "live from Crossref API"
                            result["connector_datasets"].append(live_ds)
                    annotate_result_quality(result, query, intent)
        except Exception as exc:
            logger.debug("Live Crossref search skipped: %s", exc)

    # Tavily web discovery fallback — triggers when DB + APIs returned weak evidence.
    if live_search:
        try:
            if should_run_tavily_fallback(result):
                if tavily_search_fn is None:
                    from app.workers.tavily_discovery import search_live as tavily_search
                else:
                    tavily_search = tavily_search_fn
                tavily_result = tavily_search(query, limit=min(limit, TAVILY_RESULT_LIMIT))
                if tavily_result.get("ok") and tavily_result.get("results"):
                    result["tavily_candidates"] = {
                        "source": "Tavily (web discovery fallback)",
                        "query": query,
                        "total": tavily_result["total_results"],
                        "results": tavily_result["results"],
                        "note": "These are candidate sources from web search, not validated data. "
                                "Store as external_source_candidates for review before ingestion.",
                    }
                    # Don't merge into connector_datasets — they're candidates, not validated
                    annotate_result_quality(result, query, intent)
        except Exception as exc:
            logger.debug("Tavily fallback skipped: %s", exc)

    return result


def search_object_types(intent: dict, query: str) -> list[str]:
    object_types = [
        "variable",
        "dataset",
        "report",
        "source",
        "organization",
        "connector_dataset",
        "connector_candidate",
        "connector_metric",
    ]
    if should_include_chunk_search(intent, query):
        object_types.append("chunk")
    return object_types


def should_include_chunk_search(intent: dict, query: str) -> bool:
    lowered = query.lower()
    trend_terms = ("trend", "trends", "shift", "overview", "brief", "ecosystem", "latest", "recent", "why", "how")
    return bool(intent.get("broad") or any(term in lowered for term in trend_terms))


def should_run_tavily_fallback(result: dict) -> bool:
    quality = result.get("evidence_quality") or {}
    direct_or_partial = int(quality.get("direct", 0)) + int(quality.get("partial", 0))
    if direct_or_partial > 0:
        return False
    return True


def annotate_result_quality(result: dict, query: str, intent: dict) -> None:
    summary = {level: 0 for level in RELEVANCE_LEVELS}
    excluded = []

    for key in (
        "closest_variables",
        "closest_datasets",
        "connector_datasets",
        "connector_metrics",
        "relevant_reports",
        "relevant_chunks",
        "source_links",
        "relevant_organizations",
        "connector_candidates",
    ):
        for item in result.get(key) or []:
            label = classify_relevance(item, query, intent)
            item["relevance"] = label
            summary[label] += 1
            if label == "irrelevant":
                excluded.append(
                    {
                        "title": item.get("title") or item.get("name"),
                        "source_url": item.get("source_url") or item.get("url"),
                        "reason": "No meaningful query terms matched this item.",
                        "source_group": key,
                    }
                )

    tavily = result.get("tavily_candidates") or {}
    for item in tavily.get("results") or []:
        label = classify_relevance(item, query, intent)
        item["relevance"] = label
        summary[label] += 1
        if label == "irrelevant":
            excluded.append(
                {
                    "title": item.get("title"),
                    "source_url": item.get("url") or item.get("source_url"),
                    "reason": "No meaningful query terms matched this external candidate.",
                    "source_group": "tavily_candidates",
                }
            )

    result["evidence_quality"] = {
        **summary,
        "direct_or_partial": summary["direct"] + summary["partial"],
        "fallback_recommended": summary["direct"] + summary["partial"] == 0,
    }
    result["excluded_results"] = excluded[:10]


def classify_relevance(item: dict, query: str, intent: dict) -> str:
    text = item_search_text(item)
    if not text:
        return "irrelevant"
    tokens = query_terms(query)
    token_hits = sum(1 for token in tokens if token in text)
    geo = (intent.get("geography") or "").strip().lower()
    geo_match = bool(geo and geo in text)
    source_status = str(item.get("data_status") or item.get("source_status") or "").lower()
    is_internal = source_status not in {"live_api_result"} and not item.get("data_status_label", "").lower().startswith("live from")
    score = float(item.get("score") or item.get("confidence_score") or 0)

    if geo_match and token_hits >= 2:
        return "direct"
    if token_hits >= 3:
        return "direct"
    if geo_match and token_hits >= 1:
        return "partial"
    if token_hits >= 2:
        return "partial"
    if token_hits >= 1 and (is_internal or score >= 0.5):
        return "contextual"
    return "irrelevant"


def item_search_text(item: dict) -> str:
    parts = []
    for key in (
        "title",
        "name",
        "description",
        "definition",
        "snippet",
        "content",
        "why_it_matched",
        "portal",
        "publisher",
        "geography",
        "source_url",
        "url",
        "evidence_quote",
    ):
        value = item.get(key)
        if value is not None:
            parts.append(str(value))
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        parts.append(json.dumps(metadata, ensure_ascii=True, default=str))
    return " ".join(parts).lower()


def query_terms(query: str) -> set[str]:
    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "about",
        "data",
        "dataset",
        "datasets",
        "source",
        "sources",
        "singapore",
        "hong",
        "kong",
        "china",
        "asia",
        "what",
        "which",
        "need",
        "show",
        "find",
        "latest",
        "recent",
    }
    words = {
        word
        for word in re.findall(r"[a-z0-9]+", query.lower())
        if len(word) >= 3 and word not in stop_words and not word.isdigit()
    }
    synonyms = {
        "startup": {"startup", "startups", "venture", "vc", "entrepreneur", "entrepreneurship"},
        "funding": {"funding", "investment", "capital", "deal", "deals", "financing"},
        "founding": {"founding", "incorporation", "births", "formation", "new"},
        "trend": {"trend", "trends", "growth", "decline", "shift", "change"},
    }
    expanded = set(words)
    for word in list(words):
        expanded.update(synonyms.get(word, set()))
    return expanded


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
    """Group search results with synced connector datasets prioritized over metadata-only candidates.

    Rules:
    1. Synced datasets (with snapshots) appear before metadata-only portal candidates.
    2. connector_datasets = synced datasets with row_count, column_count, retrieved_at, source_url.
    3. connector_candidates = metadata-only sources labeled "source candidate, not yet synced".
    """
    grouped = {
        "variables": [], "datasets": [], "reports": [], "sources": [],
        "organizations": [], "connector_datasets": [], "connector_candidates": [],
        "connector_metrics": [], "chunks": [],
    }
    seen_sources: set[str] = set()

    # Phase 1: Collect connector items separately for priority sorting
    synced_connectors: list[dict] = []
    metadata_only_connectors: list[dict] = []

    for row in results:
        item = format_find_data_item(row)
        object_type = row["object_type"]

        if object_type == "variable" and len(grouped["variables"]) < limit:
            grouped["variables"].append(item)
        elif object_type == "dataset" and len(grouped["datasets"]) < limit:
            grouped["datasets"].append(item)
        elif object_type == "connector_dataset":
            # Check if this dataset has a synced snapshot
            if item.get("data_status") == "synced":
                synced_connectors.append(item)
            else:
                metadata_only_connectors.append(item)
        elif object_type == "connector_candidate":
            # Candidates are always metadata-only
            item["data_status_label"] = "source candidate, not yet synced"
            metadata_only_connectors.append(item)
        elif object_type == "report" and len(grouped["reports"]) < limit:
            grouped["reports"].append(item)
        elif object_type == "chunk" and len(grouped["chunks"]) < min(limit, CHUNK_RESULT_LIMIT):
            grouped["chunks"].append(item)
        elif object_type == "organization" and len(grouped["organizations"]) < limit:
            grouped["organizations"].append(item)
        elif object_type == "connector_metric" and len(grouped["connector_metrics"]) < limit:
            grouped["connector_metrics"].append(item)

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

    # Phase 2: Merge synced first, then metadata-only, respecting limit
    grouped["connector_datasets"] = synced_connectors[:limit]
    remaining = limit - len(grouped["connector_datasets"])
    if remaining > 0:
        # Add metadata-only connector datasets after synced ones
        for item in metadata_only_connectors:
            if len(grouped["connector_datasets"]) >= limit:
                break
            if item.get("object_type") == "connector_dataset":
                item["data_status_label"] = "source candidate, not yet synced"
                grouped["connector_datasets"].append(item)

    # connector_candidates are pure metadata-only portal/org candidates
    grouped["connector_candidates"] = [
        item for item in metadata_only_connectors
        if item.get("object_type") == "connector_candidate"
    ][:limit]

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

        # Enrich synced datasets with snapshot metadata (row_count, column_count, retrieved_at)
        if item["data_status"] == "synced":
            item["row_count"] = metadata.get("row_count")
            item["column_count"] = metadata.get("column_count")
            item["retrieved_at"] = metadata.get("retrieved_at")
            item["snapshot_id"] = metadata.get("snapshot_id")
            item["data_status_label"] = "synced dataset"
        else:
            item["data_status_label"] = "source candidate, not yet synced"

    if obj_type == "organization":
        item["organization_type"] = metadata.get("organization_type")
        item["parent_organization"] = metadata.get("parent_organization")
        item["data_status"] = "organization_metadata"
    if obj_type == "connector_metric":
        item["metric_name"] = row.get("title")
        item["metric_description"] = metadata.get("definition") or row.get("content")
        item["category"] = metadata.get("category")
        item["dimension"] = metadata.get("dimension")
        item["dataset_name"] = metadata.get("dataset_name")
        item["portal"] = metadata.get("portal")
        item["retrieved_at"] = metadata.get("retrieved_at")
        item["data_status"] = "official_metric"
        item["data_status_label"] = "official synced dataset metric"
    # Live API results
    if metadata.get("freshness") == "real-time":
        item["data_status"] = "live_api_result"
        item["data_status_label"] = f"live from {metadata.get('portal', 'external')} API"
        item["freshness"] = "real-time"
        item["last_modified"] = metadata.get("last_modified")
        item["download_url"] = metadata.get("download_url")
        item["provider"] = metadata.get("provider")
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
