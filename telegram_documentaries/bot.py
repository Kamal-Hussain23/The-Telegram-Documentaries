"""The gateway: long-poll Telegram and route updates through the pipeline.

Phase 2 (ROADMAP.md) adds the Bouncer vision gate: an inbound photo is
downloaded, validated, classified as human-present or not, and routed to the
pass path (advance the phase, unchanged Phase 1 reply) or the rejection path
(in-character rejection, session reset). Text messages keep the Phase 1 reply.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

from telegram_documentaries.bouncer import REJECTION_TEXT, Bouncer
from telegram_documentaries.client import validate_image
from telegram_documentaries.logutil import describe_message
from telegram_documentaries.models import Message, PhotoSize, Update
from telegram_documentaries.state import Phase, StateDriver

logger = logging.getLogger(__name__)

#: The reply for every inbound text (and the pass-path photo) in this phase.
REPLY_TEXT = "hey mate!"

#: Friendly fallback when something goes wrong mid-conversation (plan 5.3);
#: the user never sees a traceback and polling keeps running.
ERROR_TEXT = "Sorry, something went wrong on my end. Please try again."


class UpdatesClient(Protocol):
    def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[Update]: ...

    def send_message(self, chat_id: int, text: str) -> None: ...

    def get_file(self, file_id: str) -> bytes: ...


def _highest_resolution(photo: PhotoSize) -> tuple[int, int]:
    return (photo.width or 0) * (photo.height or 0), photo.file_size or 0


class Bot:
    def __init__(
        self,
        client: UpdatesClient,
        *,
        bouncer: Bouncer | None = None,
        state: StateDriver | None = None,
    ) -> None:
        self._client = client
        self._bouncer = bouncer
        self._state = state

    def handle_update(self, update: Update) -> None:
        """Handle one update. Never raises into the polling loop."""
        message = update.message
        if message is None:
            logger.debug("ignoring update %s: no message payload", update.update_id)
            return
        logger.info("received %s", describe_message(message))
        try:
            if message.photo:
                self._handle_photo(message)
            else:
                self._reply(message.chat.id, REPLY_TEXT)
        except Exception:
            # The conversation path degrades gracefully: log loudly, keep polling.
            logger.exception("failed to handle chat %s", message.chat.id)
            self._try_reply(message.chat.id, ERROR_TEXT)

    def _handle_photo(self, message: Message) -> None:
        if self._bouncer is None or self._state is None or message.photo is None:
            # Photo handling isn't wired up (Phase 1 configuration): keep the
            # old behaviour rather than crashing the update.
            self._reply(message.chat.id, REPLY_TEXT)
            return

        photo = max(message.photo, key=_highest_resolution)
        image = self._client.get_file(photo.file_id)
        validate_image(image, "image/jpeg")
        verdict = self._bouncer.classify(image)

        if verdict.human_present:
            session = self._state.load(message.chat.id)
            session.phase = Phase.INTERVIEWING
            session.photo = image
            self._state.save(session)
            self._reply(message.chat.id, REPLY_TEXT)
        else:
            self._state.reset(message.chat.id)
            self._reply(message.chat.id, REJECTION_TEXT)

    def _reply(self, chat_id: int, text: str) -> None:
        self._client.send_message(chat_id=chat_id, text=text)
        logger.info("replied chat_id=%s text=%r", chat_id, text)

    def _try_reply(self, chat_id: int, text: str) -> None:
        try:
            self._reply(chat_id, text)
        except Exception:
            logger.exception("failed to send fallback reply to chat %s", chat_id)

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
