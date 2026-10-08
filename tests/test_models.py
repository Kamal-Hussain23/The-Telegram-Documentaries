"""Boundary contract: raw Telegram JSON is parsed into typed models at the edge."""

import pytest
from pydantic import ValidationError
from telegram_documentaries.models import Chat, Message, Update

SAMPLE_UPDATE = {
    "update_id": 1001,
    "message": {
        "message_id": 42,
        "date": 1759740000,
        "chat": {"id": 895425501, "type": "private"},
        "text": "hello",
    },
}


def test_parses_a_text_message() -> None:
    update = Update.model_validate(SAMPLE_UPDATE)

    assert update.update_id == 1001
    assert update.message is not None
    assert update.message.message_id == 42
    assert update.message.chat.id == 895425501
    assert update.message.chat.type == "private"
    assert update.message.text == "hello"


def test_message_without_text_still_yields_a_chat() -> None:
    payload = {
        "update_id": 1002,
        "message": {
            "message_id": 43,
            "date": 1759740001,
            "chat": {"id": 555, "type": "private"},
        },
    }

    update = Update.model_validate(payload)

    assert update.message is not None
    assert update.message.text is None
    assert update.message.chat.id == 555


def test_update_without_a_message_is_allowed() -> None:
    """Channel edits, callbacks etc. arrive without a `message` key."""

    update = Update.model_validate({"update_id": 1003})

    assert update.message is None


def test_missing_update_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Update.model_validate({"message": {"message_id": 1, "chat": {"id": 1}}})


def test_missing_chat_is_rejected() -> None:
    """A message we cannot route is invalid — never a raw dict downstream."""

    with pytest.raises(ValidationError):
        Update.model_validate({"update_id": 1, "message": {"message_id": 1}})


def test_chat_and_message_are_typed_models() -> None:
    update = Update.model_validate(SAMPLE_UPDATE)

    assert isinstance(update.message, Message)
    assert isinstance(update.message.chat, Chat)
