from pathlib import Path

from app.storage.base import StorageClient, StoredObject
from app.utils.hashing import sha256_bytes, sha256_file


class LocalStorageClient(StorageClient):
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative_path: str | Path) -> Path:
        path = Path(relative_path)
        if path.is_absolute():
            return path
        return self.root / path

    def write_bytes(self, relative_path: str, content: bytes) -> StoredObject:
        path = self.resolve(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return StoredObject(path=path, sha256=sha256_bytes(content), size_bytes=len(content))

    def write_text(self, relative_path: str, text: str) -> StoredObject:
        content = text.encode("utf-8")
        return self.write_bytes(relative_path, content)

    def read_text(self, relative_path: str | Path) -> str:
        return self.resolve(relative_path).read_text(encoding="utf-8")

    def describe_file(self, relative_path: str | Path) -> StoredObject:
        path = self.resolve(relative_path)
        return StoredObject(path=path, sha256=sha256_file(path), size_bytes=path.stat().st_size)
