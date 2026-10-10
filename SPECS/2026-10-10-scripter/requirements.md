# The Scripter — requirements (Phase 5)

Feature spec for ROADMAP.md Phase 5: *"One paragraph of narration built from the
dossier."* It defers to `SPECS/MISSION.md`, `SPECS/TECH.md`, and `SPECS/ROADMAP.md`
for anything not stated here.

## Context

Phase 4 (the Converter) has completed the hybrid portrait and advanced the state
machine to `SCRIPTING`. The session now holds:

- The original photo bytes (unchanged)
- The completed dossier: profile (behavioural summary), suggested_animal, and
  the accumulated Q&A
- The hybrid portrait reference (stored in the dossier by the Converter)

The Scripter is the **first stage since the Interviewer to use
`gemini-3.1-flash-lite`** (the Converter used `gemini-3.1-flash-image`). Its
job: read the dossier and produce exactly one paragraph of narration — ready
for the Narrator (Phase 6) to send straight to Gemini TTS.

## User-approved intent

On a chat in `SCRIPTING` phase:

1. Retrieve the **completed dossier** (profile, suggested_animal, questions,
   answers) from session state, scoped to `chat_id`.
2. Send the dossier context to **`gemini-3.1-flash-lite`** through Google ADK,
   with a structured output schema (`ScripterOutput`).
3. The model adopts the persona of **Brian Cox (physicist)** — wonder-struck,
   cosmic-scale narrator who frames the subject's quirks, bedtime habits, and
   snacking patterns as funny animal behaviours, making it sound like a nature
   documentary about humans. The tone is: "In the vast kitchen of the universe,
   the subject prepares a midnight toast..." — poetic, intellectual, finding
   cosmic wonder in mundane human rituals.
4. **Output contract:** exactly **one paragraph**, **max 90 words**, **no
   markdown formatting**, plain text ready for voice synthesis.
5. Parse the model's structured output into the typed `ScripterOutput` model.
   Free text is never interpreted downstream; anything that fails the schema is
   a handled `ScripterError`.
6. **Send the script text directly to the user's Telegram chat** as a message
   (this is the Scripter's output action — the Narrator will separately pick it
   up for TTS).
7. On success, advance the state machine to `NARRATING` (a new phase), preserving
   the script text for the Narrator stage.
8. On failure (validation error, timeout, unstructured output): log loudly,
   reply with a friendly in-character message, and **stay in `SCRIPTING`** so
   it can be retried.
9. Add the ADK wiring following the same patterns as `interview_client.py`
   (Bouncer/Interviewer) — an `LlmAgent` with `output_schema`, async session
   service driven by `asyncio.run`, `GEMINI_API_KEY` via `client_kwargs`.

## Scope

### In scope

- **Dossier retrieval**: read the completed dossier (profile, suggested_animal,
  questions/answers) from session state, scoped to `chat_id` only.
- **The Scripter agent** (ADK `LlmAgent` on `gemini-3.1-flash-lite`):
  - Accepts the dossier context as text input.
  - Uses a **structured output schema** (`ScripterOutput`) with at least a
    `script` field (the narration paragraph).
  - The instruction directs the model to adopt the Brian Cox physicist persona,
    framing human quirks as cosmic animal behaviours, in one paragraph ≤ 90
    words, no markdown.
  - Returns the model's raw structured output for edge parsing.
- **Telegram dispatch**: use the existing `TelegramClient.send_message` to
  deliver the script text directly to the user's chat.
- **State advancement**: on successful script generation, advance the phase
  from `SCRIPTING` to `NARRATING`, persisting the script text in the dossier
  for the Narrator stage.
- **Graceful degradation**: if the model fails (validation error, timeout,
  unstructured output), log loudly, do NOT crash, and reply with a friendly
  in-character message. The conversation stays in `SCRIPTING` so it can be
  retried.
- **ADK dependency**: already installed (`google-adk`, `google-genai` pinned).
  `GEMINI_API_KEY` read from `.env` via `python-dotenv` only.
- **Tests**: Red/Green TDD — tests written before the code they cover. Fixture
  data under `tests/fixtures/` if needed. The default suite stays green offline
  (stubbed Gemini client); a live opt-in check exists for real
  `gemini-3.1-flash-lite` script generation.

### Out of scope (YAGNI)

- Webhooks / public URLs (long polling only).
- Database or any persistence — state lives in process memory; a restart
  wiping sessions is acceptable.
- Group-chat usage (1:1 DMs only) and multi-language support (English only).
- Wrong-payload guards and broader API-timeout fallbacks — those are Phase 7
  (Resilience), not Phase 5.
- The Narrator itself (Phase 6): TTS synthesis and audio delivery. The
  Scripter only produces and sends the text script; the Narrator reads it from
  the session.
- Config toggles, extension points, or speculative abstractions no current
  requirement demands.

## Decisions

These are fixed for this feature; deviation requires updating the specs in
`SPECS/`.

1. **Model:** `gemini-3.1-flash-lite` for the Scripter, per the TECH.md stack
   table. No other model is introduced in this phase.
2. **Persona:** Brian Cox (physicist) — wonder-struck, cosmic scale, poetic
   intellectual amusement. Finding the universe in a midnight snack.
3. **Typed contract, never free text.** The model answers through a Pydantic
   schema:
   - `ScripterOutput { script: str }` — the single narration paragraph.
     Anything that fails this schema is a **handled error** (`ScripterError`),
     logged loudly, never interpreted downstream.
4. **Output constraints (code-enforced, not just prompted):**
   - Exactly one paragraph (no double newlines).
   - Maximum 90 words (split on whitespace).
   - No markdown formatting (no `*`, `_`, `#`, ```, etc.).
   - These are validated in `parse_output` after the model returns; violations
     raise `ScripterError`.
5. **Session state:** versioned schema, keyed by `chat_id`, in-memory only,
   behind the one shared `StateDriver`. All reads/writes go through the driver
   — no stage touches state directly. Schema version bumps to **3** to add the
   `NARRATING` phase and the `script` field on `Dossier`.
6. **Telegram dispatch:** deliver the script via `send_message` (Telegram Bot
   API). This is the Scripter's output action — the user sees the text before
   the voice note arrives.
7. **Phase advancement:** on success, advance from `SCRIPTING → NARRATING`. On
   failure, stay in `SCRIPTING` so it can be retried; never advance on a bad
   verdict.
8. **Untrusted input at the boundary:** Telegram / Gemini payloads are treated
   as arbitrary. Model output is validated against the schema before anything
   downstream sees it; raw dicts never cross a module boundary.
9. **Logging:** decorator-based structured logging via the existing
   `logutil.log_call` (entry/exit/duration/exception), consistent with
   TECH.md — no logging statements mixed into business logic.
10. **Testing:** Red/Green TDD — tests written before the code they cover.
    `scripts/test` (pytest + ruff + mypy) is the ground truth and must stay
    green.
11. **Security non-negotiables** (MISSION.md): no cross-user leakage — two
    `chat_id`s never share a dossier, script, or photo; no hardcoded secrets.

## Acceptance criteria (from ROADMAP.md Phase 5)

- Output is a single paragraph, roughly 60–90 words.
- Tone is dramatic British wildlife documentary (Brian Cox physicist persona),
  drawing on the dossier.
- Output is parsed against a schema; malformed model output is a handled error.
- The script is sent to the user's Telegram chat as a text message.
- `scripts/test` runs green (pytest + ruff + mypy).

## Verification

- **Negative test:** scripter failure (stub raises or returns malformed) →
  logged error, friendly reply, phase stays at SCRIPTING.
- **Positive test:** dossier → verdict says script generated → script delivered
  via Telegram, phase advances to NARRATING, script persisted in session.
- **Contract tests:** parse_output accepts valid JSON, rejects free text, rejects
  schema violations, rejects multi-paragraph output, rejects >90 words, rejects
  markdown.
- Both paths exercised with a stubbed Gemini client so `scripts/test` runs
  offline; a live opt-in check exists for real `gemini-3.1-flash-lite` script
  generation (details in `validation.md`).
- Two distinct `chat_id`s in the same process: perform a flow to SCRIPTING in
  chat A, then assert chat B's session is still at the initial phase and has no
  record of A's script, phase, or dossier.

(End of file - total 165 lines)