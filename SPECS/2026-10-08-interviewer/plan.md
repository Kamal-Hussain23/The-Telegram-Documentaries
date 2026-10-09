# The Interviewer — implementation plan (Phase 3)

Task groups for `SPECS/2026-10-08-interviewer/requirements.md`. Red/Green TDD:
group 1 is written first and must fail; groups 2–5 make it pass; group 6 is the
gate. Plan only — no application code lives in this file.

Ground truth throughout: run the dev scripts from the README — `scripts/test`
(pytest + `ruff format --check` + `ruff check` + mypy) and `scripts/hooks`
(same tooling, pre-commit). A group is done only when those are green.

## 1. Test scaffolding first (Red)

- 1.1 A fake interview client implementing the same protocol the real ADK
  client will implement — scripted `NextQuestion` / `InterviewProfile` JSON,
  records every call with its prompt context, never touches the network. The
  default suite stays fully offline.
- 1.2 Contract tests: both structured outputs parse into their typed Pydantic
  models; malformed / free-text / schema-violating model output raises a
  **handled** `InterviewerError`, never an uncaught crash and never
  interpreted downstream.
- 1.3 Budget tests (hostile model output): "finish now" at question 1 or 2 is
  overridden (interview continues); a model that would keep asking is stopped
  at question 4 with no fifth question ever generated — floor 3 and ceiling 4
  both hard, asserted from the outside via call counts and replies.
- 1.4 Turn-taking tests: one inbound message ⇒ exactly one outbound question;
  each answer is persisted before the next question goes out; the interview
  resumes from session state across separate `handle_update` calls (simulated
  as separate Telegram messages).
- 1.5 Completion/handoff test: the final answer produces a structured profile
  synthesis; the session then holds a non-empty `profile` and
  `suggested_animal` and the phase is `CONVERTING`; the user-facing reply
  reveals the animal in character and does **not** contain the full profile.
- 1.6 Reset tests: mid-interview `/start` and `/restart` each purge the
  dossier and stored photo via the state driver, land at `AWAITING_PHOTO`, and
  a subsequent photo starts a genuinely fresh interview (old answers absent).
- 1.7 Start-path tests: a Bouncer pass replies with question 1 (placeholder
  reply gone from the pass path); a photo arriving mid-interview re-sends the
  pending question and leaves questions/answers/photo intact (idempotent
  start).
- 1.8 Isolation tests: two `chat_id`s run interleaved interviews without
  sharing a dossier, photo, question index, or reveal — no cross-user leakage.
- 1.9 Degradation tests: Gemini failure and malformed output mid-interview
  each log loudly and reply with the friendly `ERROR_TEXT`, leaving the
  dossier intact so the conversation is resumable; a send failure never
  raises into the polling loop.

## 2. Session state (makes group 1 state assertions possible)

- 2.1 `SCHEMA_VERSION` 1 → 2 (schema change invalidates stale in-memory
  sessions cleanly, per TECH.md).
- 2.2 Typed dossier sub-model on `SessionState`: questions, answers, completed
  profile, suggested animal — all optional/defaulted, validated by Pydantic.
- 2.3 Phase enum gains `CONVERTING` (TECH.md's state machine); existing
  phases untouched.
- 2.4 Everything still flows through the one shared `StateDriver`
  (load/save/reset); no stage reaches around it.

## 3. The Interviewer (domain logic, no network)

- 3.1 The two output schemas (`NextQuestion`, `InterviewProfile`) and the
  edge parsers raising `InterviewerError` on anything malformed.
- 3.2 `Interviewer` class taking the `StateDriver` and an interview-client
  protocol by injection; `log_call` on its public entry points.
- 3.3 Turn loop: record the answer → decide question-or-finish → persist →
  return exactly one reply string. Progress is derived from the recorded
  dossier, not from a stored counter.
- 3.4 Budget enforcement (decision 3): model's `is_final` honoured only from
  question 3 onward; question 4 always final; no generation call once the
  ceiling is reached — finish straight into profile synthesis.
- 3.5 Completion: run the profile synthesis, persist `profile` +
  `suggested_animal`, advance the phase to `CONVERTING` via the state driver,
  and build the in-character animal-reveal reply (animal only — profile stays
  internal).
- 3.6 Idempotent `start`: first call generates and sends question 1; later
  calls with an interview already in progress return the pending question
  without touching the dossier.
- 3.7 Interview instruction text for the agent: investigative, playful,
  slightly eccentric field-interviewer persona, English only.

## 4. ADK client

- 4.1 A Gemini interview client mirroring `vision.py`: ADK `LlmAgent` on
  `gemini-3.1-flash-lite` with the schema as `output_schema`, session created
  and deleted per call, runner drained to completion, driven synchronously
  with `asyncio.run`.
- 4.2 Question-generation and profile-synthesis calls each carry the relevant
  accumulated Q&A as context (the model adapts to prior answers).
- 4.3 Dependency/secret hygiene unchanged: pinned entries in `requirements.txt`
  only if a new one is genuinely needed; `GEMINI_API_KEY` from `.env` via
  `python-dotenv`, never in source, tests, or docs.

## 5. Gateway wiring

- 5.1 Command handling in `bot.py`: `/start` and `/restart` (with optional
  `@BotName` suffix) reset through the state driver and reply with the
  in-character fresh-start invitation — before any phase routing.
- 5.2 Pass path: a human-present photo now hands over to
  `Interviewer.start(...)` and sends its question instead of the placeholder
  `REPLY_TEXT`. Rejection path unchanged.
- 5.3 Turn routing: text while `phase is INTERVIEWING` goes to the
  Interviewer's answer path; text in other phases keeps existing behaviour
  (Phase 7 owns wrong-payload copy). Text in `CONVERTING` must not re-enter
  or disturb the completed dossier.
- 5.4 Constructor/DI wiring in `bot.py` and `__main__.py` for the new
  collaborator, mirroring how `Bouncer` is injected; the existing
  `try/except → ERROR_TEXT` conversation-path guard covers the new calls.
- 5.5 Update the Phase 2 test that asserts the placeholder reply on the pass
  path (`test_human_photo_keeps_the_phase_1_reply`): it is superseded by the
  user-approved pass-path change. Surface this as an implementation-vs-spec
  note in `validation.md` (check 5.4) — the Bouncer's *classification*
  behaviour and rejection path are unchanged.

## 6. Green

- 6.1 Run `scripts/test` (pytest + `ruff format --check` + `ruff check` +
  mypy) until green; fix typing/lint fallout rather than loosening config.
- 6.2 Also run `scripts/hooks` (same tooling) to confirm the pre-commit path.
- 6.3 Live opt-in test: a real interview against `gemini-3.1-flash-lite`,
  enabled only when `GEMINI_API_KEY` is present and skipped visibly
  otherwise — the default suite stays green offline (final wording belongs in
  `validation.md`).
- 6.4 Verify ROADMAP.md Phase 3 acceptance criteria end to end, including the
  constitution sync (MISSION/ROADMAP/README now say 3–4 questions).
- 6.5 Update `README.md` status/pipeline wording for Phase 3.

## Risks / notes

- **ADK pattern is proven.** `vision.py` (google-adk 2.11.0) already
  established `LlmAgent(output_schema=...)`, `client_kwargs={"api_key": ...}`,
  async session services driven by `asyncio.run`, and draining the runner to
  completion. Phase 3 reuses that shape; deviations get recorded in
  `validation.md` §7.
- **The model decides *when*, the code decides *how many*.** The only
  model-held choice is `is_final` from question 3 onward; everything else
  (floor, ceiling, no fifth question) is deterministic and unit-tested against
  hostile output, so interview length can never fall outside 3–4.
- **Pass-path reply change is deliberate and user-approved.** Phase 2's
  validation check 3.2 ("pass path is exactly Phase 1 behaviour") existed
  because the Interviewer was out of scope then; this phase supersedes it for
  the reply text only. Flagged in `validation.md` check 5.4 rather than
  silently diverged.
- **Empty-ish answers.** Telegram does not deliver empty text; a
  whitespace-only message is treated as an answer like any other (no
  content-quality filtering — that is the model's job, and guarding payloads
  is Phase 7's).
- **Completion without a Converter.** After the interview the session sits in
  `CONVERTING` with nothing to call. Further text falls through to existing
  default routing untouched by the Interviewer — Phase 4 gives the phase a
  real consumer; Phase 7 gives it a proper wrong-payload reply.
- **Ground truth:** the dev scripts referenced in the README — `scripts/test`
  and `scripts/hooks` — decide when this phase is done.
