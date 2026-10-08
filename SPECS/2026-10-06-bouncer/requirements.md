# The Bouncer — requirements (Phase 2)

Feature spec for ROADMAP.md Phase 2: *"Vision gate on incoming photos, with
rejection and reset routing."* It defers to `SPECS/MISSION.md`,
`SPECS/TECH.md`, and `SPECS/ROADMAP.md` for anything not stated here.

## Context

Phase 1 left the repository in a deliberately minimal state:

- `bot.py` long-polls Telegram and replies with the hardcoded `"hey mate!"` to
  every inbound message — no routing, no state, no Gemini.
- `models.py` `Message` has no photo field; photo payloads are summarised only
  as `media` by `logutil.describe_message`.
- There is no session state, no Gemini client, no ADK installed
  (`requirements.txt` carries pydantic, python-dotenv, requests only).
- `scripts/test` (pytest + ruff + mypy) is green; that greenness is the
  ground truth for this phase too.

This is the project's **first Google ADK agent**. The Bouncer is the first
pipeline stage to talk to Gemini, the first to depend on session state, and
therefore the phase that establishes the ADK wiring, the state driver, and the
model-output contract that the later stages (Interviewer, Converter, Scripter)
will reuse.

## User-approved intent

On a photo upload:

1. Download the image bytes from Telegram.
2. Send the bytes to `gemini-3.1-flash-lite` as **multimodal input**.
3. Classify whether a **discernible human face or body** is present.
4. **No human present** → reset the ephemeral conversation state to the
   initial phase, and reply with a humorous, cheeky, in-character rejection
   telling the user their submission must contain a human.
5. **Human present** → continue the confirmation flow unchanged. The pass path
   invents nothing new: no new reply, no Interviewer questions, no dossier —
   the Interviewer is explicitly out of scope for this phase.
6. Add the **ADK wiring** needed to hook the agent into the pipeline.
7. Verify with a **negative test** (object/landscape) and a **positive test**
   (person).

## Scope

### In scope

- Telegram photo intake: parse the photo out of the inbound `Update`
  (`models.Message` gains a photo field), download the highest-resolution
  image bytes via the Telegram Bot API, validate them at the boundary.
- The Bouncer agent (ADK) calling `gemini-3.1-flash-lite` with the image as
  multimodal input and returning a **structured verdict** parsed into a typed
  Pydantic model — human present or not — never free text.
- Session state: the ephemeral, in-memory, versioned state keyed by `chat_id`,
  behind **one shared state driver**; the reset-to-initial-phase path for a
  rejected photo.
- The rejection reply (humorous, in-character, states the submission must
  contain a human) and the pass path that simply advances the state machine.
- ADK dependency install + the wiring that makes the agent reachable from the
  update-handling pipeline.
- Tests: the positive and negative classification tests, plus coverage of
  validation, verdict parsing, state reset, and routing.

### Out of scope (YAGNI)

Everything below is explicitly **not** built, configured, or left room for:

- Webhooks / public URLs (long polling only, never expose a port).
- Database or any persistence — state lives in process memory; a restart
  wiping sessions is acceptable.
- Group-chat usage (1:1 DMs only) and multi-language support (English only).
- Wrong-payload guards and broader API-timeout fallbacks — those are Phase 7
  (Resilience), not Phase 2.
- All Interviewer work: questions, dossier, animal suggestion, orchestration
  hand-off logic beyond simply advancing the phase.
- Config toggles, extension points, or speculative abstractions no current
  requirement demands.

## Decisions

These are fixed for this feature; deviation requires updating the specs in
`SPECS/`.

1. **Model:** `gemini-3.1-flash-lite` for the Bouncer, per the TECH.md stack
   table. No other model is introduced in this phase.
2. **Secrets:** `GEMINI_API_KEY` is read from `.env` only (via
   `python-dotenv`), alongside `TELEGRAM_BOT_TOKEN`. It never appears in
   source, tests, docs, or `.env.example`.
3. **Session state:** in-memory, **versioned schema**, keyed by `chat_id`. All
   reads and writes go through **one shared state driver**; stages never touch
   state directly. The version field lets a schema change invalidate old
   in-memory sessions cleanly.
4. **Verdict is a typed contract:** the Bouncer's answer is parsed from the
   model response into a typed Pydantic model (a boolean human-present verdict
   plus any supporting fields the schema needs). Free-text Gemini output is
   never interpreted downstream; anything that fails to fit the schema is a
   handled error.
5. **Untrusted input at the boundary:** downloaded image bytes and Telegram /
   Gemini payloads are treated as arbitrary. Size, type, and shape are
   validated at the edge before anything downstream sees them; raw dicts never
   cross a module boundary.
6. **Logging:** decorator-based structured logging via the existing
   `logutil.log_call` (entry/exit/duration/exception), consistent with
   TECH.md — no logging statements mixed into business logic.
7. **Testing:** Red/Green TDD — tests written before the code they cover.
   `scripts/test` (pytest + ruff + mypy) is the ground truth and must stay
   green.
8. **Test strategy:** the default suite must stay green **offline** — the
   Gemini client is stubbed for CI, and the live-call test is opt-in,
   enabled only when `GEMINI_API_KEY` is present. The final wording of that
   strategy belongs in `validation.md`; this spec records only the intent.
9. **Security non-negotiables** (from MISSION.md): no cross-user leakage —
   state and downloaded media are scoped strictly to one `chat_id`; no
   hardcoded secrets anywhere.

## Acceptance criteria (from ROADMAP.md Phase 2)

- A portrait with a human passes and advances the state machine.
- A non-human / unusable image gets an in-character rejection and resets the
  session to the initial phase.
- Photo-stage state is keyed by `chat_id`; no cross-user leakage.
- `scripts/test` runs green (pytest + ruff + mypy).

## Verification

- **Negative test:** an object/landscape image → verdict says no human →
  rejection reply sent, session reset to the initial phase.
- **Positive test:** an image with a person → verdict says human present →
  flow continues unchanged, state advanced, no rejection sent.
- Both paths exercised with a stubbed Gemini client so `scripts/test` runs
  offline; a live opt-in check exists for real `gemini-3.1-flash-lite`
  classification (details in `validation.md`).
