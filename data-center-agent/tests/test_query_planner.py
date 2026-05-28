from app.agents.query_planner import plan_query


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
