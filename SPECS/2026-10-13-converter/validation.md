# The Converter — validation checklist (Phase 4)

Reference: `SPECS/2026-10-13-converter/requirements.md`,
`SPECS/2026-10-13-converter/plan.md`.

All checks must pass for the phase to be marked **verified**.

## 1. Static checks (run via `scripts/test`)

- [ ] `ruff check .` — no lint violations
- [ ] `ruff format --check .` — formatting consistent
- [ ] `mypy` — no type errors
- [ ] `pytest` — all tests pass (offline suite, no `GEMINI_API_KEY` required)

## 2. Contract tests (`tests/test_converter.py`)

- [ ] `parse_output` accepts valid JSON with `image_bytes` field
- [ ] `parse_output` rejects free text (not JSON)
- [ ] `parse_output` rejects JSON missing `image_bytes` field
- [ ] `parse_output` rejects `image_bytes` as non-bytes / empty
- [ ] `Converter.generate_and_send` returns typed `ConverterOutput` for stubbed response
- [ ] `Converter.generate_and_send` passes exact photo bytes and dossier context to client
- [ ] `Converter.generate_and_send` raises `ConverterError` on malformed model output
- [ ] `ConverterError` is logged at ERROR level by `@log_call` decorator
- [ ] `Converter.generate_and_send` on failure: sends failure text via Telegram, advances to `SCRIPTING`, returns `None`

## 3. Flow tests (`tests/test_converter_flow.py`)

- [ ] **Happy path:** photo → interview (3–4 Qs) → converter generates hybrid image → image delivered via Telegram `send_photo` → phase advances to `SCRIPTING` → dossier intact
- [ ] Image bytes are non-empty and delivered to correct `chat_id`
- [ ] **Failure path:** stubbed client raises / returns malformed → `CONVERTER_FAILURE_TEXT` sent → phase advances to `SCRIPTING` → dossier intact → Scripter/Narrator still run (pipeline continues)
- [ ] **Cross-chat isolation:** two `chat_id`s reach CONVERTING independently; images, phases, dossiers don't leak

## 4. Live opt-in test (`tests/test_converter_live.py`)

- [ ] Test gated with `@pytest.mark.skipif(not _API_KEY, ...)` — the repo's existing convention (`test_interviewer_live.py`, `test_bouncer_live.py`), so the suite skips it offline
- [ ] Real `gemini-3.1-flash-image` call produces valid hybrid image
- [ ] Image delivered to test chat (manual verification or fake client capture)

## 5. Integration checks

- [ ] Bot starts without error (`python -m telegram_documentaries` imports cleanly)
- [ ] `CONVERTING` phase added to `Phase` enum, `SCHEMA_VERSION = 4`
- [ ] `Dossier` has no new fields (existing fields sufficient)
- [ ] `CONVERTING` phase exists and is used after Interviewer completes
- [ ] `CONVERTER_FAILURE_TEXT` constant defined and in-character
- [ ] `_run_converter` method added to `Bot`, called after Interviewer advances to `CONVERTING`
- [ ] Converter advances to `SCRIPTING` on both success and failure (per Narrator spec amendment)
- [ ] No new dependencies added beyond existing `google-adk`, `google-genai`

## 6. Constitution sync

- [ ] `ROADMAP.md` Phase 4 updated to "implemented and verified — see `SPECS/2026-10-13-converter/`"
- [ ] `MISSION.md` unchanged (Converter already described in pipeline)
- [ ] `TECH.md` unchanged (follows existing patterns)
- [ ] `README.md` unchanged (no new deps / run instructions)

## 7. Acceptance criteria from ROADMAP.md Phase 4

- [ ] Photo + dossier are sent together to the image model in one call
- [ ] The resulting image is delivered to the Telegram chat directly — no intermediate text hop
- [ ] Failure to generate the image produces a logged, graceful user-facing message rather than a dead end
- [ ] The bot automatically transitions from the final interview question to returning an animal hybrid portrait in the chat
- [ ] `scripts/test` runs green

(End of file - total 83 lines)