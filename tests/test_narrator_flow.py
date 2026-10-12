"""The Narrator flow: full pipeline → voice note → AWAITING_PHOTO.

Reference: SPECS/2026-10-11-narrator/requirements.md acceptance criteria,
plan.md groups 5.1–5.2 and 6.5, validation.md check 5. Everything runs offline
against the scripted TTS client; the full pipeline (photo → interview →
converter → scripter → narrator) is exercised through the Bot.
"""

from __future__ import annotations

import logging

import pytest
from telegram_documentaries.bot import CONVERTER_FAILURE_TEXT, REPLY_TEXT, Bot
from telegram_documentaries.bouncer import Bouncer
from telegram_documentaries.converter import Converter
from telegram_documentaries.interviewer import Interviewer
from telegram_documentaries.narrator import NARRATOR_FAILURE_TEXT, Narrator, NarratorResult
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
HYBRID = fixture_bytes("landscape.jpg")  # reuse as the "generated" hybrid

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

STUB_OGG_TWO = b"OggS" + b"B" * 64


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
    interview_stub: StubInterviewClient,
    converter_stub: StubConverterClient,
    scripter_stub: StubScripterClient,
    tts_stub: StubTTSClient,
    vision: StubVisionClient,
    *,
    with_narrator: bool = True,
) -> Bot:
    """A Bot wired through the full pipeline on shared state."""
    if with_narrator:
        return Bot(
            client,
            bouncer=Bouncer(vision),
            state=state,
            interviewer=Interviewer(state, interview_stub),
            converter=Converter(state, converter_stub),
            scripter=Scripter(state, scripter_stub),
            narrator=Narrator(state, tts_stub, client),
        )
    return Bot(
        client,
        bouncer=Bouncer(vision),
        state=state,
        interviewer=Interviewer(state, interview_stub),
        converter=Converter(state, converter_stub),
        scripter=Scripter(state, scripter_stub),
    )


def make_bot(
    client: FakeTelegramClient,
    *,
    tts_responses: list[NarratorResult | BaseException] | None = None,
    verdicts: list[str] | None = None,
    with_narrator: bool = True,
) -> tuple[Bot, StateDriver, StubTTSClient]:
    state = StateDriver()
    vision = StubVisionClient(verdicts if verdicts is not None else [verdict_json(True)])
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([converter_output_json(HYBRID)])
    scripter_stub = StubScripterClient([scripter_output_json(SCRIPT)])
    tts_stub = StubTTSClient(tts_responses)
    bot = wired_bot(
        client,
        state,
        interview_stub,
        converter_stub,
        scripter_stub,
        tts_stub,
        vision,
        with_narrator=with_narrator,
    )
    return bot, state, tts_stub


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
    """Drive the full photo → interview → converter → scripter → narrator flow."""
    bot.handle_update(photo_update(start_id, chat_id=chat_id, file_id=file_id))
    bot.handle_update(text_update(start_id + 1, chat_id=chat_id, text="answer one"))
    bot.handle_update(text_update(start_id + 2, chat_id=chat_id, text="answer two"))
    bot.handle_update(text_update(start_id + 3, chat_id=chat_id, text="answer three"))


# --- happy path (plan 6.5, validation 5.1) -----------------------------------


def test_full_flow_delivers_a_voice_note_and_completes_the_pipeline() -> None:
    """Photo → interview → image → narration → voice note, all in one turn."""
    client = client_with_people()
    bot, state, tts_stub = make_bot(
        client, tts_responses=[NarratorResult(audio_bytes=STUB_OGG, format="ogg")]
    )

    run_flow(bot, client)

    # The script text was handed to TTS, and the voice note came back out.
    assert tts_stub.synthesize_calls == [SCRIPT]
    assert len(client.sent_voices) == 1
    chat_id, voice, mime_type, filename = client.sent_voices[0]
    assert chat_id == 42
    assert voice == STUB_OGG
    assert mime_type == "audio/ogg"
    assert filename.endswith(".ogg")

    session = state.load(42)
    assert session.phase is Phase.AWAITING_PHOTO
    assert session.dossier.script is None


def test_voice_note_arrives_in_the_same_turn_as_the_text_script() -> None:
    """The script text is delivered, then the Narrator adds the voice note."""
    client = client_with_people()
    bot, _, _ = make_bot(client, tts_responses=[NarratorResult(audio_bytes=STUB_OGG, format="ogg")])

    run_flow(bot, client)

    # The Scripter delivered the narration text in the same turn the Narrator
    # voiced it: the cascade runs Scripter before Narrator, so the text is
    # already on its way when the voice note arrives.
    assert (42, SCRIPT) in client.sent
    assert len(client.sent_voices) == 1


# --- converter failure: narration still happens (Phase 6 amendment) ----------


def test_converter_failure_still_narrates_without_a_hybrid_portrait() -> None:
    """A failed Converter skips the portrait but the voice note is still sent."""
    client = client_with_people()
    state = StateDriver()
    vision = StubVisionClient([verdict_json(True)])
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([RuntimeError("image model is down")])
    scripter_stub = StubScripterClient([scripter_output_json(SCRIPT)])
    tts_stub = StubTTSClient([NarratorResult(audio_bytes=STUB_OGG, format="ogg")])
    bot = wired_bot(client, state, interview_stub, converter_stub, scripter_stub, tts_stub, vision)

    run_flow(bot, client)

    # No hybrid portrait, but the failure is announced and narration proceeds.
    assert client.sent_photos == []
    assert (42, CONVERTER_FAILURE_TEXT) in client.sent
    assert (42, SCRIPT) in client.sent
    assert tts_stub.synthesize_calls == [SCRIPT]
    assert len(client.sent_voices) == 1
    assert state.load(42).phase is Phase.AWAITING_PHOTO


# --- failure and retry (plan 6.5, validation 5.2) ----------------------------


def test_narrator_failure_stays_in_narrating_and_retries_via_public_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A TTS failure degrades gracefully; a text reply re-runs the Narrator."""
    client = client_with_people()
    bot, state, _ = make_bot(
        client,
        tts_responses=[
            RuntimeError("gemini tts exploded"),
            NarratorResult(audio_bytes=STUB_OGG, format="ogg"),
        ],
    )

    with caplog.at_level(logging.ERROR):
        run_flow(bot, client)

    # Graceful degradation: friendly text, no voice note, phase stays NARRATING.
    assert client.sent[-1] == (42, NARRATOR_FAILURE_TEXT)
    assert client.sent_voices == []
    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    session = state.load(42)
    assert session.phase is Phase.NARRATING
    assert session.dossier.script == SCRIPT

    # The user replies with any text — the Narrator retries and succeeds.
    bot.handle_update(text_update(5, chat_id=42, text="try the narration again"))

    assert len(client.sent_voices) == 1
    assert client.sent_voices[0][1] == STUB_OGG
    assert state.load(42).phase is Phase.AWAITING_PHOTO
    assert state.load(42).dossier.script is None


def test_narrator_failure_text_points_at_a_retry_not_a_photo() -> None:
    lowered = NARRATOR_FAILURE_TEXT.lower()
    assert "try again" in lowered or "retry" in lowered
    assert "photo" not in lowered


# --- wiring behaviour (plan 5.1, validation 5.4) -----------------------------


def test_unwired_bot_keeps_the_default_reply_after_scripting() -> None:
    """No Narrator wired: the chat parks in NARRATING and text gets REPLY_TEXT."""
    client = client_with_people()
    bot, state, tts_stub = make_bot(client, with_narrator=False)

    run_flow(bot, client)

    assert tts_stub.synthesize_calls == []
    assert client.sent_voices == []
    assert state.load(42).phase is Phase.NARRATING

    bot.handle_update(text_update(5, chat_id=42, text="hello?"))
    assert client.sent[-1] == (42, REPLY_TEXT)


# --- cross-chat isolation (plan 6.5, validation 5.3) -------------------------


def test_two_chats_each_get_their_own_voice_notes() -> None:
    """Two chats narrate independently; scripts and audio never leak."""
    client = FakeTelegramClient(downloads={"person": PERSON, "other": OTHER_PERSON})
    state = StateDriver()
    vision = StubVisionClient([verdict_json(True), verdict_json(True)])
    interview_stub = StubInterviewClient(
        questions=three_questions() * 2,
        profiles=[profile_json(PROFILE, ANIMAL), profile_json("A different profile", "badger")],
    )
    converter_stub = StubConverterClient(
        [converter_output_json(HYBRID), converter_output_json(OTHER_PERSON)]
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
    bot = wired_bot(
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

    assert tts_stub.synthesize_calls == [SCRIPT, SCRIPT_TWO]
    voices_by_chat = {chat_id: voice for chat_id, voice, _, _ in client.sent_voices}
    assert voices_by_chat == {1: STUB_OGG, 2: STUB_OGG_TWO}
    assert state.load(1).phase is Phase.AWAITING_PHOTO
    assert state.load(2).phase is Phase.AWAITING_PHOTO
    assert state.load(1).dossier.script is None
    assert state.load(2).dossier.script is None


def test_an_untouched_chat_has_no_script_or_voice_after_another_completes() -> None:
    """Completing chat A leaves chat B at the initial phase with nothing."""
    client = client_with_people()
    bot, state, _ = make_bot(
        client, tts_responses=[NarratorResult(audio_bytes=STUB_OGG, format="ogg")]
    )

    run_flow(bot, client, chat_id=1, start_id=1, file_id="person")

    untouched = state.load(2)
    assert untouched.phase is Phase.AWAITING_PHOTO
    assert untouched.dossier.script is None
    assert untouched.dossier.profile is None
    voice_chats = {chat_id for chat_id, _, _, _ in client.sent_voices}
    assert 2 not in voice_chats
