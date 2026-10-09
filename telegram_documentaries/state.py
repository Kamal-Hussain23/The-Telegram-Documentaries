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

from pydantic import BaseModel, ConfigDict, Field

#: Bump when ``SessionState`` changes shape; older entries are then discarded.
SCHEMA_VERSION = 2


class Phase(StrEnum):
    """The state-machine phases driven by the pipeline stages."""

    AWAITING_PHOTO = "AWAITING_PHOTO"
    INTERVIEWING = "INTERVIEWING"
    CONVERTING = "CONVERTING"
    SCRIPTING = "SCRIPTING"


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
        """Return one chat to the initial phase, in-process (no restart)."""
        self._sessions[chat_id] = SessionState(chat_id=chat_id)
