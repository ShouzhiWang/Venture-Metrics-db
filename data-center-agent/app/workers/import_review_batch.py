import argparse
import csv
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from app.agents.llm_codebook_parser import LLMParseError, parse_review_response
from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.llm_batches import BatchItemRepository, BatchRepository
from app.llm.openai_batch_client import OpenAIBatchClient
from app.utils.logging import configure_logging


FIELDS = [
    "request_custom_id",
    "original_index",
    "review_decision",
    "keep_for_codebook",
    "review_reason",
    "confidence_adjustment",
    "parse_error",
]


def import_review_batch(*, batch_id: str, output_dir: str | Path = "/data/hermes/batches", review_csv: str | Path) -> dict[str, Any]:
    settings = get_settings()
    output_dir = Path(output_dir)
    review_csv = Path(review_csv)

    engine = get_engine()
    with engine.begin() as connection:
        batch_repo = BatchRepository(connection)
        item_repo = BatchItemRepository(connection)
        batch = _resolve_batch(batch_repo, batch_id)
        if not batch:
            raise ValueError(f"Review batch not found: {batch_id}")
        output_path = _ensure_output_file(batch, output_dir, settings.openai_api_key)

        rows: list[dict[str, Any]] = []
        for raw in _read_jsonl(output_path):
            custom_id = raw.get("custom_id")
            parse_error = None
            try:
                decisions = parse_review_response(raw)
            except LLMParseError as exc:
                decisions = []
                parse_error = str(exc)
            if parse_error:
                rows.append({"request_custom_id": custom_id, "parse_error": parse_error})
            for decision in decisions:
                row = {"request_custom_id": custom_id, **decision.model_dump(mode="json"), "parse_error": None}
                rows.append(row)
            item_repo.update_item_result(
                custom_id,
                status="parsed" if not parse_error else "failed",
                raw_response=raw,
                parsed_items=[decision.model_dump(mode="json") for decision in decisions],
                validation_errors=[parse_error] if parse_error else None,
            )

        review_csv.parent.mkdir(parents=True, exist_ok=True)
        with review_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        batch_repo.mark_imported(batch["id"], output_path=str(output_path), metadata={"reviewed": len(rows)})

    return {"reviewed": len(rows), "review_csv": str(review_csv)}


def _ensure_output_file(batch: dict[str, Any], output_dir: Path, api_key: str | None) -> Path:
    if batch.get("output_path") and Path(batch["output_path"]).exists():
        return Path(batch["output_path"])
    if not batch.get("output_file_id"):
        raise ValueError("Batch has no output_path or output_file_id yet.")
    return OpenAIBatchClient(api_key).download_output_file(batch["output_file_id"], output_dir / f"{batch['id']}_review_output.jsonl")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _resolve_batch(repo: BatchRepository, identifier: str) -> dict[str, Any] | None:
    try:
        return repo.get_batch_by_id(UUID(identifier))
    except ValueError:
        return repo.get_batch_by_openai_id(identifier)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import OpenAI Batch reviewer decisions.")
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--output-dir", default="/data/hermes/batches")
    parser.add_argument("--review-csv", required=True)
    args = parser.parse_args()
    configure_logging()
    result = import_review_batch(batch_id=args.batch_id, output_dir=args.output_dir, review_csv=args.review_csv)
    print(f"Imported review batch: reviewed={result['reviewed']} review_csv={result['review_csv']}")


if __name__ == "__main__":
    main()
