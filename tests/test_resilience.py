"""Resilience unit tests: purge, wrong-payload constants, timeouts.

Reference: SPECS/2026-10-13-resilience/requirements.md, plan.md groups 1.3, 2.7, 3.5.
Everything runs offline — no GEMINI_API_KEY required.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from telegram_documentaries.bot import (
    AWAITING_PHOTO_REPLY,
    CONVERTING_REPLY,
    INTERVIEWING_PHOTO_REPLY,
    INTERVIEWING_TEXT_REPLY,
    NARRATING_REPLY,
    SCRIPTING_REPLY,
)
from telegram_documentaries.converter_client import GeminiConverterClient
from telegram_documentaries.interview_client import GeminiInterviewClient
from telegram_documentaries.narrator_client import GeminiTTSClient
from telegram_documentaries.state import StateDriver

# --- Purge tests (plan 1.3) ----------------------------------------------------


def test_reset_deletes_converted_files() -> None:
    """StateDriver.reset(chat_id) deletes converted_<chat_id>_* files from temp dir."""
    state = StateDriver()
    chat_id = 42

    # Create temp dir and fake converted files
    audio_dir = Path(tempfile.gettempdir()) / "telegram_documentaries"
    audio_dir.mkdir(parents=True, exist_ok=True)

    converted_file = audio_dir / f"converted_{chat_id}_test.jpg"
    converted_file.write_bytes(b"fake-image-data")

    # Also create the existing patterns to ensure no regression
    narration_file = audio_dir / f"narration_{chat_id}_test.ogg"
    narration_file.write_bytes(b"fake-audio-data")

    photo_file = audio_dir / f"photo_{chat_id}_test.jpg"
    photo_file.write_bytes(b"fake-photo-data")

    # Another chat's files should not be touched
    other_chat_file = audio_dir / f"converted_{chat_id + 1}_other.jpg"
    other_chat_file.write_bytes(b"other-chat-data")

    # Call reset
    state.reset(chat_id)

    # Assert converted file is deleted
    assert not converted_file.exists(), "converted_<chat_id>_* file should be deleted"

    # Assert existing patterns still deleted (no regression)
    assert not narration_file.exists(), "narration_<chat_id>_* file should still be deleted"
    assert not photo_file.exists(), "photo_<chat_id>_* file should still be deleted"

    # Other chat's file should remain
    assert other_chat_file.exists(), "other chat's files should not be deleted"

    # Session should be at AWAITING_PHOTO
    session = state.load(chat_id)
    assert session.phase.name == "AWAITING_PHOTO"


def test_reset_clears_dossier_and_phase() -> None:
    """Reset clears dossier, profile, suggested_animal, script, and resets phase."""
    state = StateDriver()
    chat_id = 99

    session = state.load(chat_id)
    session.phase = session.phase.__class__.SCRIPTING
    session.dossier.profile = "Some profile"
    session.dossier.suggested_animal = "raccoon"
    session.dossier.script = "Some script"
    session.dossier.questions = ["Q1", "Q2"]
    session.dossier.answers = ["A1", "A2"]
    state.save(session)

    state.reset(chat_id)

    session = state.load(chat_id)
    assert session.phase.name == "AWAITING_PHOTO"
    assert session.photo is None
    assert session.dossier.profile is None
    assert session.dossier.suggested_animal is None
    assert session.dossier.script is None
    assert session.dossier.questions == []
    assert session.dossier.answers == []


# --- Wrong-payload constant tests (plan 2.7) -----------------------------------


def test_wrong_payload_constants_exist_and_non_empty() -> None:
    """All wrong-payload reply constants are defined and non-empty strings."""
    constants = [
        AWAITING_PHOTO_REPLY,
        INTERVIEWING_PHOTO_REPLY,
        INTERVIEWING_TEXT_REPLY,
        CONVERTING_REPLY,
        SCRIPTING_REPLY,
        NARRATING_REPLY,
    ]
    for const in constants:
        assert isinstance(const, str), f"Expected string, got {type(const)}"
        assert len(const) > 0, "Constant should be non-empty"


def test_wrong_payload_constants_in_character() -> None:
    """Wrong-payload replies are in-character, cheeky tone (not robotic)."""
    # These should not contain robotic/error-like phrases
    robotic_phrases = ["error", "invalid", "unexpected", "fail", "crash", "traceback", "exception"]

    constants = [
        AWAITING_PHOTO_REPLY,
        INTERVIEWING_PHOTO_REPLY,
        INTERVIEWING_TEXT_REPLY,
        CONVERTING_REPLY,
        SCRIPTING_REPLY,
        NARRATING_REPLY,
    ]

    for const in constants:
        lowered = const.lower()
        for phrase in robotic_phrases:
            assert phrase not in lowered, f"Constant contains robotic phrase '{phrase}': {const}"

    # Check specific in-character content
    assert "photo" in AWAITING_PHOTO_REPLY.lower()
    assert (
        "mid-interview" in INTERVIEWING_PHOTO_REPLY.lower()
        or "interview" in INTERVIEWING_PHOTO_REPLY.lower()
    )
    assert "text" in INTERVIEWING_TEXT_REPLY.lower()
    assert "darkroom" in CONVERTING_REPLY.lower() or "develop" in CONVERTING_REPLY.lower()
    assert "script" in SCRIPTING_REPLY.lower()
    assert "voice" in NARRATING_REPLY.lower() or "record" in NARRATING_REPLY.lower()


# --- Timeout tests (plan 3.5) --------------------------------------------------


class MockAsyncIterator:
    """Helper to make an async generator into a proper async iterator."""

    def __init__(self, agen):
        self._agen = agen

    def __aiter__(self):
        return self._agen()


class MockQuestionRunner:
    """Mock runner that simulates a slow ADK runner."""

    def __init__(self, delay: float = 10.0):
        self._delay = delay

    def run_async(self, user_id: str, session_id: str, new_message):
        async def _agen():
            await asyncio.sleep(self._delay)
            yield MagicMock(
                is_final_response=lambda: True,
                content=MagicMock(parts=[MagicMock(text="test question")]),
            )

        return MockAsyncIterator(_agen)

    class session_service:
        @staticmethod
        async def create_session(app_name: str, user_id: str):
            return MagicMock(id="test-session")

        @staticmethod
        async def delete_session(app_name: str, user_id: str, session_id: str):
            pass


class MockProfileRunner:
    """Mock runner that simulates a slow ADK runner."""

    def __init__(self, delay: float = 10.0):
        self._delay = delay

    def run_async(self, user_id: str, session_id: str, new_message):
        async def _agen():
            await asyncio.sleep(self._delay)
            yield MagicMock(
                is_final_response=lambda: True,
                content=MagicMock(parts=[MagicMock(text="test profile")]),
            )

        return MockAsyncIterator(_agen)

    class session_service:
        @staticmethod
        async def create_session(app_name: str, user_id: str):
            return MagicMock(id="test-session")

        @staticmethod
        async def delete_session(app_name: str, user_id: str, session_id: str):
            pass


class MockConverterRunner:
    """Mock runner that simulates a slow ADK runner."""

    def __init__(self, delay: float = 10.0):
        self._delay = delay

    def run_async(self, user_id: str, session_id: str, new_message):
        async def _agen():
            await asyncio.sleep(self._delay)
            yield MagicMock(
                is_final_response=lambda: True,
                content=MagicMock(parts=[MagicMock(inline_data=MagicMock(data=b"fake-image"))]),
            )

        return MockAsyncIterator(_agen)

    class session_service:
        @staticmethod
        async def create_session(app_name: str, user_id: str):
            return MagicMock(id="test-session")

        @staticmethod
        async def delete_session(app_name: str, user_id: str, session_id: str):
            pass


def test_interviewer_client_timeout_raises_handled_error() -> None:
    """Interviewer client with 10s sleep and 1s timeout raises InterviewerError."""
    from telegram_documentaries.interviewer import InterviewerError

    # Create a real client but with mocked runners
    client = GeminiInterviewClient.__new__(GeminiInterviewClient)
    client._timeout = 1.0
    client._question_runner = MockQuestionRunner(delay=10.0)
    client._profile_runner = MockProfileRunner(delay=10.0)

    with pytest.raises(InterviewerError) as exc_info:
        client.generate_question("test context")

    assert "timeout" in str(exc_info.value).lower()


def test_converter_client_timeout_raises_handled_error() -> None:
    """Converter client with 10s sleep and 1s timeout raises ConverterError."""
    from telegram_documentaries.converter import ConverterError

    # Create a real client but with mocked runner
    client = GeminiConverterClient.__new__(GeminiConverterClient)
    client._timeout = 1.0
    client._runner = MockConverterRunner(delay=10.0)

    with pytest.raises(ConverterError) as exc_info:
        client.generate_image(b"photo", "context")

    assert "timeout" in str(exc_info.value).lower()


def test_narrator_client_timeout_raises_handled_error() -> None:
    """Narrator client with 10s sleep and 1s timeout raises NarratorError."""
    from concurrent.futures import Future

    from telegram_documentaries.narrator import NarratorError

    # Create a real client but mock the executor
    client = GeminiTTSClient.__new__(GeminiTTSClient)
    client._timeout = 1.0
    client._model = "test"
    client._voice = "test"

    # Create a mock executor that returns a Future that never completes
    from unittest.mock import MagicMock

    mock_executor = MagicMock()

    def slow_submit(fn, *args, **kwargs):
        future = Future()
        # Never set result - this simulates a slow/blocking call
        return future

    mock_executor.submit = slow_submit
    client._executor = mock_executor

    with pytest.raises(NarratorError) as exc_info:
        client.synthesize("test script")

    assert "timeout" in str(exc_info.value).lower()


# --- DEFAULT_GEMINI_TIMEOUT constant defined and used by all three clients ---


def test_default_gemini_timeout_constant_exists() -> None:
    """DEFAULT_GEMINI_TIMEOUT = 60.0 constant defined and used by all clients."""
    from telegram_documentaries.converter_client import DEFAULT_GEMINI_TIMEOUT as converter_timeout
    from telegram_documentaries.interview_client import DEFAULT_GEMINI_TIMEOUT as interview_timeout
    from telegram_documentaries.narrator_client import DEFAULT_GEMINI_TIMEOUT as narrator_timeout

    assert interview_timeout == 60.0
    assert converter_timeout == 60.0
    assert narrator_timeout == 60.0
    assert interview_timeout == converter_timeout == narrator_timeout


# --- SCHEMA_VERSION unchanged (still 4) ---


def test_schema_version_unchanged() -> None:
    """SCHEMA_VERSION remains 4 (no session state shape change)."""
    from telegram_documentaries.state import SCHEMA_VERSION

    assert SCHEMA_VERSION == 4
