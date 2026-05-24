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
