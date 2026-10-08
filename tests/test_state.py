"""One shared, in-memory, chat_id-keyed state driver.

Reference: SPECS/2026-10-06-bouncer/plan.md groups 1.4/1.6 and 3.x,
TECH.md "Session state".
"""

from __future__ import annotations

from telegram_documentaries.state import Phase, StateDriver


def test_unknown_chat_starts_at_the_initial_phase() -> None:
    assert StateDriver().load(42).phase is Phase.AWAITING_PHOTO


def test_saved_session_round_trips() -> None:
    state = StateDriver()
    session = state.load(7)
    session.phase = Phase.INTERVIEWING
    state.save(session)

    assert state.load(7).phase is Phase.INTERVIEWING


def test_reset_returns_the_chat_to_the_initial_phase() -> None:
    state = StateDriver()
    session = state.load(7)
    session.phase = Phase.SCRIPTING
    state.save(session)

    state.reset(7)

    assert state.load(7).phase is Phase.AWAITING_PHOTO


def test_state_is_isolated_per_chat_id() -> None:
    state = StateDriver()
    chat_a = state.load(1)
    chat_a.phase = Phase.INTERVIEWING
    state.save(chat_a)

    assert state.load(2).phase is Phase.AWAITING_PHOTO
    assert state.load(1).phase is Phase.INTERVIEWING
    assert state.load(1).chat_id == 1
