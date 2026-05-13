from pathlib import Path
from uuid import uuid4

from app.workers import process_report as worker


class FakeEngine:
    def begin(self):
        return self

    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeSettings:
    def __init__(self, storage_root: Path):
        self.storage_root = storage_root


class FakeReportRepository:
    report_id = uuid4()
    source_id = uuid4()
    updated_paths = {}
    updated_metadata = {}

    def __init__(self, _connection):
        pass

    def get(self, report_id):
        return {"id": report_id, "source_id": self.source_id}

    def update_paths(self, report_id, *, raw_text_path, parsed_json_path=None):
        type(self).updated_paths = {"raw_text_path": raw_text_path, "parsed_json_path": parsed_json_path}

    def update_metadata(self, report_id, values):
        type(self).updated_metadata = values


class FakeSourceRepository:
    raw_file_path = "raw/source-1/report.html"
    source_id = uuid4()
    updated_status = {}

    def __init__(self, _connection):
        pass

    def get(self, _source_id):
        return {
            "id": self.source_id,
            "raw_file_path": self.raw_file_path,
            "source_type": "html",
            "mime_type": "text/html",
        }

    def update_status(self, source_id, *, crawl_status, notes=None):
        type(self).updated_status = {"source_id": source_id, "crawl_status": crawl_status, "notes": notes}
        return {}


class FakeChunkRepository:
    inserted_chunks = []

    def __init__(self, _connection):
        pass

    def create_many(self, chunks):
        type(self).inserted_chunks = chunks
        return len(chunks)


def test_process_report_with_html_fixture(tmp_path: Path, monkeypatch) -> None:
    raw_path = tmp_path / FakeSourceRepository.raw_file_path
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text(
        """
        <html>
          <head><title>Population Report</title></head>
          <body>
            <p>Data source: public census table.</p>
            <p>Population is defined as total resident population for the reporting year.</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    fake_report_repo = FakeReportRepository
    fake_chunk_repo = FakeChunkRepository
    fake_report_repo.updated_paths = {}
    fake_report_repo.updated_metadata = {}
    fake_chunk_repo.inserted_chunks = []
    FakeSourceRepository.updated_status = {}

    monkeypatch.setattr(worker, "get_settings", lambda: FakeSettings(tmp_path))
    monkeypatch.setattr(worker, "get_engine", lambda: FakeEngine())
    monkeypatch.setattr(worker, "ReportRepository", fake_report_repo)
    monkeypatch.setattr(worker, "SourceRepository", FakeSourceRepository)
    monkeypatch.setattr(worker, "ChunkRepository", fake_chunk_repo)

    count = worker.process_report(fake_report_repo.report_id)

    assert count == 1
    assert (tmp_path / "parsed" / str(fake_report_repo.report_id) / "raw_text.txt").exists()
    assert (tmp_path / "parsed" / str(fake_report_repo.report_id) / "parsed.json").exists()
    assert (tmp_path / "parsed" / str(fake_report_repo.report_id) / "pages.json").exists()
    assert fake_report_repo.updated_paths["parsed_json_path"].endswith("parsed.json")
    assert fake_report_repo.updated_metadata["title"] == "Population Report"
    assert FakeSourceRepository.updated_status["crawl_status"] == "parsed"
    assert fake_chunk_repo.inserted_chunks[0]["chunk_type"] == "source_note"
    assert fake_chunk_repo.inserted_chunks[0]["metadata"]["parser"] in {"trafilatura", "beautifulsoup"}
