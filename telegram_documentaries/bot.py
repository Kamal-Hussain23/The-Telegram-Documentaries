"""The gateway: long-poll Telegram and answer every message the same way.

Phase 1 (ROADMAP.md) — no Gemini calls yet, just a hardcoded reply.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

from telegram_documentaries.logutil import describe_message
from telegram_documentaries.models import Update

logger = logging.getLogger(__name__)

#: The single hardcoded reply for every inbound message in Phase 1.
REPLY_TEXT = "hey mate!"


class UpdatesClient(Protocol):
    def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[Update]: ...

    def send_message(self, chat_id: int, text: str) -> None: ...


class Bot:
    def __init__(self, client: UpdatesClient) -> None:
        self._client = client

    def handle_update(self, update: Update) -> None:
        """Handle one update. Never raises into the polling loop."""
        message = update.message
        if message is None:
            logger.debug("ignoring update %s: no message payload", update.update_id)
            return
        logger.info("received %s", describe_message(message))
        try:
            self._client.send_message(chat_id=message.chat.id, text=REPLY_TEXT)
        except Exception:
            # The conversation path degrades gracefully: log loudly, keep polling.
            logger.exception("failed to reply to chat %s", message.chat.id)
            return
        logger.info("replied chat_id=%s text=%r", message.chat.id, REPLY_TEXT)

    def run(self, timeout: int = 30, error_backoff: float = 2.0) -> None:
        """Poll forever, advancing the offset past every update we've seen."""
        offset: int | None = None
        logger.info("gateway started: long-polling every %ss", timeout)
        while True:
            try:
                updates = self._client.get_updates(offset=offset, timeout=timeout)
            except KeyboardInterrupt:
                logger.info("gateway stopped")
                raise
            except Exception:
                # Transient network/API trouble: log, back off, keep going.
                logger.exception("poll failed; retrying in %.0fs", error_backoff)
                time.sleep(error_backoff)
                continue
            for update in updates:
                offset = update.update_id + 1
                self.handle_update(update)
