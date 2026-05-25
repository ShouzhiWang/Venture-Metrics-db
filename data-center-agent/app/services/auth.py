from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from app.config import get_settings


PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 260_000
SESSION_COOKIE_NAME = "sdi_session"


class AuthConfigError(RuntimeError):
    pass


class InvalidSessionError(ValueError):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PASSWORD_ITERATIONS)
    return f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = password_hash.split("$", 3)
        if algorithm != PASSWORD_ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def create_session_token(user_id: str, *, now: int | None = None) -> str:
    settings = get_settings()
    secret = settings.auth_session_secret
    if not secret:
        raise AuthConfigError("AUTH_SESSION_SECRET is required for login sessions.")
    issued_at = now or int(time.time())
    payload = {
        "sub": user_id,
        "iat": issued_at,
        "exp": issued_at + settings.auth_session_ttl_seconds,
    }
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
    signature = _sign(payload_b64, secret)
    return f"{payload_b64}.{signature}"


def read_session_token(token: str, *, now: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    secret = settings.auth_session_secret
    if not secret:
        raise AuthConfigError("AUTH_SESSION_SECRET is required for login sessions.")
    try:
        payload_b64, signature = token.split(".", 1)
    except ValueError as exc:
        raise InvalidSessionError("Invalid session token.") from exc
    expected = _sign(payload_b64, secret)
    if not hmac.compare_digest(signature, expected):
        raise InvalidSessionError("Invalid session signature.")
    try:
        payload = json.loads(_b64decode(payload_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        raise InvalidSessionError("Invalid session payload.") from exc
    if int(payload.get("exp", 0)) < (now or int(time.time())):
        raise InvalidSessionError("Session expired.")
    if not payload.get("sub"):
        raise InvalidSessionError("Session subject is missing.")
    return payload


def public_user(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "name": row.get("name"),
        "email": row.get("email"),
        "created_at": row.get("created_at"),
    }


def _sign(payload_b64: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).digest()
    return _b64encode(digest)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")
