# The Telegram Documentaries

<p align="center">
  <img src="orangutan-interviewer.png" alt="Interviewer Agent" width="120">
</p>

A Telegram bot that turns a user's portrait photo into a narrated wildlife documentary.
The user sends a photo, answers a few questions, and receives:

1. **A hybrid animal portrait** — the original photo fused with AI-generated animal features via the Converter stage.
2. **A dramatic one-paragraph narration** — British wildlife-documentary style, built from the behavioural dossier.
3. **A voice note** — the narration rendered to audio by Gemini TTS.

The comedy emerges from sincerity: the bot treats every subject as a majestic, rare animal observed in the wild.

---

## Pipeline Overview

| Stage | Model | What it does |
| --- | --- | --- |
| **The Bouncer** | Gemini 3.1 Flash Lite (vision) | Vision gate: confirms a human face is in the uploaded photo. Non‑human images get a cheeky in‑character rejection and a session reset. |
| **The Interviewer** | Gemini 3.1 Flash Lite | **Orchestrator**. Asks 3–4 investigative, playful, slightly eccentric questions **one at a time**, accumulates a behavioural dossier keyed to the user's `chat_id`, and suggests an animal. |
| **The Converter** | Gemini 3.1 Flash Image | Fuses the original photo with the behavioural dossier into a hybrid animal portrait, delivered directly to the Telegram chat. |
| **The Scripter** | Gemini 3.1 Flash Lite | Writes one paragraph (~60–90 words) of dramatic British wildlife narration, drawn from the dossier. |
| **The Narrator** | Gemini TTS (not an agent) | The script goes directly to text‑to‑speech and returns as a voice note — no extra conversational turn. |

**Session state** is held in memory, keyed by the user's Telegram `chat_id`. `/start` and `/restart` purge the session and any temporary media files without restarting the bot.

---

## Requirements

- Python 3.11+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A Google Gemini API key

---

## Setup

Two scripts are the ground truth for this repo:

- **`scripts/test`** — runs the full check suite: `pytest`, `ruff check`, and `mypy`. Run this before you consider any change done.
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

## Pipeline Stages (detailed)

- **Bouncer** — vision gate on incoming photos.
- **Interviewer** — 3–4 question one‑at‑a‑time orchestration, dossier accumulation, animal suggestion.
- **Converter** — multimodal fusion of photo + dossier → hybrid portrait (delivered as a Telegram image).
- **Scripter** — one paragraph of dramatic British wildlife narration from the dossier (Phase 5, now on `main`).
- **Narrator** — TTS synthesis → voice note (Phase 6, plumbing, not an agent).

---

## Development

- Tests are written **before** the code (Red/Green TDD).
- A phase from the roadmap is complete only when its acceptance criteria are verified with `scripts/test` green.
- Both `scripts/test` and `scripts/hooks` must keep working as the toolchain changes.

---

## Project Constitution

The contract this project is built against lives in `SPECS/`:

- [`SPECS/MISSION.md`](SPECS/MISSION.md) — what the product is, and what it explicitly is not.
- [`SPECS/TECH.md`](SPECS/TECH.md) — stack, architecture, and engineering policies.
- [`SPECS/ROADMAP.md`](SPECS/ROADMAP.md) — the ordered phase plan.

Feature specs live alongside them as `SPECS/<YYYY-MM-DD>-<feature-name>/`.

---

## Status

- **Phase 1** — Repository & gateway ✅
- **Phase 2** — Bouncer vision gate ✅
- **Phase 3** — Interviewer ✅
- **Phase 4** — Converter ✅
- **Phase 5** — **Scripter** ✅ *(newly added: one‑paragraph narration, Brian Cox persona, output contract)*
- **Phase 6** — Narrator (TTS, plumbing, not an agent)

---

## Contact & License

- **GitHub:** [Kamal-Hussain23/The-Telegram-Documentaries](https://github.com/Kamal-Hussain23/The-Telegram-Documentaries)
- **License:** MIT (see `LICENSE` if present)

---

*Built with Python, Google ADK, and Telegram Bot API — long polling, no webhooks, no extra infrastructure.*