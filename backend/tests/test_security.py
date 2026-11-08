import asyncio

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


def test_csrf_check_accepts_matching_token():
    asyncio.run(main.require_csrf(csrf_cookie="csrf-value", csrf_header="csrf-value"))


def test_csrf_check_rejects_missing_or_mismatched_token():
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.require_csrf(csrf_cookie="csrf-value", csrf_header="different"))
    assert error.value.status_code == 403

    with pytest.raises(HTTPException) as missing:
        asyncio.run(main.require_csrf(csrf_cookie="csrf-value", csrf_header=None))
    assert missing.value.status_code == 403


def test_training_dataset_accepts_valid_conversations():
    dataset = main.TrainingDatasetInput(
        name="Python basics",
        examples=[
            {"messages": [
                {"role": "user", "content": "What is Python?"},
                {"role": "assistant", "content": "Python is a programming language."},
            ]},
            {"messages": [
                {"role": "user", "content": "What is an API?"},
                {"role": "assistant", "content": "An API lets software communicate."},
            ]},
        ],
    )
    assert len(dataset.examples) == 2


def test_training_dataset_rejects_examples_without_assistant_answer():
    with pytest.raises(ValidationError):
        main.TrainingDatasetInput(
            name="Invalid set",
            examples=[
                {"messages": [
                    {"role": "user", "content": "Question only"},
                    {"role": "user", "content": "Another user message"},
                ]},
                {"messages": [
                    {"role": "user", "content": "Question"},
                    {"role": "assistant", "content": "Answer"},
                ]},
            ],
        )


def test_training_job_restricts_epochs_and_lora_rank():
    valid = main.TrainingJobInput(dataset_id="12345678-1234-1234-1234-123456789012", epochs=2, lora_rank=16)
    assert valid.epochs == 2
    with pytest.raises(ValidationError):
        main.TrainingJobInput(dataset_id="12345678-1234-1234-1234-123456789012", epochs=10, lora_rank=16)
