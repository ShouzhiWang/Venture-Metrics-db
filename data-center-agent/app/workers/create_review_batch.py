import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from app.agents.llm_codebook_prompts import build_codebook_review_prompt
from app.agents.llm_candidate_selector import estimate_tokens
from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.llm_batches import BatchItemRepository, BatchRepository
from app.llm.openai_batch_client import OpenAIBatchClient, create_jsonl_file, make_response_request
from app.utils.logging import configure_logging


def create_review_batch(
    *,
    extraction_batch_id: str,
    output_dir: str | Path = "/data/hermes/batches",
    model: str | None = None,
    prompt_version: str | None = None,
    submit: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    model = model or settings.openai_batch_review_model
    prompt_version = prompt_version or f"{settings.openai_batch_prompt_version}_review"
    output_dir = Path(output_dir)

    engine = get_engine()
    with engine.begin() as connection:
        batch_repo = BatchRepository(connection)
        item_repo = BatchItemRepository(connection)
        extraction_batch = _resolve_batch(batch_repo, extraction_batch_id)
        if not extraction_batch:
            raise ValueError(f"Extraction batch not found: {extraction_batch_id}")
        extraction_items = item_repo.get_items_by_batch(extraction_batch["id"])

        requests: list[dict[str, Any]] = []
        item_records: list[dict[str, Any]] = []
        estimated_tokens = 0
        for item in extraction_items:
            parsed_items = item.get("parsed_items") or []
            if not parsed_items:
                continue
            prompt = build_codebook_review_prompt(parsed_items)
            custom_id = f"extraction_item:{item['id']}:review:{prompt_version}"
            requests.append(
                make_response_request(
                    custom_id=custom_id,
                    model=model,
                    prompt=prompt,
                    report_id=str(item.get("report_id")) if item.get("report_id") else None,
                    prompt_version=prompt_version,
                )
            )
            estimated_tokens += estimate_tokens(prompt)
            item_records.append(
                {
                    "request_custom_id": custom_id,
                    "report_id": item.get("report_id"),
                    "status": "pending",
                    "metadata": {"extraction_batch_id": str(extraction_batch["id"]), "extraction_item_id": str(item["id"])},
                }
            )

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        input_path = output_dir / f"codebook_review_{timestamp}.jsonl"
        create_jsonl_file(requests, input_path)
        review_batch = batch_repo.create_batch_record(
            {
                "batch_kind": "codebook_review",
                "model": model,
                "prompt_version": prompt_version,
                "status": "created",
                "report_ids": [str(item.get("report_id")) for item in extraction_items if item.get("report_id")],
                "input_path": str(input_path),
                "request_count": len(requests),
                "estimated_input_tokens": estimated_tokens,
                "estimated_output_tokens": len(requests) * 1000,
                "metadata": {"extraction_batch_id": str(extraction_batch["id"])},
            }
        )
        for item in item_records:
            item["batch_id"] = review_batch["id"]
        item_repo.insert_items(item_records)

        openai_batch_id = None
        if submit:
            client = OpenAIBatchClient(settings.openai_api_key)
            uploaded = client.upload_batch_file(input_path)
            remote = client.create_batch(
                uploaded.id,
                endpoint="/v1/responses",
                metadata={"db_batch_id": str(review_batch["id"]), "kind": "codebook_review"},
            )
            openai_batch_id = remote.id
            review_batch = batch_repo.update_batch_status(
                review_batch["id"],
                status=getattr(remote, "status", "submitted"),
                openai_batch_id=remote.id,
                input_file_id=uploaded.id,
                submitted_at=datetime.now(UTC),
            ) or review_batch

    return {"batch": review_batch, "request_count": len(requests), "input_path": str(input_path), "openai_batch_id": openai_batch_id}


def _resolve_batch(repo: BatchRepository, identifier: str) -> dict[str, Any] | None:
    try:
        return repo.get_batch_by_id(UUID(identifier))
    except ValueError:
        return repo.get_batch_by_openai_id(identifier)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an OpenAI Batch reviewer job for extracted codebook candidates.")
    parser.add_argument("--batch-id", required=True, help="Extraction batch DB id or OpenAI id.")
    parser.add_argument("--output-dir", default="/data/hermes/batches")
    parser.add_argument("--model")
    parser.add_argument("--prompt-version")
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()
    configure_logging()
    result = create_review_batch(
        extraction_batch_id=args.batch_id,
        output_dir=args.output_dir,
        model=args.model,
        prompt_version=args.prompt_version,
        submit=args.submit,
    )
    print(
        "Created review batch: "
        f"requests={result['request_count']} input_path={result['input_path']} "
        f"batch_db_id={result['batch']['id']} openai_batch_id={result.get('openai_batch_id')}"
    )


if __name__ == "__main__":
    main()
