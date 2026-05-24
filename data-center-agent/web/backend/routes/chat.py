from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter
except ImportError:  # pragma: no cover
    APIRouter = None
from pydantic import BaseModel, Field

from app.agents.query_planner import plan_query
from web.backend.services.tool_client import SAFE_WEB_TOOLS, call_demo_tool


if APIRouter:
    router = APIRouter()
else:  # pragma: no cover
    router = None


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class FeedbackRequest(BaseModel):
    answer_id: str | None = None
    result_id: str | None = None
    feedback_type: str
    comment: str | None = None


def handle_chat(payload: dict[str, Any], tool_caller=call_demo_tool) -> dict[str, Any]:
    message = (payload.get("message") or "").strip()
    context = payload.get("context") or {}
    plan = plan_query(message, context)
    if plan["should_ask_clarifying_question"]:
        return {
            "type": "clarification",
            "message": "I need one or two details before searching.",
            "intent": plan["intent"],
            "clarifying_questions": plan["clarifying_questions"],
            "results": _empty_results(),
            "limitations": [],
            "debug": {"plan": plan},
        }

    if plan["intent"] == "compare_concepts":
        tool_result = tool_caller(
            "compare_concepts_auto",
            {
                "query": message,
                "geography": plan["extracted_filters"].get("geography"),
                "public_only": plan["extracted_filters"].get("public_only", False),
            },
        )
        return _comparison_response(message, plan, tool_result)

    if plan["intent"] == "find_organizations":
        tool_result = tool_caller("semantic_search", {"query": message, "object_types": ["organization"], "limit": 8})
        return _organization_response(message, plan, tool_result)

    tool_result = tool_caller(
        "find_data",
        {
            "query": message,
            "limit": 8,
            "public_only": plan["extracted_filters"].get("public_only", False),
            "geography": plan["extracted_filters"].get("geography"),
            "time_range": plan["extracted_filters"].get("time_range"),
        },
    )
    return _find_data_response(message, plan, tool_result)


def _find_data_response(message: str, plan: dict[str, Any], tool_result: dict[str, Any]) -> dict[str, Any]:
    if not tool_result.get("ok"):
        return _error_response(message, plan, tool_result)
    data = tool_result.get("data") or {}
    variables = data.get("closest_variables") or []
    reports = data.get("relevant_reports") or []
    organizations = data.get("relevant_organizations") or []
    sources = data.get("source_links") or []
    count = len(variables) + len(reports) + len(organizations)
    response_type = "answer" if count else "no_results"
    message_text = (
        f"Found {len(variables)} variable matches, {len(reports)} reports, and {len(organizations)} organizations."
        if count
        else "I could not find strong matches yet."
    )
    return {
        "type": response_type,
        "message": message_text,
        "intent": plan["intent"],
        "clarifying_questions": _questions_from_data(data),
        "results": {
            "closest_variables": variables,
            "relevant_reports": reports,
            "relevant_organizations": organizations,
            "source_links": sources,
            "comparison": {},
        },
        "limitations": _limitations_from_data(data, count),
        "debug": {"plan": plan, "tool": "find_data"},
    }


def _comparison_response(message: str, plan: dict[str, Any], tool_result: dict[str, Any]) -> dict[str, Any]:
    if not tool_result.get("ok"):
        return _error_response(message, plan, tool_result)
    data = tool_result.get("data") or {}
    status = data.get("status")
    return {
        "type": "answer" if status == "ok" else "no_results",
        "message": data.get("comparison", {}).get("summary") or "Comparison results are available.",
        "intent": "compare_concepts",
        "clarifying_questions": [{"question": q, "options": []} for q in data.get("clarifying_questions", [])],
        "results": {
            "closest_variables": data.get("closest_variables", []),
            "relevant_reports": data.get("selected_reports", []),
            "relevant_organizations": [],
            "source_links": [],
            "comparison": data.get("comparison", {}),
        },
        "limitations": data.get("limitations", []),
        "debug": {"plan": plan, "metadata": data.get("metadata", {})},
    }


def _organization_response(message: str, plan: dict[str, Any], tool_result: dict[str, Any]) -> dict[str, Any]:
    if not tool_result.get("ok"):
        return _error_response(message, plan, tool_result)
    rows = (tool_result.get("data") or {}).get("results") or []
    organizations = [_format_organization(row) for row in rows]
    return {
        "type": "answer" if organizations else "no_results",
        "message": f"Found {len(organizations)} organization matches." if organizations else "I could not find matching organizations yet.",
        "intent": "find_organizations",
        "clarifying_questions": [],
        "results": {
            "closest_variables": [],
            "relevant_reports": [],
            "relevant_organizations": organizations,
            "source_links": _source_links_from_rows(rows),
            "comparison": {},
        },
        "limitations": [] if organizations else ["No organization records matched the query."],
        "debug": {"plan": plan, "tool": "semantic_search"},
    }


def _format_organization(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") or {}
    return {
        "object_id": row.get("object_id"),
        "title": row.get("title"),
        "name": row.get("title"),
        "organization_type": metadata.get("organization_type"),
        "geography": row.get("geography"),
        "description": row.get("snippet"),
        "website_url": metadata.get("website_url") or row.get("source_url"),
        "score": row.get("score"),
    }


def _questions_from_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"question": item.get("question"), "options": []} for item in data.get("suggested_clarifications", []) if item.get("question")][:3]


def _limitations_from_data(data: dict[str, Any], count: int) -> list[str]:
    limitations = []
    if data.get("warning"):
        limitations.append(data["warning"])
    if count == 0:
        limitations.append("The current index may not contain this concept or geography yet.")
    return limitations


def _source_links_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    links = []
    seen = set()
    for row in rows:
        url = row.get("source_url")
        if url and url not in seen:
            seen.add(url)
            links.append({"title": row.get("title"), "source_url": url, "availability": row.get("availability")})
    return links


def _error_response(message: str, plan: dict[str, Any], tool_result: dict[str, Any]) -> dict[str, Any]:
    error = tool_result.get("error") or {}
    return {
        "type": "error",
        "message": error.get("message") or "The request could not be completed.",
        "intent": plan.get("intent", "unknown"),
        "clarifying_questions": [],
        "results": _empty_results(),
        "limitations": [error.get("code", "unknown_error")],
        "debug": {"plan": plan, "tool_error": error},
    }


def _empty_results() -> dict[str, Any]:
    return {"closest_variables": [], "relevant_reports": [], "relevant_organizations": [], "source_links": [], "comparison": {}}


if router:
    @router.post("/api/chat")
    def chat(request: ChatRequest) -> dict[str, Any]:
        return handle_chat(request.model_dump())

    @router.post("/api/tool/find_data")
    def tool_find_data(args: dict[str, Any]) -> dict[str, Any]:
        return call_demo_tool("find_data", args)

    @router.post("/api/tool/compare_concepts_auto")
    def tool_compare_concepts_auto(args: dict[str, Any]) -> dict[str, Any]:
        return call_demo_tool("compare_concepts_auto", args)

    @router.get("/api/variable/{variable_id}")
    def variable_detail(variable_id: str) -> dict[str, Any]:
        return call_demo_tool("get_variable_detail", {"variable_id": variable_id})

    @router.get("/api/report/{report_id}")
    def report_detail(report_id: str) -> dict[str, Any]:
        return call_demo_tool("get_report_detail", {"report_id": report_id})

    @router.get("/api/source/{source_id}")
    def source_detail(source_id: str) -> dict[str, Any]:
        return call_demo_tool("get_source_detail", {"source_id": source_id})

    @router.get("/api/organization/{organization_id}")
    def organization_detail(organization_id: str) -> dict[str, Any]:
        return call_demo_tool("get_organization_detail", {"organization_id": organization_id})

    @router.post("/api/feedback")
    def feedback(request: FeedbackRequest) -> dict[str, Any]:
        return call_demo_tool("submit_feedback", request.model_dump())
