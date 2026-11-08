import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import main


def test_password_hash_verifies_without_storing_plaintext():
    password = "correct-horse-battery"
    encoded = main.password_hash.hash(password)
    assert encoded != password
    assert main.password_hash.verify(password, encoded)
    assert not main.password_hash.verify("wrong-password", encoded)


def test_signed_session_token_contains_user_subject(monkeypatch):
    monkeypatch.setattr(main, "JWT_SECRET", "test-secret-that-is-long-enough-for-unit-tests")
    token = main.token_for("user-123")
    payload = main.jwt.decode(token, main.JWT_SECRET, algorithms=[main.JWT_ALGORITHM])
    assert payload["sub"] == "user-123"
    assert "exp" in payload


def test_auth_input_rejects_invalid_email_and_short_password():
    with pytest.raises(ValidationError):
        main.AuthInput(name="Ajmal", email="not-an-email", password="short")


def test_chat_input_enforces_message_limits():
    with pytest.raises(ValidationError):
        main.ChatRequest(message="")
    with pytest.raises(ValidationError):
        main.ChatRequest(message="x" * 12001)


@pytest.mark.asyncio
async def test_csrf_check_accepts_matching_token():
    await main.require_csrf(csrf_cookie="csrf-value", csrf_header="csrf-value")


@pytest.mark.asyncio
async def test_csrf_check_rejects_missing_or_mismatched_token():
    with pytest.raises(HTTPException) as error:
        await main.require_csrf(csrf_cookie="csrf-value", csrf_header="different")
    assert error.value.status_code == 403

    with pytest.raises(HTTPException) as missing:
        await main.require_csrf(csrf_cookie="csrf-value", csrf_header=None)
    assert missing.value.status_code == 403
