"""Opt-in live check against the real `gemini-3.1-flash-lite` Interviewer.

Skipped unless ``GEMINI_API_KEY`` is present, so the default suite stays green
offline (plan 6.3, requirements decision 8). The offline suite proves the
wiring against a scripted client; this one is the judgement check — a real
model must carry a 3–4 question interview through to a profile and a
suggested animal.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from telegram_documentaries.interview_client import GeminiInterviewClient
from telegram_documentaries.interviewer import (
    MAX_QUESTIONS,
    MIN_QUESTIONS,
    Interviewer,
)
from telegram_documentaries.state import Phase, StateDriver
from tests.support.fakes import fixture_bytes

load_dotenv()
_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

#: Terse, distinctive answers so the model has something concrete to adapt to.
ANSWERS = [
    "I reorganise the entire bookshelf whenever I can't sleep.",
    "Probably the chipped blue mug — it has seen some things.",
    "The narrator would call me methodically unhurried.",
    "My spare blanket. It gets used every single night.",
]


@pytest.mark.skipif(not _API_KEY, reason="GEMINI_API_KEY not set; live interview check is opt-in")
def test_live_interview_runs_three_to_four_questions_and_completes() -> None:
    state = StateDriver()
    interviewer = Interviewer(state, GeminiInterviewClient(api_key=_API_KEY))

    replies = [interviewer.start(42, fixture_bytes("person.jpg"))]
    assert replies[0].strip(), "the first question must not be empty"

    # Answer until the interview completes; the ceiling guarantees it does.
    for answer in ANSWERS:
        if state.load(42).phase is not Phase.INTERVIEWING:
            break
        replies.append(interviewer.answer(42, answer))

    session = state.load(42)
    dossier = session.dossier
    assert session.phase is Phase.SCRIPTING
    assert MIN_QUESTIONS <= len(dossier.questions) <= MAX_QUESTIONS
    assert dossier.profile and dossier.profile.strip()
    assert dossier.suggested_animal and dossier.suggested_animal.strip()
    # One reply per turn, ending on the in-character reveal — never the profile.
    assert len(replies) == len(dossier.answers) + 1
    assert dossier.suggested_animal in replies[-1]
    assert dossier.profile not in replies[-1]
