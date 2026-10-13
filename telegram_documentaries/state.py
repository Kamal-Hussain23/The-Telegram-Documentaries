"""The one shared, in-memory session state driver.

TECH.md: session state is a versioned schema keyed by ``chat_id``, held in
process memory, and every stage reads/writes it through this single driver —
no stage touches state directly. There is deliberately no persistence: a
process restart wiping sessions is acceptable (MISSION.md).

The version field sits on each session so a future schema change can invalidate
stale in-memory sessions cleanly.

Transient media (photos, generated voice notes) are stored on disk under the
system temp dir in a chat-scoped subfolder. The ``reset`` method removes
those artifacts so a /start or /restart command completely clears a user's
context without a Python restart.
"""

from __future__ import annotations

import tempfile
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

#: Bump when ``SessionState`` changes shape; older entries are then discarded.
SCHEMA_VERSION = 3


#: Purge ALL temporary media scoped to *chat_id*.
#: The Narrator stage writes files under ``<system-temp>/telegram_documentaries/``
#: with names like ``narration_<chat_id>_<random>.<format>``. The Bouncer may store
#: the original photo bytes. This function removes any temp files matching known
#: patterns so a ``/start`` / ``/restart`` command completely clears a user's
#: on-disk context without a Python restart.
def _purge_chat_temp_files(chat_id: int) -> None:
    audio_dir = Path(tempfile.gettempdir()) / "telegram_documentaries"
    if not audio_dir.is_dir():
        return
    for file_path in audio_dir.iterdir():
        try:
            name = file_path.name
            # Voice notes from the Narrator stage: narration_<chat_id>_*.<format>
            if name.startswith(f"narration_{chat_id}_"):
                file_path.unlink()
            # Original photo bytes that may have been cached on disk
            elif name.startswith(f"photo_{chat_id}_"):
                file_path.unlink()
            
        except OSError:
            pass


class Phase(StrEnum):
    """The state-machine phases driven by the pipeline stages."""

    AWAITING_PHOTO = "AWAITING_PHOTO"
    INTERVIEWING = "INTERVIEWING"
    SCRIPTING = "SCRIPTING"
    NARRATING = "NARRATING"


class Dossier(BaseModel):
    """One chat's accumulated interview (plan 2.2).

    Progress is derived from these records — questions asked against answers
    given — rather than from a stored counter. ``profile`` and
    ``suggested_animal`` are the completed handoff the next stage reads.
    """

    model_config = ConfigDict(extra="ignore")

    questions: list[str] = Field(default_factory=list)
    answers: list[str] = Field(default_factory=list)
    #: The synthesised behavioural/personality summary. Internal only: it is
    #: never sent to the user (requirements decision 6).
    profile: str | None = None
    suggested_animal: str | None = None
    #: The generated narration paragraph, ready for the Narrator stage (Phase
    #: 6) to send to TTS. Written by the Scripter on success; ``None`` until
    #: then.
    script: str | None = None
    #: The question awaiting an answer is the interview's last one — set when a
    #: final question goes out (model-marked from question 3, forced at 4).
    awaiting_final: bool = False


class SessionState(BaseModel):
    """One chat's ephemeral conversation state."""

    model_config = ConfigDict(extra="ignore")

    version: int = SCHEMA_VERSION
    chat_id: int
    phase: Phase = Phase.AWAITING_PHOTO
    #: The raw bytes of the accepted photo, scoped to this chat only.
    photo: bytes | None = None
    dossier: Dossier = Field(default_factory=Dossier)


class StateDriver:
    """The only code that touches session state (TECH.md).

    Load, save, and reset are the whole surface. Unknown or stale (wrong
    version) chats are transparently given a fresh session at the initial
    phase.
    """

    def __init__(self) -> None:
        self._sessions: dict[int, SessionState] = {}

    def load(self, chat_id: int) -> SessionState:
        session = self._sessions.get(chat_id)
        if session is None or session.version != SCHEMA_VERSION:
            session = SessionState(chat_id=chat_id)
            self._sessions[chat_id] = session
        return session

    def save(self, session: SessionState) -> None:
        self._sessions[session.chat_id] = session

    def reset(self, chat_id: int) -> None:
        """Return one chat to the initial phase, in-process (no restart).

        Three actions are performed:

        1. **Cancel Active Sessions** — the session state is replaced with a fresh
           ``SessionState`` at ``AWAITING_PHOTO``, clearing phase, photo, and
           dossier. Any running interview loop or waiting state for this chat_id
           is terminated.
        2. **Purge Ephemeral Assets** — any temporary media on disk scoped to this
           chat_id are deleted: narrator voice notes (``narration_<chat_id>_*``),
           cached original photos (``photo_<chat_id>_*``).
        3. **Re-initialize Agent Memory** — conversation history buffers (dossier,
           profile, suggested_animal, script) are cleared, resetting the
           conversation back to the greeting stage.
        """
        self._sessions[chat_id] = SessionState(chat_id=chat_id)
        _purge_chat_temp_files(chat_id)
