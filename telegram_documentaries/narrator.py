"""The Narrator: Gemini TTS synthesis and Telegram voice-note delivery (Phase 6).

TECH.md: the Narrator is plumbing, not an agent. The Scripter's text goes
straight to Gemini TTS and back out as a voice note — no conversational turn,
no ADK `LlmAgent` (the real client lives in `narrator_client.py`).

The stage reads `dossier.script` from session state, synthesises it through an
injected TTS client, persists the audio to a uniquely-named temporary file
(always cleaned up), and delivers it as a Telegram voice note through an
injected delivery client. On success the phase advances `NARRATING →
AWAITING_PHOTO` and the script is cleared; on failure the stage raises a
handled `NarratorError` — the Bot logs loudly and replies in-character, and
the chat stays in `NARRATING` so a reply retries.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from telegram_documentaries.logutil import log_call
from telegram_documentaries.narrator_audio import AUDIO_MIME_TYPES
from telegram_documentaries.state import Phase, StateDriver

#: Sent when the Narrator fails to synthesise or deliver audio. In-character,
#: cheeky, and explicit that the script is safe — replying with any text
#: retries it. Never suggests a photo (that would reset the conversation).
NARRATOR_FAILURE_TEXT = (
    "Alas — the narration spirits are being temperamental and the voice note "
    "refuses to generate. The script is safe and waiting, so simply reply "
    "with anything and we'll try again."
)


class NarratorResult(BaseModel):
    """Result of a TTS synthesis call.

    Attributes:
        audio_bytes: The audio payload, already in a Telegram-compatible
            container (OGG/Opus or MP3).
        format: The container — ``"ogg"`` or ``"mp3"``. The stage allowlists
            this against ``AUDIO_MIME_TYPES`` before it becomes a file
            extension, so a free string can never reach a path.
    """

    model_config = ConfigDict(extra="ignore")

    audio_bytes: bytes
    format: str  # "ogg" or "mp3"


class NarratorError(ValueError):
    """The model did not return a deliverable TTS result."""


class GeminiTTSClient(Protocol):
    """The slice of the Gemini TTS client the Narrator depends on.

    ``synthesize`` returns the audio in a Telegram-compatible container;
    the full script text travels in the request.
    """

    def synthesize(self, text: str) -> NarratorResult: ...


class VoiceNoteSender(Protocol):
    """The narrow slice of ``TelegramClient`` the Narrator needs.

    Delivering a voice note is the Narrator's only outbound Telegram action —
    it never builds a Telegram client itself (dependency injection).
    """

    def send_voice(self, chat_id: int, voice: bytes, *, mime_type: str, filename: str) -> None: ...


def _temporary_audio_dir() -> Path:
    """The scratch space for narration files, under the system temp dir.

    A module function so tests can redirect the space deterministically.
    """
    return Path(tempfile.gettempdir()) / "telegram_documentaries"


class Narrator:
    """Reads the script from session state and synthesises it to a voice note.

    Phase machine: NARRATING --(success)--> AWAITING_PHOTO
                     NARRATING --(failure)--> NARRATING (retry)
    """

    def __init__(
        self,
        state: StateDriver,
        tts_client: GeminiTTSClient,
        telegram_client: VoiceNoteSender,
    ) -> None:
        self._state = state
        self._tts_client = tts_client
        self._telegram_client = telegram_client

    @log_call
    def synthesize_and_deliver(self, chat_id: int) -> None:
        """Synthesise the script to audio and send it as a Telegram voice note.

        On success: advance phase from NARRATING to AWAITING_PHOTO, clearing
        the script from the session.

        On failure: raise a handled ``NarratorError`` (the traceback is logged
        by ``log_call`` at ERROR); the Bot sends the friendly message and the
        session stays in NARRATING so it can be retried.
        """
        session = self._state.load(chat_id)

        if session.phase is not Phase.NARRATING:
            raise NarratorError(f"chat {chat_id} is not in NARRATING phase: {session.phase}")

        script = session.dossier.script
        if not script or not script.strip():
            raise NarratorError(f"chat {chat_id} has no script text in NARRATING phase")

        result = self._synthesize(script)

        mime_type = AUDIO_MIME_TYPES.get(result.format)
        if mime_type is None:
            # The format becomes a file extension — only allowlisted containers
            # may reach a path (requirements decision 6).
            raise NarratorError(f"TTS returned unsupported audio format {result.format!r}")

        audio_file = self._persist_audio(chat_id, result)
        try:
            self._telegram_client.send_voice(
                chat_id=chat_id,
                voice=result.audio_bytes,
                mime_type=mime_type,
                filename=audio_file.name,
            )
        except Exception as exc:
            raise NarratorError(f"failed to send voice note to chat {chat_id}: {exc}") from exc
        finally:
            audio_file.unlink(missing_ok=True)

        # The pipeline is complete: hand the chat back to the initial phase and
        # clear the script so a stale narration can never be re-sent.
        session.phase = Phase.AWAITING_PHOTO
        session.dossier.script = None
        self._state.save(session)

    def _synthesize(self, script: str) -> NarratorResult:
        """Call the TTS client, turning any failure into a handled error."""
        try:
            result = self._tts_client.synthesize(script)
        except NarratorError:
            raise
        except Exception as exc:
            raise NarratorError(f"unexpected TTS error: {exc}") from exc
        if not result.audio_bytes:
            raise NarratorError("TTS returned empty audio")
        return result

    def _persist_audio(self, chat_id: int, result: NarratorResult) -> Path:
        """Write the audio to a unique, chat-scoped temp file.

        The file lives under ``_temporary_audio_dir()`` with a
        ``narration_<chat_id>_<random>.<format>`` name so concurrent
        narrations for the same chat never collide (MISSION.md: no cross-user
        leakage). The caller removes it in a ``finally``.
        """
        audio_dir = _temporary_audio_dir()
        try:
            audio_dir.mkdir(parents=True, exist_ok=True)
            descriptor, path = tempfile.mkstemp(
                prefix=f"narration_{chat_id}_",
                suffix=f".{result.format}",
                dir=audio_dir,
            )
        except OSError as exc:
            raise NarratorError(f"cannot create narration temp dir: {exc}") from exc
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(result.audio_bytes)
        except OSError as exc:
            Path(path).unlink(missing_ok=True)
            raise NarratorError(f"failed to write narration temp file: {exc}") from exc
        return Path(path)
