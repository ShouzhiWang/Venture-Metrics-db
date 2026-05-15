import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.agents.llm_candidate_selector import LLMCandidateChunkSelector, estimate_tokens
from app.agents.llm_codebook_prompts import build_codebook_extraction_prompt
from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.llm_batches import BatchItemRepository, BatchRepository
from app.llm.openai_batch_client import OpenAIBatchClient, create_jsonl_file, make_response_request
from app.utils.logging import configure_logging


def create_extraction_batch(
    *,
    report_ids: list[UUID | str] | None = None,
    limit: int = 10,
    eligibility: set[str] | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    output_dir: str | Path = "/data/hermes/batches",
    max_chunks: int = 30,
    max_input_tokens: int | None = None,
    dry_run: bool = False,
    submit: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    model = model or settings.openai_batch_model
    prompt_version = prompt_version or settings.openai_batch_prompt_version
    max_input_tokens = max_input_tokens or settings.openai_batch_max_input_tokens_per_report
    output_dir = Path(output_dir)

    engine = get_engine()
    with engine.begin() as connection:
        reports = _load_reports(connection, report_ids=report_ids, limit=limit, eligibility=eligibility)
        chunk_repo = ChunkRepository(connection)
        selector = LLMCandidateChunkSelector(max_chunks=max_chunks, max_input_tokens=max_input_tokens)

        requests: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = []
        selected_counts: dict[str, int] = {}
        estimated_tokens = 0
        for report in reports:
            chunks = chunk_repo.list_by_report(report["id"])
            selected_chunks = selector.select(chunks)
            if not selected_chunks:
                continue
            metadata = {
                "report_id": str(report["id"]),
                "title": report.get("title"),
                "publisher": report.get("publisher"),
                "report_year": report.get("report_year"),
                "geography": report.get("geography"),
                "language": report.get("language"),
            }
            prompt = build_codebook_extraction_prompt(metadata, selected_chunks)
            custom_id = f"report:{report['id']}:extract:{prompt_version}"
            requests.append(
                make_response_request(
                    custom_id=custom_id,
                    model=model,
                    prompt=prompt,
                    report_id=str(report["id"]),
                    prompt_version=prompt_version,
                )
            )
            selected_counts[str(report["id"])] = len(selected_chunks)
            estimated_tokens += estimate_tokens(prompt)
            items.append(
                {
                    "request_custom_id": custom_id,
                    "report_id": report["id"],
                    "status": "pending",
                    "metadata": {"selected_chunk_ids": [chunk.chunk_id for chunk in selected_chunks]},
                }
            )

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        input_path = output_dir / f"codebook_extraction_{timestamp}.jsonl"
        create_jsonl_file(requests, input_path)

        batch_repo = BatchRepository(connection)
        item_repo = BatchItemRepository(connection)
        batch = batch_repo.create_batch_record(
            {
                "batch_kind": "codebook_extraction",
                "model": model,
                "prompt_version": prompt_version,
                "status": "created",
                "report_ids": [str(report["id"]) for report in reports],
                "input_path": str(input_path),
                "request_count": len(requests),
                "estimated_input_tokens": estimated_tokens,
                "estimated_output_tokens": len(requests) * 2000,
                "metadata": {"selected_counts": selected_counts, "dry_run": dry_run},
            }
        )
        for item in items:
            item["batch_id"] = batch["id"]
        item_repo.insert_items(items)

        openai_batch_id = None
        if submit:
            client = OpenAIBatchClient(settings.openai_api_key)
            uploaded = client.upload_batch_file(input_path)
            openai_batch = client.create_batch(
                uploaded.id,
                endpoint="/v1/responses",
                metadata={"db_batch_id": str(batch["id"]), "prompt_version": prompt_version, "kind": "codebook_extraction"},
            )
            openai_batch_id = openai_batch.id
            batch = batch_repo.update_batch_status(
                batch["id"],
                status=getattr(openai_batch, "status", "submitted"),
                openai_batch_id=openai_batch.id,
                input_file_id=uploaded.id,
                submitted_at=datetime.now(UTC),
            ) or batch

    return {
        "batch": batch,
        "report_count": len(reports),
        "request_count": len(requests),
        "selected_counts": selected_counts,
        "estimated_input_tokens": estimated_tokens,
        "input_path": str(input_path),
        "openai_batch_id": openai_batch_id,
    }


def _load_reports(connection: Any, *, report_ids: list[UUID | str] | None, limit: int, eligibility: set[str] | None) -> list[dict[str, Any]]:
    if report_ids:
        rows = connection.execute(
            text("SELECT * FROM reports WHERE id::text = ANY(:report_ids) ORDER BY created_at"),
            {"report_ids": [str(report_id) for report_id in report_ids]},
        )
        return [dict(row._mapping) for row in rows]
    if eligibility:
        rows = connection.execute(
            text(
                """
                SELECT r.*
                FROM reports r
                WHERE EXISTS (SELECT 1 FROM document_chunks dc WHERE dc.report_id = r.id)
                  AND r.citation_info->'content_quality'->>'extraction_eligibility' = ANY(:eligibility)
                ORDER BY r.created_at DESC
                LIMIT :limit
                """
            ),
            {"eligibility": list(eligibility), "limit": limit},
        )
    else:
        rows = connection.execute(
            text(
                """
                SELECT r.*
                FROM reports r
                WHERE EXISTS (SELECT 1 FROM document_chunks dc WHERE dc.report_id = r.id)
                ORDER BY r.created_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    return [dict(row._mapping) for row in rows]


def _parse_report_ids(values: list[str] | None) -> list[UUID] | None:
    if not values:
        return None
    ids: list[UUID] = []
    for value in values:
        ids.extend(UUID(part.strip()) for part in value.split(",") if part.strip())
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an OpenAI Batch JSONL for LLM codebook extraction.")
    parser.add_argument("--report-id", action="append")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--eligibility", default="eligible,eligible_conditional")
    parser.add_argument("--model")
    parser.add_argument("--prompt-version")
    parser.add_argument("--output-dir", default="/data/hermes/batches")
    parser.add_argument("--max-chunks", type=int, default=30)
    parser.add_argument("--max-input-tokens", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()
    configure_logging()
    result = create_extraction_batch(
        report_ids=_parse_report_ids(args.report_id),
        limit=args.limit,
        eligibility={item.strip() for item in args.eligibility.split(",") if item.strip()} if args.eligibility else None,
        model=args.model,
        prompt_version=args.prompt_version,
        output_dir=args.output_dir,
        max_chunks=args.max_chunks,
        max_input_tokens=args.max_input_tokens,
        dry_run=args.dry_run,
        submit=args.submit,
    )
    print(
        "Created extraction batch: "
        f"reports={result['report_count']} requests={result['request_count']} "
        f"estimated_input_tokens={result['estimated_input_tokens']} input_path={result['input_path']} "
        f"batch_db_id={result['batch']['id']} openai_batch_id={result.get('openai_batch_id')}"
    )


if __name__ == "__main__":
    main()
