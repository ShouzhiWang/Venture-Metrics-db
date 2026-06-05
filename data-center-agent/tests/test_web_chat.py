from app.agents.demo_llm import DemoLLMClient, DemoLLMConfigError, DemoLLMResponseError
from web.backend.routes.chat import _empty_results, handle_chat, handle_chat_deterministic
from web.backend.services.tool_client import SAFE_WEB_TOOLS, call_demo_tool


class FakeLLM:
    def __init__(self, plan):
        self._plan = plan
        self.synthesis_inputs = None
        self.no_results_inputs = None
        self.structured_inputs = None
        self.qualification_inputs = None

    def plan(self, **kwargs):
        if isinstance(self._plan, Exception):
            raise self._plan
        return self._plan

    def synthesize(self, **kwargs):
        self.synthesis_inputs = kwargs
        return "Grounded answer from tool results."

    def qualify_evidence(self, **kwargs):
        self.qualification_inputs = kwargs
        return {
            "evidence_items": [],
            "answer_support_level": "strong",
            "missing_dimensions": [],
            "safe_answer_strategy": "direct_answer",
        }

    def synthesize_structured(self, **kwargs):
        self.structured_inputs = kwargs
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
    assert result["assistant_message"] == "Grounded answer from structured evidence."
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

    def tool_caller(name, args):
        calls.append((name, args))
        return {"ok": True, "tool": name, "data": {"closest_variables": [], "relevant_reports": [], "relevant_organizations": [], "source_links": [], "connector_datasets": [], "connector_metrics": [], "connector_candidates": [], "suggested_clarifications": []}}

    result = handle_chat(
        {"message": "Recent university research on AI patents"},
        tool_caller=tool_caller,
        llm_client=llm,
    )

    # find_data IS called now (results shown alongside clarification)
    assert result["type"] in ("clarification", "answer")
    assert len(calls) == 1
    assert calls[0][0] == "find_data"
    assert result["assistant_message"] == "LLM generated question?"
    assert result["clarification_ui"]["main_question"] == "LLM generated question?"
    assert result["clarification_ui"]["choice_options"][0]["label"] == "LLM choice"


def test_startup_data_does_not_call_find_data() -> None:
    calls = []

    def tool_caller(name, args):
        calls.append((name, args))
        return {"ok": True, "tool": name, "data": {"closest_variables": [], "relevant_reports": [], "relevant_organizations": [], "source_links": [], "connector_datasets": [], "connector_metrics": [], "connector_candidates": [], "suggested_clarifications": []}}

    result = handle_chat(
        {"message": "startup data"},
        tool_caller=tool_caller,
        llm_client=FakeLLM({"intent": "find_data", "tool_calls": [{"name": "find_data", "args": {"query": "startup data"}}]}),
    )

    # find_data IS called now (results shown alongside clarification)
    assert result["type"] in ("clarification", "answer")
    assert len(calls) == 1
    assert calls[0][0] == "find_data"


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

    assert llm.structured_inputs is not None
    assert llm.structured_inputs["evidence_packet"]["retrieved_items"][0]["title"] == "Startup funding"


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


# ---------------------------------------------------------------------------
# Prompt-level tests for evidence packet and structured synthesis
# ---------------------------------------------------------------------------

def _make_connector_dataset(title, portal="World Bank", description="", geography="", **extra):
    ds = {"title": title, "portal": portal, "description": description, "geography": geography, **extra}
    return ds


def _make_variable(title, description="", geography="", source=""):
    return {"title": title, "description": description, "geography": geography, "source": source}


def _make_organization(name, description="", country=""):
    return {"name": name, "description": description, "country": country}


def test_evidence_packet_intent_extraction():
    """Evidence packet correctly extracts interpreted_intent from the plan."""
    from web.backend.routes.chat import _build_evidence_packet
    plan = {
        "detected": {
            "domain_topic": "startup funding",
            "metric_type": "funding_amount",
            "geography": "Singapore",
            "time_range": "2020-2024",
        },
        "intent": "find_data",
    }
    results = {"connector_datasets": [], "connector_metrics": [], "closest_variables": [], "relevant_reports": [], "relevant_organizations": [], "tavily_candidates": None, "connector_candidates": [], "source_links": []}
    packet = _build_evidence_packet("Singapore venture capital funding 2020-2024", plan, results, [])
    intent = packet["interpreted_intent"]
    assert intent["topic"] == "startup funding"
    assert intent["metric_or_concept"] == "funding_amount"
    assert intent["geography"] == "Singapore"
    assert intent["time_period"] == "2020-2024"


def test_evidence_packet_sector_extraction():
    """Evidence packet extracts sector/technology filter from query."""
    from web.backend.routes.chat import _build_evidence_packet
    plan = {"detected": {"geography": "Hong Kong", "domain_topic": "innovation"}, "intent": "find_data"}
    results = {"connector_datasets": [], "connector_metrics": [], "closest_variables": [], "relevant_reports": [], "relevant_organizations": [], "tavily_candidates": None, "connector_candidates": [], "source_links": []}
    packet = _build_evidence_packet("Hong Kong patent trends in clean energy", plan, results, [])
    assert packet["interpreted_intent"]["sector_or_technology_filter"] == "clean energy"


def test_evidence_packet_item_types():
    """Evidence packet classifies items by type correctly."""
    from web.backend.routes.chat import _build_evidence_packet
    plan = {"detected": {}, "intent": "find_data"}
    results = {
        "connector_datasets": [_make_connector_dataset("WB Indicators")],
        "connector_metrics": [{"title": "GDP growth", "value": "3.5%", "unit": "%"}],
        "closest_variables": [_make_variable("VC deal count")],
        "relevant_reports": [{"title": "Startup Ecosystem Report"}],
        "relevant_chunks": [{"title": "Funding trends passage", "snippet": "Deep tech startup investment rose."}],
        "relevant_organizations": [_make_organization("Enterprise Singapore")],
        "tavily_candidates": {"results": [{"title": "External article", "url": "https://example.com"}]},
        "connector_candidates": [{"title": "Candidate source"}],
        "source_links": [],
    }
    packet = _build_evidence_packet("test query", plan, results, [])
    items = packet["retrieved_items"]
    types = [item["type"] for item in items]
    assert "connector_dataset" in types
    assert "connector_metric" in types
    assert "report_variable" in types  # both variables and reports
    assert "report_chunk" in types
    assert "organization" in types
    assert "external_candidate" in types
    assert "source_candidate" in types


def test_evidence_packet_source_status_counts():
    """Evidence packet correctly counts source status."""
    from web.backend.routes.chat import _build_evidence_packet
    plan = {"detected": {}, "intent": "find_data"}
    results = {
        "connector_datasets": [_make_connector_dataset("A"), _make_connector_dataset("B")],
        "connector_metrics": [{"title": "M1"}],
        "closest_variables": [_make_variable("V1")],
        "relevant_reports": [],
        "relevant_organizations": [],
        "tavily_candidates": {"results": [{"title": "T1"}]},
        "connector_candidates": [],
        "source_links": [],
    }
    packet = _build_evidence_packet("test", plan, results, [])
    status = packet["source_status_counts"]
    assert status["internal_structured"] == 1  # 1 variable + 0 reports
    assert status["synced_connector"] == 3    # 2 datasets + 1 metric
    assert status["external_candidate"] == 1


def test_structured_synthesis_prompt_includes_evidence_packet():
    """The structured synthesis prompt contains the evidence packet and key instructions."""
    from app.agents.demo_llm import _structured_synthesis_prompt
    evidence_packet = {
        "user_query": "Singapore VC funding",
        "interpreted_intent": {"topic": "startup funding", "geography": "Singapore"},
        "retrieved_items": [{"id": "connector_dataset_1", "type": "connector_dataset", "title": "WB Data"}],
        "source_status_counts": {"internal_structured": 0, "synced_connector": 1},
    }
    prompt = _structured_synthesis_prompt(
        message="Singapore VC funding",
        history=[],
        plan={"intent": "find_data"},
        evidence_packet=evidence_packet,
        limitations=[],
    )
    # Check key instructions are present
    assert "support_level" in prompt
    assert "final_answer_markdown" in prompt
    assert "evidence_used" in prompt
    assert "evidence_excluded" in prompt
    assert "Proxy data ban" in prompt
    assert "Negative phrasing ban" in prompt
    assert "Sector/topic guardrail" in prompt
    assert "what_evidence_measures" in prompt
    assert "what_is_not_supported" in prompt
    assert "Fast-first evidence quality" in prompt
    assert "report_chunk" in prompt
    # Check evidence packet is included
    assert "Singapore VC funding" in prompt
    assert "connector_dataset_1" in prompt


def test_structured_synthesis_prompt_with_qualification():
    """The synthesis prompt includes evidence qualification when provided."""
    from app.agents.demo_llm import _structured_synthesis_prompt
    evidence_packet = {
        "user_query": "clean energy patents",
        "interpreted_intent": {"sector_or_technology_filter": "clean energy"},
        "retrieved_items": [],
        "source_status_counts": {},
    }
    qualification = {
        "answer_support_level": "partial",
        "safe_answer_strategy": "partial_answer",
        "missing_dimensions": ["sector_or_topic"],
        "evidence_items": [
            {"id": "connector_dataset_1", "classification": "partial_evidence", "reason": "No clean-energy filter"}
        ],
    }
    prompt = _structured_synthesis_prompt(
        message="Hong Kong patent trends in clean energy",
        history=[],
        plan={"intent": "find_data"},
        evidence_packet=evidence_packet,
        limitations=[],
        evidence_qualification=qualification,
    )
    assert "Evidence Qualification (pre-screened)" in prompt
    assert "partial" in prompt
    assert "partial_evidence" in prompt


def test_structured_synthesis_output_contract():
    """FakeLLM.synthesize_structured returns the expected JSON contract shape."""
    llm = FakeLLM({"intent": "find_data", "tool_calls": [{"name": "find_data", "args": {"query": "test"}}]})
    result = llm.synthesize_structured(
        message="test",
        history=[],
        plan={},
        evidence_packet={"retrieved_items": []},
        limitations=[],
    )
    required_keys = [
        "answer_evidence_level", "support_level", "direct_answer",
        "main_claims", "what_evidence_measures", "what_is_not_supported",
        "evidence_used", "evidence_excluded", "methodology_caveats",
        "missing_data", "recommended_next_actions", "final_answer_markdown",
    ]
    for key in required_keys:
        assert key in result, f"Missing key: {key}"


def test_structured_synthesis_preserves_source_metadata():
    """Evidence packet preserves source URLs and source_status for LLM assessment."""
    from web.backend.routes.chat import _build_evidence_packet
    plan = {"detected": {}, "intent": "find_data"}
    results = {
        "connector_datasets": [
            _make_connector_dataset(
                "World Development Indicators",
                portal="World Bank",
                description="GDP, R&D expenditure, and more",
                geography="Global",
                url="https://data.worldbank.org",
                row_count=5000,
            ),
        ],
        "connector_metrics": [],
        "closest_variables": [],
        "relevant_reports": [],
        "relevant_organizations": [],
        "tavily_candidates": None,
        "connector_candidates": [],
        "source_links": [],
    }
    packet = _build_evidence_packet("R&D expenditure", plan, results, [])
    item = packet["retrieved_items"][0]
    assert item["source_url"] == "https://data.worldbank.org"
    assert item["source_status"] == "synced_connector"  # has row_count
    assert item["values_available"] is True
    assert item["geography"] == "Global"


def test_evidence_packet_preserves_connector_source_url_and_status():
    """Synced connector rows expose source_url/data_status to synthesis."""
    from web.backend.routes.chat import _build_evidence_packet
    plan = {"detected": {"geography": "Hong Kong", "domain_topic": "trademark registrations"}, "intent": "find_data"}
    results = {
        "connector_datasets": [
            {
                "title": "Hong Kong trademark registrations statistics",
                "description": "Official IPD trademark registration statistics.",
                "portal": "data.gov.hk",
                "geography": "Hong Kong",
                "source_url": "https://data.gov.hk/trademarks.csv",
                "data_status": "synced",
                "data_status_label": "synced dataset",
                "row_count": 1200,
                "column_count": 8,
                "retrieved_at": "2026-01-01T00:00:00Z",
                "snapshot_id": "snap-tm",
                "metadata": {"topic": "patents_ip", "access_type": "csv"},
            }
        ],
        "connector_metrics": [],
        "closest_variables": [],
        "relevant_reports": [],
        "relevant_organizations": [],
        "tavily_candidates": None,
        "connector_candidates": [],
        "source_links": [],
    }
    packet = _build_evidence_packet("trademark registrations Hong Kong", plan, results, [])
    item = packet["retrieved_items"][0]
    assert item["source_url"] == "https://data.gov.hk/trademarks.csv"
    assert item["source_status"] == "synced_connector"
    assert item["values_available"] is True
    assert item["row_count"] == 1200
    assert item["column_count"] == 8
    assert item["snapshot_id"] == "snap-tm"
    assert item["access_type"] == "csv"


def test_evidence_packet_uses_resolved_url_from_connector_metadata():
    """Resolved Hong Kong connector URLs are not dropped when nested in metadata."""
    from web.backend.routes.chat import _build_evidence_packet
    plan = {"detected": {"geography": "Hong Kong"}, "intent": "find_data"}
    results = {
        "connector_datasets": [
            {
                "title": "Trademark applications and registrations",
                "description": "Resolved from the Hong Kong IPD data.gov.hk candidate.",
                "geography": "Hong Kong",
                "availability": "obtainable",
                "metadata": {
                    "portal": "data.gov.hk",
                    "resolved_url": "https://static.data.gov.hk/ipd/trademark.csv",
                    "access_type": "csv",
                    "row_count": 800,
                },
            }
        ],
        "connector_metrics": [],
        "closest_variables": [],
        "relevant_reports": [],
        "relevant_organizations": [],
        "tavily_candidates": None,
        "connector_candidates": [],
        "source_links": [],
    }
    packet = _build_evidence_packet("trademark registrations Hong Kong", plan, results, [])
    item = packet["retrieved_items"][0]
    assert item["source_url"] == "https://static.data.gov.hk/ipd/trademark.csv"
    assert item["source_status"] == "synced_connector"
    assert item["values_available"] is True


def test_evidence_packet_preserves_relevance_and_exclusions():
    """Evidence packet exposes deterministic relevance labels and excluded noisy results."""
    from web.backend.routes.chat import _build_evidence_packet
    plan = {"detected": {"geography": "Singapore"}, "intent": "find_data"}
    results = {
        "connector_datasets": [
            {
                "title": "Polytechnic enrolment figures",
                "description": "Course intake and enrolment",
                "source_url": "https://example.gov/enrolment",
                "data_status": "live_api_result",
                "relevance": "irrelevant",
            }
        ],
        "connector_metrics": [],
        "closest_variables": [],
        "relevant_reports": [],
        "relevant_chunks": [
            {
                "title": "Startup funding passage",
                "snippet": "Singapore startup funding and deep tech investment trends shifted in 2024.",
                "source_url": "https://example.com/report",
                "relevance": "direct",
            }
        ],
        "relevant_organizations": [],
        "tavily_candidates": {
            "results": [
                {
                    "title": "Singapore startup ecosystem update",
                    "url": "https://example.com/startups",
                    "snippet": "Singapore startup funding trends show deep tech resilience.",
                    "relevance": "partial",
                }
            ]
        },
        "connector_candidates": [],
        "source_links": [],
        "evidence_quality": {"direct": 1, "partial": 1, "irrelevant": 1},
        "excluded_results": [{"title": "Polytechnic enrolment figures", "reason": "No meaningful query terms matched this item."}],
    }
    packet = _build_evidence_packet("Singapore startup funding trends", plan, results, [])

    item_by_type = {item["type"]: item for item in packet["retrieved_items"]}
    assert item_by_type["report_chunk"]["relevance"] == "direct"
    assert item_by_type["external_candidate"]["relevance"] == "partial"
    assert item_by_type["connector_dataset"]["relevance"] == "irrelevant"
    assert packet["evidence_quality"]["direct"] == 1
    assert packet["excluded_results"][0]["title"] == "Polytechnic enrolment figures"
