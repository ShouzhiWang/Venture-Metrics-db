from __future__ import annotations

import argparse
import json

from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.search_index import SearchIndexRepository
from app.llm.embedding_client import EmbeddingClient, LocalEmbeddingClient, validate_dimension
from app.utils.logging import configure_logging
from app.workers.build_search_index import parse_object_types


def embed_search_index(
    *,
    limit: int | None = None,
    object_types: list[str] | None = None,
    model: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    client: EmbeddingClient | None = None,
) -> dict:
    settings = get_settings()
    batch_limit = limit or settings.search_index_batch_size
    max_chars = settings.search_index_max_text_chars
    engine = get_engine()
    with engine.begin() as connection:
        repo = SearchIndexRepository(connection)
        items = repo.get_pending_embedding_items(batch_limit, object_types=object_types, force=force)
        if dry_run:
            return {
                "dry_run": True,
                "pending_count": len(items),
                "samples": [
                    {"id": str(item["id"]), "object_type": item["object_type"], "title": item.get("title")}
                    for item in items[:5]
                ],
            }
        embedding_client = client or LocalEmbeddingClient(model=model)
        embedded = 0
        failed = 0
        texts = [(item.get("search_text") or "")[:max_chars] for item in items]
        try:
            results = embedding_client.embed_texts(texts)
        except Exception as exc:
            for item in items:
                repo.mark_embedding_failed(item["id"], str(exc))
            raise
        for item, result in zip(items, results, strict=True):
            try:
                validate_dimension(result.dimension, settings.embedding_dimension, model=result.model)
                repo.update_embedding(
                    item["id"],
                    result.vector,
                    provider=result.provider,
                    model=result.model,
                    dimension=result.dimension,
                    normalized=result.normalized,
                )
                embedded += 1
            except Exception as exc:
                repo.mark_embedding_failed(item["id"], str(exc))
                failed += 1
    return {
        "dry_run": False,
        "provider": (client.provider if client else "local"),
        "model": model or (client.model if client else settings.local_embedding_model),
        "embedded": embedded,
        "failed": failed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed pending search_index rows with the active local embedding model.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--object-types", help="Comma-separated object types.")
    parser.add_argument("--model", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    configure_logging()
    result = embed_search_index(
        limit=args.limit,
        object_types=parse_object_types(args.object_types) if args.object_types else None,
        model=args.model,
        dry_run=args.dry_run,
        force=args.force,
    )
    print(json.dumps(result, default=str, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
