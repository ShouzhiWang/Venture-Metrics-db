from app.agents.query_planner import PreSearchPlanner, build_refined_query, plan_query


def test_vague_query_returns_clarification() -> None:
    result = plan_query("startup data")

    assert result["should_ask_clarifying_question"] is True
    assert result["ambiguity_level"] == "high"
    assert result["clarifying_questions"]


def test_compare_query_routes_to_compare_concepts() -> None:
    result = plan_query("Compare startup funding definitions across reports")

    assert result["intent"] == "compare_concepts"
    assert result["should_ask_clarifying_question"] is False


def test_organization_query_routes_to_organization_search() -> None:
    result = plan_query("Shenzhen startup organizations")

    assert result["intent"] == "find_organizations"
    assert result["extracted_filters"]["geography"] == "Shenzhen"


def test_specific_query_can_run_find_data() -> None:
    result = plan_query("VC deal count by stage")

    assert result["intent"] == "find_data"
    assert result["should_ask_clarifying_question"] is False
    assert result["extracted_filters"]["preferred_metric_type"] == "count"


def test_startup_data_asks_domain_before_search() -> None:
    result = plan_query("startup data")

    assert result["specificity"] == "high"
    assert result["action"] == "ask_clarification"
    assert result["should_run_tool"] is False
    assert result["clarifying_questions"][0]["dimension"] == "domain_topic"


def test_startup_funding_in_singapore_searches_with_metric_refinement() -> None:
    result = plan_query("startup funding in Singapore")

    assert result["specificity"] == "medium"
    assert result["action"] == "search_with_refinement"
    assert result["should_run_tool"] is True
    assert result["detected"]["geography"] == "Singapore"
    assert any(chip["dimension"] == "metric_type" for chip in result["refinement_chips"])


def test_singapore_vc_deal_count_by_stage_searches_directly() -> None:
    result = plan_query("Singapore VC deal count by stage")

    assert result["specificity"] == "low"
    assert result["action"] == "search_directly"
    assert result["should_run_tool"] is True
    assert result["clarifying_questions"] == []


def test_dataset_request_asks_output_and_unit() -> None:
    result = plan_query("make me a dataset on Asian startups")

    assert result["action"] == "ask_clarification"
    dimensions = [item["dimension"] for item in result["clarifying_questions"]]
    assert dimensions == ["output_format", "unit_of_analysis"]


def test_project_context_reduces_geography_questions() -> None:
    result = plan_query(
        "funding trends",
        {"project_title": "Singapore Startup Environment", "research_question": "Track startup funding in Singapore"},
    )

    assert result["detected"]["geography"] == "Singapore"
    assert "geography" not in result["missing_dimensions"]
    assert result["clarifying_questions"][0]["dimension"] == "time_range"


def test_public_data_query_sets_public_only() -> None:
    result = plan_query("public data on business births")

    assert result["detected"]["availability"] == "public_only"
    assert result["extracted_filters"]["public_only"] is True
    assert "availability" not in result["missing_dimensions"]


def test_clarification_chip_creates_refined_query() -> None:
    from app.agents.query_planner import refined_query

    assert refined_query("startup funding in Singapore", "Stage breakdown") == "startup funding in Singapore, Stage breakdown"


def test_research_query_asks_clarification_with_no_retrieval() -> None:
    result = PreSearchPlanner().plan("Recent university research on AI patents")

    assert result["action"] == "ask_clarification"
    assert result["should_run_tool"] is False
    assert result["tool_calls"] == []
    assert result["clarification_ui"]["main_question"] == "Which angle do you want to focus on?"
    labels = [item["label"] for item in result["clarification_ui"]["choice_options"]]
    assert "University AI patent filings" in labels
    assert "Research papers about AI patents" in labels


def test_startup_data_pre_search_gate_has_no_tool_calls() -> None:
    result = PreSearchPlanner().plan("startup data")

    assert result["action"] == "ask_clarification"
    assert result["should_run_tool"] is False
    assert result["tool_calls"] == []


def test_specific_query_searches_directly_with_year() -> None:
    result = plan_query("Singapore VC deal count by stage in 2022")

    assert result["action"] == "search_directly"
    assert result["should_run_tool"] is True
    assert result["detected"]["time_range"] == "2022"


def test_research_query_generates_optional_fields() -> None:
    result = plan_query("Recent university research on AI patents")

    fields = {item["name"]: item for item in result["clarification_ui"]["optional_fields"]}
    assert fields["geography"]["placeholder"] == "e.g. Hong Kong, Singapore, China"
    assert fields["university"]["placeholder"] == "e.g. HKUST, NUS, Tsinghua"
    assert fields["time_period"]["options"] == ["Last 3 years", "Last 5 years", "Since 2020"]


def test_suggested_search_labels_are_short() -> None:
    result = plan_query("Recent university research on AI patents")

    labels = [item["label"] for item in result["clarification_ui"]["suggested_searches"]]
    assert labels == ["Broader overview", "Official statistics and publications", "Organizations and programs"]
    assert all("Recent university research on AI patents" not in label for label in labels)


def test_build_refined_query_from_choice_and_fields() -> None:
    query = build_refined_query(
        "Recent university research on AI patents",
        choice="University AI patent filings",
        fields={"geography": "Hong Kong", "time_period": "Since 2020", "output_format": "Table"},
    )

    assert query == "University AI patent filings in Hong Kong since 2020, output as table"


def test_project_context_removes_geography_field_when_inferred() -> None:
    result = plan_query(
        "funding trends",
        {"project_title": "Singapore Startup Environment", "research_question": "Track startup funding in Singapore"},
    )

    field_names = [item["name"] for item in result["clarification_ui"]["optional_fields"]]
    assert "geography" not in field_names
