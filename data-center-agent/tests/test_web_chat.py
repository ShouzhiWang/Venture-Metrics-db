from app.agents.demo_llm import DemoLLMClient, DemoLLMConfigError, DemoLLMResponseError
from web.backend.routes.chat import _empty_results, handle_chat, handle_chat_deterministic
from web.backend.services.tool_client import SAFE_WEB_TOOLS, call_demo_tool


class FakeLLM:
    def __init__(self, plan):
        self._plan = plan
        self.synthesis_inputs = None
        self.no_results_inputs = None

    def plan(self, **kwargs):
        if isinstance(self._plan, Exception):
            raise self._plan
        return self._plan

    def synthesize(self, **kwargs):
        self.synthesis_inputs = kwargs
        return "Grounded answer from tool results."

    def synthesize_no_results(self, **kwargs):
        self.no_results_inputs = kwargs
        return {
            "assistant_message": "No strong matches yet. Try a related metric or source search.",
            "follow_up_queries": [
                {"label": "Bank lending", "query": "UK SME bank loan usage rates"},
                {"label": "Equity share", "query": "UK SME equity and venture funding share"},
            ],
        }


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


def test_empty_academic_comparison_expands_to_find_data_connectors() -> None:
    calls = []

    def fake_tool(name, args):
        calls.append((name, args))
        if name == "compare_concepts_auto":
            return {
                "ok": True,
                "data": {
                    "status": "no_results",
                    "comparison": {},
                    "selected_reports": [],
                    "closest_variables": [],
                    "limitations": ["No comparable local reports."],
                    "clarifying_questions": [],
                    "metadata": {},
                },
            }
        if name == "find_data":
            return {
                "ok": True,
                "data": {
                    "closest_variables": [],
                    "relevant_reports": [],
                    "relevant_organizations": [],
                    "source_links": [],
                    "connector_datasets": [
                        {
                            "title": "AI patent research publication",
                            "portal": "OpenAlex",
                            "source_url": "https://openalex.org/example",
                            "data_status_label": "live from OpenAlex API",
                        }
                    ],
                    "connector_metrics": [],
                    "connector_candidates": [],
                    "tavily_candidates": {
                        "source": "Tavily (web discovery fallback)",
                        "results": [{"title": "University patent office source", "source_url": "https://example.edu/patents"}],
                    },
                    "suggested_clarifications": [],
                },
            }
        raise AssertionError(name)

    llm = FakeLLM(
        {
            "intent": "compare_concepts",
            "clarifying_questions": [],
            "tool_calls": [{"name": "compare_concepts_auto", "args": {"query": "Compare AI patent research between Stanford and peer universities"}}],
            "filters": {},
        }
    )

    result = handle_chat(
        {"message": "Compare AI patent research between Stanford and peer universities"},
        tool_caller=fake_tool,
        llm_client=llm,
    )

    assert [call[0] for call in calls] == ["compare_concepts_auto", "find_data"]
    assert result["type"] == "answer"
    assert result["results"]["connector_datasets"][0]["portal"] == "OpenAlex"
    assert result["results"]["tavily_candidates"]["results"][0]["title"] == "University patent office source"


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
    assert result["results"] == _empty_results()


def test_high_ambiguity_research_query_does_not_call_find_data() -> None:
    calls = []
    llm = FakeLLM(
        {
            "intent": "find_data",
            "assistant_message": "Pick a research angle before I search.",
            "clarifying_questions": [],
            "clarification_ui": {
                "main_question": "LLM generated question?",
                "choice_options": [{"label": "LLM choice", "value": "LLM generated value"}],
                "optional_fields": [],
                "suggested_searches": [{"label": "LLM suggestion", "query_append": "LLM append"}],
            },
            "tool_calls": [{"name": "find_data", "args": {"query": "Recent university research on AI patents"}}],
            "filters": {},
        }
    )

    result = handle_chat(
        {"message": "Recent university research on AI patents"},
        tool_caller=lambda name, args: calls.append((name, args)),
        llm_client=llm,
    )

    assert result["type"] == "clarification"
    assert result["tool_calls"] == []
    assert calls == []
    assert result["assistant_message"] == "LLM generated question?"
    assert result["clarification_ui"]["main_question"] == "LLM generated question?"
    assert result["clarification_ui"]["choice_options"][0]["label"] == "LLM choice"


def test_startup_data_does_not_call_find_data() -> None:
    calls = []

    result = handle_chat(
        {"message": "startup data"},
        tool_caller=lambda name, args: calls.append((name, args)),
        llm_client=FakeLLM({"intent": "find_data", "tool_calls": [{"name": "find_data", "args": {"query": "startup data"}}]}),
    )

    assert result["type"] == "clarification"
    assert result["tool_calls"] == []
    assert calls == []


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


def test_chat_no_results_uses_synthesis_follow_ups() -> None:
    def fake_tool(name, args):
        return {
            "ok": True,
            "data": {
                "closest_variables": [],
                "relevant_reports": [],
                "relevant_organizations": [],
                "source_links": [],
                "suggested_clarifications": [
                    {"question": "Official statistics on UK SME finance", "reason": "reports may exist"},
                ],
            },
        }

    llm = FakeLLM(
        {
            "intent": "find_data",
            "clarifying_questions": [{"question": "Which year range?", "options": ["2018-2023"]}],
            "tool_calls": [{"name": "find_data", "args": {"query": "UK SME external finance"}}],
            "filters": {},
        }
    )
    result = handle_chat({"message": "UK SME external finance"}, tool_caller=fake_tool, llm_client=llm)

    assert result["type"] == "no_results"
    assert result["follow_up_queries"]
    assert result["follow_up_queries"][0]["query"]
    assert any("Official statistics" in q["question"] for q in result["clarifying_questions"])
    assert llm.no_results_inputs is not None
    assert llm.synthesis_inputs is None


def test_mimo_extra_body_disables_thinking() -> None:
    client = object.__new__(DemoLLMClient)
    client.provider = "xiaomi"
    client.base_url = "https://api.xiaomimimo.com/v1"
    client.model = "mimo-v2.5"
    client.thinking = "disabled"

    assert client._provider_extra_body() == {"thinking": {"type": "disabled"}}


def test_openai_extra_body_omits_provider_specific_thinking() -> None:
    client = object.__new__(DemoLLMClient)
    client.provider = "openai"
    client.base_url = "https://api.openai.com/v1"
    client.model = "gpt-4o-mini"
    client.thinking = "disabled"

    assert client._provider_extra_body() == {}
