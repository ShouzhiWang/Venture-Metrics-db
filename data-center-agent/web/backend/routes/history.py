from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter, Request, Response
except ImportError:  # pragma: no cover
    APIRouter = None
    Request = None
    Response = None

from app.db.connection import get_engine
from app.db.repositories.history import ChatHistoryRepository
from app.services.auth import SESSION_COOKIE_NAME
from web.backend.routes.auth import user_from_session_token


if APIRouter:
    router = APIRouter(prefix="/api/history")
else:  # pragma: no cover
    router = None


def list_history_for_token(token: str | None, limit: int = 50) -> dict[str, Any]:
    user = user_from_session_token(token)
    if not user:
        return _auth_required()
    with get_engine().begin() as connection:
        rows = ChatHistoryRepository(connection).list_saved_results(user["id"], limit=min(max(limit, 1), 100))
    return {"ok": True, "items": [_public_history_item(row) for row in rows]}


def get_history_result_for_token(token: str | None, result_id: str) -> dict[str, Any]:
    user = user_from_session_token(token)
    if not user:
        return _auth_required()
    with get_engine().begin() as connection:
        row = ChatHistoryRepository(connection).get_saved_result(result_id, user["id"])
    if not row:
        return {"ok": False, "error": {"code": "not_found", "message": "History item not found.", "status": 404}}
    return {"ok": True, "item": _public_history_item(row, include_payload=True)}


def _public_history_item(row: dict[str, Any], *, include_payload: bool = False) -> dict[str, Any]:
    item = {
        "id": str(row["id"]),
        "session_id": str(row["session_id"]) if row.get("session_id") else None,
        "title": row.get("session_title") or row.get("query") or "Untitled search",
        "query": row.get("query"),
        "result_summary": row.get("result_summary"),
        "created_at": row.get("created_at"),
    }
    if include_payload:
        item["result_payload"] = row.get("result_payload")
    return item


def _auth_required() -> dict[str, Any]:
    return {"ok": False, "error": {"code": "auth_required", "message": "Login is required.", "status": 401}}


def _set_error_status(response: Any, result: dict[str, Any]) -> None:
    if not result.get("ok") and result.get("error", {}).get("status"):
        response.status_code = int(result["error"]["status"])


if router:
    @router.get("")
    def list_history(request: Request, response: Response, limit: int = 50) -> dict[str, Any]:
        result = list_history_for_token(request.cookies.get(SESSION_COOKIE_NAME), limit=limit)
        _set_error_status(response, result)
        return result

    @router.get("/{result_id}")
    def get_history_result(request: Request, response: Response, result_id: str) -> dict[str, Any]:
        result = get_history_result_for_token(request.cookies.get(SESSION_COOKIE_NAME), result_id)
        _set_error_status(response, result)
        return result
