import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import httpx


class FetchResult:
    def __init__(self, content: bytes, filename: str, mime_type: str | None, final_url: str | None = None):
        self.content = content
        self.filename = filename
        self.mime_type = mime_type
        self.final_url = final_url


def detect_content_format(content: bytes, mime_type: str | None, filename: str | None = None) -> tuple[str, str | None]:
    lowered_mime = (mime_type or "").lower()
    suffix = Path(filename or "").suffix.lower()
    head = content[:512].lstrip()

    if content.startswith(b"%PDF") or lowered_mime == "application/pdf" or suffix == ".pdf":
        return "pdf", "pdf"
    if content.startswith(b"PK\x03\x04") or suffix in {".xlsx", ".xlsm"}:
        return "xlsx", suffix.lstrip(".") or "xlsx"
    if lowered_mime in {"text/csv", "application/csv"} or suffix == ".csv":
        return "csv", "csv"
    if head.startswith((b"<!DOCTYPE html", b"<!doctype html", b"<html", b"<HTML")) or "text/html" in lowered_mime or suffix in {
        ".html",
        ".htm",
    }:
        return "html", "html"
    if lowered_mime.endswith("json") or suffix == ".json":
        return "api", "json"
    return "unknown", suffix.lstrip(".") if suffix else None


def fetch_source(location: str, timeout_seconds: int = 30) -> FetchResult:
    parsed = urlparse(location)
    if parsed.scheme in {"http", "https"}:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            response = client.get(location)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";")[0] or None
            filename = Path(parsed.path).name or "index.html"
            if "." not in filename:
                extension = mimetypes.guess_extension(content_type or "") or ".html"
                filename = f"index{extension}"
            return FetchResult(response.content, filename, content_type, str(response.url))

    path = Path(location)
    content = path.read_bytes()
    mime_type = mimetypes.guess_type(path.name)[0]
    return FetchResult(content, path.name, mime_type, None)
