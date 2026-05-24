from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.db.repositories.base import BaseRepository, row_to_dict


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.12g}" for value in vector) + "]"


class SearchIndexRepository(BaseRepository):
    def upsert_search_item(self, item: dict[str, Any]) -> dict[str, Any]:
        params = self._normalize_item(item)
        row = self.connection.execute(
            text(
                """
                INSERT INTO search_index (
                  object_type, object_id, title, content, search_text,
                  source_id, report_id, variable_id, dataset_id, chunk_id,
                  geography, time_coverage, availability, source_url, local_path,
                  evidence_quote, rank_weight, metadata, embedding_status
                )
                VALUES (
                  :object_type, :object_id, :title, :content, :search_text,
                  :source_id, :report_id, :variable_id, :dataset_id, :chunk_id,
                  :geography, :time_coverage, :availability, :source_url, :local_path,
                  :evidence_quote, :rank_weight, CAST(:metadata AS jsonb), 'pending'
                )
                ON CONFLICT (object_type, object_id) DO UPDATE SET
                  title = EXCLUDED.title,
                  content = EXCLUDED.content,
                  search_text = EXCLUDED.search_text,
                  source_id = EXCLUDED.source_id,
                  report_id = EXCLUDED.report_id,
                  variable_id = EXCLUDED.variable_id,
                  dataset_id = EXCLUDED.dataset_id,
                  chunk_id = EXCLUDED.chunk_id,
                  geography = EXCLUDED.geography,
                  time_coverage = EXCLUDED.time_coverage,
                  availability = EXCLUDED.availability,
                  source_url = EXCLUDED.source_url,
                  local_path = EXCLUDED.local_path,
                  evidence_quote = EXCLUDED.evidence_quote,
                  rank_weight = EXCLUDED.rank_weight,
                  metadata = EXCLUDED.metadata,
                  embedding = CASE
                    WHEN search_index.search_text = EXCLUDED.search_text THEN search_index.embedding
                    ELSE NULL
                  END,
                  embedding_provider = CASE
                    WHEN search_index.search_text = EXCLUDED.search_text THEN search_index.embedding_provider
                    ELSE NULL
                  END,
                  embedding_model = CASE
                    WHEN search_index.search_text = EXCLUDED.search_text THEN search_index.embedding_model
                    ELSE NULL
                  END,
                  embedding_dimension = CASE
                    WHEN search_index.search_text = EXCLUDED.search_text THEN search_index.embedding_dimension
                    ELSE NULL
                  END,
                  embedding_status = CASE
                    WHEN search_index.search_text = EXCLUDED.search_text THEN search_index.embedding_status
                    ELSE 'pending'
                  END,
                  updated_at = now()
                RETURNING *
                """
            ),
            params,
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def get_pending_embedding_items(self, limit: int, object_types: list[str] | None = None, force: bool = False) -> list[dict[str, Any]]:
        where = ["embedding_status IN ('pending', 'failed')" if not force else "1 = 1"]
        params: dict[str, Any] = {"limit": limit}
        if object_types:
            where.append("object_type = ANY(:object_types)")
            params["object_types"] = object_types
        rows = self.connection.execute(
            text(
                f"""
                SELECT *
                FROM search_index
                WHERE {' AND '.join(where)}
                ORDER BY updated_at, created_at
                LIMIT :limit
                """
            ),
            params,
        )
        return [dict(row._mapping) for row in rows]

    def update_embedding(self, item_id: Any, vector: list[float], *, provider: str, model: str, dimension: int, normalized: bool) -> None:
        self.connection.execute(
            text(
                """
                UPDATE search_index
                SET embedding = CAST(:embedding AS vector),
                    embedding_provider = :provider,
                    embedding_model = :model,
                    embedding_dimension = :dimension,
                    embedding_normalized = :normalized,
                    embedding_status = 'embedded',
                    metadata = coalesce(metadata, '{}'::jsonb) - 'embedding_error',
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": str(item_id),
                "embedding": vector_literal(vector),
                "provider": provider,
                "model": model,
                "dimension": dimension,
                "normalized": normalized,
            },
        )

    def mark_embedding_failed(self, item_id: Any, error: str) -> None:
        self.connection.execute(
            text(
                """
                UPDATE search_index
                SET embedding_status = 'failed',
                    metadata = coalesce(metadata, '{}'::jsonb) || CAST(:error AS jsonb),
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": str(item_id), "error": json.dumps({"embedding_error": error})},
        )

    def count_by_status(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                """
                SELECT object_type, embedding_status, count(*) AS count
                FROM search_index
                GROUP BY object_type, embedding_status
                ORDER BY object_type, embedding_status
                """
            )
        )
        return [dict(row._mapping) for row in rows]

    def delete_by_object_type(self, object_type: str) -> int:
        result = self.connection.execute(
            text("DELETE FROM search_index WHERE object_type = :object_type"),
            {"object_type": object_type},
        )
        return result.rowcount or 0

    def keyword_search(
        self,
        query: str,
        object_types: list[str] | None = None,
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        where, params = self._filter_clauses(object_types, filters)
        params.update({"query": query, "pattern": f"%{query}%", "limit": limit})
        rows = self.connection.execute(
            text(
                f"""
                SELECT *,
                  greatest(similarity(search_text, :query), CASE WHEN search_text ILIKE :pattern THEN 0.25 ELSE 0 END) * rank_weight AS score,
                  left(search_text, 500) AS snippet
                FROM search_index
                WHERE {' AND '.join(where)}
                  AND (search_text ILIKE :pattern OR similarity(search_text, :query) > 0.05)
                ORDER BY score DESC, updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        )
        return [dict(row._mapping) for row in rows]

    def semantic_search(
        self,
        query_embedding: list[float],
        *,
        provider: str,
        model: str,
        dimension: int,
        object_types: list[str] | None = None,
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        where, params = self._filter_clauses(object_types, filters)
        params.update(
            {
                "embedding": vector_literal(query_embedding),
                "provider": provider,
                "model": model,
                "dimension": dimension,
                "limit": limit,
            }
        )
        rows = self.connection.execute(
            text(
                f"""
                SELECT *,
                  ((1 - (embedding <=> CAST(:embedding AS vector))) * rank_weight) AS score,
                  left(search_text, 500) AS snippet
                FROM search_index
                WHERE {' AND '.join(where)}
                  AND embedding_status = 'embedded'
                  AND embedding_provider = :provider
                  AND embedding_model = :model
                  AND embedding_dimension = :dimension
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :limit
                """
            ),
            params,
        )
        return [dict(row._mapping) for row in rows]

    def hybrid_search(
        self,
        query: str,
        query_embedding: list[float] | None = None,
        *,
        provider: str | None = None,
        model: str | None = None,
        dimension: int | None = None,
        object_types: list[str] | None = None,
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        keyword = self.keyword_search(query, object_types=object_types, limit=limit, filters=filters)
        if query_embedding is None or not provider or not model or not dimension:
            return keyword
        semantic = self.semantic_search(
            query_embedding,
            provider=provider,
            model=model,
            dimension=dimension,
            object_types=object_types,
            limit=limit,
            filters=filters,
        )
        merged: dict[str, dict[str, Any]] = {}
        for row in keyword:
            key = str(row["id"])
            merged[key] = {**row, "score": float(row.get("score") or 0) + 0.25}
        for row in semantic:
            key = str(row["id"])
            if key in merged:
                merged[key]["score"] = float(merged[key].get("score") or 0) + float(row.get("score") or 0)
            else:
                merged[key] = row
        return sorted(merged.values(), key=lambda row: float(row.get("score") or 0), reverse=True)[:limit]

    def embedded_count(self, *, provider: str, model: str, dimension: int) -> int:
        row = self.connection.execute(
            text(
                """
                SELECT count(*) AS count
                FROM search_index
                WHERE embedding_status = 'embedded'
                  AND embedding_provider = :provider
                  AND embedding_model = :model
                  AND embedding_dimension = :dimension
                """
            ),
            {"provider": provider, "model": model, "dimension": dimension},
        ).first()
        return int(row._mapping["count"]) if row else 0

    def _normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "object_type",
            "object_id",
            "title",
            "content",
            "search_text",
            "source_id",
            "report_id",
            "variable_id",
            "dataset_id",
            "chunk_id",
            "geography",
            "time_coverage",
            "availability",
            "source_url",
            "local_path",
            "evidence_quote",
            "rank_weight",
        )
        params = {key: item.get(key) for key in keys}
        for key in ("object_id", "source_id", "report_id", "variable_id", "dataset_id", "chunk_id"):
            if params.get(key) is not None:
                params[key] = str(params[key])
        params["availability"] = params.get("availability") or "unclear"
        params["rank_weight"] = params.get("rank_weight") or 1.0
        params["metadata"] = json.dumps(item.get("metadata") or {}, default=str)
        return params

    def _filter_clauses(
        self,
        object_types: list[str] | None,
        filters: dict[str, Any] | None,
    ) -> tuple[list[str], dict[str, Any]]:
        where = ["1 = 1"]
        params: dict[str, Any] = {}
        if object_types:
            where.append("object_type = ANY(:object_types)")
            params["object_types"] = object_types
        if filters:
            if filters.get("public_only"):
                where.append("availability NOT ILIKE '%private%'")
            if filters.get("geography"):
                where.append("(geography ILIKE :geography OR search_text ILIKE :geography)")
                params["geography"] = f"%{filters['geography']}%"
            if filters.get("time_range"):
                where.append("(time_coverage ILIKE :time_range OR search_text ILIKE :time_range)")
                params["time_range"] = f"%{filters['time_range']}%"
        return where, params
