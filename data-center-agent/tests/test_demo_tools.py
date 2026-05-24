from contextlib import contextmanager
from uuid import uuid4

from app.tools import demo


@contextmanager
def fake_read_connection():
    yield object()


class FakeVariableRepo:
    def __init__(self, _connection):
        pass

    def get_detail(self, variable_id):
        return {"id": variable_id, "raw_variable_name": "VC deal count"}

    def list_by_report(self, report_id):
        return [{"id": str(uuid4()), "report_id": report_id, "raw_variable_name": "Funding amount"}]

    def compare_concepts(self, query, report_ids=None):
        return [{"raw_variable_name": query, "report_id": (report_ids or ["report-1"])[0]}]


class FakeReportRepo:
    def __init__(self, _connection):
        pass

    def get_detail(self, report_id):
        return {"id": report_id, "title": "Startup Report"}


class FakeSourceRepo:
    def __init__(self, _connection):
        pass

    def get_detail(self, source_id):
        return {"id": source_id, "original_url": "https://example.org/report.pdf"}


class FakeOrganizationRepo:
    def __init__(self, _connection):
        pass

    def get_detail(self, organization_id):
        return {"id": organization_id, "name": "Startup Association"}


class FakeJobRepo:
    def __init__(self, _connection):
        pass

    def get(self, job_id):
        return {"id": job_id, "status": "completed"}


class FakeFeedbackRepo:
    def __init__(self, _connection):
        pass

    def create(self, values):
        return {"id": str(uuid4()), **values}


class FakeEngine:
    def begin(self):
        return self

    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


def install_common_fakes(monkeypatch):
    monkeypatch.setattr(demo, "read_connection", fake_read_connection)
    monkeypatch.setattr(demo, "VariableRepository", FakeVariableRepo)
    monkeypatch.setattr(demo, "ReportRepository", FakeReportRepo)
    monkeypatch.setattr(demo, "SourceRepository", FakeSourceRepo)
    monkeypatch.setattr(demo, "EcosystemOrganizationRepository", FakeOrganizationRepo)
    monkeypatch.setattr(demo, "JobRepository", FakeJobRepo)
    monkeypatch.setattr(demo, "FeedbackRepository", FakeFeedbackRepo)
    monkeypatch.setattr(demo, "get_engine", lambda: FakeEngine())
    monkeypatch.setattr(demo, "_list_available_filters", lambda connection: {"object_types": ["variable"], "max_limit": 25})


def test_find_data_tool_returns_structured_json(monkeypatch):
    install_common_fakes(monkeypatch)

    def fake_find_data(query, **kwargs):
        return {"query": query, "closest_variables": [{"title": "VC deal count"}]}

    monkeypatch.setattr(demo, "find_data_worker", fake_find_data)

    result = demo.call_tool("find_data", {"query": "VC deals", "limit": 2})

    assert result["ok"] is True
    assert result["data"]["query"] == "VC deals"


def test_semantic_search_tool_returns_structured_json(monkeypatch):
    install_common_fakes(monkeypatch)
    monkeypatch.setattr(demo, "semantic_search_worker", lambda query, **kwargs: {"query": query, "results": []})

    result = demo.call_tool("semantic_search", {"query": "funding", "object_types": ["variable"], "limit": 2})

    assert result["ok"] is True
    assert result["data"]["results"] == []


def test_get_variable_detail_tool(monkeypatch):
    install_common_fakes(monkeypatch)

    result = demo.call_tool("get_variable_detail", {"variable_id": "var-1"})

    assert result["ok"] is True
    assert result["data"]["raw_variable_name"] == "VC deal count"


def test_get_report_detail_tool(monkeypatch):
    install_common_fakes(monkeypatch)

    result = demo.call_tool("get_report_detail", {"report_id": "report-1"})

    assert result["ok"] is True
    assert result["data"]["title"] == "Startup Report"
    assert result["data"]["variables"]


def test_get_source_detail_tool(monkeypatch):
    install_common_fakes(monkeypatch)

    result = demo.call_tool("get_source_detail", {"source_id": "source-1"})

    assert result["ok"] is True
    assert result["data"]["original_url"].endswith(".pdf")


def test_get_organization_detail_tool(monkeypatch):
    install_common_fakes(monkeypatch)

    result = demo.call_tool("get_organization_detail", {"organization_id": "org-1"})

    assert result["ok"] is True
    assert result["data"]["name"] == "Startup Association"


def test_compare_concepts_tool(monkeypatch):
    install_common_fakes(monkeypatch)

    result = demo.call_tool("compare_concepts", {"query_or_concept_id": "funding", "report_ids": ["report-1"]})

    assert result["ok"] is True
    assert result["data"]["comparisons"][0]["raw_variable_name"] == "funding"


def test_list_available_filters_tool(monkeypatch):
    install_common_fakes(monkeypatch)

    result = demo.call_tool("list_available_filters", {})

    assert result["ok"] is True
    assert result["data"]["max_limit"] == 25


def test_job_status_tool(monkeypatch):
    install_common_fakes(monkeypatch)

    result = demo.call_tool("job_status", {"job_id": "job-1"})

    assert result["ok"] is True
    assert result["data"]["status"] == "completed"


def test_submit_feedback_tool(monkeypatch):
    install_common_fakes(monkeypatch)

    result = demo.call_tool("submit_feedback", {"answer_id": "answer-1", "feedback_type": "thumbs_up"})

    assert result["ok"] is True
    assert result["data"]["feedback_type"] == "thumbs_up"


def test_unsafe_tool_is_not_exposed(monkeypatch):
    install_common_fakes(monkeypatch)

    result = demo.call_tool("process_source", {"source_id": "source-1"})

    assert result["ok"] is False
    assert result["error"]["code"] == "tool_not_allowed"
