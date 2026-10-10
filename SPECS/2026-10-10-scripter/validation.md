# The Scripter — validation checklist (Phase 5)

Reference: `SPECS/2026-10-10-scripter/requirements.md`,
`SPECS/2026-10-10-scripter/plan.md`.

All checks must pass for the phase to be marked **verified**.

## 1. Static checks (run via `scripts/test`)

- [ ] `ruff check .` — no lint violations
- [ ] `ruff format --check .` — formatting consistent
- [ ] `mypy` — no type errors
- [ ] `pytest` — all tests pass (offline suite, no `GEMINI_API_KEY` required)

## 2. Contract tests (`tests/test_scripter.py`)

- [ ] `parse_output` accepts valid JSON with `script` field
- [ ] `parse_output` rejects free text (not JSON)
- [ ] `parse_output` rejects JSON missing `script` field
- [ ] `parse_output` rejects `script` as non-string
- [ ] `parse_output` rejects empty or whitespace-only `script`
- [ ] `parse_output` rejects multi-paragraph output (`\n\n`, and the CRLF /
      bare-CR / unicode paragraph-separator spellings after normalisation)
- [ ] `parse_output` rejects output > 90 words
- [ ] `parse_output` rejects markdown **constructs** (bold, italic, headings,
      code, `~~strikethrough~~`, `[link](url)`)
- [ ] `parse_output` **accepts** ordinary prose punctuation — `( )`, `[ ]`, a
      single `~`, apostrophes, hyphens, ellipses, decimals
- [ ] `Scripter.generate` returns typed `ScripterOutput` for stubbed response
- [ ] `Scripter.generate` passes exact dossier context to client
- [ ] `Scripter.generate` raises `ScripterError` on malformed model output
- [ ] `ScripterError` is logged at ERROR level by `@log_call` decorator

## 3. Flow tests (`tests/test_scripter_flow.py`)

- [ ] **Happy path:** photo → interview (3–4 Qs) → converter → scripter
      produces script → script sent to Telegram → phase advances to
      `NARRATING` → script persisted in `session.dossier.script`
- [ ] Script text is a single paragraph, ≤ 90 words, no markdown
- [ ] Script references dossier content (profile, animal, at least one Q&A
      detail)
- [ ] **Failure path:** stubbed client raises / returns malformed →
      `SCRIPTING_FAILURE_TEXT` sent → phase stays `SCRIPTING` → dossier
      intact → retry succeeds **via the public path** (an ordinary text reply
      through `bot.handle_update` re-runs the Scripter, per the user-approved
      "reply any text to retry" design)
- [ ] **Cross-chat isolation:** two `chat_id`s reach SCRIPTING independently;
      scripts, phases, dossiers don't leak

## 4. Live opt-in test (`tests/test_scripter_live.py`)

- [ ] Test gated with `@pytest.mark.skipif(not _API_KEY, ...)` — the repo's
      existing convention (`test_interviewer_live.py`,
      `test_bouncer_live.py`), so the suite skips it offline
- [ ] Real `gemini-3.1-flash-lite` call produces valid script meeting all
      constraints
- [ ] Script delivered to test chat (manual verification or fake client capture)

## 5. Integration checks

- [ ] Bot starts without error (`python -m telegram_documentaries` imports
      cleanly)
- [ ] `SCRIPTING` phase added to `Phase` enum, `SCHEMA_VERSION = 3`
- [ ] `Dossier` has `script: str | None` field
- [ ] `NARRATING` phase exists and is used after successful script generation
- [ ] `SCRIPTING_FAILURE_TEXT` constant defined and in-character
- [ ] `_run_scripter` method added to `Bot`, called after Converter advances
      to `SCRIPTING`
- [ ] No new dependencies added beyond existing `google-adk`, `google-genai`

## 6. Constitution sync

- [ ] `ROADMAP.md` Phase 5 updated to "implemented and verified — see
      `SPECS/2026-10-10-scripter/`"
- [ ] `MISSION.md` unchanged (Scripter already described in pipeline)
- [ ] `TECH.md` unchanged (follows existing patterns)
- [ ] `README.md` unchanged (no new deps / run instructions)

## 7. Acceptance criteria from ROADMAP.md Phase 5

- [ ] Output is a single paragraph, roughly 60–90 words
- [ ] Tone is Brian Cox physicist persona (wonder-struck, cosmic scale, poetic)
- [ ] Output parsed against schema; malformed model output is handled error
- [ ] Script sent to user's Telegram chat as text message
- [ ] `scripts/test` runs green

(End of file - total 83 lines)