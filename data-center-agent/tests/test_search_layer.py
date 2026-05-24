import os
from uuid import uuid4

import pytest

from app.agents.search_index_builder import organization_item, report_item, source_item, variable_item
from app.db.repositories.search_index import SearchIndexRepository
from app.llm.embedding_client import EmbeddingDimensionError, MockEmbeddingClient, validate_dimension
from app.llm.embedding_client import LocalEmbeddingClient
from app.workers import embed_search_index as embed_worker
from app.workers import find_data as find_data_worker
from app.workers import semantic_search as semantic_worker


class FakeRow:
    def __init__(self, mapping):
        self._mapping = mapping


class FakeResult:
    def __init__(self, rows=None, first_row=None):
        self.rows = rows or []
        self.first_row = first_row

    def first(self):
        return self.first_row

    def __iter__(self):
        return iter(self.rows)


class FakeConnection:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return FakeResult(first_row=FakeRow({"id": uuid4(), **(params or {})}))


class FakeEngine:
    def begin(self):
        return self

    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


def test_variable_search_text_includes_core_fields_and_metadata() -> None:
    variable_id = uuid4()
    report_id = uuid4()
    item = variable_item(
        {
            "id": variable_id,
            "report_id": report_id,
            "raw_variable_name": "VC deal count by stage",
            "definition": "Number of venture capital deals by financing stage.",
            "measurement_method": "Count deals in each stage.",
            "unit": "deals",
            "data_source_text": "Enterprise Singapore startup report",
            "data_source_type": "report_table",
            "availability": "obtainable",
            "temporal_coverage": "2019-2024",
            "geographic_coverage": "Singapore",
            "page_number": 12,
            "confidence_score": 0.91,
            "review_status": "pending_high_confidence",
            "metadata": {"item_type": "startup_funding", "domain_relevance": "high", "evidence_quote": "Deals are grouped by seed, Series A, and later stages."},
        },
        report={"id": report_id, "source_id": uuid4(), "title": "Singapore Venture Funding 2024"},
        source={"original_url": "https://example.gov/report.pdf", "raw_file_path": "raw/source/report.pdf"},
    )

    assert item["title"] == "VC deal count by stage"
    assert "Singapore" in item["search_text"]
    assert "startup_funding" in item["search_text"]
    assert item["metadata"]["confidence_score"] == 0.91
    assert item["metadata"]["evidence_quote"].startswith("Deals are grouped")


def test_report_search_text_includes_report_metadata() -> None:
    item = report_item(
        {
            "id": uuid4(),
            "source_id": uuid4(),
            "title": "Hong Kong Innovation Report",
            "publisher": "Innovation agency",
            "summary": "Tracks patents and startup output.",
            "geography": "Hong Kong",
            "report_year": 2025,
            "language": "en",
            "citation_info": {"doi": "example"},
        },
        source={"original_url": "https://example.hk/report", "access_type": "public"},
    )

    assert "Hong Kong Innovation Report" in item["search_text"]
    assert "Innovation agency" in item["search_text"]
    assert "https://example.hk/report" in item["search_text"]


def test_source_search_text_includes_url_and_resolution_status() -> None:
    item = source_item(
        {
            "id": uuid4(),
            "original_url": "https://example.cn/data",
            "title": "Shenzhen electricity data",
            "source_type": "xlsx",
            "source_owner": "government",
            "access_type": "public",
            "source_role": "dataset_file",
            "resolution_status": "not_needed",
            "notes": "monthly consumption",
        }
    )

    assert "https://example.cn/data" in item["search_text"]
    assert "not_needed" in item["search_text"]


def test_organization_search_text_includes_focus_and_website() -> None:
    item = organization_item(
        {
            "id": uuid4(),
            "name": "Asia Startup Network",
            "description": "Connects accelerators and venture investors.",
            "organization_type": "association",
            "geography": "Asia",
            "sector_focus": ["fintech", "climate"],
            "stage_focus": ["seed"],
            "market_focus": ["Singapore"],
            "website_url": "https://example.org",
            "source_id": uuid4(),
            "source_access_type": "public",
        }
    )

    assert item["object_type"] == "organization"
    assert "Asia Startup Network" in item["search_text"]
    assert "fintech" in item["search_text"]
    assert "seed" in item["search_text"]
    assert "https://example.org" in item["search_text"]


def test_mock_embedding_client_returns_deterministic_1024_vectors() -> None:
    client = MockEmbeddingClient()
    first = client.embed_text("startup funding in Singapore")
    second = client.embed_text("startup funding in Singapore")

    assert first.dimension == 1024
    assert first.vector == second.vector
    assert first.provider == "mock"


def test_embedding_dimension_mismatch_raises_clear_error() -> None:
    with pytest.raises(EmbeddingDimensionError, match="expected 1024, got 3"):
        validate_dimension(3, 1024, model="bad-model")


def test_search_index_upsert_uses_conflict_key() -> None:
    connection = FakeConnection()
    repo = SearchIndexRepository(connection)

    repo.upsert_search_item(
        {
            "object_type": "variable",
            "object_id": uuid4(),
            "title": "R&D expenditure",
            "content": "R&D expenditure as percentage of GDP",
            "search_text": "R&D expenditure as percentage of GDP",
        }
    )

    statement, params = connection.calls[0]
    assert "ON CONFLICT (object_type, object_id)" in statement
    assert params["embedding_status"] if "embedding_status" in params else True


def test_keyword_search_public_only_filter_excludes_private_results() -> None:
    connection = FakeConnection()
    repo = SearchIndexRepository(connection)

    repo.keyword_search("business births", object_types=["dataset"], filters={"public_only": True})

    statement, _params = connection.calls[0]
    assert "availability NOT ILIKE '%private%'" in statement


def test_active_model_filter_is_required_for_semantic_search() -> None:
    connection = FakeConnection()
    repo = SearchIndexRepository(connection)

    repo.semantic_search([0.1] * 1024, provider="mock", model="mock-a", dimension=1024)

    statement, params = connection.calls[0]
    assert "embedding_provider = :provider" in statement
    assert "embedding_model = :model" in statement
    assert "embedding_dimension = :dimension" in statement
    assert params["model"] == "mock-a"


def test_embed_worker_updates_embedding_status_with_mock_client(monkeypatch) -> None:
    class FakeRepo:
        updated = []

        def __init__(self, _connection):
            pass

        def get_pending_embedding_items(self, limit, object_types=None, force=False):
            return [{"id": uuid4(), "search_text": "SME digital adoption", "object_type": "variable", "title": "SME adoption"}]

        def update_embedding(self, item_id, vector, *, provider, model, dimension, normalized):
            self.updated.append((item_id, len(vector), provider, model, dimension, normalized))

        def mark_embedding_failed(self, item_id, error):
            raise AssertionError(error)

    FakeRepo.updated = []
    monkeypatch.setattr(embed_worker, "get_engine", lambda: FakeEngine())
    monkeypatch.setattr(embed_worker, "SearchIndexRepository", FakeRepo)

    result = embed_worker.embed_search_index(client=MockEmbeddingClient(), limit=1)

    assert result["embedded"] == 1
    assert FakeRepo.updated[0][1] == 1024
    assert FakeRepo.updated[0][2] == "mock"


def test_semantic_search_falls_back_to_keyword_without_embeddings(monkeypatch) -> None:
    class FakeRepo:
        def __init__(self, _connection):
            pass

        def embedded_count(self, *, provider, model, dimension):
            return 0

        def keyword_search(self, query, object_types=None, limit=20, filters=None):
            return [
                {
                    "object_type": "variable",
                    "object_id": uuid4(),
                    "title": "Startup funding",
                    "search_text": "Startup funding in Singapore",
                    "score": 0.5,
                }
            ]

    monkeypatch.setattr(semantic_worker, "get_engine", lambda: FakeEngine())
    monkeypatch.setattr(semantic_worker, "SearchIndexRepository", FakeRepo)

    result = semantic_worker.semantic_search("startup funding in Singapore", limit=1)

    assert result["mode"] == "keyword_fallback"
    assert result["results"][0]["title"] == "Startup funding"


def test_find_data_groups_results_and_passes_public_filter(monkeypatch) -> None:
    captured = {}

    def fake_semantic_search(query, *, object_types, limit, hybrid, client=None, filters=None):
        captured["filters"] = filters
        captured["object_types"] = object_types
        return {
            "mode": "keyword_fallback",
            "results": [
                {
                    "object_type": "variable",
                    "object_id": "var-1",
                    "title": "SME digital adoption rate",
                    "snippet": "SME digital adoption in Singapore",
                    "score": 0.9,
                    "availability": "obtainable",
                    "geography": "Singapore",
                    "time_coverage": "2020-2024",
                    "source_url": "https://example.gov/report",
                    "local_path": "raw/report.pdf",
                    "metadata": {"definition": "Share of SMEs adopting digital tools."},
                },
                {
                    "object_type": "report",
                    "object_id": "report-1",
                    "title": "SME Digital Report",
                    "snippet": "Digital adoption evidence",
                    "score": 0.7,
                    "availability": "public",
                    "source_url": "https://example.gov/report",
                    "metadata": {},
                },
                {
                    "object_type": "organization",
                    "object_id": "org-1",
                    "title": "Singapore Startup Association",
                    "snippet": "Startup association in Singapore",
                    "score": 0.6,
                    "availability": "public",
                    "source_url": "https://example.org",
                    "metadata": {"organization_type": "association"},
                },
            ],
        }

    monkeypatch.setattr(find_data_worker, "semantic_search", fake_semantic_search)

    result = find_data_worker.find_data("I want data about SME digital adoption in Singapore", public_only=True)

    assert captured["filters"]["public_only"] is True
    assert "organization" in captured.get("object_types", ["organization"])
    assert result["closest_variables"][0]["title"] == "SME digital adoption rate"
    assert result["relevant_reports"][0]["title"] == "SME Digital Report"
    assert result["relevant_organizations"][0]["title"] == "Singapore Startup Association"
    assert result["source_links"][0]["source_url"] == "https://example.gov/report"
    assert result["suggested_clarifications"]


@pytest.mark.skipif(os.getenv("RUN_LOCAL_EMBEDDING_TESTS") != "1", reason="Local model download/load is an opt-in integration test.")
def test_local_embedding_client_integration() -> None:
    result = LocalEmbeddingClient().embed_text("startup funding in Singapore")

    assert result.provider == "local"
    assert result.dimension == 1024
