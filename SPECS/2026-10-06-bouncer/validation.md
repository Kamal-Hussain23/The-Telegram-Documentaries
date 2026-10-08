# The Bouncer — validation (Phase 2)

How a reviewer verifies `SPECS/2026-10-06-bouncer/requirements.md` and
`plan.md` are correctly implemented and the phase is mergeable. Every ROADMAP
Phase 2 acceptance criterion maps to at least one check below. Nothing is
"done" until the ground-truth commands pass (final section).

Checklist items are ordered: acceptance criteria first, then the required
checks, then the gate.

## 1. ROADMAP Phase 2 acceptance criteria

- [x] **(a) Portrait passes and advances.** Feed an image fixture containing a
  person through the photo path (stubbed Gemini in CI) and assert: verdict =
  human present, **no** rejection reply sent, session phase advanced from the
  initial phase to the next phase, reply otherwise unchanged from Phase 1
  (`"hey mate!"` behaviour — see check 3.2).
- [x] **(b) Non-human gets a cheeky rejection AND resets.** Feed an
  object/landscape image fixture and assert **all** of: (i) an in-character,
  humorous rejection reply is sent, (ii) the reply states the submission must
  contain a human, (iii) the session for that `chat_id` is back at the
  **initial phase**, (iv) the process did not restart — the reset happens
  in-process via the state driver.
- [x] **(c) State keyed by `chat_id`, no cross-user leakage.** With two
  distinct `chat_id`s in the same process: perform a photo flow in chat A,
  then assert chat B's session is still at the initial phase and has no
  record of A's verdict, phase, or downloaded media; a rejection in A does not
  touch B's state. Also assert two chats never see each other's downloads.

## 2. Required tests — both paths, precise strategy

- [x] **Negative test exists and passes:** object/landscape image → verdict
  "no human" → in-character rejection reply sent **and** session reset to the
  initial phase. (Corresponds to plan group 1.4.)
- [x] **Positive test exists and passes:** person image → verdict "human
  present" → no rejection sent, state machine advances, reply unchanged.
  (Corresponds to plan group 1.5.)
- [x] **Test strategy — deterministic offline suite (ground truth).** The
  default suite run by `./scripts/test` is deterministic unit/integration
  tests using a **stubbed Gemini client** (same protocol as the real client,
  scripted verdicts, records calls): **no network, no `GEMINI_API_KEY`
  required, must stay green in CI.** Confirm by running `./scripts/test` with
  no `.env` / no key exported and no network access — it must pass.
- [x] **Test strategy — explicitly marked live test.** A separate live test
  exercising real `gemini-3.1-flash-lite` classification exists, **runs only
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

- [x] **3.1 Boundary validation of the photo payload + downloaded bytes.**
  The inbound Telegram photo payload is parsed into a typed model at the edge
  (no raw dicts cross module boundaries), and the downloaded bytes are
  validated for **size, type, and shape** before use. Tests cover oversize
  bytes, wrong/absent content type, and non-image payloads, each producing a
  handled error with a loud log — not a silent drop and not a crash.
- [x] **3.2 Pass path is exactly Phase 1 behaviour — no invented Interviewer.**
  On a passing photo: no new reply text, no Interviewer questions, no dossier,
  no animal suggestion, no orchestration hand-off beyond advancing the phase.
  Assert the outbound reply matches Phase 1's behaviour exactly.
- [x] **3.3 Verdict parsed into a typed Pydantic model.** The Bouncer's model
  output is validated against a schema (boolean human-present plus any
  supporting fields); free text is never interpreted downstream. Test that
  malformed / free-text / schema-violating model output raises a **handled**
  error (logged, routed to the failure path) — never an uncaught crash.
- [x] **3.4 Indeterminate/borderline verdict is typed, not free text.** If the
  implementation adds a third state, retry, or maps uncertainty to rejection,
  the choice is typed in the model and logged (per plan Risks) — confirm it is
  covered by a test either way.
- [x] **3.5 Rejection resets state without restarting the process.** The reset
  goes through the single shared state driver; no process restart, no
  persistence layer, no subprocess recycle. Assert the same process instance
  serves the next update after a reset and lands at the initial phase.
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
- [x] **4.2 Graceful degradation on the conversation path.** Simulate Gemini
  failure (stub raises) and Telegram download/send failure: the update handler
  catches the error, **logs it loudly** (structured, decorator-based via
  `logutil.log_call`), and replies with a **friendly in-character message** —
  the user never sees a traceback and polling keeps running. No bare
  `except`, no unlogged fallbacks, no silent drops.
- [x] **4.3 Logging style.** Logging is decorator-based
  (`logutil.log_call` entry/exit/duration/exception); no log statements
  sprinkled through business logic (TECH.md).
- [x] **4.4 No cross-user leakage beyond state.** Downloaded media and any
  temp files are scoped to one `chat_id`; nothing user A supplies is visible
  to user B (re-check of criterion (c) from the media angle).

## 5. Spec conformance sweep

- [x] **5.1 Model and stack match TECH.md:** Bouncer uses
  `gemini-3.1-flash-lite` only, via Google ADK; no other model introduced;
  ADK dependency pinned in the lockfile.
- [x] **5.2 Out-of-scope work absent (YAGNI):** no webhooks/ports, no
  database/persistence, no group-chat or multi-language support, no
  wrong-payload guards or broad timeout fallbacks (Phase 7), no Interviewer
  behaviour, no speculative config toggles or extension points.
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
Phase 2 is complete only when every box here is checked and the user has
seen the notes.

## 7. Verification results (2026-10-08)

Verified on branch `feature/2026-10-06-repository-gateway`.

- **Offline suite:** `./scripts/test` is green with `GEMINI_API_KEY` unset and
  `.env` absent — `ruff check`, `ruff format --check`, `mypy` (9 source files),
  `pytest`: **56 passed, 1 skipped** (the live test visibly skipped). No
  network required.
- **With key:** the marked live test runs and passes — real
  `gemini-3.1-flash-lite` classifies `person.jpg` as human-present and
  `landscape.jpg` as human-absent (57 passed).
- **Positive/negative paths:** `tests/test_bouncer_flow.py` asserts the pass
  path keeps the Phase 1 `"hey mate!"` reply and advances the phase, and the
  rejection path sends `REJECTION_TEXT` and resets through `StateDriver`.
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
   forces a boolean, uncertainty rides on the optional typed
   `confidence`/`reason`, and output lacking the boolean is a handled
   `VerdictError`. Covered by `tests/test_bouncer.py`.
3. **Downloaded content type.** Telegram photo downloads are JPEG, so the
   photo path calls `validate_image(image, "image/jpeg")`; magic-byte, size,
   and shape checks still apply. No content-type sniffing added (YAGNI).
4. **No lockfile.** TECH.md asks for a pinned lockfile, but the repository has
   none (Phase 1 used `requirements.txt` with bounded ranges); the new
   `google-adk`/`google-genai` entries follow that existing convention.
   Flagged as a possible follow-up rather than introduced here.
