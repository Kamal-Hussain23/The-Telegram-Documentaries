# The Interviewer — validation (Phase 3)

How a reviewer verifies `SPECS/2026-10-08-interviewer/requirements.md` and
`plan.md` are correctly implemented and the phase is mergeable. Every ROADMAP
Phase 3 acceptance criterion maps to at least one check below. Nothing is
"done" until the ground-truth commands pass (final section).

Checklist items are ordered: acceptance criteria first, then the required
checks, then the gate.

## 1. ROADMAP Phase 3 acceptance criteria

- [ ] **(a) 3–4 questions, one at a time, answers persisted.** Drive a full
  interview with the stubbed client: after the photo, question 1 goes out;
  each inbound text yields exactly one reply containing exactly one new
  question; after each turn the session's dossier holds the answer just
  given. Assert the interview never runs shorter than 3 or longer than 4
  questions (see check 3.2).
- [ ] **(b) Dossier summarised + suggested animal produced.** After the final
  answer, the profile-synthesis call ran and the session holds a non-empty
  `profile` (behavioural/personality summary covering quirks and habits) and
  a non-empty `suggested_animal`.
- [ ] **(c) Profile + animal handed to the next stage.** The session's
  completed dossier is persisted through the shared `StateDriver` and the
  phase has advanced to `CONVERTING` — the exact state Phase 4's Converter
  will read. Nothing about the handoff lives only in local variables or a
  reply message.
- [ ] **(d) Interviewer drives the state machine.** Phase transitions
  (`INTERVIEWING → CONVERTING`) are made by the Interviewer through the
  injected `StateDriver`; `bot.py` only routes and delegates, and no stage
  touches session state outside the driver.
- [ ] **(e) Mid-interview `/start` and `/restart` invoke the explicit reset
   routine.** From an in-progress interview with a populated dossier and stored
   photo: each command leaves the chat at `AWAITING_PHOTO` with all conversation
   history buffers (dossier, profile, suggested_animal, script) cleared, state
   trackers reset to the greeting stage, and all temporary media on disk
   (voice notes ``narration_<chat_id>_*``, cached original photos
   ``photo_<chat_id>_*``, converted hybrids ``converted_<chat_id>_*``) deleted.
   A subsequent photo begins a fresh interview whose questions and answers
   contain nothing from the old one.
- [ ] **(f) `scripts/test` green:** pytest + ruff + mypy all pass.

## 2. Required tests — precise strategy

- [ ] **Turn-taking test exists and passes:** one question per inbound
  message, never two; answers persisted before the next question; the
  interview resumes correctly across separate Telegram messages (separate
  `handle_update` calls, state reloaded from the driver each time).
  (Plan group 1.4.)
- [ ] **Budget tests exist and pass:** with the model demanding to finish at
  question 1 or 2, the code forces continuation to the floor of 3; with the
  model wanting to continue, the ceiling of 4 stops it — asserted via call
  counts and replies, proving no fifth question can be generated. (Plan 1.3.)
- [ ] **Completion/handoff test exists and passes:** final answer → profile +
  animal persisted → phase `CONVERTING` → reply reveals the animal and does
  **not** leak the full profile text. (Plan 1.5.)
- [ ] **Reset and isolation tests exist and pass:** both commands invoke the
   explicit reset routine (5.1); both commands purge and restart (1.6); two
   `chat_id`s never share dossier, photo, or reveal (1.8).
- [ ] **Test strategy — deterministic offline suite (ground truth).** The
  default suite run by `./scripts/test` uses the **stubbed interview client**
  (scripted structured outputs, records calls): **no network, no
  `GEMINI_API_KEY` required, must stay green in CI.** Confirm by running
  `./scripts/test` with no `.env`/key exported and no network — it must pass.
- [ ] **Test strategy — explicitly marked live test.** A separate live test
  exercising a real `gemini-3.1-flash-lite` interview exists, **runs only
  when `GEMINI_API_KEY` is set, and is skipped otherwise** (visible skip, not
  a silent pass). Verify both: key unset → skip reported; key set → runs and
  passes with an interview of 3–4 questions ending in a profile + animal.
- [ ] **Strategy justification honoured.** Offline suite = wiring; live test =
  judgement against the real model. Neither is dropped for the other.

## 3. Behavioural and contract checks

- [ ] **3.1 Both model outputs are typed Pydantic contracts.** `NextQuestion`
  and `InterviewProfile` are parsed at the edge; free text is never
  interpreted downstream. Malformed, free-text, or schema-violating output
  raises a **handled** `InterviewerError` (logged loudly, friendly user-facing
  reply) — never an uncaught crash and never a half-parsed field used as
  state. (Plan 1.2, 1.9.)
- [ ] **3.2 Budget bounds are code-enforced, not model-trusted.** The floor
  (3) and ceiling (4) hold regardless of model output; `is_final` is honoured
  only from question 3 onward; the ceiling forces completion without a
  generation call. Confirm no code path can ask a 5th question or end at fewer
  than 3. (Plan 1.3, 3.4.)
- [ ] **3.3 Exactly one question per turn, waiting for the response.** No
  turn sends two questions; no question is asked while one is pending an
  answer; the first question goes out on the Bouncer pass (placeholder reply
  removed from that path only). (Plan 1.4, 1.7, 5.2.)
- [ ] **3.4 Idempotent start.** A photo mid-interview re-sends the pending
  question and leaves questions, answers, and stored photo intact — a
  dossier is never silently destroyed by the start path. (Plan 1.7, 3.6.)
- [ ] **3.5 Reveal policy.** The user-facing completion reply contains the
  suggested animal in character and not the full profile; the profile string
  exists only in session state for the next stage. (Plan 1.5, 3.5.)
- [ ] **3.6 Single shared state driver + schema versioning.** All
  reads/writes go through `StateDriver`; `SCHEMA_VERSION` was bumped for the
  schema change so stale in-memory sessions invalidate cleanly; state remains
  in-memory, keyed by `chat_id`. (Plan 2.1–2.4.)
- [ ] **3.7 Interview resumes across messages.** Simulate a multi-message
  interview with the state reloaded between messages (as the real long-poll
  loop does): question N's pending state survives, answers accumulate, and
  completion triggers exactly once — no re-asking, no double synthesis.

## 4. Security, secrets, and resilience checks

- [ ] **4.1 Secrets come only from `.env`.** Grep-style check — no hits
  outside `.env`/`.env.example` placeholders:
  ```bash
  grep -rnE "(AIza[0-9A-Za-z_-]{35}|GEMINI_API_KEY\s*=\s*['\"][^'\"]+)" \
    --include='*.py' --include='*.md' --include='*.toml' --include='*.txt' \
    --include='*.example' . | grep -v '\.env:'
  ```
  Also confirm `.env` is gitignored, `.env.example` carries placeholders only,
  and no real key appears in the repo or git history for this change.
- [ ] **4.2 No cross-user leakage.** Two chats run interleaved interviews in
  one process: neither sees the other's questions, answers, profile, animal,
  photo, or reveal. (Plan 1.8; re-check of MISSION.md non-negotiable.)
- [ ] **4.3 Graceful degradation on the conversation path.** Gemini failure
  and malformed model output mid-interview are caught, **logged loudly**
  (decorator-based via `logutil.log_call`), and answered with the friendly
  `ERROR_TEXT` while leaving the dossier resumable; a Telegram send failure
  never raises into the polling loop. No bare `except`, no unlogged
  fallbacks, no silent drops, no traceback to the user. (Plan 1.9.)
- [ ] **4.4 Logging style.** Logging is decorator-based (`log_call`
  entry/exit/duration/exception); no log statements sprinkled through
  business logic (TECH.md).

## 5. Spec conformance sweep

- [ ] **5.1 Model and stack match TECH.md:** Interviewer uses
  `gemini-3.1-flash-lite` only, via Google ADK; no other model introduced; any
  new dependency pinned in `requirements.txt` per existing convention.
- [ ] **5.2 Out-of-scope work absent (YAGNI):** no Converter/Scripter/Narrator
  behaviour, no wrong-payload guards or broad timeout fallbacks (Phase 7), no
  profile shown to the user, no budget config field, no webhooks/persistence/
  group/multi-language work, no speculative toggles.
- [ ] **5.3 TDD evidence:** tests for every behaviour above exist and were
  written before/alongside the code (plan group 1); no downloaded media or
  generated artefacts committed.
- [ ] **5.4 Implementation-vs-spec diffs surfaced.** Any deviation from
  `requirements.md`/`plan.md` is written up and **shown to the user before
  merge** — specs updated or code corrected, not silently diverged. Two
  known, user-approved deltas to confirm and record here: (i) the Phase 2
  pass-path test/check 3.2 superseded by the new first-question reply, and
  (ii) any ADK API difference discovered at implementation time. If there are
  no further diffs, say "no additional implementation-vs-spec diffs" explicitly.
- [ ] **5.5 Constitution sync.** `MISSION.md`, `ROADMAP.md`, and `README.md`
  say **3–4 questions** (user-approved 2026-10-08), with no "5–7" remnants
  anywhere in `SPECS/` or the README; `README.md` status/pipeline text
  reflects Phase 3.

## 6. Ground-truth gate — run these last

- [ ] **`./scripts/test` passes:** `ruff check` + `ruff format --check` +
  `mypy` + `pytest`, all green, with no `GEMINI_API_KEY` set and no network
  (offline). Fix typing/lint fallout; do not loosen config to get green.
- [ ] **`./scripts/hooks` passes:** the pre-commit path (same tooling, same
  config) is green too.
- [ ] **Live test spot-check (optional locally, required before declaring the
  phase verified):** with `GEMINI_API_KEY` set, run the marked live test and
  confirm a real interview of 3–4 questions completes with a profile and a
  suggested animal.
- [ ] **Review notes compiled:** list the results of every check above,
  including any item in 5.4, and surface them to the user **before merge**.
  Phase 3 is complete only when every box here is checked and the user has
  seen the notes.

## 7. Verification results

_(Filled in by the verifier when the phase is verified.)_
