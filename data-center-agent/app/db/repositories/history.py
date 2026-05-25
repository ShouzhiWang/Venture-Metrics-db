from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.db.repositories.base import BaseRepository, row_to_dict


class ChatHistoryRepository(BaseRepository):
    def get_session_for_user(self, session_id: str, user_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            text(
                """
                SELECT * FROM chat_sessions
                WHERE id = CAST(:session_id AS uuid)
                  AND user_id = CAST(:user_id AS uuid)
                """
            ),
            {"session_id": session_id, "user_id": user_id},
        ).first()
        return row_to_dict(row)

    def create_session(self, user_id: str, title: str) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                INSERT INTO chat_sessions (user_id, title)
                VALUES (CAST(:user_id AS uuid), :title)
                RETURNING *
                """
            ),
            {"user_id": user_id, "title": title},
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def touch_session(self, session_id: str, title: str | None = None) -> None:
        self.connection.execute(
            text(
                """
                UPDATE chat_sessions
                SET updated_at = now(),
                    title = COALESCE(chat_sessions.title, :title)
                WHERE id = CAST(:session_id AS uuid)
                """
            ),
            {"session_id": session_id, "title": title},
        )

    def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str | None = None,
        tool_name: str | None = None,
        tool_payload: dict[str, Any] | list[Any] | None = None,
    ) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                INSERT INTO chat_messages (session_id, role, content, tool_name, tool_payload)
                VALUES (CAST(:session_id AS uuid), :role, :content, :tool_name, CAST(:tool_payload AS jsonb))
                RETURNING *
                """
            ),
            {
                "session_id": session_id,
                "role": role,
                "content": content,
                "tool_name": tool_name,
                "tool_payload": json.dumps(tool_payload, default=str) if tool_payload is not None else None,
            },
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def add_saved_result(
        self,
        *,
        user_id: str,
        session_id: str,
        query: str,
        result_summary: str,
        result_payload: dict[str, Any],
    ) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                INSERT INTO saved_search_results (user_id, session_id, query, result_summary, result_payload)
                VALUES (CAST(:user_id AS uuid), CAST(:session_id AS uuid), :query, :result_summary, CAST(:result_payload AS jsonb))
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "session_id": session_id,
                "query": query,
                "result_summary": result_summary,
                "result_payload": json.dumps(result_payload, default=str),
            },
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def list_saved_results(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                """
                SELECT
                  r.id,
                  r.user_id,
                  r.session_id,
                  r.query,
                  r.result_summary,
                  r.created_at,
                  s.title AS session_title
                FROM saved_search_results r
                LEFT JOIN chat_sessions s ON s.id = r.session_id
                WHERE r.user_id = CAST(:user_id AS uuid)
                ORDER BY r.created_at DESC
                LIMIT :limit
                """
            ),
            {"user_id": user_id, "limit": limit},
        )
        return [dict(row._mapping) for row in rows]

    def get_saved_result(self, result_id: str, user_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            text(
                """
                SELECT
                  r.*,
                  s.title AS session_title
                FROM saved_search_results r
                LEFT JOIN chat_sessions s ON s.id = r.session_id
                WHERE r.id = CAST(:result_id AS uuid)
                  AND r.user_id = CAST(:user_id AS uuid)
                """
            ),
            {"result_id": result_id, "user_id": user_id},
        ).first()
        return row_to_dict(row)
