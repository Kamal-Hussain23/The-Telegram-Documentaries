# The Narrator — implementation plan (Phase 6)

Reference: `SPECS/2026-10-11-narrator/requirements.md`.

## Group 1: TTS client (offline, no ADK)

1.1 **TTS output contract** (`narrator.py`)
     - `NarratorResult` — audio payload and format
     - `NarratorError` — handled error type
     - `synthesize(text: str) -> NarratorResult` — core method

1.2 **TTS instruction** (`narrator_client.py`)
     - Direct script-to-audio mapping (not an agent). The Scripter's text
       goes straight to Gemini TTS via a direct API call, bypassing the agent
       framework used by other stages.

## Group 2: Narrator orchestrator (the stage)

2.1 **Narrator class** (`narrator.py`)
     - `__init__(state: StateDriver, tts_client, client: Telegram)`
     - `synthesize_and_deliver(chat_id: int)`:
       - Load session, assert phase is `NARRATING`
       - Assert session has `script`
       - Call `tts_client.synthesize(session.dossier.script)`
       - Send voice note via `client.send_voice`
       - Advance `session.phase = Phase.AWAITING_PHOTO`
       - Save session
       - Return the `NarratorResult`

## Group 3: Bot wiring (integration)

3.1 **Bot imports and constants** (`bot.py`)
     - Import `NARRATOR_FAILURE_TEXT` from `narrator`
     - Add `narrator: Narrator | None = None` to `Bot.__init__`

3.2 **Run Narrator in bot** (`bot.py`)
     - Add `_run_narrator(chat_id: int) -> None` method:
       - Call `self._narrator.synthesize_and_deliver(chat_id)`
       - On `NarratorError`: log loudly, stay in `NARRATING`, send
         `NARRATOR_FAILURE_TEXT`
       - On success: phase advances to `AWAITING_PHOTO` automatically

3.3 **Hook into text handler** (`bot.py`)
     - In `_handle_text`, after the Scripter advances to `NARRATING`,
       call `_run_narrator` in the same turn. The chat advances from
       `SCRIPTING` to `NARRATING` to `AWAITING_PHOTO` in a single update.

## Group 4: Cross-chat isolation

4.1 Each chat's state is independent via the shared `StateDriver` keyed by
   `chat_id`. No stage touches another chat's session.

4.2 `/start` and `/restart` reset the session and purge temporary media
   (voice notes, cached photos) scoped to the requesting `chat_id`.

## Group 5: Tests (Red/Green TDD)

5.1 **Unit tests** (`tests/test_narrator.py`)
     - `synthesize` returns `NarratorResult` for stubbed response
     - `synthesize` turns model error into handled `NarratorError`
     - `synthesize_and_deliver` advances phase correctly

5.2 **Flow tests** (`tests/test_narrator_flow.py`)
     - Complete flow: photo → interview → scripter → narrator → voice note
       all in one turn, phase at `AWAITING_PHOTO`
     - Narrator failure degrades gracefully, stays in `NARRATING`, retry
       works via text reply
     - Cross-chat isolation: two chats, independent voice notes never leak

5.3 **Live opt-in test** (`tests/test_narrator_live.py`)
     - Real `gemini-3.1-flash-tts-preview` call when `GEMINI_API_KEY` set,
       skipped otherwise.

## Group 6: Constitution sync

6.1 Update `MISSION.md` if needed (no changes expected — Narrator is already
     described in the pipeline).
6.2 Update `ROADMAP.md` Phase 6 status to "implemented and verified — see
     `SPECS/2026-10-11-narrator/`.
6.3 Update `TECH.md` if any new patterns introduced (unlikely — follows
     existing patterns for graceful degradation).
6.4 Update `README.md` if new dependencies or run instructions change.

## Group 7: Verification

7.1 Run `scripts/test` — must pass (pytest + ruff + mypy).
7.2 Run validation checks from `validation.md`.
