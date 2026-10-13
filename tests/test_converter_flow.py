"""The Converter flow: full pipeline → hybrid image → SCRIPTING.

Reference: SPECS/2026-10-13-converter/requirements.md acceptance criteria,
plan.md group 5.2, validation.md check 3. Everything runs offline against the
scripted converter client; the pipeline (photo → interview → converter →
scripter → narrator) is exercised through the Bot.
"""

from __future__ import annotations

import logging

import pytest
from telegram_documentaries.bot import Bot
from telegram_documentaries.bouncer import Bouncer
from telegram_documentaries.converter import CONVERTER_FAILURE_TEXT, Converter
from telegram_documentaries.interviewer import Interviewer
from telegram_documentaries.narrator import Narrator, NarratorResult
from telegram_documentaries.scripter import Scripter
from telegram_documentaries.state import Phase, StateDriver
from tests.support.fakes import (
    STUB_OGG,
    FakeTelegramClient,
    StubConverterClient,
    StubInterviewClient,
    StubScripterClient,
    StubTTSClient,
    StubVisionClient,
    converter_output_json,
    fixture_bytes,
    photo_update,
    profile_json,
    question_json,
    scripter_output_json,
    text_update,
    verdict_json,
)

PERSON = fixture_bytes("person.jpg")
OTHER_PERSON = fixture_bytes("landscape.jpg")
STUB_OGG_TWO = b"OggS" + b"B" * 64

HYBRID_IMAGE = b"\xff\xd8\xffhybrid-portrait-bytes"
HYBRID_IMAGE_TWO = b"\xff\xd8\xffhybrid-portrait-bytes-two"

Q1 = "What do you do when nobody is watching?"
Q2 = "Describe the strangest thing in your refrigerator."
Q3 = "If your life were a documentary, what would the narrator say?"
PROFILE = (
    "A midnight snacker with a weakness for shiny objects and a "
    "suspiciously organised snack drawer."
)
ANIMAL = "raccoon"
SCRIPT = (
    "In the vast kitchen of the universe, our subject, a midnight raccoon, "
    "prepares a humble midnight toast while the stars wheel overhead."
)
SCRIPT_TWO = (
    "Behold the badger of the break room, who guards the biscuit tin with "
    "the quiet gravity of a small, furred moon."
)


def three_questions() -> list[str]:
    """The model plays nicely: finishes at the floor of three questions."""
    return [
        question_json(Q1),
        question_json(Q2),
        question_json(Q3, is_final=True),
    ]


def wired_bot_with_converter(
    client: FakeTelegramClient,
    state: StateDriver,
    interview_stub: StubInterviewClient,
    converter_stub: StubConverterClient,
    scripter_stub: StubScripterClient | None,
    tts_stub: StubTTSClient | None,
    vision: StubVisionClient,
    *,
    with_narrator: bool = True,
) -> Bot:
    """A Bot wired through the full pipeline including Converter on shared state."""
    if with_narrator and tts_stub is not None:
        return Bot(
            client,
            bouncer=Bouncer(vision),
            state=state,
            interviewer=Interviewer(state, interview_stub),
            converter=Converter(state, converter_stub, client),
            scripter=Scripter(state, scripter_stub) if scripter_stub is not None else None,
            narrator=Narrator(state, tts_stub, client),
        )
    return Bot(
        client,
        bouncer=Bouncer(vision),
        state=state,
        interviewer=Interviewer(state, interview_stub),
        converter=Converter(state, converter_stub, client),
        scripter=Scripter(state, scripter_stub) if scripter_stub is not None else None,
    )


def make_bot_with_converter(
    client: FakeTelegramClient,
    *,
    converter_responses: list[str | BaseException] | None = None,
    tts_responses: list[NarratorResult | BaseException] | None = None,
    verdicts: list[str] | None = None,
    with_narrator: bool = True,
    with_scripter: bool = True,
) -> tuple[Bot, StateDriver, StubConverterClient, StubTTSClient | None]:
    state = StateDriver()
    vision = StubVisionClient(verdicts if verdicts is not None else [verdict_json(True)])
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    default_response = converter_responses or [converter_output_json(HYBRID_IMAGE)]
    converter_stub = StubConverterClient(default_response)
    scripter_stub = StubScripterClient([scripter_output_json(SCRIPT)]) if with_scripter else None
    tts_stub = StubTTSClient(tts_responses) if tts_responses is not None else None
    bot = wired_bot_with_converter(
        client,
        state,
        interview_stub,
        converter_stub,
        scripter_stub,
        tts_stub,
        vision,
        with_narrator=with_narrator,
    )
    return bot, state, converter_stub, tts_stub


def client_with_people() -> FakeTelegramClient:
    return FakeTelegramClient(downloads={"person": PERSON, "other": OTHER_PERSON})


def run_flow(
    bot: Bot,
    client: FakeTelegramClient,
    *,
    chat_id: int = 42,
    start_id: int = 1,
    file_id: str = "person",
) -> None:
    """Drive the photo → interview → converter → scripter → narrator flow."""
    bot.handle_update(photo_update(start_id, chat_id=chat_id, file_id=file_id))
    bot.handle_update(text_update(start_id + 1, chat_id=chat_id, text="answer one"))
    bot.handle_update(text_update(start_id + 2, chat_id=chat_id, text="answer two"))
    bot.handle_update(text_update(start_id + 3, chat_id=chat_id, text="answer three"))


# --- happy path (validation 3.1) ------------------------------------------------


def test_full_flow_delivers_hybrid_image_and_advances_to_scripting() -> None:
    """Photo → interview → converter generates hybrid image → SCRIPTING."""
    client = client_with_people()
    # No scripter/narrator: cascade stops at SCRIPTING after Converter.
    bot, state, converter_stub, _ = make_bot_with_converter(
        client, with_narrator=False, with_scripter=False
    )

    run_flow(bot, client)

    # The converter was called and returned the hybrid image.
    assert len(converter_stub.generate_calls) == 1
    photo_bytes, context = converter_stub.generate_calls[0]
    assert photo_bytes == PERSON
    assert "Profile: " + PROFILE in context
    assert "Suggested animal: " + ANIMAL in context

    # The image was delivered via Telegram send_photo.
    assert client.sent_photos == [(42, HYBRID_IMAGE)]

    # Phase advanced to SCRIPTING.
    session = state.load(42)
    assert session.phase is Phase.SCRIPTING
    # Dossier intact.
    assert session.dossier.profile == PROFILE
    assert session.dossier.suggested_animal == ANIMAL
    assert session.dossier.questions == [Q1, Q2, Q3]


def test_hybrid_image_bytes_non_empty_and_correct_chat() -> None:
    """Image bytes are non-empty and delivered to correct chat_id."""
    client = client_with_people()
    bot, state, converter_stub, _ = make_bot_with_converter(
        client, with_narrator=False, with_scripter=False
    )

    run_flow(bot, client)

    assert client.sent_photos == [(42, HYBRID_IMAGE)]
    assert len(HYBRID_IMAGE) > 0
    session = state.load(42)
    assert session.phase is Phase.SCRIPTING


# --- failure path (validation 3.2) ----------------------------------------------


def test_converter_failure_degrades_gracefully_advances_to_scripting(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Converter failure: sends failure text, advances to SCRIPTING, dossier intact."""
    client = client_with_people()
    # No scripter/narrator: cascade stops at SCRIPTING after Converter.
    bot, state, converter_stub, _ = make_bot_with_converter(
        client,
        converter_responses=["not valid json"],
        with_narrator=False,
        with_scripter=False,
    )

    with caplog.at_level(logging.ERROR):
        run_flow(bot, client)

    # Failure text sent (among interview questions).
    assert any(text == CONVERTER_FAILURE_TEXT for _, text in client.sent)
    # No photo sent.
    assert client.sent_photos == []
    # Phase advanced to SCRIPTING (pipeline continues).
    session = state.load(42)
    assert session.phase is Phase.SCRIPTING
    # Dossier intact for Scripter/Narrator.
    assert session.dossier.profile == PROFILE
    assert session.dossier.suggested_animal == ANIMAL
    assert session.dossier.questions == [Q1, Q2, Q3]
    # Error logged.
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


def test_converter_client_exception_degrades_gracefully(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Converter client exception: sends failure text, advances to SCRIPTING."""
    client = client_with_people()
    bot, state, converter_stub, _ = make_bot_with_converter(
        client,
        converter_responses=[RuntimeError("gemini exploded")],
        with_narrator=False,
        with_scripter=False,
    )

    with caplog.at_level(logging.ERROR):
        run_flow(bot, client)

    assert any(text == CONVERTER_FAILURE_TEXT for _, text in client.sent)
    assert client.sent_photos == []
    session = state.load(42)
    assert session.phase is Phase.SCRIPTING
    assert session.dossier.profile == PROFILE
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


def test_failure_path_then_scripter_and_narrator_still_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """On converter failure, pipeline continues: Scripter and Narrator still run."""
    client = client_with_people()
    bot, state, converter_stub, tts_stub = make_bot_with_converter(
        client,
        converter_responses=["not valid json"],
        tts_responses=[NarratorResult(audio_bytes=STUB_OGG, format="ogg")],
        with_narrator=True,
        with_scripter=True,
    )

    with caplog.at_level(logging.ERROR):
        run_flow(bot, client)

    # Converter failure handled.
    assert any(text == CONVERTER_FAILURE_TEXT for _, text in client.sent)
    assert client.sent_photos == []
    # But Scripter still ran and delivered script.
    assert (42, SCRIPT) in client.sent
    # And Narrator still ran and delivered voice note.
    assert len(client.sent_voices) == 1
    assert client.sent_voices[0][1] == STUB_OGG
    # Final phase is AWAITING_PHOTO.
    session = state.load(42)
    assert session.phase is Phase.AWAITING_PHOTO


# --- cross-chat isolation (validation 3.3) --------------------------------------


def test_two_chats_independent_conversions() -> None:
    """Two chats reach CONVERTING independently; images, phases, dossiers don't leak."""
    client = FakeTelegramClient(downloads={"person": PERSON, "other": OTHER_PERSON})
    state = StateDriver()
    vision = StubVisionClient([verdict_json(True), verdict_json(True)])
    interview_stub = StubInterviewClient(
        questions=three_questions() * 2,
        profiles=[profile_json(PROFILE, ANIMAL), profile_json("A different profile", "badger")],
    )
    converter_stub = StubConverterClient(
        [converter_output_json(HYBRID_IMAGE), converter_output_json(HYBRID_IMAGE_TWO)]
    )
    scripter_stub = StubScripterClient(
        [scripter_output_json(SCRIPT), scripter_output_json(SCRIPT_TWO)]
    )
    tts_stub = StubTTSClient(
        [
            NarratorResult(audio_bytes=STUB_OGG, format="ogg"),
            NarratorResult(audio_bytes=STUB_OGG_TWO, format="ogg"),
        ]
    )
    bot = wired_bot_with_converter(
        client,
        state,
        interview_stub,
        converter_stub,
        scripter_stub,
        tts_stub,
        vision,
    )

    run_flow(bot, client, chat_id=1, start_id=1, file_id="person")
    run_flow(bot, client, chat_id=2, start_id=5, file_id="other")

    # Each chat got its own hybrid image.
    assert client.sent_photos == [(1, HYBRID_IMAGE), (2, HYBRID_IMAGE_TWO)]
    # Each chat's converter call got its own photo and context.
    assert len(converter_stub.generate_calls) == 2
    chat1_photo, chat1_context = converter_stub.generate_calls[0]
    chat2_photo, chat2_context = converter_stub.generate_calls[1]
    assert chat1_photo == PERSON
    assert chat2_photo == OTHER_PERSON
    assert "Profile: " + PROFILE in chat1_context
    assert "Suggested animal: " + ANIMAL in chat1_context
    assert "Profile: A different profile" in chat2_context
    assert "Suggested animal: badger" in chat2_context

    # Phases and dossiers are independent.
    assert state.load(1).phase is Phase.AWAITING_PHOTO
    assert state.load(2).phase is Phase.AWAITING_PHOTO
    assert state.load(1).dossier.profile == PROFILE
    assert state.load(2).dossier.profile == "A different profile"
    assert state.load(1).dossier.suggested_animal == ANIMAL
    assert state.load(2).dossier.suggested_animal == "badger"
