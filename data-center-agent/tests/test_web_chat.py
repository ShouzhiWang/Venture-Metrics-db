from web.backend.routes.chat import handle_chat
from web.backend.services.tool_client import SAFE_WEB_TOOLS, call_demo_tool


def test_chat_vague_query_returns_clarification() -> None:
    result = handle_chat({"message": "startup data"})

    assert result["type"] == "clarification"
    assert result["clarifying_questions"]


def test_chat_specific_query_routes_to_find_data() -> None:
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

    result = handle_chat({"message": "VC deal count by stage"}, tool_caller=fake_tool)

    assert result["type"] == "answer"
    assert calls[0][0] == "find_data"


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

    result = handle_chat({"message": "Compare startup funding definitions across reports"}, tool_caller=fake_tool)

    assert result["intent"] == "compare_concepts"
    assert calls[0][0] == "compare_concepts_auto"


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

    result = handle_chat({"message": "Shenzhen startup organizations"}, tool_caller=fake_tool)

    assert result["intent"] == "find_organizations"
    assert result["results"]["relevant_organizations"][0]["name"] == "Shenzhen Startup Association"
    assert calls[0][0] == "semantic_search"
    assert calls[0][1]["object_types"] == ["organization"]


def test_web_tool_client_blocks_unsafe_tools() -> None:
    assert "process_source" not in SAFE_WEB_TOOLS

    result = call_demo_tool("process_source", {"source_id": "source-1"})

    assert result["ok"] is False
    assert result["error"]["code"] == "tool_not_allowed"


def test_tool_error_returns_clean_json() -> None:
    def fake_tool(name, args):
        return {"ok": False, "tool": name, "error": {"code": "invalid_args", "message": "Bad query"}}

    result = handle_chat({"message": "VC deal count by stage"}, tool_caller=fake_tool)

    assert result["type"] == "error"
    assert result["message"] == "Bad query"
    assert result["limitations"] == ["invalid_args"]
