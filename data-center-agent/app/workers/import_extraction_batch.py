import argparse
import csv
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from app.agents.llm_codebook_parser import LLMParseError, parse_extraction_response
from app.agents.llm_evidence import verify_llm_item
from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.chunks import ChunkRepository
from app.db.repositories.llm_batches import BatchItemRepository, BatchRepository
from app.db.repositories.reports import ReportRepository
from app.db.repositories.variables import VariableRepository
from app.llm.openai_batch_client import OpenAIBatchClient
from app.models.llm_codebook import LLMExtractedItem
from app.models.variable import ExtractedVariable
from app.utils.logging import configure_logging


ACCEPTED_FIELDS = [
    "report_id",
    "report_title",
    "raw_variable_name",
    "item_type",
    "definition",
    "measurement_method",
    "unit",
    "data_source_text",
    "data_source_type",
    "availability",
    "temporal_coverage",
    "geographic_coverage",
    "evidence_chunk_id",
    "evidence_quote",
    "page_number",
    "confidence_score",
    "review_status",
    "reason",
    "model",
    "prompt_version",
    "batch_id",
]

REJECTED_FIELDS = [
    "report_id",
    "report_title",
    "raw_variable_name",
    "item_type",
    "evidence_quote",
    "reject_reason",
    "review_decision",
    "raw_response_excerpt",
    "batch_id",
]


def import_extraction_batch(
    *,
    batch_id: str,
    output_dir: str | Path = "/data/hermes/batches",
    review_csv: str | Path,
    insert: bool = False,
    min_confidence: float = 0.70,
    include_chart_metrics: bool = False,
    export_rejected: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    output_dir = Path(output_dir)
    review_csv = Path(review_csv)
    rejected_csv = review_csv.with_name(f"{review_csv.stem}_rejected{review_csv.suffix}")

    engine = get_engine()
    with engine.begin() as connection:
        batch_repo = BatchRepository(connection)
        item_repo = BatchItemRepository(connection)
        report_repo = ReportRepository(connection)
        chunk_repo = ChunkRepository(connection)
        variable_repo = VariableRepository(connection)
        batch = _resolve_batch(batch_repo, batch_id)
        if not batch:
            raise ValueError(f"Batch not found: {batch_id}")

        output_path = _ensure_output_file(batch, output_dir, settings.openai_api_key)
        rows = _read_jsonl(output_path)
        db_items = {item["request_custom_id"]: item for item in item_repo.get_items_by_batch(batch["id"])}

        accepted_rows: list[dict[str, Any]] = []
        rejected_rows: list[dict[str, Any]] = []
        to_insert: list[ExtractedVariable] = []

        for raw in rows:
            custom_id = raw.get("custom_id")
            item_row = db_items.get(custom_id)
            report_id = str(item_row.get("report_id") if item_row else _report_id_from_custom_id(custom_id))
            report = report_repo.get(report_id) if report_id else None
            chunks = chunk_repo.list_by_report(report_id) if report_id else []
            chunks_by_id = {str(chunk["id"]): chunk for chunk in chunks}
            raw_response_excerpt = json.dumps(raw, ensure_ascii=True)[:500]

            try:
                parsed = parse_extraction_response(raw)
                validation_errors = None
            except LLMParseError as exc:
                parsed = []
                validation_errors = [str(exc)]
                rejected_rows.append(_rejected_row(report_id, report, None, None, str(exc), raw_response_excerpt, batch))

            accepted_for_item: list[dict[str, Any]] = []
            rejected_for_item: list[dict[str, Any]] = []
            for index, parsed_item in enumerate(parsed):
                passed, reject_reason, score = verify_llm_item(parsed_item, chunks_by_id)
                if parsed_item.item_type == "chart_metric" and include_chart_metrics:
                    passed = bool(parsed_item.evidence_chunk_id in chunks_by_id)
                    score = min(score, 0.65)
                    reject_reason = None if passed else "missing_evidence_chunk_id"
                if not passed or score < min_confidence:
                    reason = reject_reason or f"confidence_below_min:{score}"
                    row = _rejected_row(report_id, report, parsed_item, index, reason, raw_response_excerpt, batch)
                    rejected_rows.append(row)
                    rejected_for_item.append(row)
                    continue

                chunk = chunks_by_id[str(parsed_item.evidence_chunk_id)]
                review_status = "pending" if score >= 0.80 else "needs_review"
                accepted = _accepted_row(report_id, report, parsed_item, chunk, score, review_status, batch)
                accepted_rows.append(accepted)
                accepted_for_item.append(accepted)
                variable = _to_extracted_variable(report_id, parsed_item, chunk, score, review_status, batch)
                if _should_insert(parsed_item, variable, insert, min_confidence, include_chart_metrics, variable_repo):
                    to_insert.append(variable)

            item_repo.update_item_result(
                custom_id,
                status="parsed" if not validation_errors else "failed",
                raw_response=raw,
                parsed_items=[item.model_dump(mode="json") for item in parsed],
                validation_errors=validation_errors,
                metadata={"accepted_count": len(accepted_for_item), "rejected_count": len(rejected_for_item)},
            )

        review_csv.parent.mkdir(parents=True, exist_ok=True)
        _write_csv(review_csv, ACCEPTED_FIELDS, accepted_rows)
        if export_rejected or rejected_rows:
            _write_csv(rejected_csv, REJECTED_FIELDS, rejected_rows)
        inserted = variable_repo.insert_many_report_variables(to_insert) if insert and to_insert else []
        batch_repo.mark_imported(
            batch["id"],
            output_path=str(output_path),
            metadata={"accepted": len(accepted_rows), "rejected": len(rejected_rows), "inserted": len(inserted)},
        )

    return {
        "accepted": len(accepted_rows),
        "rejected": len(rejected_rows),
        "inserted": len(inserted),
        "review_csv": str(review_csv),
        "rejected_csv": str(rejected_csv),
    }


def _ensure_output_file(batch: dict[str, Any], output_dir: Path, api_key: str | None) -> Path:
    if batch.get("output_path") and Path(batch["output_path"]).exists():
        return Path(batch["output_path"])
    if not batch.get("output_file_id"):
        raise ValueError("Batch has no output_path or output_file_id yet.")
    client = OpenAIBatchClient(api_key)
    path = output_dir / f"{batch['id']}_output.jsonl"
    return client.download_output_file(batch["output_file_id"], path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _resolve_batch(repo: BatchRepository, identifier: str) -> dict[str, Any] | None:
    try:
        return repo.get_batch_by_id(UUID(identifier))
    except ValueError:
        return repo.get_batch_by_openai_id(identifier)


def _report_id_from_custom_id(custom_id: str | None) -> str | None:
    if not custom_id:
        return None
    parts = custom_id.split(":")
    return parts[1] if len(parts) >= 2 and parts[0] == "report" else None


def _accepted_row(
    report_id: str,
    report: dict[str, Any] | None,
    item: LLMExtractedItem,
    chunk: dict[str, Any],
    score: float,
    review_status: str,
    batch: dict[str, Any],
) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "report_title": (report or {}).get("title"),
        "raw_variable_name": item.raw_variable_name,
        "item_type": item.item_type,
        "definition": item.definition,
        "measurement_method": item.measurement_method,
        "unit": item.unit,
        "data_source_text": item.data_source_text,
        "data_source_type": item.data_source_type,
        "availability": item.availability,
        "temporal_coverage": item.temporal_coverage,
        "geographic_coverage": item.geographic_coverage,
        "evidence_chunk_id": item.evidence_chunk_id,
        "evidence_quote": item.evidence_quote,
        "page_number": chunk.get("page_number"),
        "confidence_score": score,
        "review_status": review_status,
        "reason": item.reason,
        "model": batch["model"],
        "prompt_version": batch["prompt_version"],
        "batch_id": batch["id"],
    }


def _rejected_row(
    report_id: str | None,
    report: dict[str, Any] | None,
    item: LLMExtractedItem | None,
    index: int | None,
    reject_reason: str,
    raw_response_excerpt: str,
    batch: dict[str, Any],
) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "report_title": (report or {}).get("title") if report else None,
        "raw_variable_name": item.raw_variable_name if item else None,
        "item_type": item.item_type if item else None,
        "evidence_quote": item.evidence_quote if item else None,
        "reject_reason": reject_reason,
        "review_decision": None,
        "raw_response_excerpt": raw_response_excerpt,
        "batch_id": batch["id"],
    }


def _to_extracted_variable(
    report_id: str,
    item: LLMExtractedItem,
    chunk: dict[str, Any],
    score: float,
    review_status: str,
    batch: dict[str, Any],
) -> ExtractedVariable:
    return ExtractedVariable(
        report_id=UUID(report_id),
        raw_variable_name=item.raw_variable_name or "",
        definition=item.definition,
        measurement_method=item.measurement_method,
        unit=item.unit,
        data_source_text=item.data_source_text,
        data_source_type=item.data_source_type if item.data_source_type in {"public_dataset", "private_database", "survey", "estimate", "report_table", "unknown"} else "unknown",
        availability=item.availability if item.availability in {"obtainable", "not_obtainable", "private", "unclear"} else "unclear",
        temporal_coverage=item.temporal_coverage,
        geographic_coverage=item.geographic_coverage,
        page_number=chunk.get("page_number"),
        evidence_chunk_id=UUID(str(item.evidence_chunk_id)),
        evidence_quote=item.evidence_quote,
        confidence_score=score,
        review_status=review_status,
        metadata={"extractor": "openai_batch", "item_type": item.item_type, "batch_id": str(batch["id"]), "prompt_version": batch["prompt_version"], "reason": item.reason},
    )


def _should_insert(
    item: LLMExtractedItem,
    variable: ExtractedVariable,
    insert: bool,
    min_confidence: float,
    include_chart_metrics: bool,
    variable_repo: VariableRepository,
) -> bool:
    if not insert:
        return False
    if variable.confidence_score < min_confidence:
        return False
    if item.item_type != "codebook_variable" and not (include_chart_metrics and item.item_type == "chart_metric"):
        return False
    existing = variable_repo.get_report_variables_by_report(variable.report_id)
    key = (variable.raw_variable_name.strip().lower(), str(variable.evidence_chunk_id))
    return key not in {(row.get("raw_variable_name", "").strip().lower(), str(row.get("evidence_chunk_id"))) for row in existing}


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Import OpenAI Batch codebook extraction results.")
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--output-dir", default="/data/hermes/batches")
    parser.add_argument("--review-csv", required=True)
    parser.add_argument("--insert", action="store_true")
    parser.add_argument("--min-confidence", type=float, default=0.70)
    parser.add_argument("--include-chart-metrics", action="store_true")
    parser.add_argument("--export-rejected", action="store_true")
    args = parser.parse_args()
    configure_logging()
    result = import_extraction_batch(
        batch_id=args.batch_id,
        output_dir=args.output_dir,
        review_csv=args.review_csv,
        insert=args.insert,
        min_confidence=args.min_confidence,
        include_chart_metrics=args.include_chart_metrics,
        export_rejected=args.export_rejected,
    )
    print(
        "Imported extraction batch: "
        f"accepted={result['accepted']} rejected={result['rejected']} inserted={result['inserted']} "
        f"review_csv={result['review_csv']} rejected_csv={result['rejected_csv']}"
    )


if __name__ == "__main__":
    main()
