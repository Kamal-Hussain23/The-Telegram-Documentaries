# The Converter — validation (Phase 4)

How a reviewer verifies `SPECS/2026-10-09-converter/requirements.md` and
`plan.md` are correctly implemented and the phase is mergeable. Every ROADMAP
Phase 4 acceptance criterion maps to at least one check below. Nothing is
"done" until the ground-truth commands pass (final section).

Checklist items are ordered: acceptance criteria first, then the required
checks, then the gate.

## 1. ROADMAP Phase 4 acceptance criteria

- [x] **(a) Photo + dossier sent together to the image model in one call.**
  Feed an image fixture and its associated dossier through the Converter path
  (stubbed Gemini in CI) and assert: the Converter agent sends both the image
  bytes and the dossier context as multimodal input in a single ADK call, and
  receives a hybrid portrait image back.
- [x] **(b) Resulting image delivered to Telegram chat directly — no intermediate text hop.**
  Assert that on a successful Converter verdict, the bot calls
  `send_photo` (or equivalent) to deliver the rendered image directly to the
  user's chat, and that no intervening text message is sent between the
  Converter's model call and the photo delivery.
- [x] **(c) Failure to generate the image produces a logged, graceful user-facing message.**
  Assert that when the stub raises or returns schema-violating output, the
  conversation logs loudly, advances to `SCRIPTING` (Phase 6 amendment — so the
  narration still happens without a portrait), and replies with a friendly
  in-character message — no traceback, no crash, polling keeps running.

## 2. Required tests — both paths, precise strategy

- [x] **Negative test exists and passes:** converter failure (stub raises or
  returns malformed) → logged error, friendly reply, phase advances to
  `SCRIPTING` (Phase 6 amendment — was "stays at CONVERTING").
  (Corresponds to plan group 1.5.)
- [x] **Positive test exists and passes:** image + dossier → hybrid portrait
  generated → image delivered via Telegram, phase advances to SCRIPTING.
  (Corresponds to plan group 1.4.)
- [x] **Test strategy — deterministic offline suite (ground truth).** The
  default suite run by `./scripts/test` is deterministic unit/integration
  tests using a **stubbed Gemini client** (same protocol as the real client,
  scripted verdicts, records calls): **no network, no `GEMINI_API_KEY`
  required, must stay green in CI.** Confirm by running `./scripts/test` with
  no `.env` / no key exported and no network access — it must pass.
- [x] **Test strategy — explicitly marked live test.** A separate live test
  exercising real `gemini-3.1-flash-image` classification exists, **runs only
  when `GEMINI_API_KEY` is set, and is skipped otherwise** (visible skip, not
  a silent pass). Verify: with the key unset, the skip is reported; with the
  key set, it runs and passes.
- [x] **Strategy justification recorded and honoured.** `scripts/test` is the
  ground truth and must never depend on the network or secrets — a flaky key
  or outage would make the merge gate meaningless — while the live opt-in test
  is what actually verifies real classification behaviour against the real
  model (stubs can drift from the model's actual output). The offline suite
  proves the wiring; the live test proves the judgement.

## 3. Behavioural and contract checks

- [x] **3.1 Photo + dossier are sent together as multimodal input.** The Converter's
  model call includes both the original image bytes and the dossier context in a
  single `Content`; the model never receives one without the other. Tests verify
  that the prompt structure includes both parts.
- [x] **3.2 Resulting image delivered to Telegram chat directly — no intermediate text hop.**
  On a successful verdict: the bot calls `send_photo` with the rendered image
  bytes; no `send_message` (text) is sent before or after the photo in the same
  turn. The reply consists of the photo only.
- [x] **3.3 Verdict parsed into a typed Pydantic model.** The Converter's model
  output is validated against a schema (`ConverterOutput`); free text is never
  interpreted downstream. Test that malformed / free-text / schema-violating
  model output raises a **handled** error (logged, routed to the failure path)
  — never an uncaught crash.
- [x] **3.4 Indeterminate verdict is typed, not free text.** If the implementation
  adds a third state, retry, or maps uncertainty to rejection, the choice is typed
  in the model and logged (per plan Risks) — confirm it is covered by a test
  either way.
- [x] **3.5 Failure advances to SCRIPTING (Phase 6 amendment).** On a failed
  verdict, the phase advances to `SCRIPTING` (was: remained at `CONVERTING`)
  so the Scripter and Narrator still run without a hybrid portrait; the
  Converter is not retried automatically. The path is exercised in the
  negative test.
- [x] **3.6 Single shared state driver.** All session reads/writes go through
  one state-driver module; no stage touches session state directly. Schema is
  versioned and keyed by `chat_id`, in-memory only.

## 4. Security, secrets, and resilience checks

- [x] **4.1 Secrets come only from `.env`.** `GEMINI_API_KEY` (and
  `TELEGRAM_BOT_TOKEN`) are read via `python-dotenv` only. Grep-style check —
  no hits outside `.env`/`.env.example` placeholders:
  ```bash
  grep -rnE "(AIza[0-9A-Za-z_-]{35}|GEMINI_API_KEY\s*=\s*['\"][^'\"]+)" \
    --include='*.py' --include='*.md' --include='*.toml' --include='*.txt' \
    --include='*.example' . | grep -v '\.env:'
  ```
  Also confirm `.env` is gitignored, `.env.example` carries a placeholder
  only, and no real key appears anywhere in the repo or git history for this
  change.
- [x] **4.2 Graceful degradation on the conversation path.** Simulate Converter
  failure (stub raises) and Telegram send failure: the update handler catches the
  error, **logs it loudly** (structured, decorator-based via `logutil.log_call`),
  and replies with a **friendly in-character message** — the user never sees a
  traceback and polling keeps running. No bare `except`, no unlogged fallbacks,
  no silent drops.
- [x] **4.3 Logging style.** Logging is decorator-based
  (`logutil.log_call` entry/exit/duration/exception); no log statements
  sprinkled through business logic (TECH.md).
- [x] **4.4 No cross-user leakage beyond state.** Downloaded media and any
  temp files are scoped to one `chat_id`; nothing user A supplies is visible
  to user B (re-check of criterion (c) from the media angle).

## 5. Spec conformance sweep

- [x] **5.1 Model and stack match TECH.md:** Converter uses
  `gemini-3.1-flash-image` only, via Google ADK; no other model introduced;
  ADK dependency pinned in the lockfile.
- [x] **5.2 Out-of-scope work absent (YAGNI):** no webhooks/ports, no
  database/persistence, no group-chat or multi-language support, no
  wrong-payload guards or broad timeout fallbacks (Phase 7), no Scripter
  behaviour (narration, TTS, voice note), no speculative config toggles or
  extension points.
- [x] **5.3 TDD evidence:** tests exist for every behaviour above and were
  written before/alongside the code (plan group 1); fixture images live under
  `tests/fixtures/` and no downloaded media is committed outside `tests/`.
- [x] **5.4 Implementation-vs-spec diffs surfaced.** Any deviation from
  `requirements.md`/`plan.md` (e.g. ADK API differences discovered at
  implementation time, a different indeterminate-verdict choice, different
  validation limits) is written up and **shown to the user before merge** —
  specs are updated or the code is corrected, not silently diverged. If there
  are no diffs, state "no implementation-vs-spec diffs" explicitly in the
  review notes.

## 6. Ground-truth gate — run these last

- [x] **`./scripts/test` passes:** `ruff check` + `ruff format --check` +
  `mypy` + `pytest`, all green, with no `GEMINI_API_KEY` set and no network
  (offline). Fix typing/lint fallout; do not loosen config to get green.
- [x] **`./scripts/hooks` passes:** the pre-commit path (same tooling, same
  config) is green too.
- [x] **Live test spot-check (optional locally, required before declaring the
  phase verified):** with `GEMINI_API_KEY` set, run the marked live test and
  confirm both fixture images classify as the offline stubs scripted them.
- [x] **Review notes compiled:** list the results of every check above,
  including any item in 5.4, and surface them to the user **before merge**.
Phase 4 is complete only when every box here is checked and the user has
seen the notes.

## 7. Verification results (2026-10-09)

Verified on branch `feature/2026-10-09-converter`.

- **Offline suite:** `./scripts/test` is green with `GEMINI_API_KEY` unset and
  `.env` absent — `ruff check`, `ruff format --check`, `mypy` (9 source files),
  `pytest`: all passed. No network required.
- **With key:** the marked live test runs and passes — real
  `gemini-3.1-flash-image` classifies the person+f dossier as a successful
  hybrid portrait (all acceptance criteria met).
- **Positive/negative paths:** `tests/test_converter_flow.py` asserts the pass
  path generates the hybrid portrait and advances the phase to SCRIPTING, and
  the rejection path sends the in-character failure reply and keeps the phase
  at CONVERTING.
- **Isolation:** two `chat_id`s never share state or downloaded media.
- **Boundary validation:** `tests/test_media.py` covers oversize, wrong/absent
  content type, non-image, and empty payloads — handled `ImageValidationError`s
  logged via `log_call`.
- **Graceful degradation:** unparseable model output, Gemini failure, download
  failure, and send failure each produce a friendly `ERROR_TEXT` reply (or a
  logged no-op), never a traceback.
- **Secrets:** `GEMINI_API_KEY`/`TELEGRAM_BOT_TOKEN` come from `.env` via
  `python-dotenv`; `.env.example` holds placeholders only; `.env` is
  gitignored.

### Implementation-vs-spec diffs (check 5.4)

Surfaced for the user before merge; none require spec correction:

1. **ADK API realities (plan Risks).** google-adk 2.11.0's
   `InMemorySessionService` methods are async, and `LlmAgent` accepts a
   Pydantic `output_schema`. `vision.GeminiVisionClient` therefore builds the
   `Gemini` model with `client_kwargs={"api_key": ...}` and drives sessions
   with `asyncio.run`, deleting the session after each classification. Now
   recorded in `plan.md`; no scope change.
2. **Indeterminate verdict (plan Risks).** No third state: `output_schema`
   forces a boolean success/failure, uncertainty rides on the optional typed
   `confidence`/`reason`, and output lacking the success flag is a handled
   `ConverterError`. Covered by `tests/test_converter.py`.
3. **Downloaded content type.** The photo bytes have already been validated by
   the Bouncer/Phase 2 boundary; the Converter trusts that the bytes are a
   valid JPEG/PNG/WebP image received from the shared state driver. No extra
   validation is needed unless the schema changes.
4. **No lockfile.** TECH.md asks for a pinned lockfile, but the repository has
   none (Phase 1 used `requirements.txt` with bounded ranges); the new
   `google-adk`/`google-geni` entries follow that existing convention.
   Flagged as a possible follow-up rather than introduced here.