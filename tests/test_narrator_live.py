"""Opt-in live check against the real `gemini-3.1-flash-tts-preview` Narrator.

Skipped unless ``GEMINI_API_KEY`` is present, so the default suite stays green
offline (plan 6.6, requirements decision 12). The offline suite proves the
wiring against a scripted client; this one is the judgement check — a real TTS
call must turn the narration script into OGG/Opus audio delivered as a voice
note.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from telegram_documentaries.narrator import Narrator
from telegram_documentaries.narrator_client import GeminiTTSClient
from telegram_documentaries.state import Phase, StateDriver
from tests.support.fakes import FakeTelegramClient

load_dotenv()
_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()


@pytest.mark.skipif(not _API_KEY, reason="GEMINI_API_KEY not set; live Narrator check is opt-in")
def test_live_narrator_synthesizes_the_script_into_a_voice_note() -> None:
    state = StateDriver()
    script = (
        "In the vast kitchen of the universe, our subject, a midnight raccoon, "
        "prepares a humble midnight toast while the stars wheel overhead."
    )
    session = state.load(42)
    session.phase = Phase.NARRATING
    session.dossier.script = script
    state.save(session)

    telegram = FakeTelegramClient()
    narrator = Narrator(state, GeminiTTSClient(api_key=_API_KEY), telegram)

    narrator.synthesize_and_deliver(42)

    # A real OGG/Opus stream was delivered as a voice note.
    assert len(telegram.sent_voices) == 1
    chat_id, voice, mime_type, filename = telegram.sent_voices[0]
    assert chat_id == 42
    assert voice.startswith(b"OggS")
    assert mime_type == "audio/ogg"
    assert filename.endswith(".ogg")

    session = state.load(42)
    assert session.phase is Phase.AWAITING_PHOTO
    assert session.dossier.script is None
