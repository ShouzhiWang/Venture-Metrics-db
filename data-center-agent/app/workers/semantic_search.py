from __future__ import annotations

import argparse
import json

from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.search_index import SearchIndexRepository
from app.llm.embedding_client import EmbeddingClient, LocalEmbeddingClient
from app.utils.logging import configure_logging
from app.workers.build_search_index import parse_object_types


def semantic_search(
    query: str,
    *,
    object_types: list[str] | None = None,
    limit: int = 10,
    hybrid: bool = False,
    client: EmbeddingClient | None = None,
    filters: dict | None = None,
) -> dict:
    settings = get_settings()
    provider = client.provider if client else settings.embedding_provider
    model = client.model if client else settings.local_embedding_model
    dimension = client.dimension if client else settings.embedding_dimension
    engine = get_engine()
    with engine.begin() as connection:
        repo = SearchIndexRepository(connection)
        if repo.embedded_count(provider=provider, model=model, dimension=dimension) == 0:
            rows = repo.keyword_search(query, object_types=object_types, limit=limit, filters=filters)
            return {
                "query": query,
                "mode": "keyword_fallback",
                "warning": f"No embedded search_index rows found for provider={provider}, model={model}, dimension={dimension}.",
                "results": [_format_result(row) for row in rows],
            }
        embedding_client = client or LocalEmbeddingClient(model=model)
        embedded_query = embedding_client.embed_text(query)
        if hybrid:
            rows = repo.hybrid_search(
                query,
                embedded_query.vector,
                provider=embedded_query.provider,
                model=embedded_query.model,
                dimension=embedded_query.dimension,
                object_types=object_types,
                limit=limit,
                filters=filters,
            )
            mode = "hybrid"
        else:
            rows = repo.semantic_search(
                embedded_query.vector,
                provider=embedded_query.provider,
                model=embedded_query.model,
                dimension=embedded_query.dimension,
                object_types=object_types,
                limit=limit,
                filters=filters,
            )
            mode = "semantic"
    return {"query": query, "mode": mode, "results": [_format_result(row) for row in rows]}


def _format_result(row: dict) -> dict:
    return {
        "object_type": row.get("object_type"),
        "object_id": str(row.get("object_id")),
        "title": row.get("title"),
        "snippet": row.get("snippet") or (row.get("search_text") or "")[:500],
        "score": float(row.get("score") or 0),
        "availability": row.get("availability"),
        "geography": row.get("geography"),
        "time_coverage": row.get("time_coverage"),
        "source_id": str(row["source_id"]) if row.get("source_id") else None,
        "report_id": str(row["report_id"]) if row.get("report_id") else None,
        "variable_id": str(row["variable_id"]) if row.get("variable_id") else None,
        "dataset_id": str(row["dataset_id"]) if row.get("dataset_id") else None,
        "source_url": row.get("source_url"),
        "local_path": row.get("local_path"),
        "evidence_quote": row.get("evidence_quote"),
        "metadata": row.get("metadata") or {},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Semantic or hybrid search over embedded search_index rows.")
    parser.add_argument("query")
    parser.add_argument("--object-types", help="Comma-separated object types.")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--hybrid", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    configure_logging()
    result = semantic_search(
        args.query,
        object_types=parse_object_types(args.object_types) if args.object_types else None,
        limit=args.limit,
        hybrid=args.hybrid,
    )
    if args.json:
        print(json.dumps(result, default=str, ensure_ascii=True, indent=2))
    else:
        if result.get("warning"):
            print(f"Warning: {result['warning']}")
        for rank, row in enumerate(result["results"], start=1):
            print(f"{rank}. [{row['object_type']}] {row.get('title') or row['object_id']} score={row['score']:.4f}")
            print(f"   {row.get('snippet') or ''}")


if __name__ == "__main__":
    main()
