"""The Bouncer's verdict is a typed contract, never free text.

Reference: SPECS/2026-10-06-bouncer/requirements.md decisions 4 & 5,
plan group 1.2/1.3, validation.md check 3.3.
"""

from __future__ import annotations

import json
import logging

import pytest
from telegram_documentaries.bouncer import (
    Bouncer,
    BouncerVerdict,
    VerdictError,
    parse_verdict,
)
from tests.support.fakes import StubVisionClient, fixture_bytes


def verdict_json(human_present: bool, **extra: object) -> str:
    return json.dumps({"human_present": human_present, **extra})


def test_parse_verdict_accepts_structured_json() -> None:
    verdict = parse_verdict(verdict_json(True, confidence=0.93, reason="a clear face"))

    assert isinstance(verdict, BouncerVerdict)
    assert verdict.human_present is True
    assert verdict.confidence == 0.93


def test_parse_verdict_reads_a_negative_verdict() -> None:
    assert parse_verdict(verdict_json(False)).human_present is False


def test_parse_verdict_rejects_free_text() -> None:
    with pytest.raises(VerdictError):
        parse_verdict("Sure, that looks like a person to me!")


@pytest.mark.parametrize(
    "raw",
    [
        "{not json",
        '["human_present"]',
        '{"confidence": 0.5}',
        '{"human_present": "maybe"}',
    ],
)
def test_parse_verdict_rejects_schema_violations(raw: str) -> None:
    with pytest.raises(VerdictError):
        parse_verdict(raw)


def test_bouncer_returns_a_typed_verdict_for_a_stubbed_response() -> None:
    bouncer = Bouncer(StubVisionClient([verdict_json(True, confidence=0.99)]))

    verdict = bouncer.classify(fixture_bytes("person.jpg"))

    assert verdict == BouncerVerdict(human_present=True, confidence=0.99)


def test_bouncer_classifies_the_exact_downloaded_bytes() -> None:
    image = fixture_bytes("landscape.jpg")
    vision = StubVisionClient([verdict_json(False)])

    Bouncer(vision).classify(image)

    assert vision.calls == [image]


def test_bouncer_turns_malformed_model_output_into_a_handled_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bouncer = Bouncer(StubVisionClient(["I am not sure, maybe a dog?"]))

    with caplog.at_level(logging.ERROR):
        with pytest.raises(VerdictError):
            bouncer.classify(fixture_bytes("person.jpg"))

    assert any(record.levelno >= logging.ERROR for record in caplog.records)
