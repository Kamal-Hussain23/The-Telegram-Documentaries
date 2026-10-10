"""The gateway: long-poll Telegram and route updates through the pipeline.

Phase 3 (ROADMAP.md) adds the Interviewer: commands (`/start`, `/restart`)
reset the session first, a Bouncer-pass photo hands the chat to
``Interviewer.start`` (whose first question replaces the placeholder reply on
the pass path), and text while ``phase is INTERVIEWING`` goes to
``Interviewer.answer``. Text in every other phase keeps the Phase 1 reply; the
rejection path is unchanged.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

from telegram_documentaries.bouncer import REJECTION_TEXT, Bouncer
from telegram_documentaries.client import validate_image
from telegram_documentaries.converter import CONVERTER_FAILURE_TEXT, Converter
from telegram_documentaries.interviewer import Interviewer
from telegram_documentaries.logutil import describe_message
from telegram_documentaries.models import Message, PhotoSize, Update
from telegram_documentaries.scripter import SCRIPTING_FAILURE_TEXT, Scripter
from telegram_documentaries.state import Phase, StateDriver

logger = logging.getLogger(__name__)

#: The reply for every inbound text outside an interview (and the pass-path
#: photo when no Interviewer is wired).
REPLY_TEXT = "hey mate!"

#: The in-character invitation sent by the reset commands (plan 5.1).
START_TEXT = "Right — a fresh session. Send me a photo and we'll begin the interview."

#: Friendly fallback when something goes wrong mid-conversation (plan 5.3);
#: the user never sees a traceback and polling keeps running.
ERROR_TEXT = "Sorry, something went wrong on my end. Please try again."

#: The commands that purge the session before any phase routing (plan 5.1).
COMMANDS = frozenset({"/start", "/restart"})


class UpdatesClient(Protocol):
    def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[Update]: ...

    def send_message(self, chat_id: int, text: str) -> None: ...

    def send_photo(self, chat_id: int, photo: bytes) -> None: ...

    def get_file(self, file_id: str) -> bytes: ...


def _highest_resolution(photo: PhotoSize) -> tuple[int, int]:
    return (photo.width or 0) * (photo.file_size or 0), photo.file_size or 0


def _command(text: str) -> str | None:
    """The leading Telegram command, if the first token is one.

    ``/start@DocumentaryBot`` normalises to ``/start``; anything else —
    ``/started``, mid-sentence mentions — is ordinary conversation.
    """
    tokens = text.strip().split(maxsplit=1)
    if not tokens:
        return None
    base = tokens[0].split("@", 1)[0]
    return base if base in COMMANDS else None


class Bot:
    def __init__(
        self,
        client: UpdatesClient,
        *,
        bouncer: Bouncer | None = None,
        state: StateDriver | None = None,
        interviewer: Interviewer | None = None,
        converter: Converter | None = None,
        scripter: Scripter | None = None,
    ) -> None:
        self._client = client
        self._bouncer = bouncer
        self._state = state
        self._interviewer = interviewer
        self._converter = converter
        self._scripter = scripter

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
            elif message.text is not None:
                self._handle_text(message)
            else:
                # A non-text payload (sticker, voice note): the default reply.
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
            if self._interviewer is None:
                # Pass path without an Interviewer wired (Phase 1/2
                # configuration): advance the phase and keep the old reply.
                session = self._state.load(message.chat.id)
                session.phase = Phase.INTERVIEWING
                session.photo = image
                self._state.save(session)
                self._reply(message.chat.id, REPLY_TEXT)
                return
            # The Interviewer stores the phase and photo itself, so an
            # idempotent start never clobbers the dossier (plan 5.2).
            self._reply(message.chat.id, self._interviewer.start(message.chat.id, image))
        else:
            self._state.reset(message.chat.id)
            self._reply(message.chat.id, REJECTION_TEXT)

    def _handle_text(self, message: Message) -> None:
        text = message.text or ""
        command = _command(text)
        if command is not None:
            self._handle_command(message)
            return
        if self._interviewer is not None and self._state is not None:
            if self._state.load(message.chat.id).phase is Phase.INTERVIEWING:
                reply = self._interviewer.answer(message.chat.id, text)
                self._reply(message.chat.id, reply)
                # If the interview just completed and advanced to CONVERTING,
                # run the Converter immediately in the same turn.
                session = self._state.load(message.chat.id)
                if session.phase is Phase.CONVERTING and self._converter is not None:
                    self._run_converter(message.chat.id)
                    session = self._state.load(message.chat.id)
                # If the Converter just advanced to SCRIPTING, run the Scripter
                # immediately in the same turn.
                if session.phase is Phase.SCRIPTING and self._scripter is not None:
                    self._run_scripter(message.chat.id)
                return
        # A chat left in SCRIPTING by a failed Scripter run: any text is a
        # retry. Commands (/start, /restart) are handled above, so this branch
        # only sees ordinary conversation — replying re-runs the Scripter
        # without wiping the dossier.
        if self._scripter is not None and self._state is not None:
            if self._state.load(message.chat.id).phase is Phase.SCRIPTING:
                self._run_scripter(message.chat.id)
                return
        # Other phases (including CONVERTING): the completed dossier must not
        # be re-entered or disturbed — existing behaviour keeps the default reply.
        self._reply(message.chat.id, REPLY_TEXT)

    def _handle_command(self, message: Message) -> None:
        """`/start` and `/restart`: purge the session, invite a fresh photo."""
        if self._state is not None:
            self._state.reset(message.chat.id)
        self._reply(message.chat.id, START_TEXT)

    def _reply(self, chat_id: int, text: str) -> None:
        self._client.send_message(chat_id=chat_id, text=text)
        logger.info("replied chat_id=%s text=%r", chat_id, text)

    def _run_converter(self, chat_id: int) -> None:
        """Run the Converter for a chat in CONVERTING phase.

        On success: deliver the hybrid portrait and advance to SCRIPTING.
        On failure (model error or send failure): stay in CONVERTING for retry.
        """
        if self._converter is None or self._state is None:
            return
        try:
            output = self._converter.convert(chat_id)
            # Deliver the hybrid portrait directly — no intermediate text hop.
            self._client.send_photo(chat_id, output.image_bytes)
            logger.info("delivered hybrid portrait to chat_id=%s", chat_id)
        except Exception:
            # Graceful degradation: log loudly, friendly in-character reply,
            # stay in CONVERTING so it can be retried.
            # Note: converter.convert() may have already advanced the phase
            # to SCRIPTING; reset it so the conversation can be retried.
            logger.exception("converter failed for chat %s", chat_id)
            session = self._state.load(chat_id)
            session.phase = Phase.CONVERTING
            self._state.save(session)
            self._try_reply(chat_id, CONVERTER_FAILURE_TEXT)

    def _run_scripter(self, chat_id: int) -> None:
        """Run the Scripter for a chat in SCRIPTING phase.

        On success: deliver the script text and advance to NARRATING.
        On failure (model error, malformed output, or send failure): stay in
        SCRIPTING for retry. ``Scripter.generate`` is decorated with
        ``log_call``, which already logs the full traceback at ERROR — here we
        log a concise context line only, so the failure is logged once, loudly.
        """
        if self._scripter is None or self._state is None:
            return
        try:
            output = self._scripter.generate(chat_id)
            # Deliver the script text directly — the Narrator picks it up
            # separately for voice synthesis.
            self._client.send_message(chat_id, output.script)
            # A logged preview of the raw script (repr'd so newlines/whitespace
            # are visible) so the handoff to the Narrator can be eyeballed in
            # the console without dumping the whole paragraph every run.
            preview = output.script if len(output.script) <= 80 else output.script[:77] + "..."
            logger.info("delivered script to chat_id=%s: %r", chat_id, preview)
        except Exception:
            # Graceful degradation: friendly in-character reply, stay in
            # SCRIPTING so it can be retried. The full traceback is already on
            # the log from @log_call (or, for a send failure, this line keeps
            # the failure visible without a second stack dump).
            logger.error("scripter failed for chat %s; staying in SCRIPTING for retry", chat_id)
            session = self._state.load(chat_id)
            session.phase = Phase.SCRIPTING
            self._state.save(session)
            self._try_reply(chat_id, SCRIPTING_FAILURE_TEXT)

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
