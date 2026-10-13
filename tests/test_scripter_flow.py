"""The Scripter flow: complete dossier → Converter → narration → NARRATING.

Reference: SPECS/2026-10-10-scripter/requirements.md acceptance criteria,
plan.md groups 1.3–4.3, validation.md checks 3. Everything here runs offline
against the scripted scripter client.
"""

from __future__ import annotations

import logging

import pytest
from telegram_documentaries.bot import Bot
from telegram_documentaries.bouncer import Bouncer
from telegram_documentaries.converter import Converter
from telegram_documentaries.interviewer import Interviewer
from telegram_documentaries.scripter import (
    MAX_SCRIPT_WORDS,
    SCRIPTING_FAILURE_TEXT,
    Scripter,
    has_markdown,
)
from telegram_documentaries.state import Phase, StateDriver
from tests.support.fakes import (
    FakeTelegramClient,
    StubConverterClient,
    StubInterviewClient,
    StubScripterClient,
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
HYBRID = fixture_bytes("landscape.jpg")  # reuse as placeholder (no longer sent)

Q1 = "What do you do when nobody is watching?"
Q2 = "Describe the strangest thing in your refrigerator."
Q3 = "If your life were a documentary, what would the narrator say?"
PROFILE = (
    "A midnight snacker with a weakness for shiny objects and a "
    "suspiciously organised snack drawer."
)
ANIMAL = "raccoon"

#: A valid narration: one paragraph, well under the word cap, no markdown.
SCRIPT = "Our subject prepares a humble midnight toast while stars wheel overhead."
SCRIPT_TWO = "The badger of the break room guards the biscuit tin with quiet gravity."


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
    vision: StubVisionClient,
) -> Bot:
    """A Bot wired with the Interviewer, Converter, and Scripter on shared state."""
    return Bot(
        client,
        bouncer=Bouncer(vision),
        state=state,
        interviewer=Interviewer(state, interview_stub),
        converter=Converter(state, converter_stub, client),
        scripter=Scripter(state, scripter_stub),
    )


def make_bot(
    client: FakeTelegramClient,
    interview_stub: StubInterviewClient,
    converter_stub: StubConverterClient,
    scripter_stub: StubScripterClient,
    *,
    verdicts: list[str] | None = None,
) -> tuple[Bot, StateDriver]:
    state = StateDriver()
    vision = StubVisionClient(verdicts if verdicts is not None else [verdict_json(True)])
    return wired_bot(client, state, interview_stub, converter_stub, scripter_stub, vision), state


def client_with_person() -> FakeTelegramClient:
    return FakeTelegramClient(downloads={"person": PERSON, "other": OTHER_PERSON})


def run_flow(
    bot: Bot,
    client: FakeTelegramClient,
    *,
    chat_id: int = 42,
    start_id: int = 1,
    file_id: str = "person",
) -> None:
    """Drive the photo → interview → converter → scripter pipeline once."""
    bot.handle_update(photo_update(start_id, chat_id=chat_id, file_id=file_id))
    bot.handle_update(text_update(start_id + 1, chat_id=chat_id, text="answer one"))
    bot.handle_update(text_update(start_id + 2, chat_id=chat_id, text="answer two"))
    bot.handle_update(text_update(start_id + 3, chat_id=chat_id, text="answer three"))


# --- happy path (plan 4.3, validation 3.1) -----------------------------------


def test_full_flow_delivers_script_persists_it_and_advances_to_narrating() -> None:
    """The script is sent to Telegram, persisted, and the phase reaches NARRATING."""
    client = client_with_person()
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([converter_output_json(b"fake-hybrid-image")])
    scripter_stub = StubScripterClient([scripter_output_json(SCRIPT)])
    bot, state = make_bot(client, interview_stub, converter_stub, scripter_stub)

    run_flow(bot, client)

    # The script is delivered as text after the converter sends the hybrid image.
    assert client.sent[-1] == (42, SCRIPT)

    session = state.load(42)
    assert session.phase is Phase.NARRATING
    assert session.dossier.script == SCRIPT


def test_delivery_logs_a_preview_of_the_raw_script(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The console log shows a repr'd preview of the raw script (the exact
    handoff to the Narrator), so it can be verified without dumping the whole
    paragraph."""
    client = client_with_person()
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([converter_output_json(b"fake-hybrid-image")])
    scripter_stub = StubScripterClient([scripter_output_json(SCRIPT)])
    bot, _ = make_bot(client, interview_stub, converter_stub, scripter_stub)

    with caplog.at_level(logging.INFO, logger="telegram_documentaries.bot"):
        run_flow(bot, client)

    delivered = [record for record in caplog.records if "delivered script" in record.getMessage()]
    assert len(delivered) == 1
    # The preview is the script itself (truncated past 80 chars), repr'd.
    expected_preview = SCRIPT if len(SCRIPT) <= 80 else SCRIPT[:77] + "..."
    assert repr(expected_preview) in delivered[0].getMessage()


def test_delivered_script_meets_the_output_contract() -> None:
    """The delivered script is one paragraph, ≤ 90 words, with no markdown."""
    client = client_with_person()
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([converter_output_json(b"fake-hybrid-image")])
    scripter_stub = StubScripterClient([scripter_output_json(SCRIPT)])
    bot, _ = make_bot(client, interview_stub, converter_stub, scripter_stub)

    run_flow(bot, client)

    delivered = client.sent[-1][1]
    assert "\n\n" not in delivered
    assert len(delivered.split()) <= MAX_SCRIPT_WORDS
    assert not has_markdown(delivered)


def test_scripter_receives_the_complete_dossier_context() -> None:
    """The Scripter is handed the profile, animal, and accumulated Q&A."""
    client = client_with_person()
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([converter_output_json(b"fake-hybrid-image")])
    scripter_stub = StubScripterClient([scripter_output_json(SCRIPT)])
    bot, _ = make_bot(client, interview_stub, converter_stub, scripter_stub)

    run_flow(bot, client)

    assert len(scripter_stub.generate_calls) == 1
    context = scripter_stub.generate_calls[0]
    assert PROFILE in context
    assert ANIMAL in context
    assert Q1 in context
    assert "answer one" in context


# --- failure path (plan 4.2, validation 3.4) ---------------------------------


def test_scripter_failure_stays_in_scripting_and_degrades_gracefully(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A raised client error: loud log, friendly reply, phase stays SCRIPTING."""
    client = client_with_person()
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([converter_output_json(b"fake-hybrid-image")])
    scripter_stub = StubScripterClient([RuntimeError("gemini exploded")])
    bot, state = make_bot(client, interview_stub, converter_stub, scripter_stub)

    with caplog.at_level(logging.ERROR):
        run_flow(bot, client)

    assert client.sent[-1] == (42, SCRIPTING_FAILURE_TEXT)
    assert any(record.levelno >= logging.ERROR for record in caplog.records)

    session = state.load(42)
    assert session.phase is Phase.SCRIPTING
    # The dossier survives the failed script.
    assert PROFILE in (session.dossier.profile or "")
    assert session.dossier.suggested_animal == ANIMAL
    assert session.dossier.script is None


def test_scripter_malformed_output_stays_in_scripting(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Free-text (unstructured) output is a handled error, not a crash."""
    client = client_with_person()
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([converter_output_json(b"fake-hybrid-image")])
    scripter_stub = StubScripterClient(["Here is your script: a raccoon!"])
    bot, state = make_bot(client, interview_stub, converter_stub, scripter_stub)

    with caplog.at_level(logging.ERROR):
        run_flow(bot, client)

    assert client.sent[-1] == (42, SCRIPTING_FAILURE_TEXT)
    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    assert state.load(42).phase is Phase.SCRIPTING


def test_scripter_retry_after_failure_succeeds() -> None:
    """After a failure the dossier survives and a retry produces the script."""
    client = client_with_person()
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([converter_output_json(b"fake-hybrid-image")])
    scripter_stub = StubScripterClient(
        [RuntimeError("first attempt failed"), scripter_output_json(SCRIPT)]
    )
    bot, state = make_bot(client, interview_stub, converter_stub, scripter_stub)

    run_flow(bot, client)
    assert state.load(42).phase is Phase.SCRIPTING
    assert state.load(42).dossier.script is None

    # Retry the stage while the session is still in SCRIPTING.
    bot._run_scripter(42)

    session = state.load(42)
    assert session.phase is Phase.NARRATING
    assert session.dossier.script == SCRIPT
    assert client.sent[-1] == (42, SCRIPT)


def test_replying_text_after_failure_reruns_scripter_via_public_path() -> None:
    """A user can reach the retry by replying any text (public handle_update path)."""
    client = client_with_person()
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([converter_output_json(b"fake-hybrid-image")])
    scripter_stub = StubScripterClient(
        [RuntimeError("first attempt failed"), scripter_output_json(SCRIPT)]
    )
    bot, state = make_bot(client, interview_stub, converter_stub, scripter_stub)

    run_flow(bot, client)

    # First attempt failed: the friendly message went out, phase stayed put.
    assert state.load(42).phase is Phase.SCRIPTING
    assert client.sent[-1] == (42, SCRIPTING_FAILURE_TEXT)

    # The user replies with ordinary text — no photo, no command.
    bot.handle_update(text_update(5, chat_id=42, text="go on then, try again"))

    session = state.load(42)
    assert session.phase is Phase.NARRATING
    assert session.dossier.script == SCRIPT
    assert client.sent[-1] == (42, SCRIPT)


def test_scripting_failure_text_asks_for_a_text_reply_not_a_photo() -> None:
    """The retry call-to-action points at replying, never at another photo."""
    lowered = SCRIPTING_FAILURE_TEXT.lower()
    assert "reply" in lowered
    assert "photo" not in lowered


# --- cross-chat isolation (validation 3.5) -----------------------------------


def test_two_chats_get_their_own_scripts_and_phases() -> None:
    """Two chats run the pipeline independently; scripts never leak."""
    client = client_with_person()
    interview_stub = StubInterviewClient(
        questions=three_questions() * 2,
        profiles=[profile_json(PROFILE, ANIMAL), profile_json("A different profile", "badger")],
    )
    converter_stub = StubConverterClient([converter_output_json(b"fake-hybrid-image")] * 2)
    scripter_stub = StubScripterClient(
        [scripter_output_json(SCRIPT), scripter_output_json(SCRIPT_TWO)]
    )
    bot, state = make_bot(
        client,
        interview_stub,
        converter_stub,
        scripter_stub,
        verdicts=[verdict_json(True), verdict_json(True)],
    )

    run_flow(bot, client, chat_id=1, start_id=1, file_id="person")
    run_flow(bot, client, chat_id=2, start_id=5, file_id="other")

    chat_one = state.load(1)
    chat_two = state.load(2)
    assert chat_one.phase is Phase.NARRATING
    assert chat_two.phase is Phase.NARRATING
    assert chat_one.dossier.script == SCRIPT
    assert chat_two.dossier.script == SCRIPT_TWO
    assert chat_one.dossier.script != chat_two.dossier.script
    assert (1, SCRIPT) in client.sent
    assert (2, SCRIPT_TWO) in client.sent


def test_an_untouched_chat_has_no_script_after_another_chat_completes() -> None:
    """Completing chat A leaves chat B at the initial phase with no script."""
    client = client_with_person()
    interview_stub = StubInterviewClient(
        questions=three_questions(), profiles=[profile_json(PROFILE, ANIMAL)]
    )
    converter_stub = StubConverterClient([converter_output_json(b"fake-hybrid-image")])
    scripter_stub = StubScripterClient([scripter_output_json(SCRIPT)])
    bot, state = make_bot(client, interview_stub, converter_stub, scripter_stub)

    run_flow(bot, client, chat_id=1, start_id=1, file_id="person")

    untouched = state.load(2)
    assert untouched.phase is Phase.AWAITING_PHOTO
    assert untouched.dossier.script is None
    assert untouched.dossier.profile is None
