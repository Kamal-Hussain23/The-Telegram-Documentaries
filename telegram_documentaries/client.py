"""Thin, typed client for the parts of the Telegram Bot API this project uses.

All external input is untrusted: responses are validated into Pydantic models
before anything downstream sees them.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

import requests

from telegram_documentaries.logutil import log_call
from telegram_documentaries.models import Update

logger = logging.getLogger(__name__)


class TelegramApiError(RuntimeError):
    """Telegram answered, but with `ok: false`."""


class ResponseProtocol(Protocol):
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

    @staticmethod
    def _result(response: ResponseProtocol) -> Any:
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TelegramApiError(f"unexpected Telegram payload: {payload!r}")
        if payload.get("ok") is not True:
            raise TelegramApiError(f"Telegram API error: {payload.get('description')}")
        return payload.get("result")
