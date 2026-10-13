# The Converter — requirements (Phase 4)

Feature spec for ROADMAP.md Phase 4: *"Multimodal fusion of the original photo and the dossier into a hybrid portrait."* It defers to `SPECS/MISSION.md`, `SPECS/TECH.md`, and `SPECS/ROADMAP.md` for anything not stated here.

## Context

Phase 3 (the Interviewer) has completed the interview and advanced the state machine to `CONVERTING`. The session now holds:

- The original photo bytes (from the Bouncer pass)
- The completed dossier: profile (behavioural summary), suggested_animal, and the accumulated Q&A
- Phase = `CONVERTING`

The Converter is the **first stage to use `gemini-3.1-flash-image`** (the Bouncer/Interviewer/Scripter use `gemini-3.1-flash-lite`, the Narrator uses `gemini-3.1-flash-tts-preview`). Its job: read the photo and dossier, generate a hybrid animal portrait, and deliver it directly to the Telegram chat.

## User-approved intent

On a chat in `CONVERTING` phase:

1. Retrieve the **original photo bytes** and the **completed dossier** (profile, suggested_animal, questions, answers) from session state, scoped to `chat_id`.
2. Send the photo + dossier context to **`gemini-3.1-flash-image`** through Google ADK, with a structured output schema (`ConverterOutput`).
3. The model **fuses the user's likeness with an animal archetype** that reflects their quirks from the dossier (e.g., a caffeinated badger for someone who drinks coffee late at night, a meticulous beaver for someone who organizes their desk perfectly, a night-owl bat for a late sleeper, etc.). The instruction directs the model to create a playful, wildlife-documentary-style hybrid portrait.
4. **Output contract:** the model returns a structured response with the generated image bytes (or a reference to the generated image). The Converter parses this into the typed `ConverterOutput` model.
5. **Telegram Dispatch:** Use the existing `TelegramClient.send_photo` to deliver the rendered hybrid image directly to the user's chat.
6. On success, advance the state machine from `CONVERTING` to `SCRIPTING`, preserving the dossier and the hybrid image reference (if applicable).
7. On failure (validation error, timeout, generation failure): log loudly, reply with a friendly in-character message, and **advance to `SCRIPTING` anyway** (per the Narrator spec amendment) so the Scripter and Narrator still run; the user gets an in-character notice that the portrait could not be made.
8. Add the ADK wiring following the same patterns as `interview_client.py` (Bouncer/Interviewer) — an `LlmAgent` with `output_schema`, async session service driven by `asyncio.run`, `GEMINI_API_KEY` via `client_kwargs`.

## Scope

### In scope

- **Dossier + photo retrieval**: read the original photo bytes and completed dossier from session state, scoped to `chat_id` only.
- **The Converter agent** (ADK `LlmAgent` on `gemini-3.1-flash-image`):
  - Accepts the photo bytes and dossier context as input.
  - Uses a **structured output schema** (`ConverterOutput`) with at least an `image_bytes` field (or `image_ref`).
  - The instruction directs the model to fuse the user's likeness with an animal archetype reflecting their quirks, in a playful wildlife-documentary style.
  - Returns the model's raw structured output for edge parsing.
- **Telegram dispatch**: use the existing `TelegramClient.send_photo` to deliver the hybrid image directly to the user's chat.
- **State advancement**: on success, advance from `CONVERTING → SCRIPTING`. On failure, also advance to `SCRIPTING` (with a user-facing notice) so the pipeline continues.
- **Graceful degradation**: if the model fails (validation error, timeout, unstructured output), log loudly, do NOT crash, and reply with a friendly in-character message. The conversation advances to `SCRIPTING` so the Scripter and Narrator still run.
- **ADK dependency**: already installed (`google-adk`, `google-genai` pinned). `GEMINI_API_KEY` read from `.env` via `python-dotenv` only.
- **Tests**: Red/Green TDD — tests written before the code they cover. Fixture data under `tests/fixtures/` if needed. The default suite stays green offline (stubbed Gemini client); a live opt-in check exists for real `gemini-3.1-flash-image` image generation.

### Out of scope (YAGNI)

- Webhooks / public URLs (long polling only).
- Database or any persistence — state lives in process memory; a restart wiping sessions is acceptable.
- Group-chat usage (1:1 DMs only) and multi-language support (English only).
- Wrong-payload guards and broader API-timeout fallbacks — those are Phase 7 (Resilience), not Phase 4.
- The Scripter or Narrator themselves (Phases 5–6). The Converter only produces the hybrid image and advances the phase.
- Config toggles, extension points, or speculative abstractions no current requirement demands.

## Decisions

These are fixed for this feature; deviation requires updating the specs in `SPECS/`.

1. **Model:** `gemini-3.1-flash-image` via Google ADK, per the TECH.md stack table. No other model is introduced.
2. **Typed contract, never free text.** The model answers through a Pydantic schema:
   - `ConverterOutput { image_bytes: bytes }` — the generated hybrid portrait image data. Anything that fails this schema is a **handled error** (`ConverterError`), logged loudly, never interpreted downstream.
3. **Session state:** versioned schema, keyed by `chat_id`, in-memory only, behind the one shared `StateDriver`. All reads/writes go through the driver — no stage touches state directly. Schema version bumps to **4** to add the `CONVERTING` phase.
4. **Telegram dispatch:** deliver the hybrid image via `send_photo` (Telegram Bot API). This is the Converter's output action — the user sees the image before the script/voice note arrive.
5. **Phase advancement:** on success, advance from `CONVERTING → SCRIPTING`. On failure, **also advance to `SCRIPTING`** (amending the original Phase 4 spec) so the Scripter and Narrator still run; the user is told in-character that the portrait couldn't be made.
6. **Untrusted input at the boundary:** Telegram / Gemini payloads are treated as arbitrary. Model output is validated against the schema before anything downstream sees it; raw dicts never cross a module boundary.
7. **Logging:** decorator-based structured logging via the existing `logutil.log_call` (entry/exit/duration/exception), consistent with TECH.md — no logging statements mixed into business logic.
8. **Testing:** Red/Green TDD — tests written before the code they cover. `scripts/test` (pytest + ruff + mypy) is the ground truth and must stay green.
9. **Security non-negotiables** (MISSION.md): no cross-user leakage — two `chat_id`s never share a dossier, photo, or generated image; no hardcoded secrets.

## Acceptance criteria (from ROADMAP.md Phase 4)

- Photo + dossier are sent together to the image model in one call.
- The resulting image is delivered to the Telegram chat directly — no intermediate text hop.
- Failure to generate the image produces a logged, graceful user-facing message rather than a dead end.
- The bot automatically transitions from the final interview question to returning an animal hybrid portrait in the chat.
- `scripts/test` runs green (pytest + ruff + mypy).

## Verification

- **Negative test:** converter failure (stub raises or returns malformed) → logged error, friendly reply, phase advances to `SCRIPTING`, dossier survives, Scripter/Narrator still run.
- **Positive test:** photo + dossier → converter generates hybrid image → image delivered via Telegram `send_photo` → phase advances to `SCRIPTING` → dossier intact.
- **Contract tests:** `parse_output` accepts valid JSON, rejects free text, rejects schema violations, rejects empty image bytes.
- Both paths exercised with a stubbed Gemini client so `scripts/test` runs offline; a live opt-in check exists for real `gemini-3.1-flash-image` generation (details in `validation.md`).
- Two distinct `chat_id`s in the same process: perform a flow to CONVERTING in chat A, then assert chat B's session is still at the initial phase and has no record of A's image, phase, or dossier.