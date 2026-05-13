import argparse
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd

from app.agents.source_classifier import classify_source
from app.db.connection import get_engine
from app.db.repositories.sources import SourceRepository
from app.utils.logging import configure_logging


URL_COLUMNS = ["url", "link", "source_url", "original_url", "href", "网址", "網站", "网站", "链接", "連結"]


def find_url_column(columns: list[str]) -> str:
    normalized = {column.lower().strip(): column for column in columns}
    for candidate in URL_COLUMNS:
        if candidate in normalized:
            return normalized[candidate]
    raise ValueError(f"Could not find URL column. Expected one of: {', '.join(URL_COLUMNS)}")


def normalize_url(url: str) -> str:
    stripped = url.strip()
    split = urlsplit(stripped)
    if not split.scheme:
        split = urlsplit(f"https://{stripped}")
    scheme = split.scheme.lower()
    netloc = split.netloc.lower()
    path = split.path or ""
    query = urlencode(sorted(parse_qsl(split.query, keep_blank_values=True)))
    return urlunsplit((scheme, netloc, path, query, ""))


def extract_first_url(value: str) -> str | None:
    stripped = value.strip()
    match = re.search(r"https?://[^\s，,；;）)]+", stripped, flags=re.IGNORECASE)
    if match:
        return match.group(0)
    if re.fullmatch(r"(?:www\.)?[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:/[^\s，,；;）)]*)?", stripped):
        return stripped
    return None


def iter_excel_frames(path: Path):
    sheets = pd.read_excel(path, sheet_name=None)
    for sheet_name, frame in sheets.items():
        yield sheet_name, frame


def ingest_excel(path: Path) -> int:
    inserted = 0
    engine = get_engine()
    with engine.begin() as connection:
        repo = SourceRepository(connection)
        for sheet_name, frame in iter_excel_frames(path):
            url_column = find_url_column(list(frame.columns))
            for _, row in frame.iterrows():
                raw_value = str(row[url_column]).strip()
                if not raw_value or raw_value.lower() == "nan":
                    continue
                raw_url = extract_first_url(raw_value)
                if not raw_url:
                    continue
                url = normalize_url(raw_url)
                classification = classify_source(url)
                repo.upsert_by_url(
                    url,
                    {
                        **classification,
                        "crawl_status": "pending",
                        "title": None,
                        "source_owner": None,
                        "notes": f"seed_sheet={sheet_name}",
                    },
                )
                inserted += 1
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest report/source links from an Excel file.")
    parser.add_argument("--path", type=Path, required=True, help="Path to .xlsx file with a URL/link column.")
    args = parser.parse_args()
    configure_logging()
    count = ingest_excel(args.path)
    print(f"Ingested {count} source rows from {args.path}")


if __name__ == "__main__":
    main()
