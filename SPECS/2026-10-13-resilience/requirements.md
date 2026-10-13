# Resilience — requirements (Phase 7)

Feature spec for ROADMAP.md Phase 7: *"Reset semantics, wrong-payload guards, and API-timeout fallbacks."* It defers to `SPECS/MISSION.md`, `SPECS/TECH.md`, and `SPECS/ROADMAP.md` for anything not stated here.

## Context

Phases 1–6 have built the full pipeline:
- **Phase 1**: Long-polling gateway, `.env` wiring
- **Phase 2**: Bouncer (vision gate)
- **Phase 3**: Interviewer (orchestrator, 3–4 Q&A, dossier + animal)
- **Phase 4**: Converter (gemini-3.1-flash-image hybrid portrait)
- **Phase 5**: Scripter (Brian Cox narration paragraph)
- **Phase 6**: Narrator (Gemini TTS → OGG/Opus voice note)

The pipeline runs end-to-end: `/start` → photo → interview → image → script → voice note → `AWAITING_PHOTO`.

**What's missing for production robustness:**
1. **Converter temp files not purged on reset** — the Converter writes `converted_<chat_id>_*` files that `_purge_chat_temp_files()` doesn't clean up.
2. **Wrong-payload replies are generic** — text during photo stage, second photo during interview, etc. all just get `"hey mate!"` (REPLY_TEXT) instead of friendly in-character guidance.
3. **ADK client timeouts unconfigured** — interview/converter/narrator clients have no explicit timeout config for Gemini API calls.
4. **ROADMAP.md not updated** — Phase 7 status still shows as pending.

## User-approved intent

### 1. Complete the reset routine (TECH.md § "Session state")

The existing `StateDriver.reset(chat_id)` performs three actions. The third bullet ("Purge Ephemeral Assets") is incomplete — it must also delete **converted hybrid images** written by the Converter stage (`converted_<chat_id>_*`).

### 2. Wrong-payload guards (friendly in-character replies)

Every out-of-order Telegram payload must produce a helpful, in-character message — never a crash, traceback, or silent drop. Specific cases:

| Current Phase | Inbound Payload | Reply Policy |
|---------------|-----------------|--------------|
| `AWAITING_PHOTO` | Text (not `/start`/`/restart`) | "I need a portrait photo to begin — send me a picture of yourself!" |
| `AWAITING_PHOTO` | Sticker / voice / video / document | Same as above |
| `INTERVIEWING` | Photo (second photo mid-interview) | "We're mid-interview! Just answer the question and I'll continue." |
| `INTERVIEWING` | Sticker / voice / video / document | "Please reply with text — I'm listening for your answer." |
| `CONVERTING` | Any text / photo / media | "I'm developing your hybrid portrait in the darkroom — one moment..." |
| `SCRIPTING` | Photo / media (not text retry) | "The script is being written — reply with anything to retry narration." |
| `NARRATING` | Photo / media (not text retry) | "The voice note is being recorded — reply with anything to retry." |

Commands `/start` and `/restart` **always** reset (handled before phase routing — already works).

### 3. Gemini API timeout configuration

Each ADK client (`Interviewer`, `Converter`, `Narrator`) must have a configurable timeout for its model call, with a sensible default (e.g., 60s). Timeouts must be caught and converted to handled errors (friendly reply, phase preserved for retry).

### 4. Constitution sync

- `ROADMAP.md` Phase 7 updated to "implemented and verified — see `SPECS/2026-10-13-resilience/`."
- `TECH.md` updated if new patterns introduced (timeout config).
- `README.md` unchanged (no new deps / run instructions).

## Scope

### In scope

- **Temp file purge**: extend `_purge_chat_temp_files()` to match `converted_<chat_id>_*` pattern.
- **Wrong-payload routing in `bot.py`**: extend `_handle_text` and `_handle_photo` with phase-specific replies before falling through to `REPLY_TEXT`.
- **ADK client timeouts**: add `timeout` parameter to `GeminiInterviewClient`, `GeminiConverterClient`, `GeminiTTSClient`; drive async runner with `asyncio.wait_for()`.
- **Timeout error handling**: catch `asyncio.TimeoutError` in each client, wrap in stage-specific handled error (`InterviewerError`, `ConverterError`, `NarratorError`), log loudly via `@log_call`.
- **Tests**: Red/Green TDD — unit tests for purge, wrong-payload replies, timeout handling; flow tests for each wrong-payload scenario; live test skipped (timeouts hard to trigger deterministically).
- **All existing tests must continue to pass** (`scripts/test` green).

### Out of scope (YAGNI)

- Webhooks / public URLs (long polling only).
- Database / persistence (in-memory state is fine).
- Group-chat usage, multi-language.
- Retry-with-backoff logic beyond "stay in phase, reply retries" (already built).
- Circuit breakers, rate limiting, health endpoints.
- Config file for timeouts — module constants are sufficient.

## Decisions

1. **Wrong-payload replies** are implemented in `bot.py` `_handle_text` / `_handle_photo` as inline logic (not a separate module) — keeps the gateway thin.
2. **Timeout default: 60 seconds** for all three ADK clients (Interviewer, Converter, Narrator). Module constant `DEFAULT_GEMINI_TIMEOUT = 60.0`.
3. **Timeouts are per-call**, not per-session. `asyncio.wait_for()` wraps the runner drain.
4. **Temp file pattern**: Converter writes `converted_<chat_id>_<random>.jpg` via `tempfile.mkstemp(prefix=f"converted_{chat_id}_", suffix=".jpg")` — the purge function matches this prefix.
5. **No schema version bump** — no session state shape change.
6. **Logging**: `@log_call` already decorates all public entry points; timeout errors will be logged at ERROR with full traceback automatically.

## Acceptance criteria (from ROADMAP.md Phase 7)

- `/start` and `/restart` invoke explicit reset routine (3 actions in order):
  1. Cancel Active Sessions — terminate running loops, replace session with fresh `SessionState` at `AWAITING_PHOTO`.
  2. Purge Ephemeral Assets — delete narrator voice notes (`narration_<chat_id>_*`), cached original photos (`photo_<chat_id>_*`), **and converted hybrids (`converted_<chat_id>_*`)**.
  3. Re-initialize Agent Memory — clear dossier, profile, suggested_animal, script, reset trackers to greeting stage.
- Text during photo stage, second photo during interview, and other out-of-order payloads each produce a friendly in-character reply — no crash, no traceback, no silent drop.
- Gemini/Telegram timeouts and errors on the conversation path are caught, logged loudly, and degrade gracefully.
- Logging is decorator-based and structured across all stages.
- `scripts/test` runs green (pytest + ruff + mypy).

## Verification

- **Purge test**: Converter runs → `converted_<chat_id>_*.jpg` exists → `/start` → file gone, session at `AWAITING_PHOTO`.
- **Wrong-payload tests** (one per row in table above): simulate update in each phase with wrong payload → assert reply matches policy, session unchanged.
- **Timeout tests**: stub client with `asyncio.sleep(10)` + 1s timeout → handled error logged, friendly reply, phase preserved.
- **Cross-cutting**: all existing flow tests still pass; no regression in happy path.
- `scripts/test` green.