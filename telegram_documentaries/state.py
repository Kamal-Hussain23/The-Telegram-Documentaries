"""The one shared, in-memory session state driver.

TECH.md: session state is a versioned schema keyed by ``chat_id``, held in
process memory, and every stage reads/writes it through this single driver —
no stage touches state directly. There is deliberately no persistence: a
process restart wiping sessions is acceptable (MISSION.md).

The version field sits on each session so a future schema change can invalidate
stale in-memory sessions cleanly.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

#: Bump when ``SessionState`` changes shape; older entries are then discarded.
SCHEMA_VERSION = 1


class Phase(StrEnum):
    """The state-machine phases driven by the pipeline stages."""

    AWAITING_PHOTO = "AWAITING_PHOTO"
    INTERVIEWING = "INTERVIEWING"
    SCRIPTING = "SCRIPTING"


class SessionState(BaseModel):
    """One chat's ephemeral conversation state."""

    model_config = ConfigDict(extra="ignore")

    version: int = SCHEMA_VERSION
    chat_id: int
    phase: Phase = Phase.AWAITING_PHOTO
    #: The raw bytes of the accepted photo, scoped to this chat only.
    photo: bytes | None = None


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
        """Return one chat to the initial phase, in-process (no restart)."""
        self._sessions[chat_id] = SessionState(chat_id=chat_id)
