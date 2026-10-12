# The Narrator — validation checklist (Phase 6)

Reference: `SPECS/2026-10-11-narrator/requirements.md`,
`SPECS/2026-10-11-narrator/plan.md`.

All checks must pass for the phase to be marked **verified**.

## 1. Static checks (run via `scripts/test`)

- [ ] `ruff check .` — no lint violations (including the previously-broken
      `bot.py`, which referenced `NarratorError` without importing it)
- [ ] `ruff format --check .` — formatting consistent
- [ ] `mypy` — no type errors
- [ ] `pytest` — all tests pass (offline suite, no `GEMINI_API_KEY` required)

## 2. Contract tests (`tests/test_narrator.py`)

- [ ] `Narrator.synthesize_and_deliver` passes the **full script string** from
      `dossier.script` into the TTS client untouched
- [ ] Happy path: stub TTS returns audio → temp file written under the system
      temp dir → `send_voice` delivered with the exact audio bytes, MIME
      `audio/ogg`, and a `.ogg` filename → phase advanced `NARRATING →
      AWAITING_PHOTO` → `dossier.script` cleared
- [ ] Temp file is **removed** after success (no leaked files)
- [ ] Wrong-phase precondition (not `NARRATING`) → `NarratorError`
- [ ] Missing or blank script → `NarratorError`
- [ ] Empty audio bytes → `NarratorError`
- [ ] Unsupported `NarratorResult.format` (e.g. `"wav"`) → `NarratorError`
      (the format is an allowlisted extension — never a free path string)
- [ ] TTS client raising → `NarratorError`, logged at ERROR (`log_call`),
      phase stays `NARRATING`, script preserved, nothing sent
- [ ] Temp-file write failure (scratch dir unwritable) → `NarratorError`,
      phase stays `NARRATING`, nothing sent
- [ ] `send_voice` failure → `NarratorError`, temp file still cleaned up,
      phase stays `NARRATING`, script preserved
- [ ] Cross-chat isolation: narrating chat A leaves chat B untouched, and A's
      audio never appears in B's sends

## 2b. TTS-client parsing tests (`tests/test_narrator_client.py`)

- [ ] `_extract_audio` returns the first non-empty inline audio payload and its
      MIME type; a response with no inline audio (or no candidates) →
      `NarratorError`
- [ ] `_wrap_audio` passes through an `OggS`-prefixed payload and a declared
      OGG/MP3 MIME; an unexpected MIME → `NarratorError`
- [ ] Raw PCM with no encoder available → `NarratorError`

## 3. Transcoder tests (`tests/test_narrator_audio.py`)

- [ ] `pcm_to_ogg` turns raw 16-bit PCM (24 kHz mono) into bytes starting with
      the `OggS` magic (skipped offline when no encoder is installed)
- [ ] Empty PCM → `AudioTranscodeError`
- [ ] No encoder available → `AudioTranscodeError` with a clear message
- [ ] `AUDIO_MIME_TYPES` maps `ogg → audio/ogg`, `mp3 → audio/mpeg`

## 4. Client tests (`tests/test_client.py`)

- [ ] `send_voice` posts multipart/form-data to `/sendVoice` with the given
      filename, MIME type, and the exact audio bytes
- [ ] Telegram `ok: false` on `sendVoice` → `TelegramApiError`

## 5. Flow tests (`tests/test_narrator_flow.py`)

- [ ] **Happy path:** photo → interview (3–4 Qs) → converter → scripter →
      narrator runs in the same turn → voice note delivered, phase
      `AWAITING_PHOTO`, script cleared
- [ ] **Failure path:** stubbed TTS raises → `NARRATOR_FAILURE_TEXT` sent →
      phase stays `NARRATING` → dossier/script intact → retry succeeds **via
      the public path** (an ordinary text reply through `bot.handle_update`
      re-runs the Narrator)
- [ ] **Cross-chat isolation:** two chats narrate independently; voice notes
      and scripts never leak
- [ ] **Converter-failure crossover:** a stubbed Converter raises → the chat
      advances to `SCRIPTING`, `CONVERTER_FAILURE_TEXT` is sent, and the
      Scripter + Narrator still run in the same turn → voice note delivered,
      phase `AWAITING_PHOTO`
- [ ] Unwired bot (no Narrator wired) keeps the default reply in `NARRATING`

## 6. Live opt-in test (`tests/test_narrator_live.py`)

- [ ] Test gated with `@pytest.mark.skipif(not _API_KEY, ...)` — the repo's
      existing convention, so the suite skips it offline
- [ ] Real `gemini-3.1-flash-tts-preview` call, through the direct
      `google-genai` client (NO ADK `LlmAgent`), produces OGG/Opus audio
      (`OggS` magic)
- [ ] Voice note delivered to a fake Telegram client, phase advanced,
      script cleared

## 7. Integration checks

- [ ] Bot starts without error (`python -m telegram_documentaries` imports
      cleanly)
- [ ] The Narrator is **plumbing, not an agent**: `narrator_client.py` uses
      `genai.Client.models.generate_content` directly — no `LlmAgent`, no ADK
      runner, no conversational turn
- [ ] `NARRATOR_MODEL = "gemini-3.1-flash-tts-preview"` module constant exists
- [ ] `NARRATOR_FAILURE_TEXT` constant defined, in-character, and points at a
      retry without suggesting a photo
- [ ] `TelegramClient.send_voice` exists and mirrors `send_photo`'s
      multipart/`BytesIO` style
- [ ] `__main__.py` wires `Narrator(state, GeminiTTSClient(api_key), telegram_client)`
      and passes `narrator=` to `Bot`
- [ ] Session schema unchanged: `SCHEMA_VERSION = 3`, `Phase.NARRATING` and
      `Dossier.script` reused as-is
- [ ] No hardcoded secrets; `GEMINI_API_KEY`/`TELEGRAM_BOT_TOKEN` via `.env`

## 8. Constitution sync

- [ ] `ROADMAP.md` Phase 6 updated to "implemented and verified — see
      `SPECS/2026-10-11-narrator/`"
- [ ] `MISSION.md` unchanged (Narrator already described in the pipeline)
- [ ] `TECH.md` updated for the `imageio-ffmpeg` runtime dependency
- [ ] `README.md` updated for the Narrator stage / run instructions

## 9. Acceptance criteria from ROADMAP.md Phase 6

- [ ] The Scripter's text reaches Gemini TTS directly (no conversational turn)
- [ ] The audio is rendered to a Telegram-compatible format (OGG/MP3) and
      arrives as a voice note
- [ ] The full happy path `/start` → photo → interview → image → narration →
      voice note completes unattended
- [ ] `scripts/test` runs green