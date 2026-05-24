from pathlib import PurePosixPath
from urllib.parse import urlparse

from app.agents.ecosystem_org_extractor import classify_source_route


EXTENSION_TO_TYPE = {
    ".pdf": "pdf",
    ".html": "html",
    ".htm": "html",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".csv": "csv",
    ".json": "api",
}


def classify_source(url_or_path: str | None) -> dict[str, str | None]:
    if not url_or_path:
        return {"source_type": "unknown", "detected_format": None, "access_type": "unknown"}

    parsed = urlparse(url_or_path)
    path = PurePosixPath(parsed.path.lower())
    extension = path.suffix
    source_type = EXTENSION_TO_TYPE.get(extension)

    if source_type is None and parsed.query:
        query = parsed.query.lower()
        if "format=csv" in query:
            source_type = "csv"
        elif "format=json" in query or "api" in parsed.path.lower():
            source_type = "api"

    if source_type is None and parsed.scheme in {"http", "https"}:
        source_type = "html"

    route = classify_source_route(url=url_or_path, source_type=source_type)

    return {
        "source_type": source_type or "unknown",
        "detected_format": extension.lstrip(".") if extension else None,
        "access_type": "public" if parsed.scheme in {"http", "https"} else "unknown",
        "source_route": route.source_route,
    }
