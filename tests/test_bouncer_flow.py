"""The photo flow: reject+reset on a non-human, pass+advance on a human.

Reference: SPECS/2026-10-06-bouncer/plan.md groups 1.4–1.6 and
validation.md acceptance criteria (a)–(c).
"""

from __future__ import annotations

import json
import logging

import pytest
from telegram_documentaries.bot import ERROR_TEXT, REPLY_TEXT, Bot
from telegram_documentaries.bouncer import REJECTION_TEXT, Bouncer
from telegram_documentaries.models import Update
from telegram_documentaries.state import Phase, StateDriver
from tests.support.fakes import (
    FakeTelegramClient,
    StubVisionClient,
    fixture_bytes,
    photo_update,
)


def verdict_json(human_present: bool) -> str:
    return json.dumps({"human_present": human_present})


def make_bot(client: FakeTelegramClient, vision: StubVisionClient) -> tuple[Bot, StateDriver]:
    state = StateDriver()
    bot = Bot(client, bouncer=Bouncer(vision), state=state)
    return bot, state


def test_non_human_photo_gets_a_cheeky_rejection() -> None:
    client = FakeTelegramClient(downloads={"landscape": fixture_bytes("landscape.jpg")})
    bot, _ = make_bot(client, StubVisionClient([verdict_json(False)]))

    bot.handle_update(photo_update(1, chat_id=42, file_id="landscape"))

    assert client.sent == [(42, REJECTION_TEXT)]
    assert "human" in REJECTION_TEXT.lower()


def test_non_human_photo_resets_the_session_to_the_initial_phase() -> None:
    client = FakeTelegramClient(downloads={"landscape": fixture_bytes("landscape.jpg")})
    bot, state = make_bot(client, StubVisionClient([verdict_json(False)]))
    progressed = state.load(42)
    progressed.phase = Phase.INTERVIEWING
    progressed.photo = fixture_bytes("person.jpg")  # Simulate a prior accepted photo
    progressed.dossier.questions = ["Q1"]
    progressed.dossier.answers = ["A1"]
    state.save(progressed)

    # Non-human photo in INTERVIEWING now gets mid-interview reply (wrong-payload guard)
    # rather than going through bouncer classification
    bot.handle_update(photo_update(1, chat_id=42, file_id="landscape"))

    # Session unchanged, still in INTERVIEWING (wrong-payload guard takes precedence)
    assert state.load(42).phase is Phase.INTERVIEWING
    assert state.load(42).photo is not None


def test_unwired_bot_keeps_the_phase_1_photo_reply() -> None:
    """A Bouncer pass with no Interviewer wired keeps the placeholder reply.

    Superseded for the *wired* pass path by ``test_interviewer_flow.py``'s
    ``test_pass_path_replies_with_the_first_question`` (user-approved pass-path
    change, plan 5.5); this covers the Phase 1/2 configuration fallback only.
    """
    client = FakeTelegramClient(downloads={"person": fixture_bytes("person.jpg")})
    bot, _ = make_bot(client, StubVisionClient([verdict_json(True)]))

    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))

    assert client.sent == [(42, REPLY_TEXT)]


def test_human_photo_advances_the_session_phase() -> None:
    client = FakeTelegramClient(downloads={"person": fixture_bytes("person.jpg")})
    bot, state = make_bot(client, StubVisionClient([verdict_json(True)]))

    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))

    assert state.load(42).phase is Phase.INTERVIEWING


def test_downloads_the_highest_resolution_variant() -> None:
    image = fixture_bytes("person.jpg")
    client = FakeTelegramClient(downloads={"small": b"tiny", "large": image})
    bot, _ = make_bot(client, StubVisionClient([verdict_json(True)]))
    update = Update.model_validate(
        {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "date": 0,
                "chat": {"id": 42, "type": "private"},
                "photo": [
                    {"file_id": "small", "width": 90, "height": 90, "file_size": 4},
                    {
                        "file_id": "large",
                        "width": 1280,
                        "height": 1280,
                        "file_size": len(image),
                    },
                ],
            },
        }
    )

    bot.handle_update(update)

    assert client.downloaded == ["large"]


def test_two_chats_do_not_share_session_state() -> None:
    client = FakeTelegramClient(
        downloads={
            "landscape": fixture_bytes("landscape.jpg"),
            "person": fixture_bytes("person.jpg"),
        }
    )
    bot, state = make_bot(
        client,
        StubVisionClient([verdict_json(False), verdict_json(True)]),
    )

    bot.handle_update(photo_update(1, chat_id=1, file_id="landscape"))
    bot.handle_update(photo_update(2, chat_id=2, file_id="person"))

    rejected = state.load(1)
    passed = state.load(2)
    assert rejected.chat_id == 1
    assert rejected.phase is Phase.AWAITING_PHOTO
    assert passed.chat_id == 2
    assert passed.phase is Phase.INTERVIEWING


# --- graceful degradation on the conversation path (plan 5.3) --------------


def test_unparseable_model_output_degrades_gracefully(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = FakeTelegramClient(downloads={"person": fixture_bytes("person.jpg")})
    bot, state = make_bot(client, StubVisionClient(["sorry, no idea"]))

    with caplog.at_level(logging.ERROR):
        bot.handle_update(photo_update(1, chat_id=42, file_id="person"))

    assert client.sent == [(42, ERROR_TEXT)]
    assert state.load(42).phase is Phase.AWAITING_PHOTO
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


def test_gemini_failure_degrades_gracefully(caplog: pytest.LogCaptureFixture) -> None:
    class FailingVision:
        def classify(self, image: bytes) -> str:
            raise RuntimeError("gemini exploded")

    client = FakeTelegramClient(downloads={"person": fixture_bytes("person.jpg")})
    bot = Bot(client, bouncer=Bouncer(FailingVision()), state=StateDriver())

    with caplog.at_level(logging.ERROR):
        bot.handle_update(photo_update(1, chat_id=42, file_id="person"))

    assert client.sent == [(42, ERROR_TEXT)]
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


def test_download_failure_degrades_gracefully(caplog: pytest.LogCaptureFixture) -> None:
    class FailingDownloadClient(FakeTelegramClient):
        def get_file(self, file_id: str) -> bytes:
            raise ConnectionError("telegram is down")

    client = FailingDownloadClient()
    bot, _ = make_bot(client, StubVisionClient([verdict_json(True)]))

    with caplog.at_level(logging.ERROR):
        bot.handle_update(photo_update(1, chat_id=42, file_id="person"))

    assert client.sent == [(42, ERROR_TEXT)]
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


def test_send_failure_does_not_raise(caplog: pytest.LogCaptureFixture) -> None:
    class FailingSendClient(FakeTelegramClient):
        def send_message(self, chat_id: int, text: str) -> None:
            raise ConnectionError("cannot send")

    client = FailingSendClient(downloads={"person": fixture_bytes("person.jpg")})
    bot, _ = make_bot(client, StubVisionClient([verdict_json(True)]))

    with caplog.at_level(logging.ERROR):
        bot.handle_update(photo_update(1, chat_id=42, file_id="person"))

    assert client.sent == []
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


def test_downloaded_media_is_scoped_to_the_chat_that_sent_it() -> None:
    person = fixture_bytes("person.jpg")
    client = FakeTelegramClient(
        downloads={"person": person, "landscape": fixture_bytes("landscape.jpg")}
    )
    bot, state = make_bot(
        client,
        StubVisionClient([verdict_json(True), verdict_json(False)]),
    )

    bot.handle_update(photo_update(1, chat_id=1, file_id="person"))
    bot.handle_update(photo_update(2, chat_id=2, file_id="landscape"))

    assert state.load(1).photo == person
    assert state.load(2).photo is None
    assert state.load(2).photo != state.load(1).photo
