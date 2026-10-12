# The Narrator — requirements (Phase 6)

Feature spec for ROADMAP.md Phase 6: *"TTS synthesis and audio delivery."* It
defers to `SPECS/MISSION.md`, `SPECS/TECH.md`, and `SPECS/ROADMAP.md` for
anything not stated here.

## Context

Phase 5 (the Scripter) has produced the narration paragraph and advanced the
state machine to `NARRATING`. The session now holds:

- The original photo bytes (unchanged)
- The completed dossier: profile, suggested_animal, the Q&A, and the hybrid
  portrait note appended to the profile
- `dossier.script`: the single-paragraph narration, ready for voice synthesis

The Narrator is the **final pipeline stage**: it reads `dossier.script` and
turns it into a Telegram voice note. Unlike every stage before it, the Narrator
is **plumbing, not an agent** (TECH.md): the Scripter's text goes **straight to
Gemini TTS** and back out as a voice note — no conversational turn, no ADK
`LlmAgent`.

## User-approved intent

On a chat in `NARRATING` phase:

1. Retrieve `dossier.script` from session state, scoped to `chat_id` only.
2. Send the **full script text** to **`gemini-3.1-flash-tts-preview`** through
   the direct `google-genai` client (`client.models.generate_content`, the TTS
   model — not an ADK `LlmAgent`).
3. TTS replies with binary audio (raw 16-bit PCM, 24 kHz, mono — the model's
   native output). The audio is wrapped into a **Telegram-compatible
   container** — **OGG/Opus** (`audio/ogg`) as the primary target, MP3 accepted
   as a pass-through if the API ever returns a pre-wrapped stream.
4. Persist the audio to a **temporary audio file** under the system temp dir,
   scoped to the chat and **always cleaned up** afterwards.
5. Send the audio to the user's Telegram chat as a **voice note** via the
   Telegram Bot API `sendVoice` endpoint (multipart/form-data, mirroring the
   existing `send_photo`).
6. On success, advance the state machine from `NARRATING` to
   `AWAITING_PHOTO` and clear `dossier.script` — the pipeline is complete.
7. On failure (TTS error, transcode error, file-write error, send error): log
   loudly, reply with a friendly in-character message, and **stay in
   `NARRATING`** so it can be retried — the script is preserved.
8. **Pipeline amendment (Converter failure).** When the Converter cannot
   produce a hybrid portrait, the chat advances from `CONVERTING` to
   `SCRIPTING` (it no longer parks in `CONVERTING`) so the Scripter and
   Narrator still run; the user gets an in-character notice that the portrait
   could not be made. This supersedes the Phase 4 Converter spec's "stay in
   `CONVERTING`" decision (see `SPECS/2026-10-09-converter/`).

## Scope

### In scope

- **Script retrieval**: read `dossier.script` from session state via the one
  shared `StateDriver`, scoped to `chat_id` only.
- **The Gemini TTS client** (direct `google-genai`, no ADK agent):
  - Calls `client.models.generate_content` with `model =
    "gemini-3.1-flash-tts-preview"`, `response_modalities=["AUDIO"]`, and a
    `speech_config` voice so the narration has a documentary narrator.
  - Returns a typed `NarratorResult { audio_bytes, format }` for the edge
    parser — free-form `GenerateContentResponse` objects never cross into the
    core.
  - Wraps the model's raw PCM output into **OGG/Opus** via `ffmpeg` (the
    bundled `imageio-ffmpeg` binary when available, otherwise the system
    `ffmpeg` on PATH). If the model ever returns a pre-wrapped
    Telegram-compatible stream (`audio/ogg`, `audio/mpeg`/`audio/mp3`), it is
    passed through untouched.
- **Telegram dispatch**: a real `send_voice` on `TelegramClient` using the
  `sendVoice` endpoint with multipart/form-data, accepting the audio bytes plus
  the MIME type and filename (OGG `audio/ogg` / MP3 `audio/mpeg`). The Narrator
  receives the delivery dependency through its constructor (dependency
  injection — it never builds a Telegram client itself).
- **State advancement**: on success, advance from `NARRATING` to
  `AWAITING_PHOTO`, clearing `dossier.script`. No schema change: `Phase`
  already has `NARRATING` and `Dossier.script` already exists; the schema
  version stays at 3.
- **Graceful degradation**: any failure is caught at the Narrator public
  boundary, logged loudly (decorator-based via `log_call` plus a concise
  context line in the Bot), and answered with a friendly in-character message.
  The conversation stays in `NARRATING` so a text reply retries the stage.
- **Converter-failure routing amendment**: a failed hybrid portrait advances
  `CONVERTING → SCRIPTING` (no longer parks in `CONVERTING`) so the Scripter
  and Narrator still run without it; the user is told in-character. This
  amends the Phase 4 Converter spec.
- **Temporary-file hygiene**: audio files live under
  `<system-temp>/telegram_documentaries/`, use unique per-chat names, and are
  removed in a `finally` — success or failure, no leaked files (MISSION.md: no
  cross-user leakage; TECH.md: no generated artifacts committed).
- **Dependencies**: `google-genai` (already pinned) for the TTS call;
  `imageio-ffmpeg` (new, adds an offline-bundled `ffmpeg` binary) for the
  PCM → OGG/Opus transcode when no system `ffmpeg` exists.
- **Tests**: Red/Green TDD — tests written before the code they cover. The
  default suite stays green offline (stubbed TTS client and a stubbed
  Telegram `send_voice`); a live opt-in check exists for real
  `gemini-3.1-flash-tts-preview` synthesis.

### Out of scope (YAGNI)

- Webhooks / public URLs (long polling only).
- Database or any persistence — state lives in process memory; a restart
  wiping sessions is acceptable.
- Group-chat usage (1:1 DMs only) and multi-language support (English only).
- Voice replication / cloned voices; audio input / transcription; video output.
- Wrong-payload guards and broader API-timeout fallbacks — those are Phase 7
  (Resilience), not Phase 6.
- Streaming TTS, multi-speaker output, or any `interactions`-API features not
  required by the single-paragraph voice note.
- Config toggles, extension points, or speculative abstractions no current
  requirement demands.

## Decisions

These are fixed for this feature; deviation requires updating the specs in
`SPECS/`.

1. **Model:** `gemini-3.1-flash-tts-preview` (module constant
   `NARRATOR_MODEL`), per the TECH.md stack table. No other TTS model is
   introduced.
2. **Plumbing, not an agent.** The Narrator is NOT an ADK `LlmAgent`. The
   script text is the entire prompt of one direct `generate_content` call —
   no conversational turn, no session, no agent instruction.
3. **Direct `google-genai` call shape** (verified against `google-genai`
   2.28.0):
   - `client.models.generate_content(model, contents=script, config=...)`
   - `config.response_modalities = ["AUDIO"]`
   - `config.speech_config = SpeechConfig(voice_config=VoiceConfig(
     prebuilt_voice_config=PrebuiltVoiceConfig(voice_name=...)))`
   - The audio lands on `response.candidates[0].content.parts[*].inline_data`
     as raw PCM (`audio/L16;codec=pcm;rate=24000`).
4. **Audio format:** OGG/Opus (`format="ogg"`, MIME `audio/ogg`) is the
   primary Telegram-compatible target — Telegram clients play it back as a
   native voice note. MP3 (`audio/mpeg`) is an accepted alternative. The
   format lives in a module constant (`NARRATOR_AUDIO_FORMAT`) so it can be
   changed without code archaeology.
5. **Transcoding:** raw PCM (16-bit LE, 24 kHz, mono) → OGG/Opus via `ffmpeg`
   in a subprocess: `ffmpeg -f s16le -ar 24000 -ac 1 -i - -c:a libopus -b:a
   32k -f ogg -`. The encoder is located by (`shutil.which("ffmpeg")`, then
   the `imageio_ffmpeg` bundled binary). No encoder → handled `NarratorError`.
6. **Output contract:** `NarratorResult { audio_bytes: bytes, format: str }`
   where `format` is `"ogg"` or `"mp3"`. The Narrator stage validates the
   format against a strict allowlist (it becomes a file extension — never
   trust a free string for a path), and rejects empty audio.
7. **Telegram delivery:** `send_voice` on `TelegramClient` posts
   multipart/form-data to `/sendVoice` (mirrors `send_photo`'s `io.BytesIO`
   style): `files={"voice": (filename, BytesIO(audio), mime_type)}`. The
   filename carries the extension so Telegram detects the container.
8. **Dependency injection, not construction:** `Narrator(state, tts_client,
   telegram_client)`. The Telegram client is injected from the wiring
   (`__main__.py` / tests) through a narrow `VoiceNoteSender` protocol — the
   stage never builds a client and never calls `get_updates` etc.
9. **State:** all reads/writes through the one shared `StateDriver`; success
   advances `NARRATING → AWAITING_PHOTO` and clears `dossier.script`; failure
   leaves `NARRATING` and the script intact for retry.
10. **Failure policy:** `NarratorError` for everything handled. The public
    `synthesize_and_deliver` is decorated with `log_call` (full traceback at
    ERROR); the Bot adds one concise context line and replies with
    `NARRATOR_FAILURE_TEXT`. Never a traceback to the user. No bare
    `except: pass` anywhere.
11. **Logging:** decorator-based via `logutil.log_call`; no log statements
    mixed into the stage's business logic. Context lines (e.g. "wrote N bytes")
    are DEBUG/INFO via the decorator or tightly-scoped helpers, not sprinkled
    `logger.info` in the flow.
12. **Testing:** Red/Green TDD — tests written before the code they cover.
    `scripts/test` (pytest + ruff + mypy) is the ground truth and must stay
    green offline.
13. **Security non-negotiables** (MISSION.md): no cross-user leakage — one
    chat's script/audio/voice note never appears in another chat, and temp
    files are removed; no hardcoded secrets — `GEMINI_API_KEY` and
    `TELEGRAM_BOT_TOKEN` come from `.env` via `python-dotenv` only.

## Acceptance criteria (from ROADMAP.md Phase 6)

- The Scripter's text reaches Gemini TTS directly (no conversational turn).
- The audio is rendered to a Telegram-compatible format (OGG/MP3) and arrives
  as a voice note.
- The full happy path `/start` → photo → interview → image → narration → voice
  note completes unattended.
- `scripts/test` runs green (pytest + ruff + mypy).

## Verification

- **Negative test:** narrator failure (TTS raises, transcode fails, temp file
  can't be written, or Telegram `send_voice` fails) → logged error, friendly
  reply, phase stays at NARRATING, script preserved, no leaked temp files.
- **Positive test:** `NARRATING` session with a script → TTS stub returns audio
  → temp file written then removed → voice note delivered via `send_voice` →
  phase advances to `AWAITING_PHOTO` and the script is cleared.
- **Contract tests:** the full script string reaches the TTS client exactly;
  `NarratorResult` format is allowlisted; empty audio and unsupported formats
  are handled errors.
- Both paths exercised with a stubbed TTS client and a stubbed `send_voice`,
  so `scripts/test` runs offline; a live opt-in check exists for real
  `gemini-3.1-flash-tts-preview` synthesis (details in `validation.md`).
- Two distinct `chat_id`s in the same process: perform a flow to NARRATING and
  narrate chat A, then assert chat B's session is still at the initial phase
  with no record of A's script or audio.