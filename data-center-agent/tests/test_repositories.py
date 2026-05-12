from app.db.repositories.sources import SourceRepository


class FakeResult:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row


class FakeRow:
    def __init__(self, mapping):
        self._mapping = mapping


class FakeConnection:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return FakeResult(FakeRow({"id": "source-1", **(params or {})}))


def test_source_repository_upsert_by_url_uses_dedup_key() -> None:
    connection = FakeConnection()
    repo = SourceRepository(connection)

    result = repo.upsert_by_url("https://example.gov/report.pdf", {"source_type": "pdf", "detected_format": "pdf"})

    statement, params = connection.calls[0]
    assert "ON CONFLICT (original_url)" in statement
    assert params["original_url"] == "https://example.gov/report.pdf"
    assert params["source_type"] == "pdf"
    assert result["original_url"] == "https://example.gov/report.pdf"
