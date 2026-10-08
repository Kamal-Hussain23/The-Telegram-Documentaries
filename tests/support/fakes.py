"""Deterministic offline test doubles for the Bouncer suite.

Nothing here touches the network or requires ``GEMINI_API_KEY``: the Gemini
vision client is stubbed and the Telegram client is scripted, so the default
suite stays green in CI. The real dependencies land in groups 2–5.
"""

from __future__ import annotations

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
