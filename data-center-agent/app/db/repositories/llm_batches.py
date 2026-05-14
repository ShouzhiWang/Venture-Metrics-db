import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from app.db.repositories.base import BaseRepository, row_to_dict


def _json(value: Any) -> str | None:
    return json.dumps(value, default=str) if value is not None else None


class BatchRepository(BaseRepository):
    def create_batch_record(self, values: dict[str, Any]) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                INSERT INTO llm_extraction_batches (
                  provider, batch_kind, model, prompt_version, openai_batch_id,
                  input_file_id, output_file_id, error_file_id, status, report_ids,
                  input_path, output_path, error_path, request_count,
                  estimated_input_tokens, estimated_output_tokens, estimated_cost,
                  submitted_at, completed_at, imported_at, error_message, metadata
                )
                VALUES (
                  :provider, :batch_kind, :model, :prompt_version, :openai_batch_id,
                  :input_file_id, :output_file_id, :error_file_id, :status, CAST(:report_ids AS jsonb),
                  :input_path, :output_path, :error_path, :request_count,
                  :estimated_input_tokens, :estimated_output_tokens, :estimated_cost,
                  :submitted_at, :completed_at, :imported_at, :error_message, CAST(:metadata AS jsonb)
                )
                RETURNING *
                """
            ),
            {
                "provider": values.get("provider", "openai"),
                "batch_kind": values["batch_kind"],
                "model": values["model"],
                "prompt_version": values["prompt_version"],
                "openai_batch_id": values.get("openai_batch_id"),
                "input_file_id": values.get("input_file_id"),
                "output_file_id": values.get("output_file_id"),
                "error_file_id": values.get("error_file_id"),
                "status": values.get("status", "created"),
                "report_ids": _json(values.get("report_ids")),
                "input_path": values.get("input_path"),
                "output_path": values.get("output_path"),
                "error_path": values.get("error_path"),
                "request_count": values.get("request_count"),
                "estimated_input_tokens": values.get("estimated_input_tokens"),
                "estimated_output_tokens": values.get("estimated_output_tokens"),
                "estimated_cost": values.get("estimated_cost"),
                "submitted_at": values.get("submitted_at"),
                "completed_at": values.get("completed_at"),
                "imported_at": values.get("imported_at"),
                "error_message": values.get("error_message"),
                "metadata": _json(values.get("metadata")),
            },
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def update_batch_status(self, batch_id: UUID | str, **values: Any) -> dict[str, Any] | None:
        row = self.connection.execute(
            text(
                """
                UPDATE llm_extraction_batches
                SET status = COALESCE(:status, status),
                    openai_batch_id = COALESCE(:openai_batch_id, openai_batch_id),
                    input_file_id = COALESCE(:input_file_id, input_file_id),
                    output_file_id = COALESCE(:output_file_id, output_file_id),
                    error_file_id = COALESCE(:error_file_id, error_file_id),
                    output_path = COALESCE(:output_path, output_path),
                    error_path = COALESCE(:error_path, error_path),
                    submitted_at = COALESCE(:submitted_at, submitted_at),
                    completed_at = COALESCE(:completed_at, completed_at),
                    error_message = COALESCE(:error_message, error_message),
                    metadata = COALESCE(metadata, '{}'::jsonb) || COALESCE(CAST(:metadata AS jsonb), '{}'::jsonb),
                    updated_at = now()
                WHERE id = :id
                RETURNING *
                """
            ),
            {
                "id": str(batch_id),
                "status": values.get("status"),
                "openai_batch_id": values.get("openai_batch_id"),
                "input_file_id": values.get("input_file_id"),
                "output_file_id": values.get("output_file_id"),
                "error_file_id": values.get("error_file_id"),
                "output_path": values.get("output_path"),
                "error_path": values.get("error_path"),
                "submitted_at": values.get("submitted_at"),
                "completed_at": values.get("completed_at"),
                "error_message": values.get("error_message"),
                "metadata": _json(values.get("metadata")),
            },
        ).first()
        return row_to_dict(row)

    def get_batch_by_id(self, batch_id: UUID | str) -> dict[str, Any] | None:
        return row_to_dict(self.connection.execute(text("SELECT * FROM llm_extraction_batches WHERE id = :id"), {"id": str(batch_id)}).first())

    def get_batch_by_openai_id(self, openai_batch_id: str) -> dict[str, Any] | None:
        return row_to_dict(
            self.connection.execute(
                text("SELECT * FROM llm_extraction_batches WHERE openai_batch_id = :openai_batch_id"),
                {"openai_batch_id": openai_batch_id},
            ).first()
        )

    def list_batches(self, *, batch_kind: str | None = None, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                """
                SELECT * FROM llm_extraction_batches
                WHERE (:batch_kind IS NULL OR batch_kind = :batch_kind)
                  AND (:status IS NULL OR status = :status)
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"batch_kind": batch_kind, "status": status, "limit": limit},
        )
        return [dict(row._mapping) for row in rows]

    def mark_imported(self, batch_id: UUID | str, **values: Any) -> dict[str, Any] | None:
        row = self.connection.execute(
            text(
                """
                UPDATE llm_extraction_batches
                SET status = 'imported',
                    imported_at = now(),
                    output_path = COALESCE(:output_path, output_path),
                    error_path = COALESCE(:error_path, error_path),
                    metadata = COALESCE(metadata, '{}'::jsonb) || COALESCE(CAST(:metadata AS jsonb), '{}'::jsonb),
                    updated_at = now()
                WHERE id = :id
                RETURNING *
                """
            ),
            {"id": str(batch_id), "output_path": values.get("output_path"), "error_path": values.get("error_path"), "metadata": _json(values.get("metadata"))},
        ).first()
        return row_to_dict(row)


class BatchItemRepository(BaseRepository):
    def insert_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not items:
            return []
        rows = self.connection.execute(
            text(
                """
                INSERT INTO llm_extraction_items (
                  batch_id, request_custom_id, report_id, status, raw_response,
                  parsed_items, validation_errors, metadata
                )
                VALUES (
                  :batch_id, :request_custom_id, :report_id, :status, CAST(:raw_response AS jsonb),
                  CAST(:parsed_items AS jsonb), CAST(:validation_errors AS jsonb), CAST(:metadata AS jsonb)
                )
                RETURNING *
                """
            ),
            [
                {
                    "batch_id": str(item["batch_id"]),
                    "request_custom_id": item["request_custom_id"],
                    "report_id": str(item["report_id"]) if item.get("report_id") else None,
                    "status": item.get("status", "pending"),
                    "raw_response": _json(item.get("raw_response")),
                    "parsed_items": _json(item.get("parsed_items")),
                    "validation_errors": _json(item.get("validation_errors")),
                    "metadata": _json(item.get("metadata")),
                }
                for item in items
            ],
        )
        return [dict(row._mapping) for row in rows]

    def get_items_by_batch(self, batch_id: UUID | str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text("SELECT * FROM llm_extraction_items WHERE batch_id = :batch_id ORDER BY created_at"),
            {"batch_id": str(batch_id)},
        )
        return [dict(row._mapping) for row in rows]

    def update_item_result(self, request_custom_id: str, **values: Any) -> dict[str, Any] | None:
        row = self.connection.execute(
            text(
                """
                UPDATE llm_extraction_items
                SET status = COALESCE(:status, status),
                    raw_response = COALESCE(CAST(:raw_response AS jsonb), raw_response),
                    parsed_items = COALESCE(CAST(:parsed_items AS jsonb), parsed_items),
                    validation_errors = COALESCE(CAST(:validation_errors AS jsonb), validation_errors),
                    metadata = COALESCE(metadata, '{}'::jsonb) || COALESCE(CAST(:metadata AS jsonb), '{}'::jsonb),
                    updated_at = now()
                WHERE request_custom_id = :request_custom_id
                RETURNING *
                """
            ),
            {
                "request_custom_id": request_custom_id,
                "status": values.get("status"),
                "raw_response": _json(values.get("raw_response")),
                "parsed_items": _json(values.get("parsed_items")),
                "validation_errors": _json(values.get("validation_errors")),
                "metadata": _json(values.get("metadata")),
            },
        ).first()
        return row_to_dict(row)

    def update_item_status(self, request_custom_id: str, status: str) -> dict[str, Any] | None:
        return self.update_item_result(request_custom_id, status=status)
