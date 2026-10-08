"""Opt-in live check against the real `gemini-3.1-flash-lite` Bouncer.

Skipped unless ``GEMINI_API_KEY`` is present, so the default suite stays green
offline (requirements decision 8). The positive/negative fixtures are chosen to
be unambiguous so the live check agrees with the offline stub.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from telegram_documentaries.bouncer import Bouncer
from telegram_documentaries.vision import GeminiVisionClient
from tests.support.fakes import fixture_bytes

load_dotenv()
_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()


@pytest.mark.skipif(not _API_KEY, reason="GEMINI_API_KEY not set; live Bouncer check is opt-in")
def test_live_bouncer_accepts_a_person_and_rejects_a_landscape() -> None:
    bouncer = Bouncer(GeminiVisionClient(api_key=_API_KEY))

    assert bouncer.classify(fixture_bytes("person.jpg")).human_present is True
    assert bouncer.classify(fixture_bytes("landscape.jpg")).human_present is False
