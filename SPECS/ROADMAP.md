# ROADMAP.md — The Telegram Documentaries

Ordered build plan. One phase per pipeline capability. A phase is marked
**complete only when verified** against its acceptance criteria.

## Phase 1 — Repository & gateway

Project skeleton, `.env` wiring, and a long-polling loop that replies with a
hardcoded message.

**Acceptance criteria**
- `scripts/test` runs green on an empty-but-scaffolded project (pytest + ruff +
  mypy all pass).
- `.env` is gitignored; `.env.example` documents `TELEGRAM_BOT_TOKEN` and
  `GEMINI_API_KEY`.
- The bot polls Telegram, receives a message, and sends a fixed reply.

**Serves:** transport works — the foundation every later phase rides on.

## Phase 2 — Bouncer

Vision gate on incoming photos, with rejection and reset routing.

**Acceptance criteria**
- A portrait with a human passes and advances the state machine.
- A non-human / unusable image gets an in-character rejection and resets the
  session to the initial phase.
- Photo-stage state is keyed by `chat_id`; no cross-user leakage.

**Status:** implemented and verified — see `SPECS/2026-10-06-bouncer/`.

**Serves:** photo intake.

## Phase 3 — Interviewer

Sequential, stateful Q&A that accumulates the dossier and picks an animal.

**Acceptance criteria**
- 3–4 questions asked **one at a time**, each answer persisted to the session.
- On completion the dossier is summarised and a suggested animal is produced.
- The completed profile + suggested animal are persisted for, and handed to,
  the next pipeline stage.
- The Interviewer drives the state machine as orchestrator.
- Mid-interview `/start` or `/restart` clears the dossier and restarts cleanly.

**Serves:** orchestration.

## Phase 4 — Converter

Multimodal fusion of the original photo and the dossier into a hybrid portrait.

**Acceptance criteria**
- Photo + dossier are sent together to the image model in one call.
- The resulting image is delivered to the Telegram chat directly — no
  intermediate text hop.
- Failure to generate the image produces a logged, graceful user-facing message
  rather than a dead end.

**Serves:** image output.

## Phase 5 — Scripter

One paragraph of narration built from the dossier.

**Acceptance criteria**
- Output is a single paragraph, roughly 60–90 words.
- Tone is dramatic British wildlife documentary, drawing on the dossier.
- Output is parsed against a schema; malformed model output is a handled error.

**Serves:** content.

## Phase 6 — Narrator

TTS synthesis and audio delivery.

**Acceptance criteria**
- The Scripter's text reaches Gemini TTS directly (no conversational turn).
- The audio is rendered to a Telegram-compatible format (OGG/MP3) and arrives
  as a voice note.
- The full happy path `/start` → photo → interview → image → narration → voice
  note completes unattended.

**Serves:** voice.

## Phase 7 — Resilience

Reset semantics, wrong-payload guards, and API-timeout fallbacks.

**Acceptance criteria**
- `/start` and `/restart` purge session state **and** temporary media without
  restarting the process.
- Text during the photo stage, a second photo during the interview, and other
  out-of-order payloads each produce a friendly in-character reply — no crash,
  no traceback, no silent drop.
- Gemini/Telegram timeouts and errors on the conversation path are caught,
  logged loudly, and degrade gracefully.
- Logging is decorator-based and structured across all stages.

**Serves:** rubric robustness.
