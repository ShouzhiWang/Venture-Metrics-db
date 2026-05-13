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
    monkeypatch.setattr(worker, "VariableRepository", FakeVariableRepository)

    result = worker.generate_codebook(FakeChunkRepository.report_id, dry_run=True, top_k=5)

    assert result["summary"]["candidate_chunks"] == 1
    assert result["summary"]["final_variables"] == 1
    assert result["variables"][0]["raw_variable_name"] == "Startup density"
    assert FakeVariableRepository.inserted == []
