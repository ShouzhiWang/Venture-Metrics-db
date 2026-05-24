from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter
except ImportError:  # pragma: no cover
    APIRouter = None
from pydantic import BaseModel, Field

from app.agents.demo_llm import DemoLLMClient, DemoLLMConfigError, DemoLLMProviderError, DemoLLMResponseError
from app.agents.query_planner import plan_query
from web.backend.services.tool_client import SAFE_WEB_TOOLS, call_demo_tool


if APIRouter:
    router = APIRouter()
else:  # pragma: no cover
    router = None


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    history: list[dict[str, str]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class FeedbackRequest(BaseModel):
    answer_id: str | None = None
    result_id: str | None = None
    feedback_type: str
    comment: str | None = None


CHAT_TOOL_NAMES = SAFE_WEB_TOOLS - {"submit_feedback"}


def handle_chat(payload: dict[str, Any], tool_caller=call_demo_tool, llm_client: Any | None = None) -> dict[str, Any]:
    message = (payload.get("message") or "").strip()
    context = payload.get("context") or {}
    history = _sanitize_history(payload.get("history") or [])
    try:
        llm = llm_client or DemoLLMClient()
        plan = _validate_plan(llm.plan(message=message, history=history, safe_tools=CHAT_TOOL_NAMES), message)
    except DemoLLMConfigError as exc:
        return _llm_error_response("llm_not_configured", str(exc))
    except DemoLLMResponseError as exc:
        return _llm_error_response("llm_invalid_response", str(exc))
    except DemoLLMProviderError as exc:
        return _llm_error_response("llm_provider_error", str(exc))

    unsafe_tool = _first_unsafe_tool(plan.get("tool_calls") or [])
    if unsafe_tool:
        return _llm_error_response("tool_not_allowed", f"Tool is not exposed to the website: {unsafe_tool}")

    if plan.get("clarifying_questions") and not plan.get("tool_calls"):
        assistant_message = plan.get("assistant_message") or "I need one or two details before searching."
        return {
            "type": "clarification",
            "message": assistant_message,
            "assistant_message": assistant_message,
            "intent": plan["intent"],
            "clarifying_questions": plan["clarifying_questions"],
            "tool_calls": [],
            "results": _empty_results(),
            "limitations": [],
            "debug": {"plan": plan},
        }

    if not plan.get("tool_calls"):
        assistant_message = plan.get("assistant_message") or "I need a more specific data question before I can search the safe tools."
        return {
            "type": "clarification",
            "message": assistant_message,
            "assistant_message": assistant_message,
            "intent": plan["intent"],
            "clarifying_questions": plan.get("clarifying_questions") or [
                {"question": "What metric, geography, or source type should I search for?", "options": []}
            ],
            "tool_calls": [],
            "results": _empty_results(),
            "limitations": ["no_tool_call_selected"],
            "debug": {"plan": plan},
        }

    executed = _execute_tool_calls(plan.get("tool_calls") or [], tool_caller)
    failed = next((item for item in executed if item["status"] != "ok"), None)
    if failed:
        return _error_response(message, plan, failed["result"], tool_calls=executed)

    results, limitations, response_type = _normalize_tool_results(executed)
    try:
        assistant_message = llm.synthesize(
            message=message,
            history=history,
            plan=plan,
            tool_results=[item["result"] for item in executed],
            normalized_results=results,
            limitations=limitations,
        )
    except (DemoLLMResponseError, DemoLLMProviderError) as exc:
        return _llm_error_response("llm_provider_error", str(exc))

    return {
        "type": response_type,
        "message": assistant_message,
        "assistant_message": assistant_message,
        "intent": plan["intent"],
        "clarifying_questions": plan.get("clarifying_questions") or [],
        "tool_calls": [{"name": item["name"], "args": item["args"], "status": item["status"]} for item in executed],
        "results": results,
        "limitations": limitations,
        "debug": {"plan": plan},
    }


def handle_chat_deterministic(payload: dict[str, Any], tool_caller=call_demo_tool) -> dict[str, Any]:
    message = (payload.get("message") or "").strip()
    context = payload.get("context") or {}
    plan = plan_query(message, context)
    if plan["should_ask_clarifying_question"]:
        return {
            "type": "clarification",
            "message": "I need one or two details before searching.",
            "assistant_message": "I need one or two details before searching.",
            "intent": plan["intent"],
            "clarifying_questions": plan["clarifying_questions"],
            "tool_calls": [],
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


def _sanitize_history(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    history = []
    for item in value[-12:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            history.append({"role": role, "content": content.strip()[:2000]})
    return history


def _validate_plan(plan: dict[str, Any], message: str) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise DemoLLMResponseError("Planner output must be a JSON object.")
    intent = plan.get("intent") if isinstance(plan.get("intent"), str) else "unknown"
    questions = plan.get("clarifying_questions") if isinstance(plan.get("clarifying_questions"), list) else []
    tool_calls = plan.get("tool_calls") if isinstance(plan.get("tool_calls"), list) else []
    filters = plan.get("filters") if isinstance(plan.get("filters"), dict) else {}
    return {
        "intent": intent,
        "ambiguity_level": plan.get("ambiguity_level") if isinstance(plan.get("ambiguity_level"), str) else "medium",
        "assistant_message": plan.get("assistant_message") if isinstance(plan.get("assistant_message"), str) else "",
        "clarifying_questions": _sanitize_questions(questions),
        "tool_calls": _sanitize_tool_calls(tool_calls, message, filters),
        "filters": filters,
    }


def _sanitize_questions(questions: list[Any]) -> list[dict[str, Any]]:
    cleaned = []
    for item in questions[:3]:
        if not isinstance(item, dict) or not isinstance(item.get("question"), str):
            continue
        options = item.get("options") if isinstance(item.get("options"), list) else []
        cleaned.append({"question": item["question"].strip(), "options": [str(option) for option in options[:6]]})
    return cleaned


def _sanitize_tool_calls(tool_calls: list[Any], message: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
    cleaned = []
    for item in tool_calls[:3]:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        if "query" not in args and item["name"] in {"find_data", "semantic_search", "compare_concepts_auto"}:
            args = {**args, "query": message}
        if item["name"] == "find_data":
            args = {
                "query": str(args.get("query") or message),
                "limit": _bounded_int(args.get("limit"), 8, 1, 25),
                "public_only": bool(args.get("public_only") or filters.get("public_only", False)),
                "geography": args.get("geography") or filters.get("geography"),
                "time_range": args.get("time_range") or filters.get("time_range"),
            }
        elif item["name"] == "semantic_search":
            args = {
                "query": str(args.get("query") or message),
                "object_types": args.get("object_types") if isinstance(args.get("object_types"), list) else None,
                "limit": _bounded_int(args.get("limit"), 8, 1, 25),
            }
        elif item["name"] == "compare_concepts_auto":
            args = {
                "query": str(args.get("query") or message),
                "limit_reports": _bounded_int(args.get("limit_reports"), 5, 2, 5),
                "limit_variables": _bounded_int(args.get("limit_variables"), 20, 1, 50),
                "geography": args.get("geography") or filters.get("geography"),
                "public_only": bool(args.get("public_only") or filters.get("public_only", False)),
            }
        cleaned.append({"name": item["name"], "args": {key: value for key, value in args.items() if value is not None}})
    return cleaned


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    return min(max(value if isinstance(value, int) else default, minimum), maximum)


def _first_unsafe_tool(tool_calls: list[dict[str, Any]]) -> str | None:
    for item in tool_calls:
        name = item.get("name")
        if name not in CHAT_TOOL_NAMES:
            return str(name)
    return None


def _execute_tool_calls(tool_calls: list[dict[str, Any]], tool_caller) -> list[dict[str, Any]]:
    executed = []
    for item in tool_calls:
        result = tool_caller(item["name"], item.get("args") or {})
        executed.append(
            {
                "name": item["name"],
                "args": item.get("args") or {},
                "status": "ok" if result.get("ok") else "error",
                "result": result,
            }
        )
    return executed


def _normalize_tool_results(executed: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str], str]:
    results = _empty_results()
    limitations: list[str] = []
    for item in executed:
        data = item["result"].get("data") or {}
        name = item["name"]
        if name == "find_data":
            results["closest_variables"].extend(data.get("closest_variables") or [])
            results["relevant_reports"].extend(data.get("relevant_reports") or [])
            results["relevant_organizations"].extend(data.get("relevant_organizations") or [])
            results["source_links"].extend(data.get("source_links") or [])
            limitations.extend(_limitations_from_data(data, _result_count(results)))
        elif name == "semantic_search":
            rows = data.get("results") or []
            if any(row.get("object_type") == "organization" for row in rows):
                results["relevant_organizations"].extend(_format_organization(row) for row in rows)
            else:
                results["source_links"].extend(_source_links_from_rows(rows))
            if not rows:
                limitations.append("No search_index rows matched the query.")
        elif name == "compare_concepts_auto":
            results["closest_variables"].extend(data.get("closest_variables") or [])
            results["relevant_reports"].extend(data.get("selected_reports") or [])
            results["comparison"] = data.get("comparison") or {}
            limitations.extend(data.get("limitations") or [])
        elif name.startswith("get_"):
            results["source_links"].append({"title": data.get("title") or data.get("name"), "source_url": data.get("source_url") or data.get("website_url")})
    count = _result_count(results)
    if results["comparison"]:
        return results, _dedupe_strings(limitations), "answer"
    return results, _dedupe_strings(limitations), "answer" if count else "no_results"


def _result_count(results: dict[str, Any]) -> int:
    return (
        len(results.get("closest_variables") or [])
        + len(results.get("relevant_reports") or [])
        + len(results.get("relevant_organizations") or [])
        + len(results.get("source_links") or [])
    )


def _dedupe_strings(items: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


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
        "assistant_message": message_text,
        "intent": plan["intent"],
        "clarifying_questions": _questions_from_data(data),
        "tool_calls": [{"name": "find_data", "args": {}, "status": "ok"}],
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
        "assistant_message": data.get("comparison", {}).get("summary") or "Comparison results are available.",
        "intent": "compare_concepts",
        "clarifying_questions": [{"question": q, "options": []} for q in data.get("clarifying_questions", [])],
        "tool_calls": [{"name": "compare_concepts_auto", "args": {}, "status": "ok"}],
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
        "assistant_message": f"Found {len(organizations)} organization matches." if organizations else "I could not find matching organizations yet.",
        "intent": "find_organizations",
        "clarifying_questions": [],
        "tool_calls": [{"name": "semantic_search", "args": {"object_types": ["organization"]}, "status": "ok"}],
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


def _error_response(
    message: str,
    plan: dict[str, Any],
    tool_result: dict[str, Any],
    *,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    error = tool_result.get("error") or {}
    message_text = error.get("message") or "The request could not be completed."
    return {
        "type": "error",
        "message": message_text,
        "assistant_message": message_text,
        "intent": plan.get("intent", "unknown"),
        "clarifying_questions": [],
        "tool_calls": [
            {"name": item["name"], "args": item["args"], "status": item["status"]}
            for item in (tool_calls or [])
        ],
        "results": _empty_results(),
        "limitations": [error.get("code", "unknown_error")],
        "debug": {"plan": plan, "tool_error": error},
    }


def _llm_error_response(code: str, message: str) -> dict[str, Any]:
    return {
        "type": "error",
        "message": message,
        "assistant_message": message,
        "intent": "unknown",
        "clarifying_questions": [],
        "tool_calls": [],
        "results": _empty_results(),
        "limitations": [code],
        "debug": {"error": {"code": code, "message": message}},
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
