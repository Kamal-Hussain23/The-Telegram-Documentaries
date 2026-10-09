"""Deterministic offline test doubles for the Bouncer and Interviewer suites.

Nothing here touches the network or requires ``GEMINI_API_KEY``: the Gemini
vision and interview clients are stubbed and the Telegram client is scripted,
so the default suite stays green in CI. The real dependencies land in groups
2–5 of each phase.
"""

from __future__ import annotations

import json
from pathlib import Path

from telegram_documentaries.models import Update

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    """Read one of the committed test images from ``tests/fixtures/``."""
    return (FIXTURE_DIR / name).read_bytes()


class StubVisionClient:
    """Scripted Gemini vision client: queues raw verdicts, records images.

    Structurally implements the real client's ``classify(image) -> str``
    protocol (the ADK-backed implementation arrives in group 4), but never
    talks to Gemini.
    """

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[bytes] = []

    def classify(self, image: bytes) -> str:
        self.calls.append(image)
        if not self._responses:
            raise AssertionError("StubVisionClient ran out of scripted responses")
        return self._responses.pop(0)


def question_json(question: str, *, is_final: bool = False) -> str:
    """A raw ``NextQuestion`` payload exactly as the model would emit it."""
    return json.dumps({"question": question, "is_final": is_final})


def profile_json(profile: str, suggested_animal: str) -> str:
    """A raw ``InterviewProfile`` payload exactly as the model would emit it."""
    return json.dumps({"profile": profile, "suggested_animal": suggested_animal})


class StubInterviewClient:
    """Scripted Gemini interview client: queues raw structured outputs.

    Structurally implements the real client's ``InterviewClient`` protocol —
    ``generate_question`` and ``synthesize_profile`` return raw JSON for the
    Interviewer to parse at the edge — but never touches the network. Every
    call records the prompt context it was handed, and any scripted entry may
    be an exception instance to simulate Gemini failing mid-interview.
    """

    def __init__(
        self,
        questions: list[str | BaseException] | None = None,
        profiles: list[str | BaseException] | None = None,
    ) -> None:
        self._questions = list(questions or [])
        self._profiles = list(profiles or [])
        #: The prompt context of every question-generation call, in order.
        self.question_calls: list[str] = []
        #: The prompt context of every profile-synthesis call, in order.
        self.profile_calls: list[str] = []

    def generate_question(self, context: str) -> str:
        self.question_calls.append(context)
        return self._next(self._questions, "question")

    def synthesize_profile(self, context: str) -> str:
        self.profile_calls.append(context)
        return self._next(self._profiles, "profile")

    @staticmethod
    def _next(script: list[str | BaseException], label: str) -> str:
        if not script:
            raise AssertionError(f"StubInterviewClient ran out of scripted {label}s")
        item = script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeTelegramClient:
    """Scripted Telegram client: serves updates/downloads, records sends."""

    def __init__(
        self,
        batches: list[list[Update]] | None = None,
        downloads: dict[str, bytes] | None = None,
    ) -> None:
        self._batches = list(batches or [])
        self._downloads = dict(downloads or {})
        self.sent: list[tuple[int, str]] = []
        self.downloaded: list[str] = []
        self.offsets: list[int | None] = []

    def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[Update]:
        self.offsets.append(offset)
        if not self._batches:
            raise KeyboardInterrupt
        return self._batches.pop(0)

    def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))

    def get_file(self, file_id: str) -> bytes:
        self.downloaded.append(file_id)
        return self._downloads[file_id]


def photo_update(
    update_id: int,
    chat_id: int,
    file_id: str,
    *,
    width: int = 100,
    height: int = 100,
    file_size: int | None = None,
) -> Update:
    """Build a valid inbound photo update carrying a single photo variant."""
    return Update.model_validate(
        {
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "date": 0,
                "chat": {"id": chat_id, "type": "private"},
                "photo": [
                    {
                        "file_id": file_id,
                        "file_unique_id": f"{file_id}-unique",
                        "width": width,
                        "height": height,
                        "file_size": file_size,
                    }
                ],
            },
        }
    )


def text_update(update_id: int, chat_id: int, text: str | None) -> Update:
    """Build a valid inbound message update.

    ``text=None`` models Telegram's non-text payloads (stickers, voice notes),
    which carry no ``text`` key at all.
    """
    message: dict[str, object] = {
        "message_id": update_id,
        "date": 0,
        "chat": {"id": chat_id, "type": "private"},
    }
    if text is not None:
        message["text"] = text
    return Update.model_validate({"update_id": update_id, "message": message})
