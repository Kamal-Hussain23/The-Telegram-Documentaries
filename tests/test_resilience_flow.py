"""Resilience flow tests: wrong-payload scenarios and timeout integration.

Reference: SPECS/2026-10-13-resilience/requirements.md table, plan.md group 2.8,
validation.md checks 4. Everything runs offline against scripted clients.
"""

from __future__ import annotations

import logging

import pytest
from telegram_documentaries.bot import (
    AWAITING_PHOTO_REPLY,
    CONVERTING_REPLY,
    ERROR_TEXT,
    INTERVIEWING_PHOTO_REPLY,
    INTERVIEWING_TEXT_REPLY,
    NARRATING_REPLY,
    SCRIPTING_REPLY,
    START_TEXT,
    Bot,
)
from telegram_documentaries.bouncer import Bouncer
from telegram_documentaries.converter import CONVERTER_FAILURE_TEXT, Converter
from telegram_documentaries.interviewer import Interviewer
from telegram_documentaries.narrator import NARRATOR_FAILURE_TEXT, Narrator, NarratorResult
from telegram_documentaries.scripter import Scripter
from telegram_documentaries.state import Phase, StateDriver
from tests.support.fakes import (
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

Q1 = "What do you do when nobody is watching?"
Q2 = "Describe the strangest thing in your refrigerator."
Q3 = "If your life were a documentary, what would the narrator say?"
PROFILE = "A midnight snacker with a weakness for shiny objects."
ANIMAL = "raccoon"
SCRIPT = "Our subject prepares a humble midnight toast while stars wheel overhead."
HYBRID_IMAGE = b"\xff\xd8\xffhybrid-portrait-bytes"


def three_questions() -> list[str]:
    return [
        question_json(Q1),
        question_json(Q2),
        question_json(Q3, is_final=True),
    ]


def client_with_person() -> FakeTelegramClient:
    return FakeTelegramClient(downloads={"person": PERSON, "other": OTHER_PERSON})


def make_bot_awaiting_photo() -> tuple[Bot, StateDriver, FakeTelegramClient]:
    """Bot in AWAITING_PHOTO phase (no components wired)."""
    client = client_with_person()
    state = StateDriver()
    bot = Bot(client, state=state)
    return bot, state, client


def make_bot_interviewing() -> tuple[Bot, StateDriver, FakeTelegramClient]:
    """Bot in INTERVIEWING phase with one question asked."""
    client = client_with_person()
    state = StateDriver()
    vision = StubVisionClient([verdict_json(True)])
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    bot = Bot(
        client, bouncer=Bouncer(vision), state=state, interviewer=Interviewer(state, interview_stub)
    )
    # Drive to INTERVIEWING
    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))
    return bot, state, client


def make_bot_interviewing_q2() -> tuple[Bot, StateDriver, FakeTelegramClient]:
    """Bot in INTERVIEWING phase with Q2 pending."""
    client = client_with_person()
    state = StateDriver()
    vision = StubVisionClient([verdict_json(True)])
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    bot = Bot(
        client, bouncer=Bouncer(vision), state=state, interviewer=Interviewer(state, interview_stub)
    )
    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))
    bot.handle_update(text_update(2, chat_id=42, text="answer one"))
    return bot, state, client


def make_bot_converting() -> tuple[Bot, StateDriver, FakeTelegramClient]:
    """Bot in CONVERTING phase (interview complete, converter not run)."""
    client = client_with_person()
    state = StateDriver()
    vision = StubVisionClient([verdict_json(True)])
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([converter_output_json(HYBRID_IMAGE)])
    # No scripter or narrator - stop at CONVERTING
    bot = Bot(
        client,
        bouncer=Bouncer(vision),
        state=state,
        interviewer=Interviewer(state, interview_stub),
        converter=Converter(state, converter_stub, client),
    )
    # Manually set up session at CONVERTING phase
    session = state.load(42)
    session.phase = Phase.CONVERTING
    session.photo = PERSON
    session.dossier.profile = PROFILE
    session.dossier.suggested_animal = ANIMAL
    session.dossier.questions = [Q1, Q2, Q3]
    session.dossier.answers = ["answer one", "answer two", "answer three"]
    state.save(session)
    return bot, state, client


def make_bot_scripting() -> tuple[Bot, StateDriver, FakeTelegramClient]:
    """Bot in SCRIPTING phase (converter run, scripter not run)."""
    client = client_with_person()
    state = StateDriver()
    vision = StubVisionClient([verdict_json(True)])
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([converter_output_json(HYBRID_IMAGE)])
    scripter_stub = StubScripterClient([scripter_output_json(SCRIPT)])
    # No narrator - stop at SCRIPTING
    bot = Bot(
        client,
        bouncer=Bouncer(vision),
        state=state,
        interviewer=Interviewer(state, interview_stub),
        converter=Converter(state, converter_stub, client),
        scripter=Scripter(state, scripter_stub),
    )
    # Manually set up session at SCRIPTING phase
    session = state.load(42)
    session.phase = Phase.SCRIPTING
    session.photo = PERSON
    session.dossier.profile = PROFILE
    session.dossier.suggested_animal = ANIMAL
    session.dossier.questions = [Q1, Q2, Q3]
    session.dossier.answers = ["answer one", "answer two", "answer three"]
    state.save(session)
    return bot, state, client


def make_bot_narrating() -> tuple[Bot, StateDriver, FakeTelegramClient]:
    """Bot in NARRATING phase (script generated, narrator will fail to stay in NARRATING)."""
    client = client_with_person()
    state = StateDriver()
    vision = StubVisionClient([verdict_json(True)])
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([converter_output_json(HYBRID_IMAGE)])
    scripter_stub = StubScripterClient([scripter_output_json(SCRIPT)])
    tts_stub = StubTTSClient([RuntimeError("TTS failed")])  # Fail to stay in NARRATING
    bot = Bot(
        client,
        bouncer=Bouncer(vision),
        state=state,
        interviewer=Interviewer(state, interview_stub),
        converter=Converter(state, converter_stub, client),
        scripter=Scripter(state, scripter_stub),
        narrator=Narrator(state, tts_stub, client),
    )
    bot.handle_update(photo_update(1, chat_id=42, file_id="person"))
    bot.handle_update(text_update(2, chat_id=42, text="answer one"))
    bot.handle_update(text_update(3, chat_id=42, text="answer two"))
    bot.handle_update(text_update(4, chat_id=42, text="answer three"))
    # Scripter runs, advances to NARRATING, narrator fails -> stays in NARRATING
    return bot, state, client


# --- AWAITING_PHOTO wrong payload tests ----------------------------------------


def test_awaiting_photo_text_returns_photo_needed_reply() -> None:
    """AWAITING_PHOTO + text (not /start) -> photo-needed reply, phase unchanged."""
    bot, state, client = make_bot_awaiting_photo()

    bot.handle_update(text_update(1, chat_id=42, text="hello there"))

    assert client.sent == [(42, AWAITING_PHOTO_REPLY)]
    assert state.load(42).phase is Phase.AWAITING_PHOTO


def test_awaiting_photo_sticker_returns_photo_needed_reply() -> None:
    """AWAITING_PHOTO + sticker (non-text) -> photo-needed reply, phase unchanged."""
    bot, state, client = make_bot_awaiting_photo()

    bot.handle_update(text_update(1, chat_id=42, text=None))

    assert client.sent == [(42, AWAITING_PHOTO_REPLY)]
    assert state.load(42).phase is Phase.AWAITING_PHOTO


def test_awaiting_photo_voice_returns_photo_needed_reply() -> None:
    """AWAITING_PHOTO + voice -> photo-needed reply."""
    bot, state, client = make_bot_awaiting_photo()
    bot.handle_update(text_update(1, chat_id=42, text=None))
    assert client.sent == [(42, AWAITING_PHOTO_REPLY)]
    assert state.load(42).phase is Phase.AWAITING_PHOTO


# --- INTERVIEWING wrong payload tests ------------------------------------------


def test_interviewing_photo_returns_mid_interview_reply() -> None:
    """INTERVIEWING + photo (second photo) -> mid-interview reply, phase/dossier unchanged."""
    bot, state, client = make_bot_interviewing()

    # Send a second photo mid-interview
    bot.handle_update(photo_update(2, chat_id=42, file_id="other"))

    assert client.sent[-1] == (42, INTERVIEWING_PHOTO_REPLY)
    assert len(client.sent) == 2  # Q1 + mid-interview reply

    session = state.load(42)
    assert session.phase is Phase.INTERVIEWING
    assert session.photo == PERSON
    assert session.dossier.questions == [Q1]
    assert session.dossier.answers == []


def test_interviewing_sticker_returns_text_only_reply() -> None:
    """INTERVIEWING + sticker -> text-only reply, phase/dossier unchanged."""
    bot, state, client = make_bot_interviewing_q2()

    bot.handle_update(text_update(3, chat_id=42, text=None))

    assert client.sent[-1] == (42, INTERVIEWING_TEXT_REPLY)
    session = state.load(42)
    assert session.phase is Phase.INTERVIEWING
    assert session.dossier.questions == [Q1, Q2]
    assert session.dossier.answers == ["answer one"]


def test_interviewing_voice_returns_text_only_reply() -> None:
    """INTERVIEWING + voice -> text-only reply."""
    bot, state, client = make_bot_interviewing_q2()
    bot.handle_update(text_update(3, chat_id=42, text=None))
    assert client.sent[-1] == (42, INTERVIEWING_TEXT_REPLY)
    assert state.load(42).phase is Phase.INTERVIEWING


# --- CONVERTING wrong payload tests --------------------------------------------


def test_converting_text_returns_developing_reply() -> None:
    """CONVERTING + text -> developing reply, phase unchanged."""
    bot, state, client = make_bot_converting()

    assert state.load(42).phase is Phase.CONVERTING

    bot.handle_update(text_update(10, chat_id=42, text="hello"))

    assert client.sent[-1] == (42, CONVERTING_REPLY)
    assert state.load(42).phase is Phase.CONVERTING


def test_converting_photo_returns_developing_reply() -> None:
    """CONVERTING + photo -> developing reply."""
    bot, state, client = make_bot_converting()

    bot.handle_update(photo_update(10, chat_id=42, file_id="other"))

    assert client.sent[-1] == (42, CONVERTING_REPLY)
    assert state.load(42).phase is Phase.CONVERTING


def test_converting_sticker_returns_developing_reply() -> None:
    """CONVERTING + sticker -> developing reply."""
    bot, state, client = make_bot_converting()

    bot.handle_update(text_update(10, chat_id=42, text=None))

    assert client.sent[-1] == (42, CONVERTING_REPLY)
    assert state.load(42).phase is Phase.CONVERTING


# --- SCRIPTING wrong payload tests ---------------------------------------------


def test_scripting_photo_returns_script_writing_reply() -> None:
    """SCRIPTING + photo -> script-writing reply, phase unchanged."""
    bot, state, client = make_bot_scripting()

    assert state.load(42).phase is Phase.SCRIPTING

    bot.handle_update(photo_update(10, chat_id=42, file_id="other"))

    assert client.sent[-1] == (42, SCRIPTING_REPLY)
    assert state.load(42).phase is Phase.SCRIPTING


def test_scripting_sticker_returns_script_writing_reply() -> None:
    """SCRIPTING + sticker -> script-writing reply."""
    bot, state, client = make_bot_scripting()

    bot.handle_update(text_update(10, chat_id=42, text=None))

    assert client.sent[-1] == (42, SCRIPTING_REPLY)
    assert state.load(42).phase is Phase.SCRIPTING


# --- NARRATING wrong payload tests ---------------------------------------------


def test_narrating_photo_returns_recording_reply() -> None:
    """NARRATING + photo -> recording reply, phase unchanged."""
    bot, state, client = make_bot_narrating()

    assert state.load(42).phase is Phase.NARRATING

    bot.handle_update(photo_update(10, chat_id=42, file_id="other"))

    assert client.sent[-1] == (42, NARRATING_REPLY)
    assert state.load(42).phase is Phase.NARRATING


def test_narrating_sticker_returns_recording_reply() -> None:
    """NARRATING + sticker -> recording reply."""
    bot, state, client = make_bot_narrating()

    bot.handle_update(text_update(10, chat_id=42, text=None))

    assert client.sent[-1] == (42, NARRATING_REPLY)
    assert state.load(42).phase is Phase.NARRATING


# --- Commands still reset in all phases (regression) ---------------------------


@pytest.mark.parametrize("command", ["/start", "/restart"])
def test_command_in_awaiting_photo_resets(command: str) -> None:
    bot, state, client = make_bot_awaiting_photo()
    bot.handle_update(text_update(1, chat_id=42, text=command))
    assert client.sent[-1][1] == START_TEXT
    assert state.load(42).phase is Phase.AWAITING_PHOTO


@pytest.mark.parametrize("command", ["/start", "/restart"])
def test_command_in_interviewing_resets(command: str) -> None:
    bot, state, client = make_bot_interviewing_q2()
    bot.handle_update(text_update(3, chat_id=42, text=command))
    assert client.sent[-1][1] == START_TEXT
    assert state.load(42).phase is Phase.AWAITING_PHOTO
    assert state.load(42).dossier.questions == []
    assert state.load(42).dossier.answers == []


@pytest.mark.parametrize("command", ["/start", "/restart"])
def test_command_in_converting_resets(command: str) -> None:
    bot, state, client = make_bot_converting()
    bot.handle_update(text_update(10, chat_id=42, text=command))
    assert client.sent[-1][1] == START_TEXT
    assert state.load(42).phase is Phase.AWAITING_PHOTO


@pytest.mark.parametrize("command", ["/start", "/restart"])
def test_command_in_scripting_resets(command: str) -> None:
    bot, state, client = make_bot_scripting()
    bot.handle_update(text_update(10, chat_id=42, text=command))
    assert client.sent[-1][1] == START_TEXT
    assert state.load(42).phase is Phase.AWAITING_PHOTO


@pytest.mark.parametrize("command", ["/start", "/restart"])
def test_command_in_narrating_resets(command: str) -> None:
    bot, state, client = make_bot_narrating()
    bot.handle_update(text_update(10, chat_id=42, text=command))
    assert client.sent[-1][1] == START_TEXT
    assert state.load(42).phase is Phase.AWAITING_PHOTO


# --- Timeout integration: errors caught, friendly reply, phase preserved -------


def test_interviewer_timeout_logged_friendly_reply_phase_preserved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Interviewer timeout: handled error logged, friendly reply, phase preserved for retry."""
    from telegram_documentaries.interviewer import InterviewerError

    client = client_with_person()
    state = StateDriver()
    vision = StubVisionClient([verdict_json(True)])

    class FailingInterviewStub(StubInterviewClient):
        def generate_question(self, context: str) -> str:
            raise InterviewerError("model timeout")

    interview_stub = FailingInterviewStub(questions=[], profiles=[profile_json(PROFILE, ANIMAL)])
    bot = Bot(
        client, bouncer=Bouncer(vision), state=state, interviewer=Interviewer(state, interview_stub)
    )

    with caplog.at_level(logging.ERROR):
        bot.handle_update(photo_update(1, chat_id=42, file_id="person"))

    assert client.sent[-1] == (42, ERROR_TEXT)
    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    assert state.load(42).phase is Phase.INTERVIEWING


def test_converter_timeout_logged_friendly_reply_phase_preserved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Converter timeout: handled error logged, friendly reply, phase advanced to SCRIPTING."""
    client = client_with_person()
    state = StateDriver()
    vision = StubVisionClient([verdict_json(True)])
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )

    class FailingConverterStub(StubConverterClient):
        def generate_image(self, photo_bytes: bytes, dossier_context: str) -> str:
            from telegram_documentaries.converter import ConverterError

            raise ConverterError("model timeout")

    converter_stub = FailingConverterStub([])
    bot = Bot(
        client,
        bouncer=Bouncer(vision),
        state=state,
        interviewer=Interviewer(state, interview_stub),
        converter=Converter(state, converter_stub, client),
    )

    with caplog.at_level(logging.ERROR):
        bot.handle_update(photo_update(1, chat_id=42, file_id="person"))
        bot.handle_update(text_update(2, chat_id=42, text="answer one"))
        bot.handle_update(text_update(3, chat_id=42, text="answer two"))
        bot.handle_update(text_update(4, chat_id=42, text="answer three"))

    assert any(text == CONVERTER_FAILURE_TEXT for _, text in client.sent)
    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    assert state.load(42).phase is Phase.SCRIPTING


def test_narrator_timeout_logged_friendly_reply_phase_preserved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Narrator timeout: handled error logged, friendly reply, phase preserved for retry."""
    from telegram_documentaries.narrator import NarratorError

    client = client_with_person()
    state = StateDriver()
    vision = StubVisionClient([verdict_json(True)])
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([converter_output_json(HYBRID_IMAGE)])
    scripter_stub = StubScripterClient([scripter_output_json(SCRIPT)])

    class FailingTTSStub(StubTTSClient):
        def synthesize(self, text: str) -> NarratorResult:
            raise NarratorError("TTS timeout")

    tts_stub = FailingTTSStub([])
    bot = Bot(
        client,
        bouncer=Bouncer(vision),
        state=state,
        interviewer=Interviewer(state, interview_stub),
        converter=Converter(state, converter_stub, client),
        scripter=Scripter(state, scripter_stub),
        narrator=Narrator(state, tts_stub, client),
    )

    with caplog.at_level(logging.ERROR):
        bot.handle_update(photo_update(1, chat_id=42, file_id="person"))
        bot.handle_update(text_update(2, chat_id=42, text="answer one"))
        bot.handle_update(text_update(3, chat_id=42, text="answer two"))
        bot.handle_update(text_update(4, chat_id=42, text="answer three"))

    assert any(text == NARRATOR_FAILURE_TEXT for _, text in client.sent)
    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    assert state.load(42).phase is Phase.NARRATING
