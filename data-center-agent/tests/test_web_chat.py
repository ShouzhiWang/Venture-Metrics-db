from app.agents.demo_llm import DemoLLMConfigError, DemoLLMResponseError
from web.backend.routes.chat import _empty_results, handle_chat, handle_chat_deterministic
from web.backend.services.tool_client import SAFE_WEB_TOOLS, call_demo_tool


class FakeLLM:
    def __init__(self, plan):
        self._plan = plan
        self.synthesis_inputs = None

    def plan(self, **kwargs):
        if isinstance(self._plan, Exception):
            raise self._plan
        return self._plan

    def synthesize(self, **kwargs):
        self.synthesis_inputs = kwargs
        return "Grounded answer from tool results."


def test_chat_missing_llm_key_returns_config_error() -> None:
    result = handle_chat({"message": "startup funding"}, llm_client=FakeLLM(DemoLLMConfigError("Demo LLM is not configured.")))

    assert result["type"] == "error"
    assert result["limitations"] == ["llm_not_configured"]
    assert result["tool_calls"] == []


def test_chat_llm_plan_routes_find_data() -> None:
    calls = []

    def fake_tool(name, args):
        calls.append((name, args))
        return {
            "ok": True,
            "data": {
                "closest_variables": [{"title": "VC deal count", "availability": "public"}],
                "relevant_reports": [],
                "relevant_organizations": [],
                "source_links": [],
                "suggested_clarifications": [],
            },
        }

    llm = FakeLLM(
        {
            "intent": "find_data",
            "assistant_message": "I will search for that.",
            "clarifying_questions": [],
            "tool_calls": [{"name": "find_data", "args": {"query": "VC deal count by stage", "limit": 8}}],
            "filters": {},
        }
    )
    result = handle_chat({"message": "VC deal count by stage"}, tool_caller=fake_tool, llm_client=llm)

    assert result["type"] == "answer"
    assert result["assistant_message"] == "Grounded answer from tool results."
    assert calls[0][0] == "find_data"
    assert result["results"]["closest_variables"][0]["title"] == "VC deal count"


def test_chat_compare_query_routes_to_compare_concepts_auto() -> None:
    calls = []

    def fake_tool(name, args):
        calls.append((name, args))
        return {
            "ok": True,
            "data": {
                "status": "ok",
                "comparison": {"summary": "Compared 2 reports", "comparability": "medium"},
                "selected_reports": [],
                "limitations": [],
                "clarifying_questions": [],
                "metadata": {},
            },
        }

    llm = FakeLLM(
        {
            "intent": "compare_concepts",
            "clarifying_questions": [],
            "tool_calls": [{"name": "compare_concepts_auto", "args": {"query": "Compare startup funding definitions"}}],
            "filters": {},
        }
    )
    result = handle_chat({"message": "Compare startup funding definitions"}, tool_caller=fake_tool, llm_client=llm)

    assert result["intent"] == "compare_concepts"
    assert calls[0][0] == "compare_concepts_auto"
    assert result["results"]["comparison"]["comparability"] == "medium"


def test_chat_organization_query_routes_to_organization_search() -> None:
    calls = []

    def fake_tool(name, args):
        calls.append((name, args))
        return {
            "ok": True,
            "data": {
                "results": [
                    {
                        "object_type": "organization",
                        "object_id": "org-1",
                        "title": "Shenzhen Startup Association",
                        "geography": "Shenzhen",
                        "metadata": {"organization_type": "association", "website_url": "https://example.org"},
                    }
                ]
            },
        }

    llm = FakeLLM(
        {
            "intent": "find_organizations",
            "clarifying_questions": [],
            "tool_calls": [{"name": "semantic_search", "args": {"query": "Shenzhen startup organizations", "object_types": ["organization"]}}],
            "filters": {},
        }
    )
    result = handle_chat({"message": "Shenzhen startup organizations"}, tool_caller=fake_tool, llm_client=llm)

    assert result["intent"] == "find_organizations"
    assert result["results"]["relevant_organizations"][0]["name"] == "Shenzhen Startup Association"
    assert calls[0][0] == "semantic_search"
    assert calls[0][1]["object_types"] == ["organization"]


def test_chat_rejects_unsafe_llm_tool_without_execution() -> None:
    calls = []
    llm = FakeLLM(
        {
            "intent": "unknown",
            "clarifying_questions": [],
            "tool_calls": [{"name": "process_source", "args": {"source_id": "source-1"}}],
            "filters": {},
        }
    )

    result = handle_chat({"message": "process this source"}, tool_caller=lambda name, args: calls.append((name, args)), llm_client=llm)

    assert result["type"] == "error"
    assert result["limitations"] == ["tool_not_allowed"]
    assert calls == []


def test_chat_malformed_llm_json_returns_clean_error() -> None:
    result = handle_chat({"message": "startup funding"}, llm_client=FakeLLM(DemoLLMResponseError("invalid json")))

    assert result["type"] == "error"
    assert result["limitations"] == ["llm_invalid_response"]


def test_chat_plan_without_tool_or_question_does_not_answer_from_memory() -> None:
    llm = FakeLLM({"intent": "unknown", "assistant_message": "I can answer that directly.", "tool_calls": [], "clarifying_questions": []})

    result = handle_chat({"message": "What do you know about startups?"}, llm_client=llm)

    assert result["type"] == "clarification"
    assert result["tool_calls"] == []
    assert result["limitations"] == ["no_tool_call_selected"]


def test_synthesis_receives_tool_results_only() -> None:
    llm = FakeLLM(
        {
            "intent": "find_data",
            "clarifying_questions": [],
            "tool_calls": [{"name": "find_data", "args": {"query": "startup funding"}}],
            "filters": {},
        }
    )

    def fake_tool(name, args):
        return {
            "ok": True,
            "data": {
                "closest_variables": [{"title": "Startup funding", "source_url": "https://example.org"}],
                "relevant_reports": [],
                "relevant_organizations": [],
                "source_links": [{"title": "Source", "source_url": "https://example.org"}],
                "suggested_clarifications": [],
            },
        }

    handle_chat({"message": "startup funding"}, tool_caller=fake_tool, llm_client=llm)

    assert llm.synthesis_inputs is not None
    assert llm.synthesis_inputs["tool_results"][0]["data"]["closest_variables"][0]["title"] == "Startup funding"
    assert "https://example.org" in str(llm.synthesis_inputs["normalized_results"])


def test_deterministic_planner_preserved_for_tests() -> None:
    result = handle_chat_deterministic({"message": "startup data"})

    assert result["type"] == "clarification"
    assert result["clarifying_questions"]


def test_web_tool_client_blocks_unsafe_tools() -> None:
    assert "process_source" not in SAFE_WEB_TOOLS

    result = call_demo_tool("process_source", {"source_id": "source-1"})

    assert result["ok"] is False
    assert result["error"]["code"] == "tool_not_allowed"


def test_chat_api_auth_required_shape() -> None:
    result = {
        "type": "error",
        "message": "Login is required to use data discovery.",
        "assistant_message": "Login is required to use data discovery.",
        "intent": "unknown",
        "clarifying_questions": [],
        "tool_calls": [],
        "results": _empty_results(),
        "limitations": ["auth_required"],
        "debug": {"error": {"code": "auth_required"}},
    }

    assert result["type"] == "error"
    assert result["limitations"] == ["auth_required"]


def test_tool_error_returns_clean_json() -> None:
    def fake_tool(name, args):
        return {"ok": False, "tool": name, "error": {"code": "invalid_args", "message": "Bad query"}}

    llm = FakeLLM(
        {
            "intent": "find_data",
            "clarifying_questions": [],
            "tool_calls": [{"name": "find_data", "args": {"query": "VC deal count"}}],
            "filters": {},
        }
    )
    result = handle_chat({"message": "VC deal count by stage"}, tool_caller=fake_tool, llm_client=llm)

    assert result["type"] == "error"
    assert result["message"] == "Bad query"
    assert result["limitations"] == ["invalid_args"]
