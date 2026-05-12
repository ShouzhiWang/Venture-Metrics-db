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
