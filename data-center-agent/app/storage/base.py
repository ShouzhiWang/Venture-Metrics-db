from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredObject:
    path: Path
    sha256: str
    size_bytes: int


class StorageClient(ABC):
    @abstractmethod
    def write_bytes(self, relative_path: str, content: bytes) -> StoredObject:
        raise NotImplementedError

    @abstractmethod
    def write_text(self, relative_path: str, text: str) -> StoredObject:
        raise NotImplementedError

    @abstractmethod
    def read_text(self, relative_path: str | Path) -> str:
        raise NotImplementedError

    @abstractmethod
    def resolve(self, relative_path: str | Path) -> Path:
        raise NotImplementedError
