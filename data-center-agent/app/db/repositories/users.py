from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.db.repositories.base import BaseRepository, row_to_dict


class UserRepository(BaseRepository):
    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        row = self.connection.execute(
            text(
                """
                INSERT INTO users (name, email, password_hash)
                VALUES (:name, :email, :password_hash)
                RETURNING id, name, email, created_at, updated_at
                """
            ),
            {
                "name": values.get("name"),
                "email": values["email"],
                "password_hash": values["password_hash"],
            },
        ).first()
        result = row_to_dict(row)
        assert result is not None
        return result

    def get_by_email(self, email: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            text("SELECT * FROM users WHERE lower(email) = lower(:email)"),
            {"email": email},
        ).first()
        return row_to_dict(row)

    def get_public_by_id(self, user_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            text("SELECT id, name, email, created_at, updated_at FROM users WHERE id = CAST(:id AS uuid)"),
            {"id": user_id},
        ).first()
        return row_to_dict(row)
