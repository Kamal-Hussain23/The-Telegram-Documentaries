"""Opt-in live check against the real `gemini-3.1-flash-lite` Scripter.

Skipped unless ``GEMINI_API_KEY`` is present, so the default suite stays green
offline (plan 5.3, requirements decision 8). The offline suite proves the wiring
against a scripted client; this one is the judgement check — a real model must
turn a completed dossier into one short, plain paragraph of narration.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from telegram_documentaries.scripter import MAX_SCRIPT_WORDS, Scripter, has_markdown
from telegram_documentaries.scripter_client import GeminiScripterClient
from telegram_documentaries.state import Dossier, Phase, StateDriver

load_dotenv()
_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()


@pytest.mark.skipif(not _API_KEY, reason="GEMINI_API_KEY not set; live Scripter check is opt-in")
def test_live_scripter_produces_a_valid_script_and_advances_the_phase() -> None:
    state = StateDriver()
    scripter = Scripter(state, GeminiScripterClient(api_key=_API_KEY))

    session = state.load(42)
    session.phase = Phase.SCRIPTING
    session.dossier = Dossier(
        profile="A nocturnal stargazer with a chocolate habit.",
        suggested_animal="owl",
        questions=[
            "What do you do at midnight?",
            "What is your favourite snack?",
            "Where would we find you at 3am?",
        ],
        answers=[
            "I scroll through star charts.",
            "Dark chocolate, always.",
            "On the balcony, watching the sky.",
        ],
    )
    state.save(session)

    output = scripter.generate(42)

    assert output.script.strip()
    assert "\n\n" not in output.script
    assert len(output.script.split()) <= MAX_SCRIPT_WORDS
    assert not has_markdown(output.script)

    session = state.load(42)
    assert session.phase is Phase.NARRATING
    assert session.dossier.script == output.script
