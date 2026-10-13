"""The Converter's model output is a typed contract, never free text.

Reference: SPECS/2026-10-13-converter/requirements.md decisions 2 & 9,
plan group 1.1–1.3, validation.md checks 2.1–2.6.
"""

from __future__ import annotations

import json
import logging

import pytest
from telegram_documentaries.converter import (
    CONVERTER_FAILURE_TEXT,
    Converter,
    ConverterError,
    ConverterOutput,
    converter_context,
    parse_output,
)
from telegram_documentaries.state import Dossier, Phase, StateDriver
from tests.support.fakes import StubConverterClient, converter_output_json

HYBRID_IMAGE = b"\xff\xd8\xffhybrid-portrait-bytes"
PORTRAIT = b"\xff\xd8\xffportrait-bytes"

PROFILE = (
    "A midnight snacker with a weakness for shiny objects "
    "and a suspiciously organised snack drawer."
)
ANIMAL = "raccoon"


def make_dossier() -> Dossier:
    """A completed dossier with profile, suggested_animal, and Q&A."""
    return Dossier(
        questions=[
            "What do you do when nobody is watching?",
            "Describe the strangest thing in your refrigerator.",
        ],
        answers=[
            "I reorganise my spice rack by colour.",
            "A jar of pickles from 2012 — I keep it for the aesthetic.",
        ],
        profile=PROFILE,
        suggested_animal=ANIMAL,
    )


def make_session_state(chat_id: int, photo: bytes, dossier: Dossier) -> StateDriver:
    """Create a StateDriver with a session in CONVERTING phase."""
    state = StateDriver()
    session = state.load(chat_id)
    session.phase = Phase.CONVERTING
    session.photo = photo
    session.dossier = dossier
    state.save(session)
    return state


# --- parse_output contract (plan 1.2) ----------------------------------------


def test_parse_output_accepts_valid_json_with_image_bytes() -> None:
    raw = converter_output_json(HYBRID_IMAGE)

    parsed = parse_output(raw)

    assert isinstance(parsed, ConverterOutput)
    assert parsed.image_bytes == HYBRID_IMAGE


def test_parse_output_rejects_free_text() -> None:
    with pytest.raises(ConverterError):
        parse_output("here is your image, friend!")


@pytest.mark.parametrize(
    "raw",
    [
        "{not json",
        '["image"]',
        '{"image_ref": "abc"}',
        '{"image_bytes": ""}',
        '{"image_bytes": null}',
        '{"image_bytes": 123}',
    ],
)
def test_parse_output_rejects_schema_violations(raw: str) -> None:
    with pytest.raises(ConverterError):
        parse_output(raw)


def test_parse_output_rejects_empty_image_bytes() -> None:
    # Empty base64 string decodes to empty bytes
    raw = json.dumps({"image_bytes": ""})
    with pytest.raises(ConverterError):
        parse_output(raw)


# --- converter_context (plan 1.3) --------------------------------------------


def test_converter_context_formats_dossier_as_text() -> None:
    dossier = make_dossier()
    photo_bytes, context = converter_context(PORTRAIT, dossier)

    assert photo_bytes == PORTRAIT
    assert "Profile: " + PROFILE in context
    assert "Suggested animal: " + ANIMAL in context
    assert "Interview:" in context
    assert "Question 1: What do you do when nobody is watching?" in context
    assert "Answer 1: I reorganise my spice rack by colour." in context
    assert "Question 2: Describe the strangest thing in your refrigerator." in context
    assert "Answer 2: A jar of pickles from 2012 — I keep it for the aesthetic." in context


# --- StubConverterClient (plan 2.1) ------------------------------------------


def test_stub_converter_client_records_prompt_inputs() -> None:
    stub = StubConverterClient(responses=[converter_output_json(HYBRID_IMAGE)])

    result = stub.generate_image(PORTRAIT, "context text")

    assert stub.generate_calls == [(PORTRAIT, "context text")]
    assert result == converter_output_json(HYBRID_IMAGE)


def test_stub_converter_client_fails_loudly_when_script_runs_out() -> None:
    with pytest.raises(AssertionError):
        StubConverterClient().generate_image(PORTRAIT, "context")


# --- Converter.generate_and_send (plan 3.1) ----------------------------------


def test_converter_generate_and_send_returns_typed_output_for_stubbed_response() -> None:
    dossier = make_dossier()
    state = make_session_state(42, PORTRAIT, dossier)
    stub = StubConverterClient(responses=[converter_output_json(HYBRID_IMAGE)])
    telegram = StubTelegramClient()

    converter = Converter(state, stub, telegram)
    output = converter.generate_and_send(42)

    assert isinstance(output, ConverterOutput)
    assert output.image_bytes == HYBRID_IMAGE


def test_converter_generate_and_send_passes_exact_inputs_to_client() -> None:
    dossier = make_dossier()
    state = make_session_state(42, PORTRAIT, dossier)
    stub = StubConverterClient(responses=[converter_output_json(HYBRID_IMAGE)])
    telegram = StubTelegramClient()

    converter = Converter(state, stub, telegram)
    converter.generate_and_send(42)

    assert len(stub.generate_calls) == 1
    photo_bytes, context = stub.generate_calls[0]
    assert photo_bytes == PORTRAIT
    assert "Profile: " + PROFILE in context
    assert "Suggested animal: " + ANIMAL in context


def test_converter_generate_and_send_sends_photo_via_telegram() -> None:
    dossier = make_dossier()
    state = make_session_state(42, PORTRAIT, dossier)
    stub = StubConverterClient(responses=[converter_output_json(HYBRID_IMAGE)])
    telegram = StubTelegramClient()

    converter = Converter(state, stub, telegram)
    converter.generate_and_send(42)

    assert telegram.sent_photos == [(42, HYBRID_IMAGE)]


def test_converter_generate_and_send_advances_to_scripting_on_success() -> None:
    dossier = make_dossier()
    state = make_session_state(42, PORTRAIT, dossier)
    stub = StubConverterClient(responses=[converter_output_json(HYBRID_IMAGE)])
    telegram = StubTelegramClient()

    converter = Converter(state, stub, telegram)
    converter.generate_and_send(42)

    session = state.load(42)
    assert session.phase is Phase.SCRIPTING


# --- Converter failure handling (plan 3.2) -----------------------------------


def test_converter_generate_and_send_malformed_model_output_returns_none_and_logs_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dossier = make_dossier()
    state = make_session_state(42, PORTRAIT, dossier)
    stub = StubConverterClient(responses=["not valid json"])
    telegram = StubTelegramClient()

    converter = Converter(state, stub, telegram)

    with caplog.at_level(logging.ERROR):
        result = converter.generate_and_send(42)

    assert result is None
    assert telegram.sent == [(42, CONVERTER_FAILURE_TEXT)]
    session = state.load(42)
    assert session.phase is Phase.SCRIPTING
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


def test_converter_generate_and_send_client_exception_returns_none_and_logs_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dossier = make_dossier()
    state = make_session_state(42, PORTRAIT, dossier)
    stub = StubConverterClient(responses=[RuntimeError("gemini exploded")])
    telegram = StubTelegramClient()

    converter = Converter(state, stub, telegram)

    with caplog.at_level(logging.ERROR):
        result = converter.generate_and_send(42)

    assert result is None
    assert telegram.sent == [(42, CONVERTER_FAILURE_TEXT)]
    session = state.load(42)
    assert session.phase is Phase.SCRIPTING
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


def test_converter_failure_sends_text_advances_to_scripting(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dossier = make_dossier()
    state = make_session_state(42, PORTRAIT, dossier)
    stub = StubConverterClient(responses=["not valid json"])
    telegram = StubTelegramClient()

    converter = Converter(state, stub, telegram)

    with caplog.at_level(logging.ERROR):
        result = converter.generate_and_send(42)

    assert result is None
    assert telegram.sent == [(42, CONVERTER_FAILURE_TEXT)]
    session = state.load(42)
    assert session.phase is Phase.SCRIPTING
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


def test_converter_generate_and_send_missing_photo_returns_none_and_logs_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = StateDriver()
    session = state.load(42)
    session.phase = Phase.CONVERTING
    session.dossier = make_dossier()
    state.save(session)
    stub = StubConverterClient(responses=[converter_output_json(HYBRID_IMAGE)])
    telegram = StubTelegramClient()

    converter = Converter(state, stub, telegram)

    with caplog.at_level(logging.ERROR):
        result = converter.generate_and_send(42)

    assert result is None
    assert telegram.sent == [(42, CONVERTER_FAILURE_TEXT)]
    session = state.load(42)
    assert session.phase is Phase.SCRIPTING
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


def test_converter_generate_and_send_missing_dossier_returns_none_and_logs_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = StateDriver()
    session = state.load(42)
    session.phase = Phase.CONVERTING
    session.photo = PORTRAIT
    state.save(session)
    stub = StubConverterClient(responses=[converter_output_json(HYBRID_IMAGE)])
    telegram = StubTelegramClient()

    converter = Converter(state, stub, telegram)

    with caplog.at_level(logging.ERROR):
        result = converter.generate_and_send(42)

    assert result is None
    assert telegram.sent == [(42, CONVERTER_FAILURE_TEXT)]
    session = state.load(42)
    assert session.phase is Phase.SCRIPTING
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


def test_converter_generate_and_send_wrong_phase_returns_none_and_logs_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = StateDriver()
    session = state.load(42)
    session.phase = Phase.INTERVIEWING
    session.photo = PORTRAIT
    session.dossier = make_dossier()
    state.save(session)
    stub = StubConverterClient(responses=[converter_output_json(HYBRID_IMAGE)])
    telegram = StubTelegramClient()

    converter = Converter(state, stub, telegram)

    with caplog.at_level(logging.ERROR):
        result = converter.generate_and_send(42)

    assert result is None
    assert telegram.sent == [(42, CONVERTER_FAILURE_TEXT)]
    session = state.load(42)
    assert session.phase is Phase.SCRIPTING
    assert any(record.levelno >= logging.ERROR for record in caplog.records)


def test_converter_failure_preserves_dossier_for_scripter() -> None:
    """On failure, the dossier must survive so the Scripter can still run."""
    dossier = make_dossier()
    state = make_session_state(42, PORTRAIT, dossier)
    stub = StubConverterClient(responses=["not valid json"])
    telegram = StubTelegramClient()

    converter = Converter(state, stub, telegram)
    converter.generate_and_send(42)

    session = state.load(42)
    assert session.phase is Phase.SCRIPTING
    assert session.dossier.profile == PROFILE
    assert session.dossier.suggested_animal == ANIMAL
    assert session.dossier.questions == dossier.questions
    assert session.dossier.answers == dossier.answers


class StubTelegramClient:
    """Minimal stub for unit tests — records sent messages and photos."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.sent_photos: list[tuple[int, bytes]] = []

    def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))

    def send_photo(self, chat_id: int, photo: bytes) -> None:
        self.sent_photos.append((chat_id, photo))
