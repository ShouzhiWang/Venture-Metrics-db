from pathlib import Path

import pandas as pd

from app.workers import ingest_excel as worker


class FakeEngine:
    def begin(self):
        return self

    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeSourceRepository:
    rows = []

    def __init__(self, _connection):
        pass

    def upsert_by_url(self, original_url, values):
        type(self).rows.append({"original_url": original_url, **values})
        return {"id": "source-1", "original_url": original_url, **values}


def test_ingest_excel_url_only_creates_minimal_pending_sources(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "links.xlsx"
    pd.DataFrame({"link": ["HTTPS://Example.Gov/Reports/A.PDF?b=2&a=1", "example.gov/data.csv"]}).to_excel(
        path,
        index=False,
    )
    FakeSourceRepository.rows = []
    monkeypatch.setattr(worker, "get_engine", lambda: FakeEngine())
    monkeypatch.setattr(worker, "SourceRepository", FakeSourceRepository)

    count = worker.ingest_excel(path)

    assert count == 2
    assert FakeSourceRepository.rows[0]["original_url"] == "https://example.gov/Reports/A.PDF?a=1&b=2"
    assert FakeSourceRepository.rows[0]["source_type"] == "pdf"
    assert FakeSourceRepository.rows[0]["crawl_status"] == "pending"
    assert FakeSourceRepository.rows[0]["title"] is None
    assert FakeSourceRepository.rows[0]["source_owner"] is None
    assert FakeSourceRepository.rows[1]["original_url"] == "https://example.gov/data.csv"
    assert FakeSourceRepository.rows[1]["source_type"] == "csv"
