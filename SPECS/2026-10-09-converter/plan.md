# The Converter — implementation plan (Phase 4)

Task groups for `SPECS/2026-10-09-converter/requirements.md`. Red/Green TDD: group 1
is written first and must fail; groups 2–5 make it pass; group 6 is the gate.
Plan only — no application code lives in this file.

Ground truth throughout: run the dev scripts from the README — `scripts/test`
(pytest + `ruff format --check` + `ruff check` + mypy) and `scripts/hooks`
(same tooling, pre-commit). A group is done only when those are green.

## 1. Test scaffolding first (Red)

- 1.1 Fixture images under `tests/fixtures/`: already present (`person.jpg`, `landscape.jpg`).
  No downloaded media ever lands outside `tests/`.
- 1.2 A fake/stub Gemini image client implementing the same protocol the real
  Converter client will implement — scripted verdicts, records calls, never
  touches the network. The default suite stays fully offline.
- 1.3 Verdict-contract tests: the structured verdict parses into the typed
  Pydantic model; malformed / free-text model output is a handled error, never
  interpreted downstream.
- 1.4 Converter flow test: image + dossier → hybrid portrait generated →
  delivered via Telegram, phase advances to SCRIPTING.
- 1.5 Converter failure test: stub raises or returns schema-violating output →
  friendly in-character reply, phase stays at CONVERTING.
- 1.6 `chat_id` keying / isolation tests: two chats never see each other's state
  or downloads — no cross-user leakage (MISSION.md non-negotiable).
- 1.7 Boundary-validation tests for downloaded bytes: oversize, wrong/absent
  content type, and non-image payloads are rejected before anything downstream
  sees them (inherited from Bouncer/Phase 2, but the Converter must also
  validate its inputs).

## 2. Photo + dossier retrieval

- 2.1 Extend `telegram_documentaries/state.py`: the `SessionState` already carries
  `photo: bytes` and `dossier: Dossier`; ensure they are persisted together
  when the phase transitions from `CONVERTING` to `SCRIPTING`.
- 2.2 Converter retrieval helper: a small function or method that, given a
  `chat_id`, returns `(image_bytes, dossier_context)` from the shared state
  driver. The dossier context format follows `interviewer.dossier_context()`.
- 2.3 Validate retrieved bytes at the boundary (size, type, shape) before the
  model sees them; failures are handled errors with loud logs, not silent drops.

## 3. The Converter agent

- 3.1 Google ADK agent wrapping `gemini-3.1-flash-image` as multimodal fusion:
  image bytes + dossier context in, hybrid portrait out.
- 3.2 Parse the model response into a typed Pydantic verdict model (`ConverterOutput`);
  anything that fails the schema is a handled error. See risks for the
  indeterminate case.
- 3.3 Decorator-based logging via the existing `logutil.log_call`
  (entry/exit/duration/exception) — no log statements mixed into business
  logic (TECH.md, requirements decision 6).
- 3.4 On a successful verdict: advance the phase from `CONVERTING` to
  `SCRIPTING` via the shared `StateDriver`, persist the hybrid image reference.
- 3.5 On a failed verdict: stay in `CONVERTING`, log loudly, reply with a
  friendly in-character message. No process restart, no persistence.

## 4. Telegram dispatch

- 4.1 Use the existing `TelegramClient` (or an equivalent method) to deliver the
  rendered image directly to the user's chat via `send_photo`.
- 4.2 On success, the bot replies with the image and the conversation moves to
  the Scripter stage (SCRIPTING). No extra text reply is needed beyond the
  image itself.

## 5. ADK wiring

- 5.1 Install the ADK dependency (pinned, per TECH.md lockfile hygiene) and
  `GEMINI_API_KEY` read from `.env` via `python-dotenv` only — never in
  source, tests, docs, or `.env.example`.
- 5.2 Wire the Converter into `bot.py` update routing for the converting phase:
  when `phase is CONVERTING`, invoke the Converter agent, deliver the image,
  and advance the phase.
- 5.3 Error handling on the conversation path: catch, log loudly, degrade
  gracefully with a friendly message — the user never sees a traceback and
  polling keeps running. No bare `except`, no unlogged fallbacks.

## 6. Green

- 6.1 Run `scripts/test` (pytest + `ruff format --check` + `ruff check` +
  mypy) until green; fix typing/lint fallout rather than loosening config.
- 6.2 Also run `scripts/hooks` (same tooling) to confirm the pre-commit path.
- 6.3 Live opt-in test: a real Gemini call against `gemini-3.1-flash-image`,
  enabled only when `GEMINI_API_KEY` is present — the default suite stays
  green offline; final wording of the strategy belongs in `validation.md`.
- 6.4 Verify acceptance criteria from ROADMAP.md Phase 4: photo + dossier →
  hybrid portrait delivered; failure → graceful degradation.

## Risks / notes

- **ADK API specifics — verified against google-adk 2.11.0.** `LlmAgent`
  accepts a Pydantic model as `output_schema`, and its model can be built with
  `client_kwargs={"api_key": ...}` (the model caches its client per event loop
  via `PerLoopCachedProperty`). `InMemorySessionService`'s create/delete/get
  calls are **async**, so the synchronous `ConverterClient.classify` drives them
  with `asyncio.run` and deletes the session after each classification.
- **Multimodal input shape.** The Gemini `Gemini` model and `types.Part` API for
  `gemini-3.1-flash-image` accepts both image parts and text parts in a single
  `Content`. We must structure the prompt so the image arrives first (or as a
  separate part) and the dossier context is included as text.
- **Indeterminate verdict (plan Risks).** No third state: `output_schema`
  forces a success/failure, uncertainty rides on the optional typed
  `confidence`/`reason`, and output lacking the success flag is a handled
  `ConverterError`. Covered by `tests/test_converter.py`.
- **Downloaded content type.** The photo bytes have already been validated by
  the Bouncer/Phase 2 boundary; the Converter trusts that the bytes are a
  valid JPEG/PNG/WebP image received from the shared state driver. No extra
  validation is needed unless the schema changes.
- **Fixture images are model-dependent.** Positive/negative fixtures should be
  unambiguous so offline stubs and the live opt-in test agree.
- **Ground truth:** the dev scripts referenced in the README — `scripts/test`
  and `scripts/hooks` — decide when this phase is done.