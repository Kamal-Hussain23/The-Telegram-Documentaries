"""The Telegram client speaks to the Bot API through an injected session."""

from __future__ import annotations

from typing import Any

import pytest
from telegram_documentaries.client import TelegramApiError, TelegramClient


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Stands in for `requests.Session` so tests never touch the network."""

    def __init__(
        self, get_payload: dict[str, Any] | None = None, post_payload: dict[str, Any] | None = None
    ) -> None:
        self.get_payload = get_payload or {"ok": True, "result": []}
        self.post_payload = post_payload or {"ok": True, "result": {}}
        self.get_calls: list[dict[str, Any]] = []
        self.post_calls: list[dict[str, Any]] = []

    def get(
        self, url: str, params: dict[str, Any] | None = None, timeout: float | None = None
    ) -> FakeResponse:
        self.get_calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse(self.get_payload)

    def post(
        self, url: str, json: dict[str, Any] | None = None, timeout: float | None = None
    ) -> FakeResponse:
        self.post_calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse(self.post_payload)


def test_get_updates_requests_long_polling_with_an_offset() -> None:
    session = FakeSession(
        get_payload={
            "ok": True,
            "result": [
                {
                    "update_id": 7,
                    "message": {
                        "message_id": 1,
                        "date": 0,
                        "chat": {"id": 42, "type": "private"},
                        "text": "hi",
                    },
                }
            ],
        }
    )
    client = TelegramClient(token="t", session=session)

    updates = client.get_updates(offset=100, timeout=30)

    call = session.get_calls[0]
    assert call["url"].endswith("/getUpdates")
    assert call["params"]["offset"] == 100
    assert call["params"]["timeout"] == 30
    assert len(updates) == 1
    assert updates[0].message is not None
    assert updates[0].message.chat.id == 42


def test_first_poll_omits_the_offset() -> None:
    session = FakeSession()
    client = TelegramClient(token="t", session=session)

    client.get_updates(offset=None)

    assert "offset" not in session.get_calls[0]["params"]


def test_send_message_posts_the_text_to_the_chat() -> None:
    session = FakeSession()
    client = TelegramClient(token="t", session=session)

    client.send_message(chat_id=42, text="hey mate!")

    call = session.post_calls[0]
    assert call["url"].endswith("/sendMessage")
    assert call["json"]["chat_id"] == 42
    assert call["json"]["text"] == "hey mate!"


def test_api_error_flag_raises_loudly() -> None:
    session = FakeSession(post_payload={"ok": False, "description": "chat not found"})
    client = TelegramClient(token="t", session=session)

    with pytest.raises(TelegramApiError) as excinfo:
        client.send_message(chat_id=42, text="hey mate!")

    assert "chat not found" in str(excinfo.value)
