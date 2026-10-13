"""Opt-in live check against the real `gemini-3.1-flash-image` Converter.

Skipped unless ``GEMINI_API_KEY`` is present, so the default suite stays green
offline (plan 5.3, requirements decision 8). The offline suite proves the
wiring against a scripted client; this one is the judgement check — a real
model must fuse the photo and dossier into a valid hybrid portrait.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from telegram_documentaries.converter import Converter
from telegram_documentaries.converter_client import GeminiConverterClient
from telegram_documentaries.interview_client import GeminiInterviewClient
from telegram_documentaries.interviewer import Interviewer
from telegram_documentaries.state import Phase, StateDriver
from tests.support.fakes import fixture_bytes

load_dotenv()
_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()


@pytest.mark.skipif(not _API_KEY, reason="GEMINI_API_KEY not set; live converter check is opt-in")
def test_live_converter_generates_hybrid_portrait() -> None:
    """Real gemini-3.1-flash-image call produces valid hybrid image and advances to SCRIPTING."""
    state = StateDriver()
    chat_id = 42

    # First, run the Interviewer to completion to get a dossier.
    interviewer = Interviewer(state, GeminiInterviewClient(api_key=_API_KEY))
    photo = fixture_bytes("person.jpg")

    # Start interview.
    reply = interviewer.start(chat_id, photo)
    assert reply.strip(), "first question must not be empty"

    # Answer questions until interview completes.
    answers = [
        "I reorganise the entire bookshelf whenever I can't sleep.",
        "Probably the chipped blue mug — it has seen some things.",
        "The narrator would call me methodically unhurried.",
        "My spare blanket. It gets used every single night.",
    ]
    for answer in answers:
        if state.load(chat_id).phase is not Phase.INTERVIEWING:
            break
        reply = interviewer.answer(chat_id, answer)

    # Verify interview completed and advanced to CONVERTING.
    session = state.load(chat_id)
    assert session.phase is Phase.CONVERTING
    assert session.dossier.profile is not None
    assert session.dossier.suggested_animal is not None
    assert session.photo == photo

    # Now run the Converter with the real client.
    converter = Converter(
        state,
        GeminiConverterClient(api_key=_API_KEY),
        # Use a fake telegram client that records the sent photo.
        FakeTelegramClientForLive(),
    )

    output = converter.generate_and_send(chat_id)

    # Verify the output.
    assert output is not None, "Converter should return ConverterOutput on success"
    assert output.image_bytes is not None
    assert len(output.image_bytes) > 0, "Generated image bytes must not be empty"

    # Verify phase advanced to SCRIPTING.
    session = state.load(chat_id)
    assert session.phase is Phase.SCRIPTING
    # Dossier should be intact.
    assert session.dossier.profile is not None
    assert session.dossier.suggested_animal is not None


class FakeTelegramClientForLive:
    """Minimal fake Telegram client for live test that records sent photo."""

    def __init__(self) -> None:
        self.sent_photos: list[tuple[int, bytes]] = []
        self.sent_messages: list[tuple[int, str]] = []

    def send_photo(self, chat_id: int, photo: bytes) -> None:
        self.sent_photos.append((chat_id, photo))

    def send_message(self, chat_id: int, text: str) -> None:
        self.sent_messages.append((chat_id, text))
