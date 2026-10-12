# The Narrator — implementation plan (Phase 6)

Reference: `SPECS/2026-10-11-narrator/requirements.md`.

## Group 0: Fix the aborted previous attempt

The repo arrived with a half-finished Narrator. Before anything else:

0.1 **`bot.py` reconciliation**
     - Import `NarratorError` (currently referenced but not imported; the file
       does not compile).
     - Fix import sorting for the `narrator` import.
     - Add the `self._narrator is None` guard to `_run_narrator` (mirrors
       `_run_converter`/`_run_scripter`) — mypy strict requires it.
     - Keep the existing routing: text in `NARRATING` → `_run_narrator`, and
       the same-turn auto-run after the Scripter advances to `NARRATING`.
     - Chain a successful failed-Scripter retry into the Narrator in the same
       turn (mirrors the interview cascade), so a retry does not need a second
       message before the voice note arrives.

0.4 **Amend the Converter's failure routing** (see `requirements.md` intent 7)
     - `_run_converter`'s failure handler advances the chat `CONVERTING →
       SCRIPTING` (it no longer parks in `CONVERTING`), so a failed hybrid
       portrait still lets the Scripter and Narrator run.
     - Update `CONVERTER_FAILURE_TEXT` so it no longer promises a photo retry —
       it says we carry on and narrate anyway.
     - This supersedes `SPECS/2026-10-09-converter/` decision 6 ("stay in
       `CONVERTING`"); that spec is annotated accordingly.

0.2 **Rewrite `narrator.py` from scratch**
     - Remove the broken `_get_telegram_client()`/`NotImplementedError` design.
     - Keep the typed boundary (`NarratorResult`, `NarratorError`,
       `NARRATOR_FAILURE_TEXT`) and the `GeminiTTSClient` protocol, but make the
       real client live in `narrator_client.py` (same shape as
       `scripter_client.py`).

0.3 **`client.py` gains `send_voice`** (group 3 below).

## Group 1: Audio transcoding (`narrator_audio.py`) — offline, no Google

1.1 **Format contract**
     - `AUDIO_MIME_TYPES = {"ogg": "audio/ogg", "mp3": "audio/mpeg"}` — the
       allowlist the stage validates `NarratorResult.format` against.
     - `PCM_SAMPLE_RATE = 24000`, `PCM_CHANNELS = 1` — the TTS model's native
       output shape (16-bit LE samples, fed to ffmpeg as `s16le`).

1.2 **Encoder discovery**
     - `find_ffmpeg() -> str | None`: `shutil.which("ffmpeg")` first, then the
       bundled `imageio_ffmpeg.get_ffmpeg_exe()` (imported lazily).
     - Result is cached at module level so repeated synthesis doesn't re-probe.

1.3 **`pcm_to_ogg(pcm: bytes) -> bytes`**
     - Reject empty input (`AudioTranscodeError`).
     - No encoder → `AudioTranscodeError` with a clear message.
     - `subprocess.run(ffmpeg -hide_banner -loglevel error -f s16le -ar 24000
       -ac 1 -i pipe:0 -c:a libopus -b:a 32k -f ogg pipe:1, input=pcm)`;
       non-zero exit or a non-`OggS` prefix → `AudioTranscodeError`.
     - Pure function: stdin/stdout, no temp files.

## Group 2: Gemini TTS client (`narrator_client.py`) — the real TTS hop

2.1 **Constants**
     - `NARRATOR_MODEL = "gemini-3.1-flash-tts-preview"`
     - `NARRATOR_VOICE = "Orus"` (a prebuilt documentary-narrator voice)
     - `NARRATOR_AUDIO_FORMAT = "ogg"`
     - `PCM_MIME_TYPE = "audio/L16;codec=pcm;rate=24000"`

2.2 **`GeminiTTSClient`**
     - `__init__(api_key, *, model=NARRATOR_MODEL, voice=NARRATOR_VOICE)`:
       empty key → `ValueError`; builds one `genai.Client(api_key=api_key)`.
     - `synthesize(text: str) -> NarratorResult`:
       - Empty/whitespace text → `NarratorError`.
       - One direct `generate_content` call (requirements decision 3) with
         `response_modalities=["AUDIO"]` and the `speech_config` voice.
       - Extract the audio part defensively
         (`candidates[0].content.parts[*].inline_data`) — no candidates /
         no inline data → `NarratorError`.
       - `audio/L16` (or any `audio/L16...`) payload → `pcm_to_ogg` →
         `NarratorResult(format="ogg")`; transcode failure wrapped as
         `NarratorError`.
       - Pre-wrapped `audio/ogg`/`audio/mpeg`/`audio/mp3` payload → pass
         through with the matching `format`.
       - Anything else → `NarratorError` (unexpected container).

## Group 3: Telegram `send_voice` (`client.py`)

3.1 **`TelegramClient.send_voice(chat_id, voice: bytes, *, mime_type: str,
     filename: str)`**
     - `@log_call`; multipart post to `/sendVoice` mirroring `send_photo`:
       `files={"voice": (filename, io.BytesIO(voice), mime_type)}`,
       `data={"chat_id": str(chat_id)}`, `timeout=60`; result via `_result`.

## Group 4: Narrator stage (`narrator.py`) — the orchestrator

4.1 **Boundary types**
     - `NarratorResult(audio_bytes: bytes, format: str)` — unchanged shape
       (`ConfigDict(extra="ignore")`).
     - `NarratorError(ValueError)`; `NARRATOR_FAILURE_TEXT` kept (in-character,
       script-safe, retryable).

4.2 **Protocols**
     - `GeminiTTSClient` protocol: `synthesize(text: str) -> NarratorResult`.
     - `VoiceNoteSender` protocol: `send_voice(chat_id, voice, *, mime_type,
       filename)` — the narrow slice of `TelegramClient` the stage needs.

4.3 **`Narrator(state, tts_client, telegram_client)`**
     - `@log_call def synthesize_and_deliver(chat_id: int) -> None`:
       - Load session; not `NARRATING` → `NarratorError`.
       - Missing/blank `dossier.script` → `NarratorError`.
       - `result = tts_client.synthesize(script)`; any exception → wrapped
         `NarratorError` (traceback already logged by `log_call`).
       - Empty `audio_bytes` → `NarratorError`.
       - `result.format` not in `AUDIO_MIME_TYPES` → `NarratorError`.
       - Persist to `<tempdir>/telegram_documentaries/narration_{chat}_*.{ext}`
         via `tempfile.mkstemp` (unique, chat-scoped); write failure →
         clean up + `NarratorError`.
       - `telegram_client.send_voice(...)` with `mime_type` from the allowlist
         and the temp file's name (extension carries the container); send
         failure → `NarratorError`.
       - `finally`: unlink the temp file (`missing_ok=True`).
       - Success: `session.phase = AWAITING_PHOTO`, `dossier.script = None`,
         save via `StateDriver`.

4.4 **Temp-dir helper**
     - `_temporary_audio_dir() -> Path` =
       `Path(tempfile.gettempdir()) / "telegram_documentaries"` — a module
       function so tests can redirect the scratch space deterministically.

## Group 5: Bot + entrypoint wiring

5.1 **`bot.py`**
     - Import `NarratorError` alongside `Narrator, NARRATOR_FAILURE_TEXT`.
     - `_run_narrator`: None-guards, `try/except NarratorError`, one concise
       error line, `_try_reply(chat_id, NARRATOR_FAILURE_TEXT)`.

5.2 **`__main__.py`**
     - Build `GeminiTTSClient(api_key=api_key)` and construct
       `Narrator(state, tts_client, telegram_client)` sharing the same
       `TelegramClient` instance; pass `narrator=...` to `Bot`.

## Group 6: Tests (Red/Green TDD)

6.1 **Fakes (`tests/support/fakes.py`)**
     - `StubTTSClient`: scripted `NarratorResult`s or `BaseException`s,
       records every `synthesize` text argument.
     - `FakeTelegramClient.send_voice`: records `(chat_id, voice, mime_type,
       filename)` in `sent_voices`.
     - A deterministic `STUB_OGG` byte blob for offline assertions.

6.2 **Unit tests (`tests/test_narrator.py`)**
     - Happy path: full script text passed to TTS; audio persisted then
       cleaned up; voice note delivered with exact bytes + `audio/ogg` +
       `.ogg` filename; phase `NARRATING → AWAITING_PHOTO`; script cleared.
     - Preconditions: wrong phase, missing/blank script → `NarratorError`.
     - Edge cases: unsupported format, empty audio → `NarratorError`.
     - Failure paths: TTS exception; temp-dir write failure; `send_voice`
       exception — each logged loudly (ERROR record), phase stays NARRATING,
       script preserved, no leaked temp files.
     - Cross-chat isolation: two chats' audio/scripts never cross.

6.3 **Client tests (`tests/test_client.py`)**
     - `send_voice` posts multipart to `/sendVoice` with the right filename,
       MIME, and exact audio bytes; API `ok: false` → `TelegramApiError`.
     - Extend the local `FakeSession.post` to accept `data`/`files`.

6.4 **Transcoder tests (`tests/test_narrator_audio.py`)**
     - `pcm_to_ogg` returns a stream starting with `OggS` (skipped when no
       encoder is installed); empty PCM and missing-encoder → handled errors;
       MIME allowlist mapping.
     - `find_ffmpeg` prefers PATH, falls back to imageio-ffmpeg, returns None
       when neither exists.

6.5 **Flow tests (`tests/test_narrator_flow.py`)**
     - Full pipeline in one turn: photo → interview → converter → scripter →
       narrator → voice note delivered, phase `AWAITING_PHOTO`, script cleared.
     - Narrator failure degrades gracefully (friendly text, stays NARRATING),
       then a text reply retries via the public path and succeeds.
     - Cross-chat isolation at the Bot level.
     - Unwired bot (no narrator) keeps the old REPLY_TEXT behaviour in
       NARRATING.

6.6 **Live opt-in test (`tests/test_narrator_live.py`)**
     - Skipped unless `GEMINI_API_KEY` set; real `gemini-3.1-flash-tts-preview`
       call → OGG bytes (`OggS` magic) delivered to a fake Telegram client,
       phase advanced, script cleared.

## Group 7: Constitution sync

7.1 `ROADMAP.md` Phase 6 marked "implemented and verified — see
     `SPECS/2026-10-11-narrator/`".
7.2 `TECH.md` — add the `imageio-ffmpeg` dependency note under Repo hygiene /
     Stack (transcoding is a runtime concern).
7.3 `README.md` — note the Narrator stage and any new dependency/run
     instruction.
7.4 `MISSION.md` — Narrator already described in the pipeline; unchanged.

## Group 8: Verification

8.1 Run `scripts/test` — must pass (pytest + ruff + mypy).
8.2 Run validation checks from `validation.md`.