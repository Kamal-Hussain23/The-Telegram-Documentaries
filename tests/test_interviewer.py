"""The Interviewer's two model outputs are typed contracts, never free text.

Reference: SPECS/2026-10-08-interviewer/requirements.md decisions 2 & 9,
plan group 1.1–1.2, validation.md checks 3.1 and 4.4.
"""

from __future__ import annotations

import logging

import pytest
from telegram_documentaries.interviewer import (
    Interviewer,
    InterviewerError,
    InterviewProfile,
    NextQuestion,
    parse_next_question,
    parse_profile,
)
from telegram_documentaries.state import StateDriver
from tests.support.fakes import StubInterviewClient, profile_json, question_json

PORTRAIT = b"\xff\xd8\xffportrait-bytes"


# --- the scripted interview client (plan 1.1) ------------------------------


def test_stub_interview_client_records_the_prompt_context_of_every_call() -> None:
    stub = StubInterviewClient(
        questions=[question_json("First question?")],
        profiles=[profile_json("A tidy chaos-monkey.", "macaque")],
    )

    stub.generate_question("context one")
    stub.synthesize_profile("context two")

    assert stub.question_calls == ["context one"]
    assert stub.profile_calls == ["context two"]


def test_stub_interview_client_fails_loudly_when_the_script_runs_out() -> None:
    with pytest.raises(AssertionError):
        StubInterviewClient().generate_question("context")


# --- NextQuestion contract (plan 1.2) --------------------------------------


def test_parse_next_question_accepts_structured_json() -> None:
    parsed = parse_next_question(question_json("What is your middle name?", is_final=True))

    assert isinstance(parsed, NextQuestion)
    assert parsed.question == "What is your middle name?"
    assert parsed.is_final is True


def test_parse_next_question_reads_a_non_final_question() -> None:
    parsed = parse_next_question(question_json("What do you do at 3am?"))

    assert parsed.question == "What do you do at 3am?"
    assert parsed.is_final is False


def test_parse_next_question_rejects_free_text() -> None:
    with pytest.raises(InterviewerError):
        parse_next_question("Sure — ask them what they do for a living!")


@pytest.mark.parametrize(
    "raw",
    [
        "{not json",
        '["question"]',
        '{"is_final": true}',
        '{"question": "hi"}',
        '{"question": ["hi"], "is_final": false}',
        '{"question": "hi", "is_final": "maybe"}',
    ],
)
def test_parse_next_question_rejects_schema_violations(raw: str) -> None:
    with pytest.raises(InterviewerError):
        parse_next_question(raw)


# --- InterviewProfile contract (plan 1.2) ----------------------------------


def test_parse_profile_accepts_structured_json() -> None:
    parsed = parse_profile(profile_json("Always snacks at midnight.", "raccoon"))

    assert isinstance(parsed, InterviewProfile)
    assert parsed.profile == "Always snacks at midnight."
    assert parsed.suggested_animal == "raccoon"


def test_parse_profile_rejects_free_text() -> None:
    with pytest.raises(InterviewerError):
        parse_profile("I'd say they're basically a raccoon already.")


@pytest.mark.parametrize(
    "raw",
    [
        "{not json",
        '["profile"]',
        '{"suggested_animal": "raccoon"}',
        '{"profile": "A tidy chaos-monkey."}',
        '{"profile": ["messy"], "suggested_animal": "raccoon"}',
        '{"profile": "A tidy chaos-monkey.", "suggested_animal": 7}',
    ],
)
def test_parse_profile_rejects_schema_violations(raw: str) -> None:
    with pytest.raises(InterviewerError):
        parse_profile(raw)


# --- handled errors, logged loudly by the decorator (plan 1.2 / decision 9) -


def test_malformed_question_output_raises_a_handled_interviewer_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    interviewer = Interviewer(StateDriver(), StubInterviewClient(questions=["no idea, sorry"]))

    with caplog.at_level(logging.ERROR):
        with pytest.raises(InterviewerError):
            interviewer.start(42, PORTRAIT)

    assert any(record.levelno >= logging.ERROR for record in caplog.records)


def test_malformed_profile_output_raises_a_handled_interviewer_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = StateDriver()
    interviewer = Interviewer(
        state,
        StubInterviewClient(
            questions=[
                question_json("Question one?"),
                question_json("Question two?"),
                question_json("Question three?", is_final=True),
            ],
            profiles=["that is not a profile"],
        ),
    )

    interviewer.start(42, PORTRAIT)
    interviewer.answer(42, "answer one")
    interviewer.answer(42, "answer two")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(InterviewerError):
            interviewer.answer(42, "answer three")

    assert any(record.levelno >= logging.ERROR for record in caplog.records)
