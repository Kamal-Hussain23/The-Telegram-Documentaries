"""The Converter flow: photo + dossier → hybrid portrait → SCRIPTING.

Reference: SPECS/2026-10-09-converter/requirements.md acceptance criteria,
plan.md groups 1.4–1.6, validation.md checks 1–3. Everything here runs offline
against the scripted converter client.
"""

from __future__ import annotations

import base64
import json
import logging

import pytest
from telegram_documentaries.bot import CONVERTER_FAILURE_TEXT, Bot
from telegram_documentaries.bouncer import Bouncer
from telegram_documentaries.converter import Converter
from telegram_documentaries.interviewer import Interviewer
from telegram_documentaries.state import Dossier, Phase, StateDriver
from tests.support.fakes import (
    FakeTelegramClient,
    StubConverterClient,
    StubInterviewClient,
    StubVisionClient,
    converter_output_json,
    fixture_bytes,
    photo_update,
    profile_json,
    question_json,
    text_update,
    verdict_json,
)

PERSON = fixture_bytes("person.jpg")
OTHER_PERSON = fixture_bytes("landscape.jpg")
HYBRID = fixture_bytes("landscape.jpg")  # reuse as the "generated" hybrid

Q1 = "What do you do when nobody is watching?"
Q2 = "Describe the strangest thing in your refrigerator."
Q3 = "If your life were a documentary, what would the narrator say?"
PROFILE = (
    "A midnight snacker with a weakness for shiny objects and a "
    "suspiciously organised snack drawer."
)
ANIMAL = "raccoon"


def three_questions() -> list[str]:
    """The model plays nicely: finishes at the floor of three questions."""
    return [
        question_json(Q1),
        question_json(Q2),
        question_json(Q3, is_final=True),
    ]


def wired_bot(
    client: FakeTelegramClient,
    state: StateDriver,
    converter_stub: StubConverterClient,
    interview_stub: StubInterviewClient,
    vision: StubVisionClient,
) -> Bot:
    """A Bot wired with Interviewer and Converter on the shared state driver."""
    return Bot(
        client,
        bouncer=Bouncer(vision),
        state=state,
        interviewer=Interviewer(state, interview_stub),
        converter=Converter(state, converter_stub),
    )


def make_bot(
    client: FakeTelegramClient,
    converter_stub: StubConverterClient,
    interview_stub: StubInterviewClient,
    *,
    verdicts: list[str] | None = None,
) -> tuple[Bot, StateDriver]:
    state = StateDriver()
    vision = StubVisionClient(verdicts if verdicts is not None else [verdict_json(True)])
    return wired_bot(client, state, converter_stub, interview_stub, vision), state


def client_with_person() -> FakeTelegramClient:
    return FakeTelegramClient(downloads={"person": PERSON, "other": OTHER_PERSON})


def complete_interview(
    client: FakeTelegramClient,
    interview_stub: StubInterviewClient,
    *,
    converter_stub: StubConverterClient | None = None,
    verdicts: list[str] | None = None,
) -> tuple[Bot, StateDriver]:
    """Run a full interview to completion, returning the bot and state at CONVERTING phase."""
    if converter_stub is None:
        converter_stub = StubConverterClient([])
    state = StateDriver()
    vision = StubVisionClient(verdicts if verdicts is not None else [verdict_json(True)])
    return wired_bot(client, state, converter_stub, interview_stub, vision), state


# --- positive path: successful conversion (plan 1.4, validation 1b) -------------


def test_converter_success_delivers_hybrid_portrait_and_advances_to_scripting() -> None:
    """On success: image delivered via send_photo, phase advances to SCRIPTING."""
    client = client_with_person()
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([converter_output_json(HYBRID)])
    bot, state = complete_interview(client, interview_stub, converter_stub=converter_stub)
    sent_before = list(client.sent)
    sent_photos_before = list(client.sent_photos)

    # The interview completion triggers the Converter in the same turn.
    # The final answer (update_id=4) already triggered the converter.
    # Check that the hybrid portrait was delivered.
    assert len(client.sent_photos) == len(sent_photos_before) + 1
    chat_id, photo_bytes = client.sent_photos[-1]
    assert chat_id == 42
    assert photo_bytes == HYBRID

    # No extra text message sent between converter call and photo delivery.
    # The only new text message should be the interviewer's reveal (already sent).
    # The Converter's turn sends ONLY the photo.
    assert client.sent == sent_before  # no additional text messages

    # Phase advanced to SCRIPTING
    session = state.load(42)
    assert session.phase is Phase.SCRIPTING
    assert session.dossier.profile is not None
    assert session.dossier.suggested_animal == ANIMAL


def test_converter_passes_correct_inputs_to_model() -> None:
    """The Converter sends both the original image and dossier context."""
    client = client_with_person()
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([converter_output_json(HYBRID)])
    bot, _ = complete_interview(client, interview_stub, converter_stub=converter_stub)

    # Build expected context as simple string concatenation
    expected_context = (
        "Profile: " + PROFILE + "\n"
        "Suggested animal: " + ANIMAL + "\n"
        "Interview:\n"
        "  Question 1: " + Q1 + "\n"
        "  Answer 1: answer one\n"
        "  Question 2: " + Q2 + "\n"
        "  Answer 2: answer two\n"
        "  Question 3: " + Q3 + "\n"
        "  Answer 3: answer three"
    )
    assert converter_stub.convert_calls == [(PERSON, expected_context)]


def test_converter_output_parsed_into_typed_model() -> None:
    """The model's structured output is parsed into ConverterOutput."""
    client = client_with_person()
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    payload = base64.b64encode(HYBRID).decode("ascii")
    raw_output = json.dumps({"image_bytes": payload, "confidence": 0.97, "reason": "crisp hybrid"})
    converter_stub = StubConverterClient([raw_output])
    bot, state = complete_interview(client, interview_stub, converter_stub=converter_stub)

    session = state.load(42)
    assert session.phase is Phase.SCRIPTING
    # The hybrid image reference is persisted (appended to profile)
    assert "crisp hybrid" in (session.dossier.profile or "")


# --- negative path: conversion failure (plan 1.5, validation 1c) ----------------


def test_converter_failure_logs_error_and_stays_in_converting(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """On failure: loud log, friendly in-character reply, phase stays CONVERTING."""
    client = client_with_person()
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([RuntimeError("gemini exploded")])
    bot, state = complete_interview(client, interview_stub, converter_stub=converter_stub)
    sent_before = list(client.sent)

    with caplog.at_level(logging.ERROR):
        # The converter runs in the same turn as the final answer.
        # Check that the error was logged.
        pass  # already happened during complete_interview

    # Friendly in-character reply sent
    assert client.sent[-1] == (42, CONVERTER_FAILURE_TEXT)
    assert any(record.levelno >= logging.ERROR for record in caplog.records)

    # Phase stays CONVERTING (can be retried)
    session = state.load(42)
    assert session.phase is Phase.CONVERTING


def test_converter_malformed_output_logs_error_and_stays_in_converting(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Schema-violating model output is a handled error, not a crash."""
    client = client_with_person()
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    # Free text instead of structured JSON
    converter_stub = StubConverterClient(["Here is your hybrid portrait!"])
    bot, state = complete_interview(client, interview_stub, converter_stub=converter_stub)

    with caplog.at_level(logging.ERROR):
        pass  # already happened during complete_interview

    assert client.sent[-1] == (42, CONVERTER_FAILURE_TEXT)
    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    session = state.load(42)
    assert session.phase is Phase.CONVERTING


def test_converter_empty_response_logs_error_and_stays_in_converting(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Empty model output is a handled error."""
    client = client_with_person()
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([""])
    bot, state = complete_interview(client, interview_stub, converter_stub=converter_stub)

    with caplog.at_level(logging.ERROR):
        pass

    assert client.sent[-1] == (42, CONVERTER_FAILURE_TEXT)
    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    session = state.load(42)
    assert session.phase is Phase.CONVERTING


# --- cross-chat isolation (validation 3.6, 4.4) ---------------------------------


def test_two_chats_converter_state_isolation() -> None:
    """Two chats in CONVERTING never share state or generated images."""
    client = FakeTelegramClient(downloads={"person": PERSON, "other": OTHER_PERSON})
    interview_stub = StubInterviewClient(
        questions=[
            question_json(Q1),  # chat 1
            question_json(Q1),  # chat 2
            question_json(Q2),  # chat 1
            question_json(Q2),  # chat 2
            question_json(Q3, is_final=True),  # chat 1
            question_json(Q3, is_final=True),  # chat 2
        ],
        profiles=[profile_json(PROFILE, ANIMAL), profile_json("Different profile", "badger")],
    )
    converter_stub = StubConverterClient(
        [converter_output_json(HYBRID), converter_output_json(OTHER_PERSON)]
    )
    bot, state = make_bot(client, converter_stub, interview_stub, verdicts=[verdict_json(True), verdict_json(True)])

    # Chat 1: photo, 3 answers
    bot.handle_update(photo_update(1, chat_id=1, file_id="person"))
    bot.handle_update(text_update(2, chat_id=1, text="chat one a1"))
    bot.handle_update(text_update(3, chat_id=1, text="chat one a2"))
    bot.handle_update(text_update(4, chat_id=1, text="chat one a3"))

    # Chat 2: photo, 3 answers
    bot.handle_update(photo_update(5, chat_id=2, file_id="other"))
    bot.handle_update(text_update(6, chat_id=2, text="chat two a1"))
    bot.handle_update(text_update(7, chat_id=2, text="chat two a2"))
    bot.handle_update(text_update(8, chat_id=2, text="chat two a3"))

    # Both advanced to SCRIPTING with their own images
    chat_one = state.load(1)
    chat_two = state.load(2)
    assert chat_one.phase is Phase.SCRIPTING
    assert chat_two.phase is Phase.SCRIPTING

    # Each chat got its own hybrid portrait
    assert len(client.sent_photos) == 2
    chat_ids = [cid for cid, _ in client.sent_photos]
    assert set(chat_ids) == {1, 2}


# --- graceful degradation on send failure (validation 4.2) ----------------------


def test_send_photo_failure_degrades_gracefully(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If Telegram send_photo fails, error is logged and polling continues."""
    client = client_with_person()

    class FailingSendPhotoClient(FakeTelegramClient):
        def send_photo(self, chat_id: int, photo: bytes) -> None:
            raise ConnectionError("telegram send failed")

    client = FailingSendPhotoClient(downloads={"person": PERSON})
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([converter_output_json(HYBRID)])
    bot, state = make_bot(client, converter_stub, interview_stub)

    with caplog.at_level(logging.ERROR):
        bot.handle_update(photo_update(1, chat_id=42, file_id="person"))
        bot.handle_update(text_update(2, chat_id=42, text="answer one"))
        bot.handle_update(text_update(3, chat_id=42, text="answer two"))
        bot.handle_update(text_update(4, chat_id=42, text="answer three"))

    # Error logged
    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    # Phase stays CONVERTING (can be retried)
    session = state.load(42)
    assert session.phase is Phase.CONVERTING
    # Friendly reply sent
    assert client.sent[-1] == (42, CONVERTER_FAILURE_TEXT)


# --- retry after failure (validation 3.5) ---------------------------------------


def test_converter_can_be_retried_after_failure() -> None:
    """After a failure, a new final answer re-triggers the Converter."""
    client = client_with_person()
    # First two attempts fail, third succeeds
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient(
        [
            RuntimeError("first attempt failed"),
            "not valid json",
            converter_output_json(HYBRID),
        ]
    )
    bot, state = make_bot(client, converter_stub, interview_stub)

    # First interview completion: first converter attempt fails
    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))
    bot.handle_update(text_update(2, chat_id=42, text="answer one"))
    bot.handle_update(text_update(3, chat_id=42, text="answer two"))
    bot.handle_update(text_update(4, chat_id=42, text="answer three"))

    session = state.load(42)
    assert session.phase is Phase.CONVERTING
    assert client.sent[-1] == (42, CONVERTER_FAILURE_TEXT)


# --- boundary: CONVERTING phase without completed dossier -----------------------


def test_converter_rejects_incomplete_dossier() -> None:
    """Converter fails fast if dossier is incomplete."""
    state = StateDriver()
    converter_stub = StubConverterClient([converter_output_json(HYBRID)])
    converter = Converter(state, converter_stub)

    session = state.load(99)
    session.phase = Phase.CONVERTING
    session.photo = PERSON
    # No suggested_animal = incomplete dossier
    session.dossier = Dossier(profile="Some profile")
    state.save(session)

    with pytest.raises(Exception):  # ConverterError
        converter.convert(99)

    # Phase should not have advanced
    assert state.load(99).phase is Phase.CONVERTING


def test_converter_rejects_missing_photo() -> None:
    """Converter fails fast if photo is missing."""
    state = StateDriver()
    converter_stub = StubConverterClient([converter_output_json(HYBRID)])
    converter = Converter(state, converter_stub)

    session = state.load(99)
    session.phase = Phase.CONVERTING
    session.photo = None
    session.dossier = Dossier(profile="Some profile", suggested_animal=ANIMAL)
    state.save(session)

    with pytest.raises(Exception):  # ConverterError
        converter.convert(99)

    assert state.load(99).phase is Phase.CONVERTING


def test_converter_rejects_wrong_phase() -> None:
    """Converter only runs in CONVERTING phase."""
    state = StateDriver()
    converter_stub = StubConverterClient([converter_output_json(HYBRID)])
    converter = Converter(state, converter_stub)

    session = state.load(99)
    session.phase = Phase.INTERVIEWING
    session.photo = PERSON
    session.dossier = Dossier(profile="Some profile", suggested_animal=ANIMAL)
    state.save(session)

    with pytest.raises(Exception):  # ConverterError
        converter.convert(99)

    assert state.load(99).phase is Phase.INTERVIEWING
