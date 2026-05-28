from __future__ import annotations

import uuid
from typing import Any

try:
    from fastapi import APIRouter, Request, Response
except ImportError:  # pragma: no cover
    APIRouter = None
    Request = None
    Response = None
from pydantic import BaseModel, Field

from app.db.connection import get_engine
from app.db.repositories.projects import ResearchProjectRepository
from app.services.auth import SESSION_COOKIE_NAME
from web.backend.routes.auth import user_from_session_token


if APIRouter:
    router = APIRouter(prefix="/api/projects")
else:  # pragma: no cover
    router = None


class ProjectRequest(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=2000)
    research_question: str | None = Field(default=None, max_length=1000)


class ProjectItemRequest(BaseModel):
    item_type: str
    item_id: str | None = None
    title: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=3000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectItemNoteRequest(BaseModel):
    note: str | None = Field(default=None, max_length=3000)


class ProjectQueryRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    history: list[dict[str, str]] = Field(default_factory=list)


ALLOWED_ITEM_TYPES = {"variable", "report", "source", "organization", "concept", "chat_session", "search_result", "note"}


def list_projects_for_token(token: str | None) -> dict[str, Any]:
    user = user_from_session_token(token)
    if not user:
        return _auth_required()
    with get_engine().begin() as connection:
        projects = ResearchProjectRepository(connection).list_projects(user["id"])
    return {"ok": True, "projects": [_public_project(row) for row in projects]}


def create_project_for_token(token: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    user = user_from_session_token(token)
    if not user:
        return _auth_required()
    data = ProjectRequest.model_validate(payload)
    with get_engine().begin() as connection:
        project = ResearchProjectRepository(connection).create_project(
            user_id=user["id"],
            title=data.title.strip(),
            description=_clean_optional(data.description),
            research_question=_clean_optional(data.research_question),
        )
    return {"ok": True, "project": _public_project(project)}


def get_project_for_token(token: str | None, project_id: str) -> dict[str, Any]:
    user = user_from_session_token(token)
    if not user:
        return _auth_required()
    with get_engine().begin() as connection:
        repo = ResearchProjectRepository(connection)
        project = repo.get_project(project_id, user["id"])
        if not project:
            return _not_found("Project not found.")
        items = repo.list_items(project_id, user["id"])
    return {"ok": True, "project": _public_project(project), "items": [_public_item(row) for row in items]}


def update_project_for_token(token: str | None, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    user = user_from_session_token(token)
    if not user:
        return _auth_required()
    data = ProjectRequest.model_validate(payload)
    with get_engine().begin() as connection:
        project = ResearchProjectRepository(connection).update_project(
            project_id=project_id,
            user_id=user["id"],
            title=data.title.strip(),
            description=_clean_optional(data.description),
            research_question=_clean_optional(data.research_question),
        )
    if not project:
        return _not_found("Project not found.")
    return {"ok": True, "project": _public_project(project)}


def add_project_item_for_token(token: str | None, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    user = user_from_session_token(token)
    if not user:
        return _auth_required()
    data = ProjectItemRequest.model_validate(payload)
    if data.item_type not in ALLOWED_ITEM_TYPES:
        return _bad_request("Invalid project item type.")
    with get_engine().begin() as connection:
        item = ResearchProjectRepository(connection).add_item(
            project_id=project_id,
            user_id=user["id"],
            item_type=data.item_type,
            item_id=data.item_id,
            title=_clean_optional(data.title),
            note=_clean_optional(data.note),
            metadata=data.metadata,
        )
    if not item:
        return _not_found("Project not found.")
    return {"ok": True, "item": _public_item(item)}


def update_project_item_note_for_token(token: str | None, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    user = user_from_session_token(token)
    if not user:
        return _auth_required()
    data = ProjectItemNoteRequest.model_validate(payload)
    with get_engine().begin() as connection:
        item = ResearchProjectRepository(connection).update_item_note(item_id=item_id, user_id=user["id"], note=data.note)
    if not item:
        return _not_found("Project item not found.")
    return {"ok": True, "item": _public_item(item)}


def remove_project_item_for_token(token: str | None, item_id: str) -> dict[str, Any]:
    user = user_from_session_token(token)
    if not user:
        return _auth_required()
    with get_engine().begin() as connection:
        removed = ResearchProjectRepository(connection).remove_item(item_id=item_id, user_id=user["id"])
    if not removed:
        return _not_found("Project item not found.")
    return {"ok": True}


def export_project_markdown_for_token(token: str | None, project_id: str) -> dict[str, Any]:
    result = get_project_for_token(token, project_id)
    if not result.get("ok"):
        return result
    project = result["project"]
    items = result["items"]
    lines = [
        f"# {project['title']}",
        "",
    ]
    if project.get("research_question"):
        lines.extend(["## Research Question", project["research_question"], ""])
    if project.get("description"):
        lines.extend(["## Description", project["description"], ""])
    lines.append("## Saved Items")
    for item in items:
        lines.append(f"- **{item['item_type']}**: {item.get('title') or 'Untitled'}")
        if item.get("note"):
            lines.append(f"  - Note: {item['note']}")
    return {"ok": True, "markdown": "\n".join(lines)}


def _public_project(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "title": row.get("title"),
        "description": row.get("description"),
        "research_question": row.get("research_question"),
        "item_count": int(row.get("item_count") or 0),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _public_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "project_id": str(row["project_id"]),
        "item_type": row.get("item_type"),
        "item_id": str(row["item_id"]) if row.get("item_id") else None,
        "title": row.get("title"),
        "note": row.get("note"),
        "metadata": row.get("metadata") or {},
        "created_at": row.get("created_at"),
    }


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _auth_required() -> dict[str, Any]:
    return {"ok": False, "error": {"code": "auth_required", "message": "Login is required.", "status": 401}}


def _not_found(message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": "not_found", "message": message, "status": 404}}


def _bad_request(message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": "bad_request", "message": message, "status": 400}}


def _set_error_status(response: Any, result: dict[str, Any]) -> None:
    if not result.get("ok") and result.get("error", {}).get("status"):
        response.status_code = int(result["error"]["status"])


if router:
    @router.get("")
    def list_projects(request: Request, response: Response) -> dict[str, Any]:
        result = list_projects_for_token(request.cookies.get(SESSION_COOKIE_NAME))
        _set_error_status(response, result)
        return result

    @router.post("")
    def create_project(request: Request, response: Response, payload: ProjectRequest) -> dict[str, Any]:
        result = create_project_for_token(request.cookies.get(SESSION_COOKIE_NAME), payload.model_dump())
        _set_error_status(response, result)
        return result

    @router.get("/{project_id}")
    def get_project(request: Request, response: Response, project_id: str) -> dict[str, Any]:
        result = get_project_for_token(request.cookies.get(SESSION_COOKIE_NAME), project_id)
        _set_error_status(response, result)
        return result

    @router.put("/{project_id}")
    def update_project(request: Request, response: Response, project_id: str, payload: ProjectRequest) -> dict[str, Any]:
        result = update_project_for_token(request.cookies.get(SESSION_COOKIE_NAME), project_id, payload.model_dump())
        _set_error_status(response, result)
        return result

    @router.post("/{project_id}/items")
    def add_project_item(request: Request, response: Response, project_id: str, payload: ProjectItemRequest) -> dict[str, Any]:
        result = add_project_item_for_token(request.cookies.get(SESSION_COOKIE_NAME), project_id, payload.model_dump())
        _set_error_status(response, result)
        return result

    @router.put("/items/{item_id}")
    def update_project_item_note(request: Request, response: Response, item_id: str, payload: ProjectItemNoteRequest) -> dict[str, Any]:
        result = update_project_item_note_for_token(request.cookies.get(SESSION_COOKIE_NAME), item_id, payload.model_dump())
        _set_error_status(response, result)
        return result

    @router.delete("/items/{item_id}")
    def remove_project_item(request: Request, response: Response, item_id: str) -> dict[str, Any]:
        result = remove_project_item_for_token(request.cookies.get(SESSION_COOKIE_NAME), item_id)
        _set_error_status(response, result)
        return result

    @router.get("/{project_id}/export.md")
    def export_project_markdown(request: Request, response: Response, project_id: str) -> dict[str, Any]:
        result = export_project_markdown_for_token(request.cookies.get(SESSION_COOKIE_NAME), project_id)
        _set_error_status(response, result)
        return result

    @router.post("/{project_id}/query")
    def query_project(request: Request, response: Response, project_id: str, payload: ProjectQueryRequest) -> dict[str, Any]:
        token = request.cookies.get(SESSION_COOKIE_NAME)
        user = user_from_session_token(token)
        if not user:
            result = _auth_required()
            _set_error_status(response, result)
            return result

        project_result = get_project_for_token(token, project_id)
        if not project_result.get("ok"):
            _set_error_status(response, project_result)
            return project_result

        project = project_result["project"]
        project_title = (project.get("title") or "").strip()
        research_question = (project.get("research_question") or "").strip()

        user_message = (payload.message or "").strip()

        # Local import to avoid circular imports at module level
        from web.backend.routes.chat import ChatRequest, _finalize_chat_response, handle_chat  # noqa: PLC0415

        chat_request = ChatRequest(
            message=user_message,
            conversation_id=payload.conversation_id,
            history=payload.history,
            context={
                "project_id": project_id,
                "project_title": project_title,
                "research_question": research_question,
            },
        )
        chat_result = handle_chat(chat_request.model_dump())
        return _finalize_chat_response(user["id"], chat_request, chat_result)
