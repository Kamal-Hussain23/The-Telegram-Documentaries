# The Bouncer — implementation plan (Phase 2)

Task groups for `SPECS/2026-10-06-bouncer/requirements.md`. Red/Green TDD: group 1
is written first and must fail; groups 2–5 make it pass; group 6 is the gate.
Plan only — no application code lives in this file.

Ground truth throughout: run the dev scripts from the README — `scripts/test`
(pytest + `ruff format --check` + `ruff check` + mypy) and `scripts/hooks`
(same tooling, pre-commit). A group is done only when those are green.

## 1. Test scaffolding first (Red)

- 1.1 Fixture images under `tests/fixtures/`: a positive image containing a
  person and a negative image (object/landscape). Commit the smallest files
  that exercise both paths; no downloaded media ever lands outside `tests/`.
- 1.2 A fake/stub Gemini vision client implementing the same protocol the real
  Bouncer client will implement — scripted verdicts, records calls, never
  touches the network. The default suite stays fully offline.
- 1.3 Verdict-contract tests: the structured verdict parses into the typed
  Pydantic model; malformed / free-text model output is a handled error, never
  interpreted downstream.
- 1.4 Negative flow test: negative image → in-character rejection reply sent
  (text says the submission must contain a human) **and** session state reset
  to the initial phase, without a process restart.
- 1.5 Positive flow test: positive image → no rejection, reply unchanged from
  Phase 1 behaviour, state machine advances to the next phase.
- 1.6 `chat_id` keying / isolation tests: two chats never see each other's
  state or downloads — no cross-user leakage (MISSION.md non-negotiable).
- 1.7 Boundary-validation tests for downloaded bytes: oversize, wrong/absent
  content type, and non-image payloads are rejected before anything downstream
  sees them.

## 2. Photo intake

- 2.1 Extend `telegram_documentaries/models.py`: `PhotoSize` (or equivalent)
  and a `photo` field on `Message`, carrying `file_id` for the
  highest-resolution variant; parse at the edge, keep `extra="ignore"`.
- 2.2 Download support in `telegram_documentaries/client.py`: `getFile` →
  file bytes, exposed behind a client Protocol (injectable, like the existing
  `HttpSession`) so tests run offline.
- 2.3 Validate size and type of the downloaded bytes at the boundary before
  use; failures are handled errors with loud logs, not silent drops.

## 3. Session state

- 3.1 One shared state driver module (load / save / reset) — the only code
  that touches session state; stages go through it, never directly (TECH.md).
- 3.2 Versioned schema keyed by `chat_id`, in-memory only; a schema change
  invalidates stale sessions cleanly via the version field.
- 3.3 Initial phase constant and phase advancement on the pass path.
- 3.4 Reset-on-rejection semantics: a negative verdict returns the chat's
  session to the initial phase in-process — no restart, no persistence.

## 4. The Bouncer agent

- 4.1 Google ADK agent wrapping `gemini-3.1-flash-lite` as multimodal
  classification: image bytes in, structured verdict out.
- 4.2 Parse the model response into a typed Pydantic verdict model (boolean
  human-present plus supporting fields); anything that fails the schema is a
  handled error. See risks for the indeterminate case.
- 4.3 Decorator-based logging via the existing `logutil.log_call`
  (entry/exit/duration/exception) — no log statements mixed into business
  logic (TECH.md, requirements decision 6).
- 4.4 Negative verdict → humorous, cheeky, in-character rejection copy stating
  the submission must contain a human; state reset (group 3).
- 4.5 Positive verdict → pass path only: advance the phase, reply behaviour
  unchanged from Phase 1. No Interviewer questions, no dossier (YAGNI).

## 5. ADK wiring

- 5.1 Install the ADK dependency (pinned, per TECH.md lockfile hygiene) and
  `GEMINI_API_KEY` read from `.env` via `python-dotenv` only — never in
  source, tests, docs, or `.env.example`.
- 5.2 Wire the Bouncer into `bot.py` update routing for the photo phase:
  photo payload → download → classify → pass/reject branch.
- 5.3 Error handling on the conversation path: catch, log loudly, degrade
  gracefully with a friendly message — the user never sees a traceback, and
  polling keeps running. No bare `except`, no unlogged fallbacks.

## 6. Green

- 6.1 Run `scripts/test` (pytest + `ruff format --check` + `ruff check` +
  mypy) until green; fix typing/lint fallout rather than loosening config.
- 6.2 Also run `scripts/hooks` (same tooling) to confirm the pre-commit path.
- 6.3 Live opt-in test: a real Gemini call against `gemini-3.1-flash-lite`,
  enabled only when `GEMINI_API_KEY` is present — the default suite stays
  green offline (final wording of the strategy belongs in `validation.md`).
- 6.4 Verify acceptance criteria from ROADMAP.md Phase 2: portrait passes and
  advances; non-human image gets the in-character rejection and resets; state
  keyed by `chat_id` with no leakage; `scripts/test` green.

## Risks / notes

- **ADK API specifics — verified against google-adk 2.11.0.** `LlmAgent`
  accepts a Pydantic model as `output_schema`, and its model can be built with
  `client_kwargs={"api_key": ...}` (the model caches its client per event loop
  via `PerLoopCachedProperty`). `InMemorySessionService`'s create/delete/get
  calls are **async**, so the synchronous `GeminiVisionClient.classify` drives
  them with `asyncio.run` and deletes the session after each classification.
  No adaptation to the group 4/5 scope was needed.
- **Telegram file download limits.** `getFile` size caps and download timeouts
  apply; validation limits (group 1.7/2.3) must be chosen with the real API in
  mind and treated as untrusted input.
- **Borderline images — resolved.** No third state (YAGNI): `output_schema`
  forces the model to commit to a boolean, uncertainty is carried by the
  optional typed `confidence`/`reason` fields, and output that omits the
  boolean fails the schema as a handled `VerdictError`. Covered by
  `tests/test_bouncer.py`.
- **Fixture images are model-dependent.** Positive/negative fixtures should be
  unambiguous so offline stubs and the live opt-in test agree.
- **Ground truth:** the dev scripts referenced in the README — `scripts/test`
  and `scripts/hooks` — decide when this phase is done.
