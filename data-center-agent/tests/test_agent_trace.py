from typing import Any

from web.backend.routes.chat import handle_chat
from web.backend.services.agent_trace import AgentTraceCollector, sanitize_trace_detail


class FakeLLM:
    def __init__(self, plan):
        self._plan = plan

    def plan(self, **kwargs):
        return self._plan

    def synthesize(self, **kwargs):
        return "Grounded answer from tool results."

    def qualify_evidence(self, **kwargs):
        return {
            "evidence_items": [],
            "answer_support_level": "strong",
            "missing_dimensions": [],
            "safe_answer_strategy": "direct_answer",
        }

    def synthesize_structured(self, **kwargs):
        return {
            "answer_evidence_level": "synced_connector",
            "support_level": "strong",
            "direct_answer": "Grounded answer from structured evidence.",
            "main_claims": [],
            "what_evidence_measures": [],
            "what_is_not_supported": [],
            "evidence_used": [],
            "evidence_excluded": [],
            "methodology_caveats": [],
            "missing_data": [],
            "recommended_next_actions": [],
            "final_answer_markdown": "Grounded answer from structured evidence.",
        }

    def synthesize_no_results(self, **kwargs):
        return {"assistant_message": "No matches yet.", "follow_up_queries": []}


def test_chat_response_includes_tool_trace() -> None:
    def fake_tool(name, args):
        return {
            "ok": True,
            "data": {
                "closest_variables": [{"title": "VC deal count"}],
                "relevant_reports": [],
                "relevant_organizations": [],
                "source_links": [],
                "suggested_clarifications": [],
            },
        }

    llm = FakeLLM(
        {
            "intent": "find_data",
            "clarifying_questions": [],
            "tool_calls": [{"name": "find_data", "args": {"query": "VC deal count"}}],
            "filters": {},
        }
    )
    result = handle_chat({"message": "VC deal count"}, tool_caller=fake_tool, llm_client=llm)

    assert "tool_trace" in result
    assert len(result["tool_trace"]) >= 4
    assert any(event["type"] == "planning" for event in result["tool_trace"])
    assert any(event["type"] == "answer_generation" for event in result["tool_trace"])


def test_find_data_trace_includes_tool_start_and_complete() -> None:
    def fake_tool(name, args):
        return {
            "ok": True,
            "data": {
                "closest_variables": [{"title": "A"}, {"title": "B"}],
                "relevant_reports": [{"title": "Report"}],
                "relevant_organizations": [],
                "source_links": [{"title": "Source"}],
                "suggested_clarifications": [],
            },
        }

    llm = FakeLLM(
        {
            "intent": "find_data",
            "clarifying_questions": [],
            "tool_calls": [{"name": "find_data", "args": {"query": "startup funding"}}],
            "filters": {},
        }
    )
    result = handle_chat({"message": "startup funding"}, tool_caller=fake_tool, llm_client=llm)
    types = [event["type"] for event in result["tool_trace"]]
    assert "tool_start" in types
    assert "tool_complete" in types
    complete = next(event for event in result["tool_trace"] if event["type"] == "tool_complete")
    assert complete["metadata"]["variable_count"] == 2
    assert complete["metadata"]["report_count"] == 1
    assert complete["metadata"]["source_count"] == 1


def test_compare_concepts_auto_trace_includes_selected_reports() -> None:
    def fake_tool(name, args):
        return {
            "ok": True,
            "data": {
                "status": "ok",
                "comparison": {"summary": "Compared reports"},
                "selected_reports": [{"title": "Annual VC Report"}, {"title": "Innovation Outlook"}],
                "closest_variables": [{"title": "Funding amount"}],
                "limitations": [],
                "clarifying_questions": [],
                "metadata": {"tool_chain": ["semantic_search", "find_data"]},
            },
        }

    llm = FakeLLM(
        {
            "intent": "compare_concepts",
            "clarifying_questions": [],
            "tool_calls": [{"name": "compare_concepts_auto", "args": {"query": "Compare funding definitions"}}],
            "filters": {},
        }
    )
    result = handle_chat({"message": "Compare funding definitions"}, tool_caller=fake_tool, llm_client=llm)
    labels = " ".join(event["label"] for event in result["tool_trace"])
    assert "Reports selected for comparison" in labels
    assert any(event.get("tool_name") == "semantic_search" for event in result["tool_trace"])


def test_error_trace_does_not_expose_stack_trace() -> None:
    def fake_tool(name, args):
        return {
            "ok": False,
            "tool": name,
            "error": {
                "code": "invalid_args",
                "message": 'Bad query\nTraceback (most recent call last):\n  File "/secret/path.py", line 1',
            },
        }

    llm = FakeLLM(
        {
            "intent": "find_data",
            "clarifying_questions": [],
            "tool_calls": [{"name": "find_data", "args": {"query": "VC deal count"}}],
            "filters": {},
        }
    )
    result = handle_chat({"message": "VC deal count"}, tool_caller=fake_tool, llm_client=llm)
    trace_text = " ".join(f"{event.get('label', '')} {event.get('detail', '')}" for event in result["tool_trace"])
    assert "Traceback" not in trace_text
    assert "/secret/path.py" not in trace_text
    assert result["message"] == "Bad query"


def test_trace_collector_emits_live_updates() -> None:
    snapshots: list[list[dict[str, Any]]] = []

    def on_update(events: list[dict[str, Any]]) -> None:
        snapshots.append(list(events))

    trace = AgentTraceCollector(on_update=on_update)
    trace.planning_started()
    trace.planning_complete("find_data", ["find_data"])
    trace.tool_start("find_data")
    trace.tool_complete("find_data", {"closest_variables": [{"title": "A"}], "relevant_reports": [], "relevant_organizations": [], "source_links": []})

    assert len(snapshots) >= 4
    assert snapshots[0][0]["label"] == "Planning query"
    assert snapshots[-1][-1]["type"] == "tool_complete"
    assert snapshots[-1][-1]["status"] == "completed"


def test_sanitize_trace_detail_strips_stack_trace() -> None:
    cleaned = sanitize_trace_detail("Failed\nTraceback (most recent call last):\n  File \"/tmp/x.py\", line 9")
    assert cleaned == "Failed"
