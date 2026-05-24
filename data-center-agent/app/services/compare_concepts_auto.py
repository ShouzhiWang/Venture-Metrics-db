from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from app.db.repositories.variables import VariableRepository
from app.workers.find_data import find_data
from app.workers.semantic_search import semantic_search


OUT_OF_SCOPE_ITEM_TYPES = {
    "administrative_metric",
    "financial_accounting_metric",
    "data_source_reference",
    "analytical_claim",
}
DEFAULT_OBJECT_TYPES = ["variable", "report"]


def compare_concepts_auto(
    query: str,
    *,
    connection=None,
    limit_reports: int = 5,
    limit_variables: int = 20,
    geography: str | None = None,
    public_only: bool = False,
    min_confidence: float | None = None,
    object_types: list[str] | None = None,
    search_fn: Callable[..., dict] | None = None,
    find_data_fn: Callable[..., dict] | None = None,
    compare_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        raise ValueError("query is required.")

    selected_object_types = object_types or DEFAULT_OBJECT_TYPES
    search_callable = search_fn or semantic_search
    find_data_callable = find_data_fn or find_data
    filters = {"public_only": public_only, "geography": geography}

    search_kwargs = {
        "object_types": selected_object_types,
        "limit": max(limit_variables * 2, limit_reports * 4, 20),
        "hybrid": True,
        "filters": filters,
    }
    if connection is not None:
        search_kwargs["connection"] = connection
    search_result = search_callable(query, **search_kwargs)

    discovery_kwargs = {
        "limit": max(limit_reports, 5),
        "public_only": public_only,
        "geography": geography,
        "search_fn": (
            (lambda q, **kwargs: search_callable(q, connection=connection, **kwargs))
            if connection is not None and search_fn is None
            else None
        ),
    }
    discovery = find_data_callable(query, **{key: value for key, value in discovery_kwargs.items() if value is not None})
    variables = [
        row
        for row in search_result.get("results", [])
        if row.get("object_type") == "variable" and _variable_in_scope(row, query, public_only, min_confidence)
    ][:limit_variables]
    reports_by_id = _reports_from_search_and_discovery(search_result.get("results", []), discovery)

    if not variables:
        return _base_result(
            query=query,
            status="no_results",
            selected_reports=[],
            comparison=_empty_comparison("No matching variables were found for this concept query."),
            limitations=["No matching variables were found in the current search index."],
            clarifying_questions=_clarifying_questions(query, discovery),
            metadata={"auto_selected_report_ids": [], "auto_selected_variable_ids": [], "tool_chain": ["semantic_search", "find_data"]},
            closest_variables=[],
            closest_reports=list(reports_by_id.values())[:limit_reports],
        )

    ranked_reports = _rank_reports(variables, reports_by_id, query=query, geography=geography, public_only=public_only)
    selected_reports = ranked_reports[: max(2, min(limit_reports, 5))]
    selected_report_ids = [row["report_id"] for row in selected_reports]
    selected_variable_ids = [
        variable["variable_id"]
        for report in selected_reports
        for variable in report["matched_variables"]
        if variable.get("variable_id")
    ]

    if len(selected_reports) < 2:
        return _base_result(
            query=query,
            status="insufficient_reports",
            selected_reports=selected_reports,
            comparison=_empty_comparison("Comparison cannot be made yet because fewer than two reports matched."),
            limitations=["Only one report had matching in-scope variables."],
            clarifying_questions=_clarifying_questions(query, discovery),
            metadata={
                "auto_selected_report_ids": selected_report_ids,
                "auto_selected_variable_ids": selected_variable_ids,
                "tool_chain": ["semantic_search", "find_data"],
            },
            closest_variables=variables,
            closest_reports=list(reports_by_id.values())[:limit_reports],
        )

    compare_callable = compare_fn
    if compare_callable is None:
        if connection is None:
            raise ValueError("connection is required when compare_fn is not provided.")
        compare_callable = VariableRepository(connection).compare_concepts
    raw_comparison = compare_callable(query, report_ids=selected_report_ids)

    limitations = _limitations(selected_reports, raw_comparison)
    return _base_result(
        query=query,
        status="ok",
        selected_reports=selected_reports,
        comparison=_adapt_comparison(raw_comparison, selected_reports),
        limitations=limitations,
        clarifying_questions=_clarifying_questions(query, discovery),
        metadata={
            "auto_selected_report_ids": selected_report_ids,
            "auto_selected_variable_ids": selected_variable_ids,
            "tool_chain": ["semantic_search", "find_data", "compare_concepts"],
        },
        closest_variables=variables,
        closest_reports=list(reports_by_id.values())[:limit_reports],
    )


def _variable_in_scope(row: dict[str, Any], query: str, public_only: bool, min_confidence: float | None) -> bool:
    metadata = row.get("metadata") or {}
    item_type = metadata.get("item_type")
    lowered_query = query.lower()
    if item_type in OUT_OF_SCOPE_ITEM_TYPES and item_type not in lowered_query:
        return False
    if public_only and str(row.get("availability") or "").lower() == "private":
        return False
    confidence = _safe_float(metadata.get("confidence_score"))
    if confidence is None:
        confidence = _safe_float(metadata.get("confidence"))
    if min_confidence is not None and confidence is not None and float(confidence) < min_confidence:
        return False
    return bool(row.get("report_id"))


def _reports_from_search_and_discovery(search_rows: list[dict[str, Any]], discovery: dict[str, Any]) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for row in search_rows:
        if row.get("object_type") == "report" and row.get("object_id"):
            reports[str(row["object_id"])] = {
                "report_id": str(row["object_id"]),
                "title": row.get("title"),
                "score": float(row.get("score") or 0),
                "geography": row.get("geography"),
                "source_url": row.get("source_url"),
            }
    for row in discovery.get("relevant_reports", []):
        report_id = row.get("object_id") or row.get("report_id")
        if report_id and str(report_id) not in reports:
            reports[str(report_id)] = {
                "report_id": str(report_id),
                "title": row.get("title"),
                "score": float(row.get("score") or 0),
                "geography": row.get("geographic_coverage") or row.get("geography"),
                "source_url": row.get("source_url"),
            }
    return reports


def _rank_reports(
    variables: list[dict[str, Any]],
    reports_by_id: dict[str, dict[str, Any]],
    *,
    query: str,
    geography: str | None,
    public_only: bool,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scores: dict[str, float] = defaultdict(float)
    for row in variables:
        report_id = str(row["report_id"])
        variable = _format_variable(row)
        grouped[report_id].append(variable)
        scores[report_id] += _variable_score(row, query=query, geography=geography, public_only=public_only)

    ranked = []
    for report_id, matched in grouped.items():
        report = reports_by_id.get(report_id, {"report_id": report_id, "title": None, "score": 0.0})
        report_search_score = float(report.get("score") or 0)
        matched_sorted = sorted(matched, key=lambda item: float(item.get("score") or 0), reverse=True)
        ranked.append(
            {
                "report_id": report_id,
                "title": report.get("title") or matched_sorted[0].get("report_title") or f"Report {report_id}",
                "score": round(scores[report_id] + report_search_score + (len(matched) * 0.35), 4),
                "geography": report.get("geography"),
                "source_url": report.get("source_url"),
                "matched_variables": matched_sorted,
            }
        )
    return sorted(ranked, key=lambda item: item["score"], reverse=True)


def _variable_score(row: dict[str, Any], *, query: str, geography: str | None, public_only: bool) -> float:
    metadata = row.get("metadata") or {}
    score = float(row.get("score") or 0)
    if row.get("evidence_quote") or metadata.get("evidence_quote") or metadata.get("evidence_chunk_id"):
        score += 0.4
    if metadata.get("item_type") == "codebook_variable":
        score += 0.3
    if metadata.get("domain_relevance") and str(metadata["domain_relevance"]).lower() in query.lower():
        score += 0.2
    if geography and geography.lower() in str(row.get("geography") or "").lower():
        score += 0.25
    if public_only and str(row.get("availability") or "").lower() == "private":
        score -= 1.0
    confidence = _safe_float(metadata.get("confidence_score"))
    if confidence is not None and confidence < 0.5:
        score -= 0.4
    return score


def _format_variable(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") or {}
    return {
        "variable_id": row.get("variable_id") or row.get("object_id"),
        "raw_variable_name": row.get("title"),
        "definition": metadata.get("definition"),
        "measurement_method": metadata.get("measurement_method"),
        "availability": row.get("availability"),
        "evidence_quote": row.get("evidence_quote") or metadata.get("evidence_quote"),
        "score": float(row.get("score") or 0),
        "report_id": row.get("report_id"),
        "report_title": metadata.get("report_title"),
        "item_type": metadata.get("item_type"),
        "domain_relevance": metadata.get("domain_relevance"),
    }


def _adapt_comparison(raw_comparison: Any, selected_reports: list[dict[str, Any]]) -> dict[str, Any]:
    rows = raw_comparison if isinstance(raw_comparison, list) else []
    definitions = [
        {
            "report_id": str(row.get("report_id")),
            "variable_id": str(row.get("id")) if row.get("id") else None,
            "raw_variable_name": row.get("raw_variable_name"),
            "definition": row.get("definition"),
        }
        for row in rows
    ]
    data_sources = [
        {
            "report_id": str(row.get("report_id")),
            "raw_variable_name": row.get("raw_variable_name"),
            "data_source": row.get("data_source_text") or row.get("data_source_type"),
        }
        for row in rows
        if row.get("data_source_text") or row.get("data_source_type")
    ]
    measurement_differences = [
        {
            "report_id": str(row.get("report_id")),
            "raw_variable_name": row.get("raw_variable_name"),
            "measurement_method": row.get("measurement_method"),
            "unit": row.get("unit"),
        }
        for row in rows
        if row.get("measurement_method") or row.get("unit")
    ]
    comparability = _comparability(definitions, measurement_differences, selected_reports)
    return {
        "summary": f"Compared {len(rows)} matching variables across {len(selected_reports)} auto-selected reports.",
        "shared_concepts": sorted({item.get("raw_variable_name") for item in definitions if item.get("raw_variable_name")}),
        "definition_differences": definitions,
        "measurement_differences": measurement_differences,
        "data_source_differences": data_sources,
        "comparability": comparability,
        "raw_comparisons": raw_comparison,
    }


def _comparability(definitions: list[dict[str, Any]], measurement_differences: list[dict[str, Any]], selected_reports: list[dict[str, Any]]) -> str:
    if not definitions:
        return "unknown"
    if len(selected_reports) < 2:
        return "unknown"
    if measurement_differences and len({str(item.get("unit")) for item in measurement_differences if item.get("unit")}) > 1:
        return "mixed"
    if len(definitions) >= len(selected_reports):
        return "medium"
    return "low"


def _limitations(selected_reports: list[dict[str, Any]], raw_comparison: Any) -> list[str]:
    limitations = []
    if len(selected_reports) < 5:
        limitations.append(f"Only {len(selected_reports)} reports had matching variables.")
    if any(
        str(variable.get("availability") or "").lower() == "private"
        for report in selected_reports
        for variable in report.get("matched_variables", [])
    ):
        limitations.append("Some variables rely on private data sources.")
    if not raw_comparison:
        limitations.append("Existing compare_concepts returned no matching comparison rows.")
    return limitations


def _clarifying_questions(query: str, discovery: dict[str, Any]) -> list[str]:
    suggestions = [item.get("question") for item in discovery.get("suggested_clarifications", []) if item.get("question")]
    if suggestions:
        return suggestions[:3]
    lowered = query.lower()
    if "funding" in lowered or "investment" in lowered:
        return ["Do you want to compare funding amount, deal count, or stage breakdown?"]
    return ["Do you want definitions, measurement methods, or data sources compared?"]


def _empty_comparison(summary: str) -> dict[str, Any]:
    return {
        "summary": summary,
        "shared_concepts": [],
        "definition_differences": [],
        "measurement_differences": [],
        "data_source_differences": [],
        "comparability": "unknown",
        "raw_comparisons": [],
    }


def _base_result(
    *,
    query: str,
    status: str,
    selected_reports: list[dict[str, Any]],
    comparison: dict[str, Any],
    limitations: list[str],
    clarifying_questions: list[str],
    metadata: dict[str, Any],
    closest_variables: list[dict[str, Any]],
    closest_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "query": query,
        "status": status,
        "selected_reports": selected_reports,
        "comparison": comparison,
        "limitations": limitations,
        "clarifying_questions": clarifying_questions,
        "metadata": metadata,
        "closest_variables": closest_variables,
        "closest_reports": closest_reports,
    }


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
