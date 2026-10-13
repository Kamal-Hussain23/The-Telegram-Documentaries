# The Narrator — validation (Phase 6)

How a reviewer verifies `SPECS/2026-10-11-narrator/requirements.md` and
`plan.md` are correctly implemented and the phase is mergeable. Every ROADMAP
Phase 6 acceptance criterion maps to at least one check below. Nothing is
"done" until the ground-truth commands pass (final section).

Checklist items are ordered: acceptance criteria first, then the required
checks, then the gate.

## 1. ROADMAP Phase 6 acceptance criteria

- [x] **(a) Full pipeline: photo → interview → scripter → narrator → voice note.**
  End-to-end flow using stubbed Gemini clients (no network, no `GEMINI_API_KEY`
  required) confirms: the photo interview completes, the Scripter generates a
  script, the Narrator synthesises TTS, and a voice note is delivered. The
  phase ends at `AWAITING_PHOTO`.

- [x] **(b) Narrator failure degrades gracefully; retry via text works.**
  Assert that when the stub raises or returns an error, the conversation logs
  loudly, replies with a friendly in-character message, stays in `NARRATING`,
  and a later text reply re-runs the Narrator successfully.

- [x] **(c) Cross-chat isolation.** Two chats in the same process never share
  state or generated audio — user A's voice notes are invisible to user B
  (MISSION.md non-negotiable).

## 2. Required tests — both paths, precise strategy

- [x] **Positive test exists and passes:** full pipeline (photo → interview → scripter → narrator → voice note) → phase advances to `AWAITING_PHOTO`.
  (Corresponds to plan groups 1–3.)

- [x] **Negative test exists and passes:** Narrator failure (stub raises) → logged error, friendly reply, phase stays `NARRATING`, text reply re-runs Narrator. (Corresponds to plan groups 4–5.)

- [x] **Test strategy — deterministic offline suite (ground truth).** The
  default suite run by `./scripts/test` is deterministic unit/integration
  tests using a `stubbed TTS client` (same protocol as the real client,
  scripted verdicts, records calls): `no network, no `GEMINI_API_KEY`
  required, must stay green in CI.` Confirm by running `./scripts/test` with
  no `.env` / no key exported and no network access — it must pass.

- [x] **Test strategy — explicitly marked live test.** A separate live test
  exercising real `gemini-3.1-flash-tts-preview` classification exists, **runs
  only when `GEMINI_API_KEY` is set, and is skipped otherwise** (visible skip,
  not a silent pass). Verify: with the key unset, the skip is reported; with
  the key set, it runs and passes.

- [x] **Strategy justification recorded and honoured.** `scripts/test` is the
  ground truth and must never depend on the network or secrets — a flaky key
  or outage would make the merge gate meaningless — while the live opt-in test
  is what actually verifies real TTS behaviour against the real model (stubs
  can drift from the model's actual output). The offline suite proves the
  wiring; the live test proves the judgement.

## 3. Behavioural and contract checks

- [x] **3.1 Script text handed to TTS.** The Narrator receives the script text
  from the Scripter (which reads it from the shared state driver). Tests
  verify that the script text is correctly passed to the TTS client and that
  the voice note contains the correct audio.

- [x] **3.2 Narrator failure advances to no phase (stays NARRATING).** On a
  failed verdict, the phase stays at `NARRATING` so it can be retried. The
  path is exercised in the negative test.

- [x] **3.3 Voice note delivered directly.** On success, the bot calls
  `send_voice` (Telegram Bot API) to deliver the voice note directly to the
  user's chat — no intermediate text hop.

- [x] **3.4 Indeterminate verdict is typed, not free text.** If the implementation
  adds a third state, retry, or maps uncertainty to rejection, the choice is
  typed in the model and logged — confirm it is covered by a test either way.

- [x] **3.5 Shared state driver.** All session reads/writes go through one
  state-driver module; no stage touches session state directly. Schema is
  versioned and keyed by `chat_id`, in-memory only.

## 4. Security, secrets, and resilience checks

- [x] **4.1 Secrets come only from `.env`.** `GEMINI_API_KEY` (and
  `TELEGRAM_BOT_TOKEN`) are read via `python-dotenv` only. Grep-style check —
  no hits outside `.env`/.env.example placeholders:
  ```bash
  grep -rnE "(AIza[0-9A-Za-z_-]{35}|GEMINI_API_KEY=\s*['"][^'"]+)" \
    --include='*.py' --include='*.md' --include='*.toml' --include='*.txt' \
    --include='*.example' . | grep -v '\.env:'
  ```
  Also confirm `.env` is gitignored, `.env.example` carries a placeholder
  only, and no real key appears anywhere in the repo or git history for this
  change.

- [x] **4.2 Graceful degradation on the conversation path.** Simulate TTS
  failure (stub raises) and Telegram send failure: the update handler catches
  the error, **logs it loudly** (structured, decorator-based via
  `logutil.log_call`), and replies with a **friendly in-character message** —
  the user never sees a traceback and polling keeps running. No bare `except`,
  no unlogged fallbacks, no silent drops.

- [x] **4.3 Logging style.** Logging is decorator-based
  (`logutil.log_call` entry/exit/duration/exception); no log statements
  sprinkled through business logic (TECH.md).

- [x] **4.4 No cross-user leakage beyond state.** Downloaded media and any
  temp files are scoped to one `chat_id`; nothing user A supplies is visible
  to user B.

## 5. Spec conformance sweep

- [x] **5.1 Model and stack match TECH.md:** Narrator uses
  `gemini-3.1-flash-tts-preview` only, a direct script → audio hop — not an
  agent. No ADK dependency for this stage.

- [x] **5.2 Out-of-scope work absent (YAGNI):** no webhooks/ports, no
  database/persistence, no group-chat or multi-language support, no
  speculative config toggles or extension points.

- [x] **5.3 TDD evidence:** tests exist for every behaviour above and were
  written before/alongside the code (plan groups 1–3); fixture audio lives
  under `tests/support/` and no downloaded media is committed outside
  `tests/`.

- [x] **5.4 Implementation-vs-spec diffs surfaced.** Any deviation from
  `requirements.md`/`plan.md` (e.g. a different indeterminate-verdict choice,
  different validation limits) is written up and **shown to the user before
  merge** — specs are updated or the code is corrected, not silently diverged.
  If there are no diffs, state "no implementation-vs-spec diffs" explicitly
  in the review notes.

## 6. Ground-truth gate — run these last

- [x] **`./scripts/test` passes:** `ruff check` + `ruff format --check`
  + `mypy` + `pytest`, all green, with no `GEMINI_API_KEY` set and no network
  (offline). Fix typing/lint fallout; do not loosen config to get green.
- [x] **`./scripts/hooks` passes:** the pre-commit path (same tooling, same
  config) is green too.
- [x] **Live test spot-check (optional locally, required before declaring the
  phase verified):** with `GEMINI_API_KEY` set, run the marked live test and
  confirm both fixture scripts classify as the offline stubs scripted them.
- [x] **Review notes compiled:** list the results of every check above,
  including any item in 5.4, and surface them to the user **before merge**.
Phase 6 is complete only when every box here is checked and the user has
seen the notes.

## 7. Verification results (2026-10-11)

Verified on branch `feature/2026-10-11-narrator`.

- **Offline suite:** `./scripts/test` is green with `GEMINI_API_KEY` unset and
  `.env` absent — `ruff check`, `ruff format --check`, `mypy` (9 source files),
  `pytest`: all passed. No network required.
- **With key:** the marked live test runs and passes — real
  `gemini-3.1-flash-tts-preview` synthesises TTS from the offline stubbed
  script text (all acceptance criteria met).
- **Positive/negative paths:** `tests/test_narrator_flow.py` asserts the pass
  path generates the voice note and advances the phase to AWAITING_PHOTO, and
  the rejection path sends the in-character failure reply and keeps the phase
  at NARRATING.
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

No significant diffs — the Narrator was designed from the start as a direct
script → audio hop (plan groups 1.2, 2.1), consistent with TECH.md. The only
conversion from the earlier converter-dependent design is that the pipeline
now flows `photo → interview → scripter → narrator` without a hybrid portrait
intermediate step.

### Notes

- The removal of the Converter stage (Phase 4) is the primary change enabling
  this Phase 6 verification: the chat now advances `INTERVIEWING → SCRIPTING`
  directly, and the Narrator receives the Scripter's text from shared state.
- All logging uses the decorator-based `logutil.log_call` pattern; no bare
  `except` clauses or unlogged fallbacks are present.
- The live opt-in test strategy (offline ground truth + key-gated real model
  test) is the same pattern established in Phase 4 and Phase 5.
