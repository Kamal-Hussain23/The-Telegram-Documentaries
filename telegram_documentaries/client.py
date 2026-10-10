"""Thin, typed client for the parts of the Telegram Bot API this project uses.

All external input is untrusted: responses are validated into Pydantic models
before anything downstream sees them.
"""

from __future__ import annotations

from typing import Any, Protocol

import requests

from telegram_documentaries.logutil import log_call
from telegram_documentaries.models import Update

#: Hard cap on a downloaded image. Telegram photos are well under this.
MAX_IMAGE_BYTES = 5 * 1024 * 1024

_ALLOWED_IMAGE_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class TelegramApiError(RuntimeError):
    """Telegram answered, but with `ok: false`."""


class ImageValidationError(ValueError):
    """Downloaded bytes are not a usable image (size, type, or shape)."""


@log_call
def validate_image(data: bytes, content_type: str | None) -> None:
    """Reject untrusted downloaded bytes before anything downstream sees them.

    Validates size, declared content type, and the leading magic bytes. Failures
    are handled errors, logged loudly by ``log_call`` (TECH.md: no silent drops).
    """

    def reject(reason: str) -> ImageValidationError:
        return ImageValidationError(f"{reason} (content_type={content_type!r}, size={len(data)})")

    if not data:
        raise reject("empty payload")
    if len(data) > MAX_IMAGE_BYTES:
        raise reject(f"payload exceeds MAX_IMAGE_BYTES ({MAX_IMAGE_BYTES})")
    if content_type is None or content_type.lower() not in _ALLOWED_IMAGE_CONTENT_TYPES:
        raise reject(f"unsupported content type {content_type!r}")
    if not (data.startswith(_JPEG_MAGIC) or data.startswith(_PNG_MAGIC)):
        raise reject("payload is not a recognised image")


class ResponseProtocol(Protocol):
    @property
    def content(self) -> bytes: ...

    def json(self) -> Any: ...

    def raise_for_status(self) -> None: ...


class HttpSession(Protocol):
    """The slice of `requests.Session` we rely on — injectable for tests."""

    def get(
        self, url: str, *, params: dict[str, Any] | None = None, timeout: float | None = None
    ) -> ResponseProtocol: ...

    def post(
        self, url: str, *, json: dict[str, Any] | None = None, timeout: float | None = None
    ) -> ResponseProtocol: ...


class TelegramClient:
    def __init__(
        self,
        token: str,
        session: HttpSession | None = None,
        base_url: str | None = None,
    ) -> None:
        if not token:
            raise ValueError("Telegram bot token must not be empty")
        self._token = token
        self._session: HttpSession = session if session is not None else requests.Session()
        self._base_url = base_url or f"https://api.telegram.org/bot{token}"
        self._file_base_url = f"https://api.telegram.org/file/bot{token}"

    @log_call
    def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[Update]:
        """Long-poll `getUpdates`, returning validated messages.

        `timeout` is how long Telegram holds the connection open; the HTTP
        client waits a little longer so it doesn't time out first.
        """
        params: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        response = self._session.get(
            f"{self._base_url}/getUpdates", params=params, timeout=timeout + 10
        )
        result = self._result(response)
        return [Update.model_validate(item) for item in result]

    @log_call
    def send_message(self, chat_id: int, text: str) -> None:
        response = self._session.post(
            f"{self._base_url}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=30,
        )
        self._result(response)

    @log_call
    def send_photo(self, chat_id: int, photo: bytes) -> None:
        """Send a photo directly to the chat via multipart/form-data."""
        import io
        files = {"photo": ("portrait.jpg", io.BytesIO(photo), "image/jpeg")}
        data = {"chat_id": str(chat_id)}
        response = self._session.post(
            f"{self._base_url}/sendPhoto",
            data=data,
            files=files,
            timeout=60,
        )
        self._result(response)

    @log_call
    def get_file(self, file_id: str) -> bytes:
        """Resolve `file_id` via `getFile`, then download the raw bytes."""
        response = self._session.get(
            f"{self._base_url}/getFile", params={"file_id": file_id}, timeout=30
        )
        result = self._result(response)
        if not isinstance(result, dict) or not isinstance(result.get("file_path"), str):
            raise TelegramApiError(f"unexpected getFile response: {result!r}")
        file_path = result["file_path"]
        file_response = self._session.get(f"{self._file_base_url}/{file_path}", timeout=60)
        file_response.raise_for_status()
        return file_response.content

    @staticmethod
    def _result(response: ResponseProtocol) -> Any:
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TelegramApiError(f"unexpected Telegram payload: {payload!r}")
        if payload.get("ok") is not True:
            raise TelegramApiError(f"Telegram API error: {payload.get('description')}")
        return payload.get("result")
