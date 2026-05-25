from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError

try:
    from fastapi import APIRouter, Request, Response
except ImportError:  # pragma: no cover
    APIRouter = None
    Request = None
    Response = None
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.db.connection import get_engine
from app.db.repositories.users import UserRepository
from app.services.auth import (
    SESSION_COOKIE_NAME,
    AuthConfigError,
    InvalidSessionError,
    create_session_token,
    hash_password,
    normalize_email,
    public_user,
    read_session_token,
    verify_password,
)


if APIRouter:
    router = APIRouter(prefix="/api/auth")
else:  # pragma: no cover
    router = None


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validate_email(value)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validate_email(value)


def register_user(payload: dict[str, Any], response: Any | None = None) -> dict[str, Any]:
    data = RegisterRequest.model_validate(payload)
    settings = get_settings()
    if not settings.auth_session_secret:
        return _auth_error("auth_not_configured", "AUTH_SESSION_SECRET is required for authentication.", status=500)
    try:
        with get_engine().begin() as connection:
            user = UserRepository(connection).create(
                {
                    "name": data.name.strip(),
                    "email": normalize_email(str(data.email)),
                    "password_hash": hash_password(data.password),
                }
            )
    except IntegrityError:
        return _auth_error("email_exists", "An account with this email already exists.", status=409)
    token = create_session_token(str(user["id"]))
    if response is not None:
        _set_session_cookie(response, token, settings.auth_session_ttl_seconds)
    return {"ok": True, "user": public_user(user)}


def login_user(payload: dict[str, Any], response: Any | None = None) -> dict[str, Any]:
    data = LoginRequest.model_validate(payload)
    settings = get_settings()
    if not settings.auth_session_secret:
        return _auth_error("auth_not_configured", "AUTH_SESSION_SECRET is required for authentication.", status=500)
    with get_engine().begin() as connection:
        user = UserRepository(connection).get_by_email(normalize_email(str(data.email)))
    if not user or not verify_password(data.password, user.get("password_hash", "")):
        return _auth_error("invalid_credentials", "Email or password is incorrect.", status=401)
    token = create_session_token(str(user["id"]))
    if response is not None:
        _set_session_cookie(response, token, settings.auth_session_ttl_seconds)
    return {"ok": True, "user": public_user(user)}


def get_current_user_from_token(token: str | None) -> dict[str, Any]:
    return {"ok": True, "user": user_from_session_token(token)}


def user_from_session_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        payload = read_session_token(token)
    except (AuthConfigError, InvalidSessionError):
        return None
    with get_engine().begin() as connection:
        user = UserRepository(connection).get_public_by_id(str(payload["sub"]))
    return public_user(user)


def logout_user(response: Any | None = None) -> dict[str, Any]:
    if response is not None:
        response.delete_cookie(SESSION_COOKIE_NAME, path="/", samesite="lax")
    return {"ok": True}


def _set_session_cookie(response: Any, token: str, max_age: int) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        max_age=max_age,
        path="/",
    )


def _auth_error(code: str, message: str, *, status: int) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message, "status": status}}


def _validate_email(value: str) -> str:
    email = normalize_email(value)
    if "@" not in email or email.startswith("@") or email.endswith("@") or "." not in email.rsplit("@", 1)[-1]:
        raise ValueError("Enter a valid email address.")
    return email


if router:
    @router.post("/register")
    def register(request: RegisterRequest, response: Response) -> dict[str, Any]:
        result = register_user(request.model_dump(), response)
        _set_error_status(response, result)
        return result

    @router.post("/login")
    def login(request: LoginRequest, response: Response) -> dict[str, Any]:
        result = login_user(request.model_dump(), response)
        _set_error_status(response, result)
        return result

    @router.post("/logout")
    def logout(response: Response) -> dict[str, Any]:
        return logout_user(response)

    @router.get("/me")
    def me(request: Request) -> dict[str, Any]:
        return get_current_user_from_token(request.cookies.get(SESSION_COOKIE_NAME))


def _set_error_status(response: Any, result: dict[str, Any]) -> None:
    if not result.get("ok") and result.get("error", {}).get("status"):
        response.status_code = int(result["error"]["status"])
