from uuid import uuid4

from app.workers import generate_codebook as worker


class FakeEngine:
    def begin(self):
        return self

    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeChunkRepository:
    report_id = uuid4()
    chunk_id = uuid4()

    def __init__(self, _connection):
        pass

    def list_by_report(self, report_id):
        return [
            {
                "id": self.chunk_id,
                "report_id": report_id,
                "chunk_text": "Startup density is defined as startups per 1,000 residents. Data are sourced from official statistics.",
                "page_number": 3,
                "section_title": "Definitions",
                "chunk_type": "methodology",
                "metadata": {},
            }
        ]


class FakeLongChunkRepository(FakeChunkRepository):
    def list_by_report(self, report_id):
        return [
            {
                "id": uuid4(),
                "report_id": report_id,
                "chunk_text": "Methodology: Startup density is defined as startups per 1,000 residents. Data are sourced from official statistics. "
                * 80,
                "page_number": index,
                "section_title": "Definitions",
                "chunk_type": "methodology",
                "metadata": {},
            }
            for index in range(1, 6)
        ]


class FakeReportRepository:
    def __init__(self, _connection):
        pass

    def get(self, report_id):
        return {"id": report_id, "source_id": uuid4(), "citation_info": {}}


class FakeSourceRepository:
    def __init__(self, _connection):
        pass

    def get(self, source_id):
        return {"id": source_id, "source_type": "html", "crawl_status": "parsed"}


class FakeVariableRepository:
    inserted = []

    def __init__(self, _connection):
        pass

    def get_report_variables_by_report(self, report_id):
        return []

    def insert_many_report_variables(self, variables):
        type(self).inserted = variables
        return [variable.model_dump(mode="json") for variable in variables]

    def delete_report_variables_by_report(self, report_id):
        return 0


def test_generate_codebook_dry_run_uses_mocked_repositories(monkeypatch) -> None:
    monkeypatch.setattr(worker, "get_engine", lambda: FakeEngine())
    monkeypatch.setattr(worker, "ChunkRepository", FakeChunkRepository)
    monkeypatch.setattr(worker, "ReportRepository", FakeReportRepository)
    monkeypatch.setattr(worker, "SourceRepository", FakeSourceRepository)
    monkeypatch.setattr(worker, "VariableRepository", FakeVariableRepository)

    result = worker.generate_codebook(FakeChunkRepository.report_id, dry_run=True, top_k=5, force=True)

    assert result["summary"]["candidate_chunks"] == 1
    assert result["summary"]["final_variables"] == 1
    assert result["variables"][0]["raw_variable_name"] == "Startup density"
    assert FakeVariableRepository.inserted == []


def test_generate_codebook_skips_low_content_report_unless_force(monkeypatch) -> None:
    monkeypatch.setattr(worker, "get_engine", lambda: FakeEngine())
    monkeypatch.setattr(worker, "ChunkRepository", FakeChunkRepository)
    monkeypatch.setattr(worker, "ReportRepository", FakeReportRepository)
    monkeypatch.setattr(worker, "SourceRepository", FakeSourceRepository)
    monkeypatch.setattr(worker, "VariableRepository", FakeVariableRepository)

    result = worker.generate_codebook(FakeChunkRepository.report_id, dry_run=True, top_k=5)

    assert result["summary"]["skipped"] is True
    assert "minimum" in result["summary"]["skip_reason"]
    assert result["variables"] == []


def test_generate_codebook_runs_full_content_report(monkeypatch) -> None:
    monkeypatch.setattr(worker, "get_engine", lambda: FakeEngine())
    monkeypatch.setattr(worker, "ChunkRepository", FakeLongChunkRepository)
    monkeypatch.setattr(worker, "ReportRepository", FakeReportRepository)
    monkeypatch.setattr(worker, "SourceRepository", FakeSourceRepository)
    monkeypatch.setattr(worker, "VariableRepository", FakeVariableRepository)

    result = worker.generate_codebook(FakeChunkRepository.report_id, dry_run=True, top_k=5)

    assert result["summary"]["skipped"] is False
    assert result["summary"]["content_quality"] in {"full_report", "partial_report"}
    assert result["summary"]["final_variables"] >= 1
