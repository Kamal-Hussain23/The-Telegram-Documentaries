# Resilience — validation checklist (Phase 7)

Reference: `SPECS/2026-10-13-resilience/requirements.md`,
`SPECS/2026-10-13-resilience/plan.md`.

All checks must pass for the phase to be marked **verified**.

## 1. Static checks (run via `scripts/test`)

- [ ] `ruff check .` — no lint violations
- [ ] `ruff format --check .` — formatting consistent
- [ ] `mypy` — no type errors
- [ ] `pytest` — all tests pass (offline suite, no `GEMINI_API_KEY` required)

## 2. Purge tests (`tests/test_resilience.py` or `tests/test_state.py`)

- [ ] `StateDriver.reset(chat_id)` deletes `converted_<chat_id>_*` files from temp dir
- [ ] `narration_<chat_id>_*` files still deleted (no regression)
- [ ] `photo_<chat_id>_*` files still deleted (no regression)
- [ ] Reset still produces fresh `SessionState` at `AWAITING_PHOTO`
- [ ] Dossier, profile, suggested_animal, script all cleared

## 3. Wrong-payload unit tests (`tests/test_resilience.py`)

- [ ] Wrong-payload message constants defined and non-empty
- [ ] Each constant is in-character, cheeky tone (not robotic)

## 4. Wrong-payload flow tests (`tests/test_resilience_flow.py`)

- [ ] **AWAITING_PHOTO + text** → photo-needed reply, phase unchanged
- [ ] **AWAITING_PHOTO + sticker/voice/media** → photo-needed reply, phase unchanged
- [ ] **INTERVIEWING + photo** → mid-interview reply, phase/dossier unchanged
- [ ] **INTERVIEWING + sticker/voice/media** → text-only reply, phase/dossier unchanged
- [ ] **CONVERTING + any payload** → developing-portrait reply, phase unchanged
- [ ] **SCRIPTING + photo/media** → script-writing reply, phase unchanged
- [ ] **NARRATING + photo/media** → recording-reply, phase unchanged
- [ ] **Commands `/start` / `/restart`** still reset in all phases (regression check)

## 5. Timeout tests (`tests/test_resilience.py`)

- [ ] **Interviewer client**: stub with 10s sleep, 1s timeout → `InterviewerError` raised, logged at ERROR
- [ ] **Converter client**: stub with 10s sleep, 1s timeout → `ConverterError` raised, logged at ERROR
- [ ] **Narrator client**: stub with 10s sleep, 1s timeout → `NarratorError` raised, logged at ERROR
- [ ] Timeout errors are caught by Bot, friendly reply sent, phase preserved for retry

## 6. Integration checks

- [ ] Bot starts without error (`python -m telegram_documentaries` imports cleanly)
- [ ] `DEFAULT_GEMINI_TIMEOUT = 60.0` constant defined and used by all three clients
- [ ] All three ADK/direct clients accept `timeout` parameter in `__init__`
- [ ] `asyncio.wait_for` wraps the model call in each client
- [ ] No new dependencies added
- [ ] `SCHEMA_VERSION` unchanged (still 4)

## 7. Constitution sync

- [ ] `ROADMAP.md` Phase 7 updated to "implemented and verified — see `SPECS/2026-10-13-resilience/`"
- [ ] `TECH.md` updated with timeout pattern note (if new)
- [ ] `MISSION.md` unchanged
- [ ] `README.md` unchanged

## 8. Acceptance criteria from ROADMAP.md Phase 7

- [ ] `/start` and `/restart` invoke explicit reset routine (3 actions in order)
- [ ] Purge includes `converted_<chat_id>_*` files
- [ ] Wrong-payload replies are friendly, in-character, no crash/traceback/silent drop
- [ ] Gemini timeouts caught, logged loudly, degrade gracefully
- [ ] Logging is decorator-based (`@log_call`) across all stages
- [ ] `scripts/test` runs green

## 9. Verification results

_(Filled in by the verifier when the phase is verified.)_