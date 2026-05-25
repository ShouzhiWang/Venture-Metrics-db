from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.db.repositories.base import BaseRepository, row_to_dict


class ResearchProjectRepository(BaseRepository):
    def list_projects(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                """
                SELECT
                  p.*,
                  count(i.id)::int AS item_count
                FROM research_projects p
                LEFT JOIN project_items i ON i.project_id = p.id
                WHERE p.user_id = CAST(:user_id AS uuid)
                GROUP BY p.id
                ORDER BY p.updated_at DESC, p.created_at DESC
                """
            ),
            {"user_id": user_id},
        )
        return [dict(row._mapping) for row in rows]

    def get_project(self, project_id: str, user_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            text(
                """
                SELECT *
                FROM research_projects
                WHERE id = CAST(:project_id AS uuid)
                  AND user_id = CAST(:user_id AS uuid)
                """
            ),
            {"project_id": project_id, "user_id": user_id},
        ).first()
        return row_to_dict(row)

    def create_project(
        self,
        *,
        user_id: str,
        title: str,
        description: str | None = None,
        research_question: str | None = None,
    ) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                INSERT INTO research_projects (user_id, title, description, research_question)
                VALUES (CAST(:user_id AS uuid), :title, :description, :research_question)
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "title": title,
                "description": description,
                "research_question": research_question,
            },
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def update_project(
        self,
        *,
        project_id: str,
        user_id: str,
        title: str,
        description: str | None,
        research_question: str | None,
    ) -> dict[str, Any] | None:
        row = self.connection.execute(
            text(
                """
                UPDATE research_projects
                SET title = :title,
                    description = :description,
                    research_question = :research_question,
                    updated_at = now()
                WHERE id = CAST(:project_id AS uuid)
                  AND user_id = CAST(:user_id AS uuid)
                RETURNING *
                """
            ),
            {
                "project_id": project_id,
                "user_id": user_id,
                "title": title,
                "description": description,
                "research_question": research_question,
            },
        ).first()
        return row_to_dict(row)

    def list_items(self, project_id: str, user_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            text(
                """
                SELECT i.*
                FROM project_items i
                JOIN research_projects p ON p.id = i.project_id
                WHERE i.project_id = CAST(:project_id AS uuid)
                  AND p.user_id = CAST(:user_id AS uuid)
                ORDER BY i.created_at DESC
                """
            ),
            {"project_id": project_id, "user_id": user_id},
        )
        return [dict(row._mapping) for row in rows]

    def add_item(
        self,
        *,
        project_id: str,
        user_id: str,
        item_type: str,
        item_id: str | None = None,
        title: str | None = None,
        note: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        project = self.get_project(project_id, user_id)
        if not project:
            return None
        row = self.connection.execute(
            text(
                """
                INSERT INTO project_items (project_id, item_type, item_id, title, note, metadata)
                VALUES (
                  CAST(:project_id AS uuid),
                  :item_type,
                  CAST(:item_id AS uuid),
                  :title,
                  :note,
                  CAST(:metadata AS jsonb)
                )
                RETURNING *
                """
            ),
            {
                "project_id": project_id,
                "item_type": item_type,
                "item_id": item_id,
                "title": title,
                "note": note,
                "metadata": json.dumps(metadata or {}, default=str),
            },
        ).first()
        self.touch_project(project_id)
        return row_to_dict(row)

    def update_item_note(self, *, item_id: str, user_id: str, note: str | None) -> dict[str, Any] | None:
        row = self.connection.execute(
            text(
                """
                UPDATE project_items i
                SET note = :note
                FROM research_projects p
                WHERE p.id = i.project_id
                  AND p.user_id = CAST(:user_id AS uuid)
                  AND i.id = CAST(:item_id AS uuid)
                RETURNING i.*
                """
            ),
            {"item_id": item_id, "user_id": user_id, "note": note},
        ).first()
        result = row_to_dict(row)
        if result:
            self.touch_project(str(result["project_id"]))
        return result

    def remove_item(self, *, item_id: str, user_id: str) -> bool:
        row = self.connection.execute(
            text(
                """
                DELETE FROM project_items i
                USING research_projects p
                WHERE p.id = i.project_id
                  AND p.user_id = CAST(:user_id AS uuid)
                  AND i.id = CAST(:item_id AS uuid)
                RETURNING i.project_id
                """
            ),
            {"item_id": item_id, "user_id": user_id},
        ).first()
        if row:
            self.touch_project(str(row._mapping["project_id"]))
            return True
        return False

    def touch_project(self, project_id: str) -> None:
        self.connection.execute(
            text("UPDATE research_projects SET updated_at = now() WHERE id = CAST(:project_id AS uuid)"),
            {"project_id": project_id},
        )
