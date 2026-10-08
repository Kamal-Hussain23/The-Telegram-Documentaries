"""The gateway: every inbound message gets the same hardcoded reply."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from telegram_documentaries.bot import REPLY_TEXT, Bot
from telegram_documentaries.logutil import describe_message
from telegram_documentaries.models import Message, Update


class FakeClient:
    """Scripted Telegram client: returns batches, records sends."""

    def __init__(self, batches: list[list[Update]] | None = None) -> None:
        self._batches = list(batches or [])
        self.sent: list[tuple[int, str]] = []
        self.offsets: list[int | None] = []

    def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[Update]:
        self.offsets.append(offset)
        if not self._batches:
            raise KeyboardInterrupt
        return self._batches.pop(0)

    def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


def make_update(update_id: int, chat_id: int, text: str | None = "hello") -> Update:
    message: dict[str, Any] = {
        "message_id": update_id,
        "date": 0,
        "chat": {"id": chat_id, "type": "private"},
    }
    if text is not None:
        message["text"] = text
    return Update.model_validate({"update_id": update_id, "message": message})


def test_reply_is_the_hardcoded_message() -> None:
    client = FakeClient()
    bot = Bot(client)

    bot.handle_update(make_update(1, chat_id=42))

    assert client.sent == [(42, REPLY_TEXT)]


def test_reply_text_is_hey_mate() -> None:
    assert REPLY_TEXT == "hey mate!"


def test_every_message_gets_the_same_reply() -> None:
    client = FakeClient()
    bot = Bot(client)

    for i in range(1, 4):
        bot.handle_update(make_update(i, chat_id=42, text=f"msg {i}"))

    assert client.sent == [(42, "hey mate!"), (42, "hey mate!"), (42, "hey mate!")]


def test_replies_to_the_sender_not_someone_else() -> None:
    client = FakeClient()
    bot = Bot(client)

    bot.handle_update(make_update(1, chat_id=999))

    assert client.sent[0][0] == 999


def test_update_without_a_message_is_ignored() -> None:
    client = FakeClient()
    bot = Bot(client)

    bot.handle_update(Update.model_validate({"update_id": 5}))

    assert client.sent == []


def test_non_text_message_still_gets_a_reply() -> None:
    """A photo in phase 1 is still 'a message' — same hardcoded reply."""

    client = FakeClient()
    bot = Bot(client)

    bot.handle_update(make_update(1, chat_id=42, text=None))

    assert client.sent == [(42, REPLY_TEXT)]


def test_run_polls_with_a_monotonically_advancing_offset() -> None:
    batch_one = [make_update(10, chat_id=1), make_update(11, chat_id=2)]
    batch_two = [make_update(12, chat_id=3)]
    client = FakeClient(batches=[batch_one, batch_two])
    bot = Bot(client)

    try:
        bot.run(timeout=1)
    except KeyboardInterrupt:
        pass

    # First poll has no offset; each later poll resumes one past the last
    # update_id seen (10 -> 11, 11 -> 12, 12 -> 13).
    assert client.offsets == [None, 12, 13]
    assert client.sent == [
        (1, "hey mate!"),
        (2, "hey mate!"),
        (3, "hey mate!"),
    ]


def test_run_survives_a_client_error_and_keeps_polling() -> None:
    class FlakyClient(FakeClient):
        def __init__(self) -> None:
            super().__init__(batches=[[], [make_update(20, chat_id=7)]])
            self.calls = 0

        def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[Update]:
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("network hiccup")
            return super().get_updates(offset, timeout)

    client = FlakyClient()
    bot = Bot(client)

    try:
        bot.run(timeout=1, error_backoff=0)
    except KeyboardInterrupt:
        pass

    assert client.sent == [(7, "hey mate!")]


# --- inbound/outbound message logging -------------------------------------


def test_logs_the_incoming_message_text(caplog: pytest.LogCaptureFixture) -> None:
    bot = Bot(FakeClient())

    with caplog.at_level(logging.INFO, logger="telegram_documentaries.bot"):
        bot.handle_update(make_update(1, chat_id=42, text="Hi"))

    assert "chat_id=42" in caplog.text
    assert "'Hi'" in caplog.text


def test_logs_the_outgoing_reply(caplog: pytest.LogCaptureFixture) -> None:
    bot = Bot(FakeClient())

    with caplog.at_level(logging.INFO, logger="telegram_documentaries.bot"):
        bot.handle_update(make_update(1, chat_id=42, text="Hi"))

    assert "replied" in caplog.text
    assert "hey mate!" in caplog.text


def test_logs_a_non_text_message_as_media(caplog: pytest.LogCaptureFixture) -> None:
    bot = Bot(FakeClient())

    with caplog.at_level(logging.INFO, logger="telegram_documentaries.bot"):
        bot.handle_update(make_update(1, chat_id=42, text=None))

    assert "chat_id=42" in caplog.text
    assert "media" in caplog.text


def test_ignored_update_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    bot = Bot(FakeClient())

    with caplog.at_level(logging.DEBUG, logger="telegram_documentaries.bot"):
        bot.handle_update(Update.model_validate({"update_id": 9}))

    assert "ignoring update 9" in caplog.text


def test_describe_message_truncates_long_text() -> None:
    update = make_update(1, chat_id=7, text="x" * 500)

    assert update.message is not None
    described = describe_message(update.message)

    assert len(described) < 200
    # repr() wraps the text in quotes, so the ellipsis sits just inside one.
    assert described.endswith("…'")


def test_describe_message_never_logs_none_text() -> None:
    message = Message.model_validate({"message_id": 1, "chat": {"id": 5}})

    assert "None" not in describe_message(message)
    assert "media" in describe_message(message)
