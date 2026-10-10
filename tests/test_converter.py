"""The Converter's model output is a typed contract, never free text.

Reference: SPECS/2026-10-09-converter/requirements.md decisions 3 & 6,
plan group 1.2/1.3, validation.md check 3.3.
"""

from __future__ import annotations

import base64
import json
import logging

import pytest
from telegram_documentaries.converter import (
    Converter,
    ConverterError,
    ConverterOutput,
    parse_output,
)
from telegram_documentaries.state import Dossier, Phase, StateDriver
from tests.support.fakes import StubConverterClient, converter_output_json, fixture_bytes

PERSON = fixture_bytes("person.jpg")
HYBRID = fixture_bytes("landscape.jpg")  # reuse as the "generated" hybrid


def test_parse_output_accepts_structured_json() -> None:
    payload = base64.b64encode(HYBRID).decode("ascii")
    raw = f'{{"image_bytes": "{payload}", "confidence": 0.93, "reason": "a clear hybrid"}}'
    output = parse_output(raw)

    assert isinstance(output, ConverterOutput)
    assert output.image_bytes == HYBRID
    assert output.confidence == 0.93
    assert output.reason == "a clear hybrid"


def test_parse_output_reads_minimal_valid_output() -> None:
    payload = base64.b64encode(HYBRID).decode("ascii")
    raw = f'{{"image_bytes": "{payload}"}}'
    output = parse_output(raw)

    assert output.image_bytes == HYBRID
    assert output.confidence is None
    assert output.reason is None


def test_parse_output_accepts_line_wrapped_base64() -> None:
    """Real Gemini base64 output is commonly line-wrapped; whitespace is tolerated."""
    payload = base64.b64encode(HYBRID).decode("ascii")
    wrapped = "\n".join(payload[i : i + 76] for i in range(0, len(payload), 76)) or payload
    raw = json.dumps({"image_bytes": wrapped})

    output = parse_output(raw)

    assert output.image_bytes == HYBRID


def test_parse_output_rejects_invalid_base64_even_with_whitespace() -> None:
    """Stripping whitespace must not let genuinely invalid base64 through."""
    raw = json.dumps({"image_bytes": "not base64!!"})
    with pytest.raises(ConverterError):
        parse_output(raw)


def test_parse_output_rejects_free_text() -> None:
    with pytest.raises(ConverterError):
        parse_output("Here is your hybrid portrait!")


@pytest.mark.parametrize(
    "raw",
    [
        "{not json",
        '["image_bytes"]',
        '{"confidence": 0.5}',
        '{"image_bytes": 123}',
        '{"image_bytes": "not-base64!", "confidence": "high"}',
    ],
)
def test_parse_output_rejects_schema_violations(raw: str) -> None:
    with pytest.raises(ConverterError):
        parse_output(raw)


def test_converter_returns_a_typed_output_for_a_stubbed_response() -> None:
    payload = base64.b64encode(HYBRID).decode("ascii")
    state = StateDriver()
    client = StubConverterClient([f'{{"image_bytes": "{payload}", "confidence": 0.99}}'])
    converter = Converter(state, client)

    # Set up session state
    session = state.load(42)
    session.phase = Phase.CONVERTING
    session.photo = PERSON
    session.dossier = Dossier(profile="Test profile", suggested_animal="raccoon")
    state.save(session)

    output = converter.convert(42)

    assert output.image_bytes == HYBRID
    assert output.confidence == 0.99
    assert output.reason is None


def test_converter_passes_exact_inputs_to_client() -> None:
    state = StateDriver()
    client = StubConverterClient([converter_output_json(HYBRID)])
    converter = Converter(state, client)

    # Set up session state
    session = state.load(42)
    session.phase = Phase.CONVERTING
    session.photo = PERSON
    session.dossier = Dossier(profile="Test profile", suggested_animal="raccoon")
    state.save(session)

    converter.convert(42)

    expected_context = "Profile: Test profile\nSuggested animal: raccoon\nInterview:"
    assert client.convert_calls == [(PERSON, expected_context)]


def test_converter_turns_malformed_model_output_into_a_handled_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = StateDriver()
    client = StubConverterClient(["I am not sure, maybe a dog?"])
    converter = Converter(state, client)

    # Set up session state
    session = state.load(42)
    session.phase = Phase.CONVERTING
    session.photo = PERSON
    session.dossier = Dossier(profile="Test profile", suggested_animal="raccoon")
    state.save(session)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(ConverterError):
            converter.convert(42)

    assert any(record.levelno >= logging.ERROR for record in caplog.records)
