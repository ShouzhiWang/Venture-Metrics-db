from pathlib import Path
from uuid import uuid4

from app.agents.fetcher import FetchResult
from app.agents.source_resolver import DiscoveredArtifact
from app.workers import process_source as worker


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
        self.http_timeout_seconds = 5


class FakeSourceRepository:
    source_id = uuid4()
    updated = {}
    child = None

    def __init__(self, _connection):
        pass

    def get(self, source_id):
        return {"id": source_id, "original_url": "https://example.gov/report"}

    def update_fetch_result(self, source_id, **kwargs):
        type(self).updated = {"id": source_id, **kwargs}
        return {"id": source_id, "original_url": "https://example.gov/report", **kwargs}

    def update_status(self, source_id, *, crawl_status, notes=None):
        type(self).updated = {"id": source_id, "crawl_status": crawl_status, "notes": notes}
        return type(self).updated

    def create_child_source(self, **kwargs):
        type(self).child = {"id": uuid4(), "original_url": kwargs["original_url"], **kwargs}
        return type(self).child

    def update_resolution(self, source_id, **kwargs):
        type(self).updated = {"id": source_id, "original_url": "https://example.gov/report", **kwargs}
        return type(self).updated


class FakeReportRepository:
    created = None

    def __init__(self, _connection):
        pass

    def get_by_source(self, source_id):
        return None

    def create(self, values):
        type(self).created = {"id": uuid4(), **values}
        return type(self).created


class FakeDatasetRepository:
    created = None

    def __init__(self, _connection):
        pass

    def create(self, values):
        type(self).created = {"id": uuid4(), **values}
        return type(self).created


def install_fakes(monkeypatch, tmp_path: Path, fetch_result: FetchResult):
    FakeSourceRepository.updated = {}
    FakeSourceRepository.child = None
    FakeReportRepository.created = None
    FakeDatasetRepository.created = None
    monkeypatch.setattr(worker, "get_settings", lambda: FakeSettings(tmp_path))
    monkeypatch.setattr(worker, "get_engine", lambda: FakeEngine())
    monkeypatch.setattr(worker, "SourceRepository", FakeSourceRepository)
    monkeypatch.setattr(worker, "ReportRepository", FakeReportRepository)
    monkeypatch.setattr(worker, "DatasetRepository", FakeDatasetRepository)
    monkeypatch.setattr(worker, "fetch_source", lambda location, timeout_seconds: fetch_result)


def test_process_source_pdf_creates_sparse_report_after_fetch(tmp_path: Path, monkeypatch) -> None:
    install_fakes(monkeypatch, tmp_path, FetchResult(b"%PDF-1.7 sample", "download", "application/octet-stream"))

    result = worker.process_source(FakeSourceRepository.source_id)

    assert result["source"]["crawl_status"] == "fetched"
    assert result["source"]["source_type"] == "pdf"
    assert result["source"]["detected_format"] == "pdf"
    assert result["report"]["source_id"] == FakeSourceRepository.source_id
    assert result["report"]["title"] is None
    assert result["dataset"] is None


def test_process_source_csv_creates_dataset_not_report(tmp_path: Path, monkeypatch) -> None:
    install_fakes(monkeypatch, tmp_path, FetchResult(b"name,value\nA,1\n", "data.csv", "text/plain"))

    result = worker.process_source(FakeSourceRepository.source_id)

    assert result["source"]["crawl_status"] == "fetched"
    assert result["source"]["source_type"] == "csv"
    assert result["report"] is None
    assert result["dataset"]["source_id"] == FakeSourceRepository.source_id
    assert result["dataset"]["raw_data_path"].endswith("data.csv")


def test_process_source_html_resolves_pdf_child_without_creating_report(tmp_path: Path, monkeypatch) -> None:
    html = b'<html><body><a href="/files/report.pdf">Download PDF</a></body></html>'
    install_fakes(monkeypatch, tmp_path, FetchResult(html, "index.html", "text/html"))

    class FakeVerification:
        final_url = "https://example.gov/files/report.pdf"
        content_type = "application/pdf"
        artifact_type = "pdf"
        is_downloadable = True

        def to_dict(self):
            return {
                "final_url": self.final_url,
                "content_type": self.content_type,
                "artifact_type": self.artifact_type,
                "is_downloadable": self.is_downloadable,
            }

    monkeypatch.setattr(worker, "verify_artifact_url", lambda url, timeout_seconds: FakeVerification())

    result = worker.process_source(FakeSourceRepository.source_id)

    assert result["report"] is None
    assert result["dataset"] is None
    assert result["resolved_source"]["source_type"] == "pdf"
    assert result["resolved_source"]["source_role"] == "report_pdf"
    assert result["source"]["source_role"] == "landing_page"
    assert result["source"]["resolution_status"] == "resolved"
    assert FakeReportRepository.created is None


def test_process_source_auto_mode_uses_browser_fallback_for_js_pdf_link(tmp_path: Path, monkeypatch) -> None:
    html = b"<html><body><button>Download PDF</button><script>renderLink()</script></body></html>"
    install_fakes(monkeypatch, tmp_path, FetchResult(html, "index.html", "text/html"))

    class FakeBrowserResult:
        artifacts = [
            DiscoveredArtifact(
                url="https://example.gov/rendered/report.pdf",
                artifact_type="pdf",
                link_text="Download PDF",
                score=210,
                reason=["rendered_dom"],
                discovery_method="rendered_dom",
            )
        ]
        rendered_html = '<a href="/rendered/report.pdf">Download PDF</a>'
        status = "resolved"
        notes = "browser discovered downloadable artifact candidates"

    class FakeBrowserResolver:
        def __init__(self, timeout_seconds=20, allow_download_clicks=True):
            self.timeout_seconds = timeout_seconds
            self.allow_download_clicks = allow_download_clicks

        def resolve(self, url):
            return FakeBrowserResult()

    monkeypatch.setattr(worker, "BrowserSourceResolver", FakeBrowserResolver)

    result = worker.process_source(FakeSourceRepository.source_id, resolve_mode="auto")

    assert result["report"] is None
    assert result["resolved_source"]["original_url"] == "https://example.gov/rendered/report.pdf"
    assert result["source"]["resolution_status"] == "resolved"
    assert result["discovered_artifacts"][0]["discovery_method"] == "rendered_dom"
