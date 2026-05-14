import argparse
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.llm_batches import BatchRepository
from app.llm.openai_batch_client import OpenAIBatchClient
from app.utils.logging import configure_logging


def batch_status(batch_id: str) -> dict[str, Any]:
    settings = get_settings()
    engine = get_engine()
    with engine.begin() as connection:
        repo = BatchRepository(connection)
        batch = _resolve_batch(repo, batch_id)
        if not batch:
            raise ValueError(f"Batch not found: {batch_id}")

        openai_status = None
        if batch.get("openai_batch_id") and settings.openai_api_key:
            client = OpenAIBatchClient(settings.openai_api_key)
            remote = client.retrieve_batch(batch["openai_batch_id"])
            openai_status = _object_to_dict(remote)
            updates = {
                "status": openai_status.get("status"),
                "output_file_id": openai_status.get("output_file_id"),
                "error_file_id": openai_status.get("error_file_id"),
                "completed_at": datetime.now(UTC) if openai_status.get("status") in {"completed", "failed", "expired", "cancelled"} else None,
                "metadata": {"openai_status": openai_status},
            }
            batch = repo.update_batch_status(batch["id"], **updates) or batch
    return {"batch": batch, "openai_status": openai_status}


def _resolve_batch(repo: BatchRepository, identifier: str) -> dict[str, Any] | None:
    try:
        return repo.get_batch_by_id(UUID(identifier))
    except ValueError:
        return repo.get_batch_by_openai_id(identifier)


def _object_to_dict(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return obj
    return {key: getattr(obj, key) for key in dir(obj) if not key.startswith("_") and isinstance(getattr(obj, key), (str, int, float, bool, type(None)))}


def main() -> None:
    parser = argparse.ArgumentParser(description="Check an OpenAI LLM extraction batch status.")
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args()
    configure_logging()
    result = batch_status(args.batch_id)
    batch = result["batch"]
    print(
        "Batch status: "
        f"db_id={batch['id']} openai_batch_id={batch.get('openai_batch_id')} status={batch.get('status')} "
        f"request_count={batch.get('request_count')} output_file_id={batch.get('output_file_id')} "
        f"error_file_id={batch.get('error_file_id')}"
    )


if __name__ == "__main__":
    main()
