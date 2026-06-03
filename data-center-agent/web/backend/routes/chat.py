from __future__ import annotations

import json
import queue
import threading
import uuid
from typing import Any, Iterator

try:
    from fastapi import APIRouter, Request
    from fastapi.responses import StreamingResponse
except ImportError:  # pragma: no cover
    APIRouter = None
    Request = None
    StreamingResponse = None
from pydantic import BaseModel, Field

from app.agents.demo_llm import DemoLLMClient, DemoLLMConfigError, DemoLLMProviderError, DemoLLMResponseError
from app.agents.query_planner import plan_query
from app.db.connection import get_engine
from app.db.repositories.history import ChatHistoryRepository
from app.services.research_task import execute_research_task
from app.services.auth import SESSION_COOKIE_NAME
from web.backend.routes.auth import user_from_session_token
from web.backend.services.agent_trace import AgentTraceCollector, attach_tool_trace, sanitize_trace_detail
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


class ResearchTaskRequest(BaseModel):
    query: str
    project_id: str | None = None
    format: str = "json"
    output_dir: str = "exports/research_tasks"
    dry_run: bool = False
    max_results: int = 30
    context: dict[str, Any] = Field(default_factory=dict)


CHAT_TOOL_NAMES = SAFE_WEB_TOOLS - {"submit_feedback"}


def _planning_message_for_focus(message: str, context: dict[str, Any]) -> str:
    """Augment the planner prompt only; user-visible message stays unchanged."""
    augmented = message
    focus = str((context.get("search_focus") or "")).strip().lower()
    hints = {
        "variables": "\n\n(System hint: Prioritize structured data variables and definitions.)",
        "reports": "\n\n(System hint: Prioritize published reports and policy documents.)",
        "organizations": "\n\n(System hint: Prioritize organizations, programs, and directories.)",
        "sources": "\n\n(System hint: Prioritize primary sources and data links.)",
        "compare": "\n\n(System hint: Compare definitions and assess comparability between concepts.)",
    }
    if focus in hints:
        augmented += hints[focus]
    project_title = str(context.get("project_title") or "").strip()
    research_question = str(context.get("research_question") or "").strip()
    if project_title or research_question:
        bits = []
        if project_title:
            bits.append(f"Project: {project_title}")
        if research_question:
            bits.append(f"Research question: {research_question}")
        augmented += (
            f"\n\n(System hint: Research project context — {'; '.join(bits)}. "
            "Keep clarifying_questions options and follow_up_queries labels short; "
            "do not prefix them with project metadata.)"
        )
    return augmented


def handle_chat(
    payload: dict[str, Any],
    tool_caller=call_demo_tool,
    llm_client: Any | None = None,
    trace: AgentTraceCollector | None = None,
) -> dict[str, Any]:
    message = (payload.get("message") or "").strip()
    context = payload.get("context") or {}
    history = _sanitize_history(payload.get("history") or [])
    plan_message = _planning_message_for_focus(message, context)
    trace = trace or AgentTraceCollector()
    trace.planning_started()
    deterministic_plan = plan_query(message, context)
    if deterministic_plan["action"] == "ask_clarification":
        try:
            llm = llm_client or DemoLLMClient()
            llm_plan = _validate_plan(llm.plan(message=plan_message, history=history, safe_tools=CHAT_TOOL_NAMES), message)
            plan = _merge_planner_metadata(llm_plan, deterministic_plan)
        except (DemoLLMConfigError, DemoLLMResponseError, DemoLLMProviderError) as exc:
            trace.warning("Clarification planning fallback", str(exc))
            plan = deterministic_plan
        plan["tool_calls"] = []
        plan["clarifying_questions"] = plan.get("clarifying_questions") or deterministic_plan.get("clarifying_questions") or []
        trace.planning_complete(plan["intent"], [])
        return attach_tool_trace(_clarification_response(plan), trace)
    try:
        llm = llm_client or DemoLLMClient()
        plan = _validate_plan(llm.plan(message=plan_message, history=history, safe_tools=CHAT_TOOL_NAMES), message)
    except DemoLLMConfigError as exc:
        trace.error_event("Planning failed", str(exc))
        return attach_tool_trace(_llm_error_response("llm_not_configured", str(exc)), trace)
    except DemoLLMResponseError as exc:
        trace.error_event("Planning failed", str(exc))
        return attach_tool_trace(_llm_error_response("llm_invalid_response", str(exc)), trace)
    except DemoLLMProviderError as exc:
        trace.error_event("Planning failed", str(exc))
        return attach_tool_trace(_llm_error_response("llm_provider_error", str(exc)), trace)

    plan = _merge_planner_metadata(plan, deterministic_plan)
    tool_names = [str(item.get("name")) for item in plan.get("tool_calls") or [] if item.get("name")]
    trace.planning_complete(plan["intent"], tool_names)

    unsafe_tool = _first_unsafe_tool(plan.get("tool_calls") or [])
    if unsafe_tool:
        trace.error_event("Tool not allowed", f"Tool is not exposed to the website: {unsafe_tool}")
        return attach_tool_trace(_llm_error_response("tool_not_allowed", f"Tool is not exposed to the website: {unsafe_tool}"), trace)

    if plan.get("clarifying_questions") and not plan.get("tool_calls"):
        assistant_message = plan.get("assistant_message") or "I need one or two details before searching."
        return attach_tool_trace(
            {
                "type": "clarification",
                "message": assistant_message,
                "assistant_message": assistant_message,
                "intent": plan["intent"],
                "clarifying_questions": plan["clarifying_questions"],
                "clarification_ui": plan.get("clarification_ui") or {},
                "refinement_chips": [],
                "tool_calls": [],
                "results": _empty_results(),
                "limitations": [],
                "debug": {"plan": plan},
            },
            trace,
        )

    if not plan.get("tool_calls"):
        assistant_message = plan.get("assistant_message") or "I need a more specific data question before I can search the safe tools."
        return attach_tool_trace(
            {
                "type": "clarification",
                "message": assistant_message,
                "assistant_message": assistant_message,
                "intent": plan["intent"],
                "clarifying_questions": plan.get("clarifying_questions") or [
                    {"question": "What metric, geography, or source type should I search for?", "options": []}
                ],
                "clarification_ui": plan.get("clarification_ui") or {},
                "refinement_chips": [],
                "tool_calls": [],
                "results": _empty_results(),
                "limitations": ["no_tool_call_selected"],
                "debug": {"plan": plan},
            },
            trace,
        )

    executed = _execute_tool_calls(plan.get("tool_calls") or [], tool_caller, trace=trace)
    failed = next((item for item in executed if item["status"] != "ok"), None)
    if failed:
        return attach_tool_trace(_error_response(message, plan, failed["result"], tool_calls=executed), trace)

    results, limitations, response_type = _normalize_tool_results(executed)
    if _should_expand_with_find_data(message, plan, results, executed):
        trace.fallback(
            "Expanded beyond local comparison",
            "Local comparison returned no evidence, so the search was expanded through live data and research connectors.",
        )
        expansion_call = {
            "name": "find_data",
            "args": _find_data_expansion_args(message, plan),
        }
        expansion = _execute_tool_calls([expansion_call], tool_caller, trace=trace)
        expansion_failed = next((item for item in expansion if item["status"] != "ok"), None)
        if expansion_failed:
            error = expansion_failed.get("result", {}).get("error", {})
            trace.warning("Expansion search failed", str(error.get("message") or "find_data expansion failed"))
        else:
            executed.extend(expansion)
            results, limitations, response_type = _normalize_tool_results(executed)
    trace.rank_results(_aggregate_counts(results))
    for item in limitations:
        trace.warning("Search limitation", item)

    follow_up_queries: list[dict[str, str]] = []
    trace.answer_generation_started()
    try:
        if response_type == "no_results":
            synth = llm.synthesize_no_results(
                message=message,
                history=history,
                plan=plan,
                tool_results=[item["result"] for item in executed],
                normalized_results=results,
                limitations=limitations,
            )
            assistant_message = (
                synth.get("assistant_message") if isinstance(synth.get("assistant_message"), str) else ""
            ).strip() or "I could not find strong matches yet. Try one of the suggested follow-up searches."
            follow_up_queries = _sanitize_follow_up_queries(synth.get("follow_up_queries"), message)
        else:
            assistant_message = llm.synthesize(
                message=message,
                history=history,
                plan=plan,
                tool_results=[item["result"] for item in executed],
                normalized_results=results,
                limitations=limitations,
            )
    except (DemoLLMResponseError, DemoLLMProviderError) as exc:
        trace.error_event("Answer generation failed", str(exc))
        return attach_tool_trace(_llm_error_response("llm_provider_error", str(exc)), trace)

    trace.answer_generation_complete()
    clarifying_questions = _merge_clarifying_questions(plan.get("clarifying_questions") or [], executed, message)

    return attach_tool_trace(
        {
            "type": response_type,
            "message": assistant_message,
            "assistant_message": assistant_message,
            "intent": plan["intent"],
            "clarifying_questions": clarifying_questions,
            "clarification_ui": plan.get("clarification_ui") or {},
            "refinement_chips": plan.get("refinement_chips") or [],
            "follow_up_queries": follow_up_queries,
            "tool_calls": [{"name": item["name"], "args": item["args"], "status": item["status"]} for item in executed],
            "results": results,
            "limitations": limitations,
            "debug": {"plan": plan},
        },
        trace,
    )


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
            "clarification_ui": plan.get("clarification_ui") or {},
            "refinement_chips": [],
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
        "clarification_ui": _sanitize_clarification_ui(plan.get("clarification_ui")),
        "tool_calls": _sanitize_tool_calls(tool_calls, message, filters),
        "filters": filters,
    }


def _clarification_response(plan: dict[str, Any]) -> dict[str, Any]:
    ui = plan.get("clarification_ui") if isinstance(plan.get("clarification_ui"), dict) else {}
    main_question = ui.get("main_question") if isinstance(ui.get("main_question"), str) else ""
    assistant_message = main_question or ("Before I search, I need one detail." if len(plan.get("clarifying_questions") or []) == 1 else "Before I search, I need a couple of details.")
    return {
        "type": "clarification",
        "message": assistant_message,
        "assistant_message": assistant_message,
        "intent": plan["intent"],
        "clarifying_questions": _sanitize_questions(plan.get("clarifying_questions") or []),
        "clarification_ui": ui,
        "refinement_chips": [],
        "tool_calls": [],
        "results": _empty_results(),
        "limitations": [],
        "debug": {"plan": plan},
    }


def _should_preempt_with_clarification(message: str, plan: dict[str, Any]) -> bool:
    lowered = " ".join(message.lower().split())
    if lowered in {
        "startup data",
        "innovation ecosystem",
        "funding trends",
        "make me a dataset",
        "make me a data set",
        "analyze singapore startups",
    }:
        return True
    if lowered.startswith(("make me a dataset", "create a dataset", "make me an excel", "create an excel")):
        return True
    return bool("domain_topic" in (plan.get("missing_dimensions") or []) and len(plan.get("clarifying_questions") or []) >= 1)


def _merge_planner_metadata(llm_plan: dict[str, Any], planner: dict[str, Any]) -> dict[str, Any]:
    merged = {**llm_plan}
    merged["specificity"] = planner.get("specificity")
    merged["action"] = planner.get("action")
    merged["detected"] = planner.get("detected") or {}
    merged["missing_dimensions"] = planner.get("missing_dimensions") or []
    merged["inferred_query"] = planner.get("inferred_query") or ""
    merged["clarification_ui"] = merged.get("clarification_ui") or planner.get("clarification_ui") or {}
    merged["should_run_tool"] = planner.get("should_run_tool")
    refinement_questions = planner.get("refinement_chips") or []
    if merged.get("intent") == "unknown":
        refinement_questions = []
    if refinement_questions:
        merged["refinement_chips"] = _sanitize_questions(refinement_questions)
        merged["clarifying_questions"] = _merge_question_lists(
            merged.get("clarifying_questions") or [],
            refinement_questions,
        )
    if not merged.get("tool_calls") and merged.get("intent") != "unknown" and planner.get("should_run_tool") and planner.get("tool_calls"):
        merged["tool_calls"] = planner["tool_calls"]
    filters = merged.get("filters") if isinstance(merged.get("filters"), dict) else {}
    merged["filters"] = {**(planner.get("extracted_filters") or {}), **filters}
    merged["tool_calls"] = _sanitize_tool_calls(merged.get("tool_calls") or [], planner.get("query") or "", merged["filters"])
    return merged


def _merge_question_lists(primary: list[Any], secondary: list[Any]) -> list[dict[str, Any]]:
    merged = _sanitize_questions(primary)
    seen = {(item.get("question") or "").lower() for item in merged}
    for item in _sanitize_questions(secondary):
        key = item["question"].lower()
        if key in seen:
            continue
        merged.append(item)
        seen.add(key)
    return merged[:5]


def _sanitize_questions(questions: list[Any]) -> list[dict[str, Any]]:
    cleaned = []
    for item in questions[:5]:
        if not isinstance(item, dict) or not isinstance(item.get("question"), str):
            continue
        options = item.get("options") if isinstance(item.get("options"), list) else []
        cleaned_item = {"question": item["question"].strip(), "options": [str(option) for option in options[:7]]}
        if isinstance(item.get("dimension"), str):
            cleaned_item["dimension"] = item["dimension"].strip()
        cleaned.append(cleaned_item)
    return cleaned


def _sanitize_clarification_ui(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    if isinstance(value.get("main_question"), str):
        out["main_question"] = value["main_question"].strip()

    choices = []
    for item in value.get("choice_options") if isinstance(value.get("choice_options"), list) else []:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        option_value = item.get("value")
        if isinstance(label, str) and isinstance(option_value, str) and label.strip() and option_value.strip():
            choices.append({"label": _short_label(label), "value": option_value.strip()})
    out["choice_options"] = choices[:8]

    fields = []
    allowed_types = {"text", "text_or_chips", "single_select"}
    for item in value.get("optional_fields") if isinstance(value.get("optional_fields"), list) else []:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        label = item.get("label")
        field_type = item.get("type")
        if not (isinstance(name, str) and isinstance(label, str) and field_type in allowed_types):
            continue
        field: dict[str, Any] = {"name": name.strip(), "label": label.strip(), "type": field_type}
        if isinstance(item.get("placeholder"), str):
            field["placeholder"] = item["placeholder"].strip()
        if isinstance(item.get("options"), list):
            field["options"] = [str(option).strip() for option in item["options"][:8] if str(option).strip()]
        fields.append(field)
    out["optional_fields"] = fields[:6]

    searches = []
    for item in value.get("suggested_searches") if isinstance(value.get("suggested_searches"), list) else []:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        query_append = item.get("query_append")
        if isinstance(label, str) and isinstance(query_append, str) and label.strip() and query_append.strip():
            searches.append({"label": _short_label(label), "query_append": query_append.strip()})
    out["suggested_searches"] = searches[:4]

    defaults = value.get("defaults")
    if isinstance(defaults, dict):
        clean_defaults: dict[str, Any] = {}
        if isinstance(defaults.get("label"), str):
            clean_defaults["label"] = _short_label(defaults["label"])
        if isinstance(defaults.get("choice"), str):
            clean_defaults["choice"] = defaults["choice"].strip()
        if isinstance(defaults.get("fields"), dict):
            clean_defaults["fields"] = {str(k): str(v) for k, v in defaults["fields"].items() if v is not None}
        out["defaults"] = clean_defaults
    return out


def _short_label(value: str) -> str:
    cleaned = " ".join(value.split())
    for sep in (" — ", " - "):
        if sep in cleaned:
            cleaned = cleaned.split(sep)[-1]
    return cleaned[:64]


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


def _execute_tool_calls(
    tool_calls: list[dict[str, Any]],
    tool_caller,
    *,
    trace: AgentTraceCollector | None = None,
) -> list[dict[str, Any]]:
    executed = []
    for item in tool_calls:
        name = item["name"]
        if trace:
            trace.tool_start(name)
        result = tool_caller(name, item.get("args") or {})
        status = "ok" if result.get("ok") else "error"
        if trace:
            if result.get("ok"):
                trace.tool_complete(name, result.get("data") or {})
            else:
                error = result.get("error") or {}
                trace.tool_failed(name, str(error.get("message") or "The request could not be completed."))
        executed.append(
            {
                "name": name,
                "args": item.get("args") or {},
                "status": status,
                "result": result,
            }
        )
    return executed


def _aggregate_counts(results: dict[str, Any]) -> dict[str, int]:
    return {
        "variable_count": len(results.get("closest_variables") or []),
        "report_count": len(results.get("relevant_reports") or []),
        "source_count": len(results.get("source_links") or []),
        "organization_count": len(results.get("relevant_organizations") or []),
    }


def _should_expand_with_find_data(
    message: str,
    plan: dict[str, Any],
    results: dict[str, Any],
    executed: list[dict[str, Any]],
) -> bool:
    if any(item.get("name") == "find_data" for item in executed):
        return False
    if _result_count(results) > 0:
        return False
    tool_names = {str(item.get("name")) for item in executed}
    if not (tool_names & {"compare_concepts_auto", "semantic_search"}):
        return False
    text = f"{message} {plan.get('intent') or ''}".lower()
    external_research_terms = (
        "research",
        "publication",
        "paper",
        "journal",
        "academic",
        "university",
        "stanford",
        "mit",
        "berkeley",
        "cmu",
        "harvard",
        "princeton",
        "patent",
        "doi",
    )
    return any(term in text for term in external_research_terms)


def _find_data_expansion_args(message: str, plan: dict[str, Any]) -> dict[str, Any]:
    filters = plan.get("filters") if isinstance(plan.get("filters"), dict) else {}
    args = {
        "query": message,
        "limit": 8,
        "public_only": bool(filters.get("public_only", False)),
        "geography": filters.get("geography"),
        "time_range": filters.get("time_range"),
    }
    return {key: value for key, value in args.items() if value is not None}


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
            results["connector_datasets"].extend(data.get("connector_datasets") or [])
            results["connector_metrics"].extend(data.get("connector_metrics") or [])
            results["connector_candidates"].extend(data.get("connector_candidates") or [])
            results["tavily_candidates"] = data.get("tavily_candidates")
            results["live_api_results"] = {
                key: value
                for key, value in data.items()
                if key.startswith("live_api_results") and isinstance(value, dict)
            }
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
        + len(results.get("connector_datasets") or [])
        + len(results.get("connector_metrics") or [])
        + len(results.get("connector_candidates") or [])
        + len((results.get("tavily_candidates") or {}).get("results") or [])
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
        "clarifying_questions": _questions_from_data(data, message),
        "clarification_ui": plan.get("clarification_ui") or {},
        "refinement_chips": plan.get("refinement_chips") or [],
        "follow_up_queries": [],
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
        "clarification_ui": plan.get("clarification_ui") or {},
        "refinement_chips": [],
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
        "clarification_ui": plan.get("clarification_ui") or {},
        "refinement_chips": [],
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


def _questions_from_data(data: dict[str, Any], base_query: str = "") -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for item in data.get("suggested_clarifications", []) or []:
        if not isinstance(item, dict):
            continue
        question = item.get("question")
        if not isinstance(question, str) or not question.strip():
            continue
        text = question.strip()
        query = text if not base_query or text.lower().startswith(base_query.lower()[:20]) else f"{base_query} — {text}"
        cleaned.append({"question": text, "options": [query]})
    return cleaned[:4]


def _merge_clarifying_questions(
    plan_questions: list[dict[str, Any]],
    executed: list[dict[str, Any]],
    message: str,
) -> list[dict[str, Any]]:
    merged = _sanitize_questions(plan_questions)
    seen = {item["question"] for item in merged}
    for item in executed:
        data = (item.get("result") or {}).get("data") or {}
        for question in _questions_from_data(data, message):
            if question["question"] in seen:
                continue
            merged.append(question)
            seen.add(question["question"])
            if len(merged) >= 5:
                return merged
    return merged


def _sanitize_follow_up_queries(value: Any, message: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value[:4]:
        if not isinstance(item, dict):
            continue
        label = item.get("label") if isinstance(item.get("label"), str) else ""
        query = item.get("query") if isinstance(item.get("query"), str) else ""
        label = label.strip()
        query = query.strip()
        if not query:
            continue
        if not label:
            label = query if len(query) <= 48 else f"{query[:45]}…"
        key = query.lower()
        if key in seen or key == message.strip().lower():
            continue
        seen.add(key)
        cleaned.append({"label": label, "query": query})
    return cleaned


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
    message_text = sanitize_trace_detail(str(error.get("message") or "The request could not be completed."))
    return {
        "type": "error",
        "message": message_text,
        "assistant_message": message_text,
        "intent": plan.get("intent", "unknown"),
        "clarifying_questions": [],
        "clarification_ui": plan.get("clarification_ui") or {},
        "refinement_chips": [],
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
        "clarification_ui": {},
        "refinement_chips": [],
        "tool_calls": [],
        "results": _empty_results(),
        "limitations": [code],
        "debug": {"error": {"code": code, "message": message}},
    }


def _empty_results() -> dict[str, Any]:
    return {
        "closest_variables": [],
        "relevant_reports": [],
        "relevant_organizations": [],
        "source_links": [],
        "connector_datasets": [],
        "connector_metrics": [],
        "connector_candidates": [],
        "tavily_candidates": None,
        "live_api_results": {},
        "comparison": {},
    }


def _auth_required_response() -> dict[str, Any]:
    return {
        "type": "error",
        "message": "Login is required to use data discovery.",
        "assistant_message": "Login is required to use data discovery.",
        "intent": "unknown",
        "clarifying_questions": [],
        "clarification_ui": {},
        "refinement_chips": [],
        "tool_calls": [],
        "results": _empty_results(),
        "limitations": ["auth_required"],
        "tool_trace": [],
        "debug": {"error": {"code": "auth_required"}},
    }


def iter_chat_stream(user_id: str, payload: ChatRequest) -> Iterator[str]:
    event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
    holder: dict[str, Any] = {}

    def on_trace_update(events: list[dict[str, Any]]) -> None:
        event_queue.put(("trace", events))

    def worker() -> None:
        try:
            trace = AgentTraceCollector(on_update=on_trace_update)
            response = handle_chat(payload.model_dump(), trace=trace)
            holder["response"] = _finalize_chat_response(user_id, payload, response)
        except Exception as exc:  # pragma: no cover
            holder["error"] = str(exc)
        finally:
            event_queue.put(("done", None))

    threading.Thread(target=worker, daemon=True).start()

    while True:
        kind, data = event_queue.get()
        if kind == "trace":
            yield json.dumps({"type": "trace", "tool_trace": data}, ensure_ascii=True) + "\n"
            continue
        if kind == "done":
            if holder.get("error"):
                yield json.dumps({"type": "error", "message": sanitize_trace_detail(str(holder["error"]))}, ensure_ascii=True) + "\n"
            else:
                yield json.dumps({"type": "complete", "response": holder["response"]}, ensure_ascii=True, default=str) + "\n"
            break


if router:
    @router.post("/api/chat")
    def chat(request: Request, payload: ChatRequest) -> dict[str, Any]:
        user = user_from_session_token(request.cookies.get(SESSION_COOKIE_NAME))
        if not user:
            return _auth_required_response()
        response = handle_chat(payload.model_dump())
        return _finalize_chat_response(user["id"], payload, response)

    @router.post("/api/chat/stream")
    def chat_stream(request: Request, payload: ChatRequest):
        user = user_from_session_token(request.cookies.get(SESSION_COOKIE_NAME))
        if not user:
            return _auth_required_response()
        return StreamingResponse(
            iter_chat_stream(user["id"], payload),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

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

    @router.post("/api/research-task")
    def research_task(request: Request, payload: ResearchTaskRequest) -> dict[str, Any]:
        user = user_from_session_token(request.cookies.get(SESSION_COOKIE_NAME))
        if not user:
            return _auth_required_response()
        context = dict(payload.context or {})
        if payload.project_id:
            context["project_id"] = payload.project_id
        try:
            return execute_research_task(
                payload.query,
                tool_caller=call_demo_tool,
                context=context,
                output_dir=payload.output_dir,
                output_format=payload.format,
                dry_run=payload.dry_run,
                max_results=payload.max_results,
            )
        except ValueError as exc:
            return {"ok": False, "error": {"code": "invalid_args", "message": str(exc)}}


def _finalize_chat_response(user_id: str, payload: ChatRequest, response: dict[str, Any]) -> dict[str, Any]:
    context = payload.context or {}
    if context.get("project_id"):
        response["conversation_id"] = payload.conversation_id or str(uuid.uuid4())
        return response
    _save_chat_history(user_id, payload, response)
    return response


def _save_chat_history(user_id: str, payload: ChatRequest, response: dict[str, Any]) -> None:
    query = payload.message.strip()
    if not query:
        return
    title = _history_title(query)
    with get_engine().begin() as connection:
        repo = ChatHistoryRepository(connection)
        session = None
        if payload.conversation_id:
            session = repo.get_session_for_user(payload.conversation_id, user_id)
        if not session:
            session = repo.create_session(user_id, title)
        session_id = str(session["id"])
        repo.add_message(session_id=session_id, role="user", content=query)
        repo.add_message(session_id=session_id, role="assistant", content=response.get("assistant_message") or response.get("message"))
        repo.add_message(
            session_id=session_id,
            role="tool",
            content=None,
            tool_name="demo_tool_chain",
            tool_payload={
                "tool_calls": response.get("tool_calls") or [],
                "results": response.get("results") or {},
                "limitations": response.get("limitations") or [],
                "tool_trace": response.get("tool_trace") or [],
            },
        )
        saved = repo.add_saved_result(
            user_id=user_id,
            session_id=session_id,
            query=query,
            result_summary=response.get("assistant_message") or response.get("message") or "",
            result_payload=response,
        )
        repo.touch_session(session_id, title)
    response["conversation_id"] = session_id
    response["saved_result_id"] = str(saved["id"])


def _history_title(query: str) -> str:
    normalized = " ".join(query.split())
    return normalized[:120] if normalized else "Untitled search"
