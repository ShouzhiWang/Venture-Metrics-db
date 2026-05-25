from app.config import get_settings
from app.services.auth import (
    create_session_token,
    hash_password,
    read_session_token,
    verify_password,
)


def test_password_hash_does_not_store_plaintext() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert "correct horse" not in password_hash
    assert verify_password("correct horse battery staple", password_hash)
    assert not verify_password("wrong password", password_hash)


def test_session_token_round_trip(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("AUTH_SESSION_TTL_SECONDS", "60")
    get_settings.cache_clear()

    token = create_session_token("00000000-0000-0000-0000-000000000001", now=100)
    payload = read_session_token(token, now=120)

    assert payload["sub"] == "00000000-0000-0000-0000-000000000001"
    assert payload["exp"] == 160
    get_settings.cache_clear()
