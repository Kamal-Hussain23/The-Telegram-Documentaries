# Resilience — implementation plan (Phase 7)

Reference: `SPECS/2026-10-13-resilience/requirements.md`.

## Group 1: Temp file purge (offline, no ADK)

1.1 **Extend purge function** (`state.py`)
     - Update `_purge_chat_temp_files(chat_id)` to also match `converted_<chat_id>_*` prefix.
     - Pattern: `name.startswith(f"converted_{chat_id}_")` → `file_path.unlink()`.

1.2 **Converter temp file naming** (`converter.py`)
     - Ensure `Converter.generate_and_send` writes temp files with prefix `converted_{chat_id}_` (if it writes to disk at all — currently sends bytes directly via `send_photo`, so may not need this; verify and add only if Converter persists to disk).

1.3 **Purge test** (`tests/test_state.py` or new `tests/test_resilience.py`)
     - Create fake `converted_<chat_id>_test.jpg` in temp dir → call `StateDriver.reset(chat_id)` → assert file deleted.

## Group 2: Wrong-payload guards (bot.py)

2.1 **Text in AWAITING_PHOTO** (`bot.py` → `_handle_text`)
     - Before phase routing, if `phase is Phase.AWAITING_PHOTO` and not a command: reply with photo-needed message, return early.

2.2 **Photo in INTERVIEWING** (`bot.py` → `_handle_photo`)
     - After Bouncer pass, if `phase is Phase.INTERVIEWING`: reply with "mid-interview" message, do NOT re-run Interviewer.start (idempotent start already handles this but wrong-payload message is different).

2.3 **Non-text in INTERVIEWING** (`bot.py` → `_handle_text` catch-all)
     - If `phase is Phase.INTERVIEWING` and message is not plain text (sticker, voice, etc.): reply with "please reply with text" message.

2.4 **Any payload in CONVERTING** (`bot.py` → `_handle_text` / `_handle_photo`)
     - If `phase is Phase.CONVERTING`: reply with "developing portrait" message, return early.

2.5 **Wrong payload in SCRIPTING** (`bot.py` → `_handle_text` / `_handle_photo`)
     - If `phase is Phase.SCRIPTING` and inbound is photo/media (not text retry): reply with "script being written" message.

2.6 **Wrong payload in NARRATING** (`bot.py` → `_handle_text` / `_handle_photo`)
     - If `phase is Phase.NARRATING` and inbound is photo/media (not text retry): reply with "voice note recording" message.

2.7 **Wrong-payload test constants** (`bot.py` or `resilience.py`)
     - Define message constants for each case (in-character, cheeky tone).

2.8 **Wrong-payload flow tests** (`tests/test_resilience_flow.py`)
     - One test per scenario in the requirements table.

## Group 3: ADK client timeouts

3.1 **Timeout constant** (`converter.py` or shared `timeouts.py`)
     - `DEFAULT_GEMINI_TIMEOUT = 60.0` (seconds).

3.2 **Interviewer client timeout** (`interview_client.py`)
     - Add `timeout: float = DEFAULT_GEMINI_TIMEOUT` to `__init__`.
     - In `generate_question` / `generate_profile`: wrap `runner.run_async(...)` drain in `asyncio.wait_for(..., timeout=self._timeout)`.
     - Catch `asyncio.TimeoutError` → raise `InterviewerError("model timeout")`.

3.3 **Converter client timeout** (`converter_client.py`)
     - Same pattern: `timeout` param, `asyncio.wait_for` around runner drain.
     - Catch `asyncio.TimeoutError` → raise `ConverterError("model timeout")`.

3.4 **Narrator TTS client timeout** (`narrator_client.py`)
     - Add `timeout` param to `__init__`.
     - Wrap `generate_content` call in `asyncio.wait_for` (note: TTS uses direct `google-genai`, not ADK runner).
     - Catch `asyncio.TimeoutError` → raise `NarratorError("TTS timeout")`.

3.5 **Timeout unit tests** (`tests/test_resilience.py`)
     - Stub each client with slow response + short timeout → assert handled error raised, logged.

## Group 4: Constitution sync

4.1 Update `ROADMAP.md` Phase 7 status to "implemented and verified — see `SPECS/2026-10-13-resilience/`."
4.2 Update `TECH.md` if timeout pattern is new (add note about `DEFAULT_GEMINI_TIMEOUT` and `asyncio.wait_for` usage).
4.3 `MISSION.md` unchanged.
4.4 `README.md` unchanged.

## Group 5: Tests (Red/Green TDD)

5.1 **Unit tests** (`tests/test_resilience.py`)
     - Purge: converted files deleted on reset.
     - Timeout: each client raises handled error on timeout.
     - Wrong-payload constants exist and are non-empty strings.

5.2 **Flow tests** (`tests/test_resilience_flow.py`)
     - Text in AWAITING_PHOTO → photo-needed reply.
     - Photo in INTERVIEWING → mid-interview reply.
     - Sticker in INTERVIEWING → text-only reply.
     - Any payload in CONVERTING → developing reply.
     - Photo in SCRIPTING → script-writing reply.
     - Photo in NARRATING → recording reply.
     - All wrong-payload cases leave session phase/dossier unchanged.

5.3 **Regression tests** (existing)
     - Run full `scripts/test` — all 231+ tests must pass.

## Group 6: Verification

6.1 Run `scripts/test` — must pass (pytest + ruff + mypy).
6.2 Run validation checks from `validation.md`.