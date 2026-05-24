from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.utils.logging import configure_logging
from app.workers.semantic_search import semantic_search


EVALUATION_QUERIES = [
    "startup funding in Singapore",
    "VC deal count by stage",
    "R&D expenditure as percentage of GDP",
    "SME digital adoption",
    "innovation output in Hong Kong",
    "Asian startup exits",
    "AI investment by country",
    "public data on business births",
    "Shenzhen electricity consumption",
    "government support for startups",
]


def evaluate_search_quality(*, limit: int = 10, output: Path | None = None) -> Path:
    output_path = output or Path("exports") / "search_quality_eval.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for query in EVALUATION_QUERIES:
        result = semantic_search(query, object_types=["variable", "dataset", "report", "source"], limit=limit, hybrid=True)
        for rank, item in enumerate(result["results"], start=1):
            rows.append(
                {
                    "query": query,
                    "rank": rank,
                    "object_type": item.get("object_type"),
                    "title": item.get("title"),
                    "score": item.get("score"),
                    "source_id": item.get("source_id"),
                    "report_id": item.get("report_id"),
                    "availability": item.get("availability"),
                    "snippet": item.get("snippet"),
                }
            )
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["query", "rank", "object_type", "title", "score", "source_id", "report_id", "availability", "snippet"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run fixed retrieval quality queries and export top-k results.")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    configure_logging()
    output_path = evaluate_search_quality(limit=args.limit, output=args.output)
    print(f"Wrote retrieval evaluation results to {output_path}")


if __name__ == "__main__":
    main()
