import json
from typing import Any

from sqlalchemy import text

from app.db.repositories.base import BaseRepository, row_to_dict


class FeedbackRepository(BaseRepository):
    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                INSERT INTO demo_feedback (answer_id, result_id, feedback_type, comment, metadata)
                VALUES (:answer_id, :result_id, :feedback_type, :comment, CAST(:metadata AS jsonb))
                RETURNING *
                """
            ),
            {
                "answer_id": values.get("answer_id"),
                "result_id": values.get("result_id"),
                "feedback_type": values["feedback_type"],
                "comment": values.get("comment"),
                "metadata": json.dumps(values.get("metadata") or {}, default=str),
            },
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result
