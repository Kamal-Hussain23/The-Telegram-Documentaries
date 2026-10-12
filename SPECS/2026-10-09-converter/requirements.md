# The Converter — requirements (Phase 4)

Feature spec for ROADMAP.md Phase 4: *"Multimodal fusion of the original photo and the dossier into a hybrid portrait."* It defers to `SPECS/MISSION.md`, `SPECS/TECH.md`, and `SPECS/ROADMAP.md` for anything not stated here.

## Context

Phase 3 (the Interviewer) has completed the behavioural dossier and suggested an animal. The pipeline now needs a stage that fuses the user's original photo with the behavioural dossier into a hybrid animal portrait, delivered directly to the user via Telegram.

This is the **first stage that uses `gemini-3.1-flash-image`** (the Converter model). Earlier stages (`Bouncer`, `Interviewer`) use `gemini-3.1-flash-lite` for vision/text classification. The Converter sends **both** the original image bytes **and** the dossier context to the image model in a single call, and receives a hybrid portrait back.

## User-approved intent

On a photo interview completion (`phase is CONVERTING`):

1. Retrieve the **original photo bytes** from session state (keyed by `chat_id`).
2. Retrieve the **dossier context** (profile + suggested animal + accumulated Q&A) from the same session.
3. Send **both** the image bytes and the dossier text as **multimodal input** to `gemini-3.1-flash-image` through Google ADK, with a structured output schema.
4. The model fuses the user's likeness with an **animal archetype** reflecting their quirks (e.g., a caffeinated badger, a meticulous beaver) and returns a **hybrid portrait image**.
5. Use the **Telegram Bot API** to deliver the rendered image directly to the user's chat — **no intermediate text hop**.
6. If the model fails to produce a valid image, log the error loudly and reply with a friendly in-character message — the conversation degrades gracefully (TECH.md: no crash, no traceback). **Phase 6 amendment:** the chat then advances to `SCRIPTING` so the Scripter and Narrator still run without a hybrid portrait (see `SPECS/2026-10-11-narrator/`); it no longer parks in `CONVERTING`.
7. On success, advance the state machine to `SCRIPTING` (the Scripter stage), persisting the hybrid image reference for the next stage.
8. Add the **ADK wiring** needed to hook the agent into the pipeline, following the same patterns as `vision.py` (Bouncer) and `interview_client.py` (Interviewer).

## Scope

### In scope

- **Photo retrieval**: read the accepted photo bytes from session state, scoped to `chat_id` only.
- **Dossier retrieval**: read the completed dossier (profile, suggested_animal, questions/answers) from the same session.
- **The Converter agent** (ADK `LlmAgent` on `gemini-3.1-flash-image`):
  - Accepts the original image bytes **and** the dossier context as multimodal input.
  - Uses a **structured output schema** (`ConverterOutput`) so the model's response is always parseable into a typed model — free text is never interpreted downstream.
  - The instruction directs the model to fuse the user's likeness with an **animal archetype** that reflects their quirks (e.g., a caffeinated badger, a meticulous beaver).
  - Returns the **rendered hybrid portrait** (image bytes) from the model's final response.
- **Telegram dispatch**: use the existing `TelegramClient.send_photo` (or equivalent) to deliver the rendered image directly to the user's chat.
- **State advancement**: on successful conversion, advance the phase from `CONVERTING` to `SCRIPTING`, preserving the photo reference for the Scripter stage.
- **Graceful degradation**: if the model fails (validation error, timeout, unstructured output), log loudly, do NOT crash, and reply with a friendly in-character message. **Phase 6 amendment:** the conversation advances to `SCRIPTING` so the narration still happens without the portrait (the original "stay in `CONVERTING` so it can be retried" is superseded).
- **ADK dependency**: install `google-adk` and `google-genai` (pinned, per TECH.md lockfile hygiene). `GEMINI_API_KEY` read from `.env` via `python-dotenv` only.
- **Tests**: Red/Green TDD — tests written before the code they cover. Fixture images live under `tests/fixtures/`. The default suite stays green offline (stubbed Gemini client); a live opt-in check exists for real `gemini-3.1-flash-image` classification.

### Out of scope (YAGNI)

- Webhooks / public URLs (long polling only).
- Database or any persistence — state lives in process memory; a restart wiping sessions is acceptable.
- Group-chat usage (1:1 DMs only) and multi-language support (English only).
- Wrong-payload guards and broader API-timeout fallbacks — those are Phase 7 (Resilience), not Phase 4.
- All Scripter work: narration, TTS, voice note generation (that's Phase 5–6).
- Config toggles, extension points, or speculative abstractions no current requirement demands.

## Decisions

These are fixed for this feature; deviation requires updating the specs in `SPECS/`.

1. **Model:** `gemini-3.1-flash-image` for the Converter, per the TECH.md stack table. No other model is introduced in this phase.
2. **Input to the model:** Two parts — (a) the original image bytes as multimodal `types.Part`, and (b) the dossier context as text in the same prompt. Both travel in one ADK call.
3. **Output schema:** a Pydantic model (`ConverterOutput`) with at least an `image_bytes` field (base64-encoded or raw) and a `confidence`/`reason` field. The model's response is always parsed against this schema; free text is never interpreted downstream.
4. **Session state:** versioned schema, keyed by `chat_id`, in-memory only, behind the one shared `StateDriver`. All reads/writes go through the driver — no stage touches state directly.
5. **Telegram dispatch:** deliver the rendered image via `send_photo` (Telegram Bot API). No intermediate text hop.
6. **Phase advancement:** on success, advance from `CONVERTING → SCRIPTING`. On failure, **advance to `SCRIPTING` anyway** (Phase 6 amendment) so the Scripter and Narrator still run — the portrait is skipped, never retried. (Phase 4 originally required staying in `CONVERTING`; see `SPECS/2026-10-11-narrator/`.)
7. **Untrusted input at the boundary:** downloaded image bytes and Telegram / Gemini payloads are treated as arbitrary. Size, type, and shape are validated at the edge before the model sees them; raw dicts never cross a module boundary.
8. **Logging:** decorator-based structured logging via the existing `logutil.log_call` (entry/exit/duration/exception), consistent with TECH.md — no logging statements mixed into business logic.
9. **Testing:** Red/Green TDD — tests written before the code they cover. `scripts/test` (pytest + ruff + mypy) is the ground truth and must stay green.

## Acceptance criteria (from ROADMAP.md Phase 4)

- Photo + dossier are sent together to the image model in one call.
- The resulting image is delivered to the Telegram chat directly — no intermediate text hop.
- Failure to generate the image produces a logged, graceful user-facing message rather than a dead end.

## Verification

- **Negative test:** converter failure (stub raises or returns malformed) → logged error, friendly reply, phase advances to `SCRIPTING` (Phase 6 amendment; was "stays at CONVERTING").
- **Positive test:** image + dossier → verdict says hybrid portrait generated → image delivered via Telegram, phase advances to SCRIPTING.
- Both paths exercised with a stubbed Gemini client so `scripts/test` runs offline; a live opt-in check exists for real `gemini-3.1-flash-image` classification (details in `validation.md`).
- `scripts/test` runs green (pytest + ruff + mypy) with no `GEMINI_API_KEY` set and no network access.
- Two distinct `chat_id`s in the same process: perform a photo flow in chat A, then assert chat B's session is still at the initial phase and has no record of A's verdict, phase, or downloaded media.