# The Telegram Documentaries

A Telegram bot that turns a user's portrait photo into a narrated wildlife documentary
using Google ADK pipeline: Bouncer → Interviewer → Converter → Scripter → Narrator.

<p align="center">
  <img src="orangutan-interviewer.png" alt="Interviewer Agent" width="120">
</p>

The comedy emerges from sincerity: the bot treats every subject as a majestic, rare animal
observed in the wild.

---

## Pipeline Overview

| Stage | Model | What it does |
|------|-------|-------------|
| **The Bouncer** | `gemini-3.1-flash-lite` (vision) | Vision gate: confirms a human face is in the uploaded photo. Non‑human images get a cheeky in‑character rejection and a session reset. |
| **The Interviewer** | `gemini-3.1-flash-lite` | **Orchestrator**. Asks 3–4 investigative, playful, slightly eccentric questions **one at a time**, accumulates a behavioural dossier keyed to the user's `chat_id`, and suggests an animal. Wrong‑payload replies and API timeouts are handled gracefully. |
| **The Converter** | `gemini-3.1-flash-image` | Fuses the original photo with the behavioural dossier into a hybrid animal portrait, delivered directly to the Telegram chat. Failure advances the pipeline to `SCRIPTING` so narration/voice note still run. |
| **The Scripter** | `gemini-3.1-flash-lite` | Writes one paragraph (~60–90 words) of dramatic British wildlife narration, drawn from the dossier. Uses a Brian Cox physicist persona ("wonder‑struck, cosmic scale"). Wrong‑payload replies and API timeouts are handled gracefully. |
| **The Narrator** | `gemini-3.1-flash-tts-preview` (direct `google-genai`, no ADK agent) | The script goes straight to text‑to‑speech and returns as a Telegram voice note (OGG/Opus). No conversational turn. On failure stays in `NARRATING` for retry. |

**Session state** is held in memory, keyed by the user's Telegram `chat_id`. `/start` and `/restart` purge the session and any temporary media files without restarting the bot.

---

## Phases — Status & Acceptance Criteria

| Phase | Feature | Status |
|-------|---------|--------|
| **Phase 1** | Repository & gateway (long‑polling, `.env` wiring) | ✅ Implemented |
| **Phase 2** | Bouncer vision gate (human / non‑human) | ✅ Implemented & Verified |
| **Phase 3** | Interviewer (3–4 Q&A, dossier, animal suggestion, CONVERTING phase) | ✅ Implemented & Verified |
| **Phase 4** | Converter (gemini‑3.1‑flash‑image hybrid portrait, delivered to Telegram, CONVERTING→SCRIPTING transition) | ✅ Implemented & Verified |
| **Phase 5** | Scripter (one paragraph, Brian Cox persona, output contract, SCRIPTING→NARRATING) | ✅ Implemented & Verified |
| **Phase 6** | Narrator (Gemini TTS → voice note, NARRATING→AWAITING_PHOTO transition) | ✅ Implemented & Verified |
| **Phase 7** | Resilience (wrong‑payload guards, temp‑file purge, API timeouts per‑client, graceful degradation) | ✅ Implemented & Verified |

**All phases 1–7 are implemented and verified.** `scripts/test` passes (266 tests, ruff + mypy green).

---

## Full Pipeline Flow

```
/start → Bouncer (validate human) → Interviewer (3–4 Qs, dossier + animal) → Converter 
  (hybrid portrait image → Telegram) → Scripter (one paragraph narration) → Narrator 
  (Gemini TTS → voice note) → AWAITING_PHOTO
```

**Key behaviours:**
- Wrong‑payload inbound messages produce friendly in‑character replies per phase (e.g., "I need a portrait photo" in AWAITING_PHOTO, "We're mid‑interview" in INTERVIEWING).
- API timeouts (Gemini vision / TTS) are caught per‑client, logged, and the user gets a friendly retry prompt — the polling loop never crashes.
- `/start` / `/restart` resets the session, purges temp files (`narration_*`, `photo_*`, `converted_*`), and returns to `AWAITING_PHOTO`.
- All stages communicate through typed Pydantic models at the edge; raw dicts never cross module boundaries.

---

## Requirements

- Python 3.11+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A Google Gemini API key

---

## Setup

Two scripts are the ground truth for this repo:

- **`scripts/test`** — runs the full check suite: `pytest`, `ruff check`, and `mypy`. Run this before considering any change done.
- **`scripts/hooks`** — the pre-commit checks, using the same tooling and configuration.

### Install dependencies

```bash
pip install -r requirements.txt
```

### Configure environment

```bash
cp .env.example .env
```

```
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
GEMINI_API_KEY=your_gemini_api_key_here
```

`.env` is gitignored. Never put real keys in `.env.example`, source, or docs.

### Run the bot

```bash
python -m telegram_documentaries
```

It polls Telegram outbound over HTTPS, so it works behind NAT and firewalls with no ports opened.

---

## Development

- Tests are written **before** the code (Red/Green TDD).
- A phase from the roadmap is complete only when its acceptance criteria are verified with `scripts/test` green.
- Both `scripts/test` and `scripts/hooks` must keep working as the toolchain changes.
- Defensive guards are in place for every boundary: wrong‑payload replies, API timeouts, temp‑file purge on reset, and graceful degradation.

---

## Project Constitution

The contract this project is built against lives in `SPECS/`:

- [`SPECS/MISSION.md`](SPECS/MISSION.md) — what the product is, and what it explicitly is not.
- [`SPECS/TECH.md`](SPECS/TECH.md) — stack, architecture, and engineering policies.
- [`SPECS/ROADMAP.md`](SPECS/ROADMAP.md) — the ordered phase plan.

Feature specs live alongside them as `SPECS/<YYYY-MM-DD>-<feature-name>/`.

- `SPECS/2026-10-06-bouncer/` — Phase 2
- `SPECS/2026-10-08-interviewer/` — Phase 3
- `SPECS/2026-10-10-scripter/` — Phase 5
- `SPECS/2026-10-11-narrator/` — Phase 6
- `SPECS/2026-10-13-converter/` — Phase 4
- `SPECS/2026-10-13-resilience/` — Phase 7

---

## Contact & License

- **GitHub:** [Kamal-Hussain23/The-Telegram-Documentaries](https://github.com/Kamal-Hussain23/The-Telegram-Documentaries)
- **License:** MIT (see `LICENSE` if present)

---

Built with Python, Google ADK, and Telegram Bot API — long polling, no webhooks, no extra infrastructure.

--- 

## Quick Start (one‑liner)

```bash
cp .env.example .env   # fill in your keys
python -m telegram_documentaries  # starts long‑polling
```