from app.storage.local_storage import LocalStorageClient


def test_local_storage_writes_and_reads_text(tmp_path) -> None:
    storage = LocalStorageClient(tmp_path)

    stored = storage.write_text("parsed/report/raw_text.txt", "hello world")

    assert stored.path.exists()
    assert stored.size_bytes == len("hello world")
    assert storage.read_text("parsed/report/raw_text.txt") == "hello world"
    assert len(stored.sha256) == 64


def test_local_storage_resolves_relative_path(tmp_path) -> None:
    storage = LocalStorageClient(tmp_path)

    assert storage.resolve("raw/source/file.pdf") == tmp_path / "raw/source/file.pdf"
