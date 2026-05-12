import argparse
from pathlib import Path

import pandas as pd

from app.agents.source_classifier import classify_source
from app.db.connection import get_engine
from app.db.repositories.sources import SourceRepository
from app.utils.logging import configure_logging


URL_COLUMNS = ["url", "link", "source_url", "original_url", "href"]


def find_url_column(columns: list[str]) -> str:
    normalized = {column.lower().strip(): column for column in columns}
    for candidate in URL_COLUMNS:
        if candidate in normalized:
            return normalized[candidate]
    raise ValueError(f"Could not find URL column. Expected one of: {', '.join(URL_COLUMNS)}")


def ingest_excel(path: Path) -> int:
    frame = pd.read_excel(path)
    url_column = find_url_column(list(frame.columns))
    inserted = 0
    engine = get_engine()
    with engine.begin() as connection:
        repo = SourceRepository(connection)
        for _, row in frame.iterrows():
            url = str(row[url_column]).strip()
            if not url or url.lower() == "nan":
                continue
            classification = classify_source(url)
            repo.upsert_by_url(
                url,
                {
                    **classification,
                    "title": str(row["title"]).strip() if "title" in frame.columns and pd.notna(row["title"]) else None,
                    "source_owner": str(row["source_owner"]).strip()
                    if "source_owner" in frame.columns and pd.notna(row["source_owner"])
                    else None,
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
