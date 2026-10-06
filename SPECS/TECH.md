# TECH.md — The Telegram Documentaries

The technical contract. Every agent and feature spec defers to this file.

## Stack

| Concern | Choice |
| --- | --- |
| Language | Python |
| Transport | Telegram Bot API via **long polling** (`getUpdates`) — no webhooks |
| Agent framework | Google Agent Development Kit (ADK) |
| Bouncer / Interviewer / Scripter | `gemini-3.1-flash-lite` |
| Converter (image) | `gemini-3.1-flash-image` |
| Narrator (TTS) | `gemini-3.1-flash-tts-preview` — **not an agent**, a direct script → audio hop |
| Data models | Pydantic |
| Secrets | `.env` → `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY` |
| Tests / lint / types | `pytest` + `ruff` + `mypy` |

## Architecture

- **ADK hub-and-spoke.** The **Interviewer is the orchestrator**: it owns the
  conversation loop, decides which stage runs next, and holds the dossier.
- Each pipeline stage is a **discrete agent/module** with a single
  responsibility. Stages communicate through typed models, never by reaching
  into each other's internals.
- Explicit **state-machine phases** (e.g. AWAITING_PHOTO → INTERVIEWING →
  CONVERTING → SCRIPTING → NARRATING). Every inbound update is routed by phase;
  an update that doesn't fit the current phase is handled by the
  wrong-payload guard, not by falling through.
- **Narrator is plumbing, not an agent.** The Scripter's text goes straight to
  Gemini TTS and back out as a voice note — no conversational turn.

## Contracts at boundaries

- Parse Telegram updates, Gemini responses, and TTS output into **typed Pydantic
  models at the edge**, then pass those models inward.
- **Never pass raw dicts or unvalidated payloads across module boundaries.**
- Treat all external input — Telegram updates, file downloads, model output —
  as **untrusted and arbitrary**. Validate size, type, and shape before use.
- Model output is data, not instruction: a Gemini response is parsed against a
  schema, and anything that doesn't fit is a handled error.

## Logging & error policy

- **Comprehensive structured logging.** Prefer **decorators** for entering,
  exiting, timing, and correlating a call over mixing logging statements into
  business logic.
- **Non-critical, user-invisible work:** fail loudly and log the full context.
- **On a validated user's conversation path:** catch the error, log it loudly,
  and **degrade gracefully** so the conversation continues. The user sees a
  friendly message, never a traceback.
- Forbidden: bare `except: pass`, swallowed exceptions, fallbacks that aren't
  logged.

## Session state

- **Versioned schema**, keyed by `chat_id`. The version field lets a schema
  change invalidate old in-memory sessions cleanly.
- **One shared state driver** used by every stage — no stage reads or writes
  session state directly.
- **Reset semantics:** `/start` and `/restart` both purge the session entry and
  any temporary media on disk, then re-enter the initial phase. Neither
  restarts the process.

## Testing

- **Red/Green TDD.** Tests are written before the code they cover.
- Dev scripts are the ground truth and live in `scripts/`:
  - `scripts/test` — runs `pytest`, `ruff check`, and `mypy`.
  - `scripts/hooks` — the pre-commit checks (same tooling, same config).
- Both scripts are documented in this file **and** in the README, and must keep
  working as the toolchain changes.

## Repo hygiene

- `.env` is listed in `.gitignore` and is never committed; `.env.example`
  carries placeholder keys only.
- Dependencies are pinned in a lockfile so the environment is reproducible.
- No generated artifacts, downloaded media, or model outputs committed.

## README policy

The README must document, and stay in sync with:

- how to install dependencies and configure `.env`;
- what `scripts/test` and `scripts/hooks` run and when to run them;
- how to run the bot locally (long polling, no extra infrastructure);
- the pipeline overview at a level a new contributor can follow.
